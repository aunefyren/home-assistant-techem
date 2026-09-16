"""Tests for the long-term statistics import."""

from __future__ import annotations

import re
from datetime import date

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.techem.api import TechemClient
from custom_components.techem.const import QUANTITIES
from custom_components.techem.statistics_import import (
    async_import_statistics,
    slugify_unit,
    statistic_id_for,
)

from .conftest import FakeSession, TechemApiMock
from .const import COLD, HEAT, HOT, MOCK_EMAIL, MOCK_HOST, MOCK_OBJECT_ID, MOCK_PASSWORD

# The recorder's own rule for external statistic ids.
VALID_STATISTIC_ID = re.compile(r"^(?!.+__)(?!_)[\da-z_]+(?<!_):(?!_)[\da-z_]+(?<!_)$")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("objecttest0000000001", "objecttest0000000001"),
        ("ABC-123", "abc_123"),
        ("550e8400-e29b-41d4-a716", "550e8400_e29b_41d4_a716"),
        # Runs of separators must not become a double underscore.
        ("abc--def", "abc_def"),
        # Edges must not be left dangling.
        ("-leading-and-trailing-", "leading_and_trailing"),
        ("UPPER.Case_Id", "upper_case_id"),
        # Nothing usable survives, so fall back rather than emit an empty id.
        ("", "unit"),
        ("///", "unit"),
    ],
)
def test_slugify_unit(raw: str, expected: str) -> None:
    """Unit ids are reduced to the charset statistic ids allow."""
    assert slugify_unit(raw) == expected


@pytest.mark.parametrize("quantity_key", [COLD, HOT, HEAT])
@pytest.mark.parametrize(
    "object_id",
    [
        "objecttest0000000001",
        "abc--def",
        "-leading-and-trailing-",
        "550e8400-e29b-41d4-a716-446655440000",
        "",
    ],
)
def test_statistic_ids_are_accepted_by_recorder(
    object_id: str, quantity_key: str
) -> None:
    """Every id we can generate must satisfy the recorder's pattern."""
    statistic_id = statistic_id_for(object_id, QUANTITIES[quantity_key])
    assert VALID_STATISTIC_ID.match(statistic_id), statistic_id
    assert statistic_id.startswith("techem:")


def test_statistic_ids_are_distinct_per_quantity() -> None:
    """Quantities on one unit must not collide."""
    ids = {
        statistic_id_for("objecttest0000000001", QUANTITIES[key])
        for key in (COLD, HOT, HEAT)
    }
    assert len(ids) == 3


# -- the import itself ----------------------------------------------------


async def read_sums(
    hass: HomeAssistant, statistic_id: str
) -> list[tuple[date, float, float]]:
    """Return (day, state, sum) for every stored bucket, oldest first."""
    await async_wait_recording_done(hass)

    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.as_utc(dt_util.parse_datetime("2020-01-01T00:00:00+00:00")),
        None,
        {statistic_id},
        "hour",
        None,
        {"state", "sum"},
    )
    rows = stats.get(statistic_id, [])
    return [
        (
            dt_util.as_local(dt_util.utc_from_timestamp(row["start"])).date(),
            row["state"],
            row["sum"],
        )
        for row in rows
    ]


@pytest.fixture
def client(session: FakeSession) -> TechemClient:
    """Return a logged-in client over the fake endpoint."""
    return TechemClient(session, MOCK_HOST, MOCK_EMAIL, MOCK_PASSWORD)


async def test_backfill_when_nothing_stored(
    hass: HomeAssistant, client: TechemClient, api: TechemApiMock
) -> None:
    """With no statistics yet, the full history is fetched and imported."""
    await client.async_login()
    quantity = QUANTITIES[HOT]
    history = api.history[HOT]

    await async_import_statistics(hass, client, MOCK_OBJECT_ID, quantity, history)

    rows = await read_sums(hass, statistic_id_for(MOCK_OBJECT_ID, quantity))
    assert len(rows) == len(history)
    assert rows[0][0] == history[0][0]
    assert rows[-1][0] == history[-1][0]


async def test_sums_are_running_totals(
    hass: HomeAssistant, client: TechemClient, api: TechemApiMock
) -> None:
    """Each bucket's sum is the cumulative total, as the recorder expects."""
    await client.async_login()
    quantity = QUANTITIES[HOT]
    history = api.history[HOT]

    await async_import_statistics(hass, client, MOCK_OBJECT_ID, quantity, history)
    rows = await read_sums(hass, statistic_id_for(MOCK_OBJECT_ID, quantity))

    running = 0.0
    for (_, state, total), (_, value) in zip(rows, history, strict=True):
        running += value
        assert state == pytest.approx(value)
        assert total == pytest.approx(running)

    assert rows[-1][2] == pytest.approx(sum(v for _, v in history))


async def test_revised_reading_is_corrected_not_double_counted(
    hass: HomeAssistant, client: TechemClient, api: TechemApiMock
) -> None:
    """Re-importing a window overwrites buckets rather than adding to them.

    Techem revises readings after the fact, so this is the behaviour that
    keeps the energy dashboard honest.
    """
    await client.async_login()
    quantity = QUANTITIES[HOT]
    statistic_id = statistic_id_for(MOCK_OBJECT_ID, quantity)
    history = list(api.history[HOT])

    await async_import_statistics(hass, client, MOCK_OBJECT_ID, quantity, history)
    before = await read_sums(hass, statistic_id)
    original_total = before[-1][2]

    # Techem revises the last day upwards by 1.0.
    revised_day, revised_value = history[-1]
    api.history[HOT][-1] = (revised_day, revised_value + 1.0)

    # Only the recent window is re-sent, spliced onto the stored history.
    await async_import_statistics(
        hass, client, MOCK_OBJECT_ID, quantity, api.history[HOT][-5:]
    )
    after = await read_sums(hass, statistic_id)

    assert len(after) == len(before), "revision must not add buckets"
    assert after[-1][1] == pytest.approx(revised_value + 1.0)
    assert after[-1][2] == pytest.approx(original_total + 1.0)


async def test_empty_recent_series_does_not_raise(
    hass: HomeAssistant, client: TechemClient, api: TechemApiMock
) -> None:
    """An empty window falls back to a rebuild instead of indexing off the end."""
    await client.async_login()
    quantity = QUANTITIES[HOT]

    await async_import_statistics(
        hass, client, MOCK_OBJECT_ID, quantity, api.history[HOT]
    )
    # Techem returns nothing for the recent window on a later poll.
    await async_import_statistics(hass, client, MOCK_OBJECT_ID, quantity, [])

    rows = await read_sums(hass, statistic_id_for(MOCK_OBJECT_ID, quantity))
    assert len(rows) == len(api.history[HOT])


async def test_gap_before_window_still_splices(
    hass: HomeAssistant, client: TechemClient, api: TechemApiMock
) -> None:
    """A missing day before the window must not force a full rebuild.

    Techem omits days with no reading, so the bucket immediately before the
    resync window often does not exist.
    """
    await client.async_login()
    quantity = QUANTITIES[HOT]
    history = list(api.history[HOT])

    # Drop the day directly before the window we will re-send.
    del history[-6]
    api.history[HOT] = history

    await async_import_statistics(hass, client, MOCK_OBJECT_ID, quantity, history)
    before = await read_sums(hass, statistic_id_for(MOCK_OBJECT_ID, quantity))

    await async_import_statistics(hass, client, MOCK_OBJECT_ID, quantity, history[-4:])
    after = await read_sums(hass, statistic_id_for(MOCK_OBJECT_ID, quantity))

    assert len(after) == len(before)
    assert after[-1][2] == pytest.approx(before[-1][2])
