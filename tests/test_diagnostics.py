"""Tests for the Techem diagnostics."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.techem.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import FakeSession
from .const import COLD, HEAT, HOT, MOCK_EMAIL, MOCK_OBJECT_ID, MOCK_PASSWORD


@pytest.fixture
def patched_setup(session: FakeSession):
    """Fake the API and skip the statistics import."""
    with (
        patch(
            "custom_components.techem.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.techem.coordinator.TechemCoordinator"
            "._schedule_statistics"
        ),
    ):
        yield session


async def get_diagnostics(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """Set the entry up and return its diagnostics."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return await async_get_config_entry_diagnostics(hass, entry)


async def test_credentials_are_redacted(
    hass: HomeAssistant, patched_setup, mock_config_entry: MockConfigEntry
) -> None:
    """Diagnostics get attached to issues, so they must carry no secrets."""
    result = await get_diagnostics(hass, mock_config_entry)

    dumped = str(result)
    assert MOCK_PASSWORD not in dumped
    assert MOCK_EMAIL not in dumped
    assert MOCK_OBJECT_ID not in dumped, "the unit id identifies the home"


async def test_statistic_id_does_not_leak_the_unit(
    hass: HomeAssistant, patched_setup, mock_config_entry: MockConfigEntry
) -> None:
    """The unit id is redacted, so it must not reappear inside statistic ids."""
    result = await get_diagnostics(hass, mock_config_entry)

    for quantity in result["quantities"].values():
        assert quantity["statistic_id"].startswith("techem:REDACTED_")


async def test_consumption_values_are_kept(
    hass: HomeAssistant, patched_setup, mock_config_entry: MockConfigEntry
) -> None:
    """Redaction must not strip the numbers that make diagnostics useful."""
    result = await get_diagnostics(hass, mock_config_entry)

    assert set(result["quantities"]) == {COLD, HOT, HEAT}
    hot = result["quantities"][HOT]
    assert hot["year_to_date"] == pytest.approx(18.607)
    assert hot["last_reading_day"] == "2026-09-14"
    assert hot["room_count"] == 1
    assert result["last_update_success"] is True
