"""Async client for the Techem (techemadmin.no) GraphQL API.

This is an undocumented API used by the beboer.techemadmin.no tenant portal.
Nothing here is a published contract; queries are kept minimal and every
response is read defensively.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

import aiohttp

from .const import API_PATH, KNOWN_HOSTS, TOKEN_EXPIRY_MARGIN_SECONDS

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=90)

# Techem's own portal is the only other consumer of this API; identify
# ourselves honestly rather than impersonating a browser.
USER_AGENT = "home-assistant-techem (+https://github.com/aunefyren/home-assistant-techem)"

_LOGIN = """
mutation Login($credentials: CredentialsInput!) {
  loginWithEmailAndPassword(credentials: $credentials) {
    ok { token refreshToken }
  }
}
"""

_REFRESH = """
mutation Refresh($refreshToken: String!) {
  refreshToken(refreshToken: $refreshToken) {
    ok { token refreshToken }
  }
}
"""

_ME = "{ me { id name email language } }"

_UNITS = """
{
  tenantUnits {
    id
    treeInfo { quantities }
    unit { id name size street location unitNumber }
  }
}
"""

_KPIS = """
query Kpis($input: UnitQuantityKPIsInput!) {
  unitQuantityKpis(input: $input) {
    total previousPeriod previousYear propertyComparison
    rooms { label value }
  }
}
"""

_GRAPH = """
query TenantGraph($graph: TenantGraphInput!) {
  tenantGraph(graph: $graph) {
    timestamps
    graphs { consumption { quantityDescriptor { quantity } values } }
  }
}
"""


class TechemError(Exception):
    """Base error for the Techem API."""


class TechemAuthError(TechemError):
    """Credentials were rejected, or the session could not be renewed."""


class TechemConnectionError(TechemError):
    """The API could not be reached."""


def _jwt_expiry(token: str) -> datetime | None:
    """Read the `exp` claim without verifying the signature.

    The signature is Techem's to check; we only want to know when to renew.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, binascii.Error, UnicodeDecodeError):
        return None

    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return datetime.fromtimestamp(exp)


def _as_api_date(value: date) -> str:
    """Techem's JSDate scalar wants a naive midnight timestamp."""
    return f"{value.isoformat()}T00:00:00"


class TechemClient:
    """Talks to the Techem GraphQL endpoint on behalf of one tenant login."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        email: str,
        password: str,
    ) -> None:
        """Initialise the client for one Techem country host."""
        self._session = session
        self._host = host
        self._url = f"https://{host}{API_PATH}"
        self._portal = KNOWN_HOSTS.get(host)
        self._email = email
        self._password = password
        self._token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires: datetime | None = None
        self._lock = asyncio.Lock()

    async def _post(self, query: str, variables: dict[str, Any] | None,
                    token: str | None) -> dict[str, Any]:
        """Send one GraphQL request and return its `data` payload."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "User-Agent": USER_AGENT,
        }
        if self._portal:
            headers["Origin"] = self._portal
            headers["Referer"] = f"{self._portal}/"
        if token:
            headers["Authorization"] = f"JWT {token}"

        payload = {"query": query, "variables": variables or {}}

        try:
            async with self._session.post(
                self._url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status in (401, 403):
                    raise TechemAuthError(f"HTTP {response.status} from Techem")
                response.raise_for_status()
                body = await response.json()
        except TechemError:
            raise
        except aiohttp.ClientResponseError as err:
            raise TechemConnectionError(f"HTTP {err.status} from Techem") from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise TechemConnectionError(f"Could not reach Techem: {err}") from err
        except ValueError as err:
            raise TechemError("Techem returned a malformed response") from err

        if errors := body.get("errors"):
            messages = [str(err.get("message", "")) for err in errors]
            joined = "; ".join(messages)
            if any(
                marker in joined
                for marker in ("login-required", "invalid-credentials", "token")
            ):
                raise TechemAuthError(joined)
            raise TechemError(f"Techem rejected the query: {joined}")

        data = body.get("data")
        if not isinstance(data, dict):
            raise TechemError("Techem returned no data")
        return data

    def _store_credentials(self, credentials: Any) -> None:
        if not isinstance(credentials, dict) or not credentials.get("token"):
            raise TechemAuthError("Techem did not return a session token")
        self._token = credentials["token"]
        self._refresh_token = credentials.get("refreshToken")
        self._token_expires = _jwt_expiry(self._token)

    async def async_login(self) -> None:
        """Authenticate from scratch with email and password."""
        data = await self._post(
            _LOGIN,
            {
                "credentials": {
                    "username": self._email,
                    "password": self._password,
                    "targetResource": "tenant",
                }
            },
            token=None,
        )
        result = (data.get("loginWithEmailAndPassword") or {}).get("ok")
        if not result:
            raise TechemAuthError("Techem rejected the email or password")
        self._store_credentials(result)

    async def _async_renew(self) -> None:
        """Renew the session, preferring the refresh token over a full login."""
        if self._refresh_token:
            try:
                data = await self._post(
                    _REFRESH, {"refreshToken": self._refresh_token}, token=None
                )
                if result := (data.get("refreshToken") or {}).get("ok"):
                    self._store_credentials(result)
                    return
            except TechemError as err:
                _LOGGER.debug("Token refresh failed, falling back to login: %s", err)

        await self.async_login()

    async def _async_token(self) -> str:
        """Return a valid token, renewing it ahead of expiry."""
        if self._token and self._token_expires:
            margin = timedelta(seconds=TOKEN_EXPIRY_MARGIN_SECONDS)
            if datetime.now() + margin < self._token_expires:
                return self._token

        if self._token and not self._token_expires:
            # No readable `exp`; keep using it until a call actually fails.
            return self._token

        await self._async_renew()
        if not self._token:
            raise TechemAuthError("No session token available")
        return self._token

    async def _async_query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run an authenticated query, renewing the session once if rejected."""
        async with self._lock:
            token = await self._async_token()
            try:
                return await self._post(query, variables, token)
            except TechemAuthError:
                _LOGGER.debug("Session rejected mid-flight, renewing")

            await self._async_renew()
            return await self._post(query, variables, self._token)

    async def async_verify_credentials(self) -> dict[str, Any]:
        """Log in and return the account profile. Used by the config flow."""
        await self.async_login()
        data = await self._async_query(_ME)
        return data.get("me") or {}

    async def async_get_units(self) -> list[dict[str, Any]]:
        """List the units this login has access to."""
        data = await self._async_query(_UNITS)
        units = data.get("tenantUnits")
        return units if isinstance(units, list) else []

    async def async_get_kpis(
        self,
        object_id: str,
        quantity: str,
        period_begin: date,
        period_end: date,
        compare_with: str = "previous-year",
    ) -> dict[str, Any] | None:
        """Fetch totals and comparisons for one quantity over one period."""
        data = await self._async_query(
            _KPIS,
            {
                "input": {
                    "objectId": object_id,
                    "quantity": quantity,
                    "periodBegin": _as_api_date(period_begin),
                    "periodEnd": _as_api_date(period_end),
                    "compareWith": compare_with,
                }
            },
        )
        kpis = data.get("unitQuantityKpis")
        return kpis if isinstance(kpis, dict) else None

    async def async_get_daily_series(
        self,
        object_id: str,
        quantity: str,
        period_begin: date,
        period_end: date,
    ) -> list[tuple[date, float]]:
        """Fetch daily consumption as (day, value) pairs, gaps omitted.

        Techem also offers HOUR resolution, but for these meters it returns the
        daily total parked in the 23:00 bucket and nulls elsewhere, so DAY is
        the real resolution and the only one worth asking for.
        """
        data = await self._async_query(
            _GRAPH,
            {
                "graph": {
                    "objectId": object_id,
                    "resolution": "DAY",
                    "periodBegin": _as_api_date(period_begin),
                    "periodEnd": _as_api_date(period_end),
                    "consumption": {
                        "evaluateOperational": True,
                        "series": [
                            {"quantityDescriptor": {
                                "quantity": quantity, "normalized": False}}
                        ],
                    },
                }
            },
        )

        graph = data.get("tenantGraph") or {}
        timestamps = graph.get("timestamps") or []
        values: list[Any] = []
        for entry in graph.get("graphs") or []:
            consumption = (entry or {}).get("consumption")
            # `consumption` is an object here, but tolerate a list in case the
            # multi-series form ever comes back.
            for series in consumption if isinstance(consumption, list) else [consumption]:
                if not series:
                    continue
                descriptor = series.get("quantityDescriptor") or {}
                if descriptor.get("quantity") not in (None, quantity):
                    continue
                if isinstance(series.get("values"), list):
                    values = series["values"]
                    break
            if values:
                break

        result: list[tuple[date, float]] = []
        for timestamp, value in zip(timestamps, values):
            if value is None or not isinstance(value, (int, float)):
                continue
            try:
                day = datetime.fromisoformat(str(timestamp)).date()
            except ValueError:
                continue
            result.append((day, float(value)))
        return result
