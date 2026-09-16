"""Tests for the long-term statistics import."""

from __future__ import annotations

import re

import pytest

from custom_components.techem.const import QUANTITIES
from custom_components.techem.statistics_import import (
    slugify_unit,
    statistic_id_for,
)

from .const import COLD, HEAT, HOT

# The recorder's own rule for external statistic ids.
VALID_STATISTIC_ID = re.compile(
    r"^(?!.+__)(?!_)[\da-z_]+(?<!_):(?!_)[\da-z_]+(?<!_)$"
)


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
