#!/usr/bin/env python3
"""Turn a redacted probe dump into test fixtures.

Tests are worth more when they run against response shapes the real API
actually produced, rather than shapes we imagined. This reads
techem-probe-scrubbed.json and writes tests/fixtures/api_responses.json with
the placeholder identifiers swapped for stable, obviously fake ones.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

# Stable stand-ins so fixtures stay readable and carry nothing real.
UNIT_OBJECT_ID = "objecttest0000000001"
UNIT_ID = "unit0001"

PLACEHOLDER = re.compile(r"^<(\w+):(\d+)>$")

FAKE = {
    "id": lambda n: f"id{n}",
    "name": lambda n: "Testveien 1A",
    "email": lambda n: "tenant@example.com",
    "street": lambda n: "Testveien",
    "location": lambda n: "1A",
    "unitNumber": lambda n: "H0101",
    "address": lambda n: "Testveien 1",
    "city": lambda n: "Oslo",
    "zipcode": lambda n: "0001",
    "number": lambda n: "12345678",
    "wmbusId": lambda n: "87654321",
    "tepdid": lambda n: "TEPD0001",
    "externalIdentifier": lambda n: "EXT0001",
    "ModelId": lambda n: f"model{n}",
}


def defake(obj):
    """Replace <key:n> placeholders with deterministic fake values."""
    if isinstance(obj, dict):
        return {k: defake(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [defake(v) for v in obj]
    if isinstance(obj, str) and (m := PLACEHOLDER.match(obj)):
        key, num = m.group(1), m.group(2)
        maker = FAKE.get(key)
        return maker(num) if maker else f"{key}{num}"
    return obj


def main() -> int:
    """Write the fixture file from a probe dump."""
    src = pathlib.Path("techem-probe-scrubbed.json")
    if not src.exists():
        print(f"{src} not found; run dev/probe_api.py first", file=sys.stderr)
        return 1

    queries = json.loads(src.read_text())["queries"]
    out: dict = {"_source": "derived from a redacted dev/probe_api.py run"}

    def grab(label: str):
        entry = queries.get(label)
        if not entry:
            return None
        response = entry["response"]
        if "data" not in response:
            return None
        return defake(response["data"])

    units = grab("tenantUnits")
    if units:
        # Pin the unit object id so tests can reference it by name.
        for unit in units.get("tenantUnits") or []:
            unit["id"] = UNIT_OBJECT_ID
            if unit.get("unit"):
                unit["unit"]["id"] = UNIT_ID
        out["tenantUnits"] = units

    out["me"] = grab("me")

    for quantity in (
        "cold-water-volume",
        "hot-water-volume",
        "heat-energy",
        "total-water-volume",
    ):
        if (kpis := grab(f"u0.kpis.{quantity}")) is not None:
            out.setdefault("kpis", {})[quantity] = kpis
        for resolution in ("day", "hour", "month"):
            if (g := grab(f"u0.graph.{quantity}.{resolution}")) is not None:
                out.setdefault("graph", {}).setdefault(quantity, {})[resolution] = g

    dest = pathlib.Path("tests/fixtures/api_responses.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"wrote {dest}")
    print("  unit object id:", UNIT_OBJECT_ID)
    print("  kpis:", sorted(out.get("kpis", {})))
    print("  graph:", sorted(out.get("graph", {})))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
