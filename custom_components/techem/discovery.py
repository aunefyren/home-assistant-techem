"""Discovery helpers shared by setup and the config flow."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from .api import TechemClient, TechemError
from .const import QUANTITIES

_LOGGER = logging.getLogger(__name__)


async def async_validate_quantities(
    client: TechemClient, object_id: str, advertised: list[str]
) -> list[str]:
    """Narrow the advertised quantities down to the ones that return data.

    `treeInfo.quantities` over-reports: `total-water-volume` is listed but
    every KPI for it comes back null. Ask before creating entities.
    """
    today = date.today()
    year_start = date(today.year, 1, 1)

    usable: list[str] = []
    for key in advertised:
        if key not in QUANTITIES:
            _LOGGER.debug("Ignoring unsupported Techem quantity %s", key)
            continue
        try:
            kpis = await client.async_get_kpis(object_id, key, year_start, today)
        except TechemError as err:
            _LOGGER.debug("Could not probe quantity %s: %s", key, err)
            continue
        if kpis and kpis.get("total") is not None:
            usable.append(key)

    return usable


def unit_label(unit: dict[str, Any]) -> str:
    """Build a human label for a unit from whatever fields are populated."""
    details = unit.get("unit") or {}
    parts = [
        details.get("street"),
        details.get("unitNumber"),
        details.get("location"),
        details.get("name"),
    ]
    label = " ".join(str(part) for part in parts if part)
    return label or f"Unit {unit.get('id')}"
