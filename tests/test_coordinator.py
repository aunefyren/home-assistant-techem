"""Tests for the coordinator and the entities it feeds."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.techem.coordinator import _percent_change

from .conftest import FakeSession, TechemApiMock
from .const import COLD, HEAT, HOT

# Derived from the captured series; see dev/make_fixtures.py.
EXPECTED_DAILY_AVERAGE = {
    HOT: 0.05414285714285784,
    COLD: 0.20257142857142948,
    HEAT: 4.0,
}
EXPECTED_PREVIOUS_DAILY_AVERAGE = {
    HOT: 0.084857142857142,
    COLD: 0.2958571428571385,
    HEAT: 3.4285714285714284,
}
EXPECTED_YEAR_TO_DATE = {HOT: 18.607, COLD: 56.490999999999985, HEAT: 3252.0}


@pytest.fixture
def patched_setup(session: FakeSession):
    """Fake the API and skip the statistics import.

    The import runs as a background task; silencing it keeps these tests
    focused on the coordinator's own output.
    """
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


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry to hass and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


# -- percentage helper ----------------------------------------------------


@pytest.mark.parametrize(
    ("current", "baseline", "expected"),
    [
        (110.0, 100.0, 10.0),
        (90.0, 100.0, -10.0),
        (100.0, 100.0, 0.0),
        # Nothing to compare against must not raise.
        (100.0, 0.0, None),
        (None, 100.0, None),
        (100.0, None, None),
        (None, None, None),
    ],
)
def test_percent_change(current, baseline, expected) -> None:
    """Percent change handles the degenerate cases January will produce."""
    assert _percent_change(current, baseline) == expected


# -- coordinator ----------------------------------------------------------


async def test_setup_creates_expected_quantities(
    hass: HomeAssistant, patched_setup, mock_config_entry: MockConfigEntry
) -> None:
    """Only the three real quantities are set up."""
    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    coordinator = mock_config_entry.runtime_data
    assert set(coordinator.quantities) == {COLD, HOT, HEAT}


@pytest.mark.parametrize("quantity", [COLD, HOT, HEAT])
async def test_coordinator_values(
    hass: HomeAssistant,
    patched_setup,
    mock_config_entry: MockConfigEntry,
    quantity: str,
) -> None:
    """Totals and averages match what the captured data implies."""
    await setup_entry(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data[quantity]

    assert data.year_to_date == pytest.approx(EXPECTED_YEAR_TO_DATE[quantity])
    assert data.daily_average == pytest.approx(EXPECTED_DAILY_AVERAGE[quantity])
    assert data.previous_daily_average == pytest.approx(
        EXPECTED_PREVIOUS_DAILY_AVERAGE[quantity]
    )
    # Readings arrive about two days late; the last one is not today.
    assert data.last_reading_day == date(2026, 9, 14)


async def test_rooms_are_captured(
    hass: HomeAssistant, patched_setup, mock_config_entry: MockConfigEntry
) -> None:
    """The per-room split is retained for the entity attributes."""
    await setup_entry(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data[HOT]
    assert data.rooms == {"Bad": pytest.approx(18.607)}


async def test_auth_failure_triggers_reauth(
    hass: HomeAssistant,
    patched_setup,
    api: TechemApiMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Rejected credentials put the entry into the reauth state."""
    api.login_error = "invalid-credentials"
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_connection_failure_retries(
    hass: HomeAssistant,
    patched_setup,
    api: TechemApiMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A server error leaves the entry retrying rather than erroring out."""
    api.status = 500
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(
    hass: HomeAssistant, patched_setup, mock_config_entry: MockConfigEntry
) -> None:
    """The entry unloads cleanly."""
    await setup_entry(hass, mock_config_entry)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
