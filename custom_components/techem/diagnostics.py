"""Diagnostics for the Techem integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import TechemConfigEntry
from .const import CONF_OBJECT_ID
from .statistics_import import slugify_unit, statistic_id_for

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, CONF_OBJECT_ID, "unique_id"}


def _mask_unit(statistic_id: str, object_id: str) -> str:
    """Replace the unit id inside a statistic id with a placeholder."""
    return statistic_id.replace(slugify_unit(object_id), "REDACTED")


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TechemConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    quantities: dict[str, Any] = {}
    for key, data in (coordinator.data or {}).items():
        quantities[key] = {
            "year_to_date": data.year_to_date,
            "previous_year": data.previous_year,
            "previous_period": data.previous_period,
            "property_comparison": data.property_comparison,
            "daily_average": data.daily_average,
            "previous_daily_average": data.previous_daily_average,
            "last_reading_day": (
                data.last_reading_day.isoformat() if data.last_reading_day else None
            ),
            "last_reading_value": data.last_reading_value,
            "room_count": len(data.rooms),
            # The full statistic id embeds the unit id, which is redacted
            # above; keep the part that is useful for debugging.
            "statistic_id": _mask_unit(
                statistic_id_for(coordinator.object_id, data.quantity),
                coordinator.object_id,
            ),
        }

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "quantities": quantities,
        "last_update_success": coordinator.last_update_success,
    }
