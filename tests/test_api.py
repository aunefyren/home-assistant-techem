"""Tests for the Techem API client."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.techem.api import (
    TechemAuthError,
    TechemClient,
    TechemConnectionError,
    TechemError,
    _jwt_expiry,
)

from .conftest import FakeSession, TechemApiMock, make_jwt
from .const import HOT, MOCK_EMAIL, MOCK_HOST, MOCK_OBJECT_ID, MOCK_PASSWORD


def build(session: FakeSession, host: str = MOCK_HOST) -> TechemClient:
    return TechemClient(session, host, MOCK_EMAIL, MOCK_PASSWORD)


async def test_login_stores_token(session: FakeSession, api: TechemApiMock) -> None:
    """A successful login yields a usable session."""
    client = build(session)
    profile = await client.async_verify_credentials()

    assert profile["email"] == MOCK_EMAIL
    assert api.login_count == 1


async def test_invalid_credentials_raise_auth_error(
    session: FakeSession, api: TechemApiMock
) -> None:
    """Techem's invalid-credentials message maps to an auth error."""
    api.login_error = "invalid-credentials"
    with pytest.raises(TechemAuthError):
        await build(session).async_login()


async def test_login_required_maps_to_auth_error(
    session: FakeSession, api: TechemApiMock
) -> None:
    """A login-required error on a query is an auth failure, not a generic one."""
    api.query_error = "login-required"
    client = build(session)
    await client.async_login()
    with pytest.raises(TechemAuthError):
        await client.async_get_units()


async def test_other_graphql_error_is_not_auth(
    session: FakeSession, api: TechemApiMock
) -> None:
    """Role errors are real failures but must not trigger reauthentication."""
    api.query_error = "incorrect-role-for-resource"
    client = build(session)
    await client.async_login()
    with pytest.raises(TechemError) as err:
        await client.async_get_units()
    assert not isinstance(err.value, TechemAuthError)


async def test_http_error_maps_to_connection_error(
    session: FakeSession, api: TechemApiMock
) -> None:
    """A 500 is a connection problem, so setup retries rather than reauthing."""
    api.status = 500
    with pytest.raises(TechemConnectionError):
        await build(session).async_login()


async def test_401_maps_to_auth_error(
    session: FakeSession, api: TechemApiMock
) -> None:
    """An unauthorised response is an auth failure."""
    api.status = 401
    with pytest.raises(TechemAuthError):
        await build(session).async_login()


async def test_expired_token_is_refreshed_not_relogged(
    session: FakeSession, api: TechemApiMock
) -> None:
    """An expiring token is renewed with the refresh token."""
    client = build(session)
    await client.async_login()
    assert api.login_count == 1

    # Force the stored token past its expiry margin.
    client._token = make_jwt(expires_in=-10)
    client._token_expires = _jwt_expiry(client._token)

    await client.async_get_units()
    assert api.refresh_count == 1
    assert api.login_count == 1, "refresh should avoid a full login"


async def test_refresh_failure_falls_back_to_login(
    session: FakeSession, api: TechemApiMock
) -> None:
    """If the refresh token is rejected, log in from scratch."""
    client = build(session)
    await client.async_login()
    api.refresh_fails = True

    client._token = make_jwt(expires_in=-10)
    client._token_expires = _jwt_expiry(client._token)

    await client.async_get_units()
    assert api.refresh_count == 1
    assert api.login_count == 2


async def test_url_and_headers(session: FakeSession, api: TechemApiMock) -> None:
    """Requests go to the configured host with an honest user agent."""
    await build(session).async_login()

    assert api.urls[0] == f"https://{MOCK_HOST}/analytics/graphql"
    headers = api.headers[0]
    assert "home-assistant-techem" in headers["User-Agent"]
    assert "Mozilla" not in headers["User-Agent"]
    # The Norwegian portal domain is known, so Origin is sent.
    assert headers["Origin"] == "https://beboer.techemadmin.no"


async def test_unknown_host_omits_origin(session: FakeSession, api: TechemApiMock) -> None:
    """For hosts whose portal we do not know, Origin is left off entirely."""
    await build(session, host="techemadmin.dk").async_login()

    assert api.urls[0] == "https://techemadmin.dk/analytics/graphql"
    assert "Origin" not in api.headers[0]
    assert "Referer" not in api.headers[0]


async def test_daily_series_skips_gaps(session: FakeSession) -> None:
    """Null buckets are dropped rather than becoming zeroes."""
    client = build(session)
    await client.async_login()

    series = await client.async_get_daily_series(
        MOCK_OBJECT_ID, HOT, date(2026, 8, 12), date(2026, 9, 15)
    )

    assert len(series) == 34
    assert series[0][0] == date(2026, 8, 12)
    assert series[-1][0] == date(2026, 9, 14)
    assert all(isinstance(value, float) for _, value in series)


async def test_daily_series_empty_range(session: FakeSession) -> None:
    """A range Techem has no data for yields an empty series, not an error."""
    client = build(session)
    await client.async_login()

    series = await client.async_get_daily_series(
        MOCK_OBJECT_ID, HOT, date(2020, 1, 1), date(2020, 12, 31)
    )
    assert series == []


def test_jwt_expiry_reads_exp() -> None:
    """The expiry claim is read without verifying the signature."""
    assert _jwt_expiry(make_jwt(expires_in=3600)) is not None


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b", "a.!!!.c"])
def test_jwt_expiry_tolerates_junk(token: str) -> None:
    """A token we cannot parse yields no expiry rather than raising."""
    assert _jwt_expiry(token) is None
