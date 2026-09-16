"""Tests for unit and quantity discovery."""

from __future__ import annotations

from custom_components.techem.api import TechemClient
from custom_components.techem.discovery import async_validate_quantities, unit_label

from .conftest import FakeSession, TechemApiMock
from .const import COLD, HEAT, HOT, MOCK_EMAIL, MOCK_HOST, MOCK_OBJECT_ID, MOCK_PASSWORD, TOTAL_WATER


async def test_phantom_quantity_is_dropped(
    session: FakeSession, api_responses: dict
) -> None:
    """`total-water-volume` is advertised but returns nulls, so it is skipped.

    This is the reason quantities are probed rather than trusted.
    """
    client = TechemClient(session, MOCK_HOST, MOCK_EMAIL, MOCK_PASSWORD)
    await client.async_login()

    advertised = api_responses["tenantUnits"]["tenantUnits"][0]["treeInfo"]["quantities"]
    assert TOTAL_WATER in advertised, "fixture should still advertise the phantom"

    usable = await async_validate_quantities(client, MOCK_OBJECT_ID, advertised)

    assert set(usable) == {COLD, HOT, HEAT}
    assert TOTAL_WATER not in usable


async def test_unknown_quantity_is_ignored(session: FakeSession) -> None:
    """Quantities we have no metadata for are skipped, not guessed at."""
    client = TechemClient(session, MOCK_HOST, MOCK_EMAIL, MOCK_PASSWORD)
    await client.async_login()

    usable = await async_validate_quantities(
        client, MOCK_OBJECT_ID, ["something-new-from-techem", HOT]
    )
    assert usable == [HOT]


async def test_probe_failure_skips_quantity(
    session: FakeSession, api: TechemApiMock
) -> None:
    """An API error while probing drops the quantity instead of failing setup."""
    client = TechemClient(session, MOCK_HOST, MOCK_EMAIL, MOCK_PASSWORD)
    await client.async_login()
    api.query_error = "something-went-wrong"

    assert await async_validate_quantities(client, MOCK_OBJECT_ID, [HOT]) == []


def test_unit_label_uses_available_fields() -> None:
    """Labels are built from whatever the unit actually populates."""
    assert unit_label({
        "id": "x",
        "unit": {"street": "Testveien", "unitNumber": "H0101"},
    }) == "Testveien H0101"


def test_unit_label_falls_back_to_id() -> None:
    """A unit with no descriptive fields still gets a usable name."""
    assert unit_label({"id": "abc", "unit": {}}) == "Unit abc"
    assert unit_label({"id": "abc"}) == "Unit abc"
