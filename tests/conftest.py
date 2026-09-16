"""Fixtures for the Techem tests.

The API is faked at the session boundary rather than by patching TechemClient,
so the client's own request building, error mapping and token handling are all
exercised by the tests that use it.
"""

from __future__ import annotations

import base64
import json
import pathlib
import time
from datetime import date, datetime
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.techem.const import CONF_OBJECT_ID, DOMAIN

from .const import (
    COLD,
    HEAT,
    HOT,
    MOCK_EMAIL,
    MOCK_HOST,
    MOCK_OBJECT_ID,
    MOCK_PASSWORD,
    MOCK_UNIQUE_ID,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom component loadable in every test."""
    return


def load_responses() -> dict[str, Any]:
    """Load the API responses captured from a real account."""
    return json.loads((FIXTURES / "api_responses.json").read_text())


def make_jwt(expires_in: int = 3600) -> str:
    """Build a token whose `exp` claim the client can read.

    Only the payload matters; nothing verifies the signature.
    """
    payload = {"exp": int(time.time()) + expires_in, "user_id": 1}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return f"header.{encoded.rstrip('=')}.signature"


def daily_history(responses: dict[str, Any], quantity: str) -> list[tuple[date, float]]:
    """Extract a quantity's daily series from the fixtures."""
    graph = responses["graph"][quantity]["day"]["tenantGraph"]
    values = graph["graphs"][0]["consumption"]["values"]
    return [
        (datetime.fromisoformat(timestamp).date(), value)
        for timestamp, value in zip(graph["timestamps"], values)
        if value is not None
    ]


class FakeResponse:
    """Minimal stand-in for an aiohttp response."""

    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    async def json(self) -> Any:
        return self._payload

    async def text(self) -> str:
        return json.dumps(self._payload)

    def raise_for_status(self) -> None:
        if self.status >= 400:
            import aiohttp

            raise aiohttp.ClientResponseError(
                request_info=None, history=(), status=self.status
            )

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return


class TechemApiMock:
    """Answers GraphQL requests the way the real endpoint does."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self.urls: list[str] = []

        # Knobs for individual tests.
        self.login_error: str | None = None
        self.query_error: str | None = None
        self.status: int = 200
        self.units: Any = responses.get("tenantUnits", {}).get("tenantUnits", [])
        self.history: dict[str, list[tuple[date, float]]] = {
            quantity: daily_history(responses, quantity)
            for quantity in (COLD, HOT, HEAT)
        }
        self.login_count = 0
        self.refresh_count = 0
        self.refresh_fails = False

    # -- request handling -------------------------------------------------

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        payload = kwargs.get("json") or {}
        self.calls.append(payload)
        self.headers.append(dict(kwargs.get("headers") or {}))
        self.urls.append(url)

        if self.status != 200:
            return FakeResponse(self.status, {})

        query = payload.get("query", "")
        variables = payload.get("variables") or {}

        if "loginWithEmailAndPassword" in query:
            return self._login()
        if "refreshToken(" in query:
            return self._refresh()
        if self.query_error:
            return FakeResponse(200, {"data": None, "errors": [
                {"message": self.query_error}]})
        if "me {" in query:
            return FakeResponse(200, {"data": self.responses["me"]})
        if "tenantUnits" in query:
            return FakeResponse(200, {"data": {"tenantUnits": self.units}})
        if "unitQuantityKpis" in query:
            return self._kpis(variables)
        if "tenantGraph" in query:
            return self._graph(variables)

        return FakeResponse(200, {"data": None, "errors": [
            {"message": f"unhandled query: {query[:60]}"}]})

    # -- individual operations -------------------------------------------

    def _login(self) -> FakeResponse:
        self.login_count += 1
        if self.login_error:
            return FakeResponse(200, {"data": None, "errors": [
                {"message": self.login_error}]})
        return FakeResponse(200, {"data": {"loginWithEmailAndPassword": {
            "ok": {"token": make_jwt(), "refreshToken": "refresh-token"}}}})

    def _refresh(self) -> FakeResponse:
        self.refresh_count += 1
        if self.refresh_fails:
            return FakeResponse(200, {"data": None, "errors": [
                {"message": "invalid-token"}]})
        return FakeResponse(200, {"data": {"refreshToken": {
            "ok": {"token": make_jwt(), "refreshToken": "refresh-token-2"}}}})

    def _kpis(self, variables: dict[str, Any]) -> FakeResponse:
        quantity = (variables.get("input") or {}).get("quantity")
        stored = self.responses.get("kpis", {}).get(quantity)
        if stored is None:
            return FakeResponse(200, {"data": {"unitQuantityKpis": None}})
        return FakeResponse(200, {"data": stored})

    def _graph(self, variables: dict[str, Any]) -> FakeResponse:
        graph = variables.get("graph") or {}
        series_input = (graph.get("consumption") or {}).get("series") or [{}]
        quantity = (series_input[0].get("quantityDescriptor") or {}).get("quantity")

        begin = datetime.fromisoformat(graph["periodBegin"]).date()
        end = datetime.fromisoformat(graph["periodEnd"]).date()

        points = [
            (day, value)
            for day, value in self.history.get(quantity, [])
            if begin <= day <= end
        ]
        return FakeResponse(200, {"data": {"tenantGraph": {
            "timestamps": [f"{day.isoformat()}T00:00:00" for day, _ in points],
            "graphs": [{"consumption": {
                "quantityDescriptor": {"quantity": quantity},
                "values": [value for _, value in points],
            }}],
        }}})


class FakeSession:
    """aiohttp session stand-in that routes everything to TechemApiMock."""

    def __init__(self, api: TechemApiMock) -> None:
        self.api = api

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.api.post(url, **kwargs)


@pytest.fixture
def api_responses() -> dict[str, Any]:
    """The captured API responses."""
    return load_responses()


@pytest.fixture
def api(api_responses: dict[str, Any]) -> TechemApiMock:
    """A configurable fake Techem endpoint."""
    return TechemApiMock(api_responses)


@pytest.fixture
def session(api: TechemApiMock) -> FakeSession:
    """A fake aiohttp session backed by the fake endpoint."""
    return FakeSession(api)


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry for the fixture unit."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Testveien 1A",
        unique_id=MOCK_UNIQUE_ID,
        data={
            "email": MOCK_EMAIL,
            "password": MOCK_PASSWORD,
            "host": MOCK_HOST,
            CONF_OBJECT_ID: MOCK_OBJECT_ID,
        },
    )
