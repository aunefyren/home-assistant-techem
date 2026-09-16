"""The Techem integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_EMAIL,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TechemAuthError, TechemClient, TechemError
from .const import CONF_OBJECT_ID, DEFAULT_API_HOST, DEFAULT_SCAN_INTERVAL_HOURS
from .coordinator import TechemCoordinator
from .discovery import async_validate_quantities

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

type TechemConfigEntry = ConfigEntry[TechemCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TechemConfigEntry) -> bool:
    """Set up Techem from a config entry."""
    session = async_get_clientsession(hass)
    client = TechemClient(
        session,
        entry.data.get(CONF_HOST, DEFAULT_API_HOST),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )
    object_id = entry.data[CONF_OBJECT_ID]

    try:
        await client.async_login()
        units = await client.async_get_units()
    except TechemAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except TechemError as err:
        raise ConfigEntryNotReady(f"Could not reach Techem: {err}") from err

    unit = next((u for u in units if str(u.get("id")) == object_id), None)
    if unit is None:
        raise ConfigEntryAuthFailed(
            f"Unit {object_id} is no longer available on this account"
        )

    advertised = (unit.get("treeInfo") or {}).get("quantities") or []
    try:
        quantities = await async_validate_quantities(client, object_id, advertised)
    except TechemError as err:
        raise ConfigEntryNotReady(f"Could not read Techem quantities: {err}") from err

    if not quantities:
        raise ConfigEntryNotReady("Techem reported no usable quantities for this unit")

    _LOGGER.debug("Techem unit %s exposes quantities %s", object_id, quantities)

    hours = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_HOURS)
    coordinator = TechemCoordinator(
        hass, entry, client, quantities, timedelta(hours=hours)
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TechemConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: TechemConfigEntry) -> None:
    """Reload when the poll interval changes."""
    await hass.config_entries.async_reload(entry.entry_id)
