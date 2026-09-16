"""Tests for the Techem sensors."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeSession

# Raw figures Techem reports are enabled; arithmetic on them is not.
ENABLED_SUFFIXES = {
    "year_to_date", "previous_year", "building_average",
    "daily_average", "last_reading", "last_reading_date",
}
DISABLED_SUFFIXES = {
    "year_change", "average_change", "property_comparison",
    "previous_daily_average",
}


@pytest.fixture(autouse=True)
def recorder(recorder_mock):
    """The integration depends on the recorder, so tests need it set up."""
    return


@pytest.fixture
def patched_setup(session: FakeSession):
    """Fake the API and skip the statistics import.

    Statistics are covered separately; here they would only add a background
    task racing the assertions.
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
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entity_count(
    hass: HomeAssistant, patched_setup, mock_config_entry: MockConfigEntry
) -> None:
    """Three quantities times ten sensors, enabled or not."""
    await setup_entry(hass, mock_config_entry)

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        registry, mock_config_entry.entry_id
    )
    assert len(entries) == 3 * (len(ENABLED_SUFFIXES) + len(DISABLED_SUFFIXES))


async def test_raw_sensors_enabled_derived_disabled(
    hass: HomeAssistant, patched_setup, mock_config_entry: MockConfigEntry
) -> None:
    """The numbers Techem reports ship enabled; derived ones do not.

    A percentage is reproducible from the raw figures, so it should never be
    the only thing visible by default.
    """
    await setup_entry(hass, mock_config_entry)

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        registry, mock_config_entry.entry_id
    )

    # "previous_daily_average" also ends with "daily_average", so always take
    # the longest matching suffix.
    all_suffixes = sorted(
        ENABLED_SUFFIXES | DISABLED_SUFFIXES, key=len, reverse=True
    )

    for entry in entries:
        suffix = next(
            (s for s in all_suffixes if entry.unique_id.endswith(f"_{s}")),
            None,
        )
        assert suffix is not None, entry.unique_id
        if suffix in DISABLED_SUFFIXES:
            assert entry.disabled_by is not None, entry.unique_id
        else:
            assert entry.disabled_by is None, entry.unique_id


async def test_statistic_id_attribute(
    hass: HomeAssistant, patched_setup, mock_config_entry: MockConfigEntry
) -> None:
    """Every sensor points at its long-term statistics."""
    await setup_entry(hass, mock_config_entry)

    states = [
        state for state in hass.states.async_all("sensor")
        if state.attributes.get("statistic_id")
    ]
    assert states
    assert all(
        state.attributes["statistic_id"].startswith("techem:")
        for state in states
    )
