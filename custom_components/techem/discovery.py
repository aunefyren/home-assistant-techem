"""Discovery helpers shared by setup and the config flow."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from typing import Any

from .api import TechemClient, TechemError
from .const import QUANTITIES

_LOGGER = logging.getLogger(__name__)


async def async_validate_quantities(
    client: TechemClient, object_id: str, candidates: Iterable[str] | None = None
) -> list[str]:
    """Narrow the candidate quantities down to the ones that return data.

    Techem no longer advertises a unit's quantities (`treeInfo` was dropped
    from the schema), and when it did it over-reported anyway. So every
    quantity we know about is probed, and only those with data are kept.
    """
    today = date.today()
    year_start = date(today.year, 1, 1)

    usable: list[str] = []
    for key in QUANTITIES if candidates is None else candidates:
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
