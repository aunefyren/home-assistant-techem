"""Push Techem's daily readings into Home Assistant long-term statistics.

Techem reports one value per day, roughly two days late, and occasionally
revises a reading after the fact. Writing those numbers to a normal sensor
would stamp them with the time Home Assistant happened to poll, so the energy
dashboard would attribute Monday's water to Wednesday afternoon. External
statistics let us write each reading against the day it belongs to, and
rewriting a bucket overwrites it rather than double-counting.

Home Assistant only derives costs itself for entity sources, never for
external statistics, so when the user sets a price we also write a matching
cost statistic for the energy dashboard's "entity tracking total costs".
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import TechemClient, TechemError
from .const import DOMAIN, MAX_BACKFILL_YEARS, TechemQuantity

_LOGGER = logging.getLogger(__name__)

# How far back to hunt for the statistics bucket preceding the resync window.
# Needs to comfortably exceed the longest gap Techem leaves in a daily series.
SPLICE_LOOKBACK_DAYS = 30


def slugify_unit(object_id: str) -> str:
    """Reduce a Techem unit id to the charset statistic ids allow.

    Recorder's VALID_STATISTIC_ID rejects anything outside [a-z0-9_], any
    double underscore, and leading or trailing underscores, so runs of other
    characters collapse to a single separator and the edges are trimmed.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", object_id.lower()).strip("_")
    return slug or "unit"


def statistic_id_for(object_id: str, quantity: TechemQuantity) -> str:
    """Build the external statistic id for one unit and quantity."""
    quantity_slug = re.sub(r"[^a-z0-9]+", "_", quantity.key.lower()).strip("_")
    return f"{DOMAIN}:{slugify_unit(object_id)}_{quantity_slug}"


def cost_statistic_id_for(object_id: str, quantity: TechemQuantity) -> str:
    """Build the external statistic id for one unit and quantity's cost."""
    return f"{statistic_id_for(object_id, quantity)}_cost"


def _day_start(day: date) -> datetime:
    """Local midnight for a reading day, which is where its bucket goes."""
    return dt_util.start_of_local_day(day)


async def async_import_statistics(
    hass: HomeAssistant,
    client: TechemClient,
    object_id: str,
    quantity: TechemQuantity,
    recent_series: list[tuple[date, float]],
    price: float | None = None,
) -> None:
    """Import or refresh statistics for one quantity.

    On first run this backfills everything Techem still has. Afterwards it
    rewrites only the recent window, so revised readings are corrected without
    re-fetching years of history on every poll.

    With a `price`, a cost statistic is kept alongside at that flat price. It
    is spliced and rebuilt together with the consumption, so a changed price
    reaches only the days that get rewritten.
    """
    statistic_id = statistic_id_for(object_id, quantity)
    cost_id = cost_statistic_id_for(object_id, quantity) if price is not None else None

    series = recent_series
    baseline: float | None = None
    cost_baseline: float | None = None

    # `series` may be empty when Techem returns nothing for the recent window;
    # fall through to a rebuild rather than indexing into it.
    if series:
        baseline = await _async_sum_before(hass, statistic_id, series[0][0])
        if cost_id is not None and baseline is not None:
            cost_baseline = await _async_sum_before(hass, cost_id, series[0][0])

    if baseline is None or (cost_id is not None and cost_baseline is None):
        # Either nothing has been imported yet, a price was only just set, or
        # the recent window does not join up with what is already stored.
        # Rebuild from the beginning.
        try:
            series = await _async_fetch_full_history(client, object_id, quantity)
        except TechemError as err:
            _LOGGER.warning("Could not backfill history for %s: %s", statistic_id, err)
            return
        baseline = 0.0
        cost_baseline = 0.0

    if not series:
        return

    total = baseline
    statistics: list[StatisticData] = []
    for day, value in series:
        total += value
        statistics.append(StatisticData(start=_day_start(day), state=value, sum=total))

    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=None,
        source=DOMAIN,
        statistic_id=statistic_id,
        unit_class=quantity.unit_class,
        unit_of_measurement=quantity.unit,
    )

    async_add_external_statistics(hass, metadata, statistics)
    _LOGGER.debug(
        "Imported %d daily statistics for %s (%s to %s)",
        len(statistics),
        statistic_id,
        series[0][0],
        series[-1][0],
    )

    if cost_id is None or price is None or cost_baseline is None:
        return

    cost_total = cost_baseline
    costs: list[StatisticData] = []
    for day, value in series:
        cost = value * price
        cost_total += cost
        costs.append(StatisticData(start=_day_start(day), state=cost, sum=cost_total))

    cost_metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=None,
        source=DOMAIN,
        statistic_id=cost_id,
        unit_class=None,
        unit_of_measurement=hass.config.currency,
    )

    async_add_external_statistics(hass, cost_metadata, costs)


async def _async_sum_before(
    hass: HomeAssistant, statistic_id: str, day: date
) -> float | None:
    """Return the most recent running sum recorded before `day`.

    Techem skips days it has no reading for, so the bucket immediately before
    the window often does not exist. Look back over a stretch and take the
    latest bucket found; the days in between contributed nothing, so the sum
    still carries over correctly. Returns None only when nothing precedes the
    window, meaning it cannot be spliced onto the stored history.
    """
    end = _day_start(day)
    start = end - timedelta(days=SPLICE_LOOKBACK_DAYS)

    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {statistic_id},
        "hour",
        None,
        {"sum"},
    )

    rows = (stats or {}).get(statistic_id)
    if not rows:
        return None

    value = rows[-1].get("sum")
    return float(value) if isinstance(value, (int, float)) else None


async def _async_fetch_full_history(
    client: TechemClient, object_id: str, quantity: TechemQuantity
) -> list[tuple[date, float]]:
    """Fetch every daily reading Techem still holds, oldest first.

    Walks back a year at a time and stops at the first year with no data, so a
    long-standing account is backfilled fully without guessing a start date.
    """
    today = date.today()
    collected: dict[date, float] = {}

    for years_back in range(MAX_BACKFILL_YEARS):
        year = today.year - years_back
        period_begin = date(year, 1, 1)
        period_end = min(date(year, 12, 31), today)

        series = await client.async_get_daily_series(
            object_id, quantity.key, period_begin, period_end
        )
        if not series:
            # Stop once history runs out, but tolerate an empty current year:
            # early in January nothing has been reported yet.
            if collected or years_back >= 1:
                break
            continue

        collected.update(dict(series))

    return sorted(collected.items())
