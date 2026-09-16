"""Shared constants for the Techem tests."""

from __future__ import annotations

MOCK_EMAIL = "tenant@example.com"
MOCK_PASSWORD = "hunter2"
MOCK_HOST = "techemadmin.no"

# Matches the id pinned by dev/make_fixtures.py.
MOCK_OBJECT_ID = "objecttest0000000001"
MOCK_UNIQUE_ID = f"{MOCK_HOST}:{MOCK_OBJECT_ID}"

COLD = "cold-water-volume"
HOT = "hot-water-volume"
HEAT = "heat-energy"
TOTAL_WATER = "total-water-volume"
