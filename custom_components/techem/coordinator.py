"""Data coordinator for the Techem integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TechemAuthError, TechemClient, TechemError
from .const import CONF_OBJECT_ID, DOMAIN, QUANTITIES, TechemQuantity
from .statistics_import import async_import_statistics

_LOGGER = logging.getLogger(__name__)

# Enough history for the rolling averages and to let the statistics resync
# window pick up readings Techem revised after the fact.
SERIES_WINDOW_DAYS = 35

# Readings arrive about two days late, so "the last seven days" means the last
# seven days that actually have data, not the last seven calendar days.
AVERAGE_DAYS = 7


@dataclass
class QuantityData:
    """Everything known about one quantity for one unit."""

    quantity: TechemQuantity
    year_to_date: float | None = None
    previous_year: float | None = None
    previous_period: float | None = None
    property_comparison: float | None = None
    rooms: dict[str, float] = field(default_factory=dict)
    last_reading_day: date | None = None
    last_reading_value: float | None = None
    daily_average: float | None = None
    previous_daily_average: float | None = None

    @property
    def year_change_percent(self) -> float | None:
        """Year to date against the same period last year, in percent."""
        return _percent_change(self.year_to_date, self.previous_year)

    @property
    def average_change_percent(self) -> float | None:
        """Recent daily average against the preceding stretch, in percent."""
        return _percent_change(self.daily_average, self.previous_daily_average)

    @property
    def property_comparison_percent(self) -> float | None:
        """Year to date against the average comparable unit, in percent."""
        return _percent_change(self.year_to_date, self.property_comparison)


def _percent_change(current: float | None, baseline: float | None) -> float | None:
    """Percent difference, or None when there is nothing to compare against."""
    if current is None or baseline is None or baseline == 0:
        return None
    return (current - baseline) / baseline * 100


class TechemCoordinator(DataUpdateCoordinator[dict[str, QuantityData]]):
    """Polls Techem and feeds both the live sensors and long-term statistics."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TechemClient,
        quantities: list[str],
        scan_interval: timedelta,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
            config_entry=entry,
        )
        self.client = client
        self.object_id: str = entry.data[CONF_OBJECT_ID]
        self.quantities = [q for q in quantities if q in QUANTITIES]
        self._statistics_lock = asyncio.Lock()

    async def _async_update_data(self) -> dict[str, QuantityData]:
        """Fetch KPIs and the recent daily series for every quantity."""
        today = date.today()
        year_start = date(today.year, 1, 1)
        series_start = today - timedelta(days=SERIES_WINDOW_DAYS)

        result: dict[str, QuantityData] = {}
        series_by_quantity: dict[str, list[tuple[date, float]]] = {}

        for key in self.quantities:
            quantity = QUANTITIES[key]
            data = QuantityData(quantity=quantity)

            try:
                kpis = await self.client.async_get_kpis(
                    self.object_id, key, year_start, today
                )
                series = await self.client.async_get_daily_series(
                    self.object_id, key, series_start, today
                )
            except TechemAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except TechemError as err:
                raise UpdateFailed(f"Could not fetch {key}: {err}") from err

            if kpis:
                data.year_to_date = _as_float(kpis.get("total"))
                data.previous_year = _as_float(kpis.get("previousYear"))
                data.previous_period = _as_float(kpis.get("previousPeriod"))
                data.property_comparison = _as_float(kpis.get("propertyComparison"))
                data.rooms = {
                    str(room["label"]): float(room["value"])
                    for room in kpis.get("rooms") or []
                    if room
                    and room.get("label") is not None
                    and _as_float(room.get("value")) is not None
                }

            if series:
                data.last_reading_day, data.last_reading_value = series[-1]
                recent = [value for _, value in series[-AVERAGE_DAYS:]]
                earlier = [
                    value for _, value in series[-2 * AVERAGE_DAYS : -AVERAGE_DAYS]
                ]
                if recent:
                    data.daily_average = sum(recent) / len(recent)
                if earlier:
                    data.previous_daily_average = sum(earlier) / len(earlier)

                series_by_quantity[key] = series

            result[key] = data

        self._schedule_statistics(series_by_quantity)
        return result

    def _schedule_statistics(
        self, series_by_quantity: dict[str, list[tuple[date, float]]]
    ) -> None:
        """Import statistics without holding up the coordinator refresh.

        The first import backfills years of history, which is far too slow to
        run inside `async_config_entry_first_refresh`, so it happens in the
        background and the sensors come up immediately.
        """
        if not series_by_quantity:
            return
        if self._statistics_lock.locked():
            _LOGGER.debug("Statistics import still running, skipping this cycle")
            return
        if self.config_entry is None:
            return

        self.config_entry.async_create_background_task(
            self.hass,
            self._async_import_statistics(series_by_quantity),
            name=f"{DOMAIN}_statistics_{self.object_id}",
        )

    async def _async_import_statistics(
        self, series_by_quantity: dict[str, list[tuple[date, float]]]
    ) -> None:
        """Import statistics for every quantity, one at a time."""
        async with self._statistics_lock:
            for key, series in series_by_quantity.items():
                try:
                    await async_import_statistics(
                        self.hass,
                        self.client,
                        self.object_id,
                        QUANTITIES[key],
                        series,
                    )
                except TechemError as err:
                    _LOGGER.warning("Statistics import failed for %s: %s", key, err)


def _as_float(value: object) -> float | None:
    """Coerce an API number, tolerating nulls and unexpected types."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
