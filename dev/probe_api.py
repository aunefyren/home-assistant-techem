#!/usr/bin/env python3
"""One-off probe of the Techem GraphQL API.

Logs in, discovers your unit(s) and meters, then runs every query shape the
integration is likely to need and dumps the responses.

Credentials never leave your machine. Two files are written:

  techem-probe-raw.json        full responses, NOT redacted -- keep private
  techem-probe-scrubbed.json   same, with identifiers redacted -- safe to share

Only the scrubbed file is meant to be shared. Look it over before you do.

Usage:
    TECHEM_EMAIL=you@example.com python3 dev/probe_api.py
    TECHEM_EMAIL=you@example.com TECHEM_HOST=techemadmin.dk python3 dev/probe_api.py
    (password is prompted for, never taken from argv)
"""
from __future__ import annotations

import datetime as dt
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Techem runs the same platform under a few country domains. Override with
# TECHEM_HOST=techemadmin.dk for the Danish server.
HOST = os.environ.get("TECHEM_HOST", "techemadmin.no")
URL = f"https://{HOST}/analytics/graphql"
UA = "ha-techem-probe/0.1 (+https://github.com/aunefyren/home-assistant-techem)"

# Keys whose values identify you, your home, or your meters. Redacted in the
# shared dump; consumption numbers are deliberately kept.
REDACT_KEYS = {
    "token", "refreshToken", "email", "name", "address", "street", "location",
    "city", "zipcode", "number", "unitNumber", "wmbusId", "tepdid",
    "externalIdentifier", "id", "ModelId",
}

_redactions: dict[str, str] = {}


def post(query: str, variables: dict | None = None, token: str | None = None,
         timeout: int = 90) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "User-Agent": UA,
        "Origin": "https://beboer.techemadmin.no",
        "Referer": "https://beboer.techemadmin.no/",
    }
    if token:
        headers["Authorization"] = f"JWT {token}"
    req = urllib.request.Request(URL, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        return {"_httpError": err.code, "_body": err.read().decode()[:2000]}
    except Exception as err:  # noqa: BLE001 - probe script, report and move on
        return {"_error": repr(err)}


def redact(obj, key: str | None = None):
    """Replace identifying values with stable placeholders, keeping shape."""
    if isinstance(obj, dict):
        return {k: redact(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v, key) for v in obj]
    if key in REDACT_KEYS and isinstance(obj, (str, int)) and obj != "":
        token = f"<{key}:{_redactions.setdefault(f'{key}:{obj}', str(len(_redactions)))}>"
        return token
    return obj


def day(offset: int) -> str:
    return (dt.date.today() - dt.timedelta(days=offset)).isoformat() + "T00:00:00"


def jan1(years_ago: int = 0) -> str:
    return f"{dt.date.today().year - years_ago}-01-01T00:00:00"


LOGIN = """
mutation Login($credentials: CredentialsInput!) {
  loginWithEmailAndPassword(credentials: $credentials) { ok { token refreshToken } }
}
"""

ME = "{ me { id name email language } }"

# Asking for units + children + grandchildren + meters in one query times out.
# Staged instead: a cheap listing first, then per-unit detail.
UNITS = """
{
  tenantUnits {
    id
    treeInfo { quantities }
    childrenCount { property section unit group operationalGroup measurementPoint }
    unit { id unitUniqueId name size street location unitNumber }
  }
}
"""

UNIT_CHILDREN = """
query UnitChildren($id: ID!) {
  object(withId: $id) {
    id
    children {
      id
      treeInfo { quantities }
      measurementPoint { id name quantity room }
      group { id quantity operational }
    }
  }
}
"""

UNIT_METERS = """
query UnitMeters($id: ID!) {
  object(withId: $id) {
    id
    children {
      id
      group {
        id quantity operational
        meter { id number wmbusId roomName external originChannel fromDate toDate }
      }
    }
  }
}
"""

TABLE = """
query TenantTable($table: TenantTableInput!) {
  tenantTable(table: $table) {
    quantityDescriptors { quantity normalized expressedAs }
    rows {
      values
      comparisonValues
      object { id measurementPoint { id name quantity room } unit { id name unitNumber } }
    }
  }
}
"""

KPIS = """
query Kpis($input: UnitQuantityKPIsInput!) {
  unitQuantityKpis(input: $input) {
    total previousPeriod previousYear propertyComparison normalized
    rooms { label value }
    meters { value object { id measurementPoint { id name quantity room } } }
  }
}
"""

GRAPH = """
query TenantGraph($graph: TenantGraphInput!) {
  tenantGraph(graph: $graph) {
    timestamps
    graphs {
      type
      consumption {
        quantityDescriptor { quantity normalized expressedAs }
        meta { average median min max sum count }
        values
        relatedValues { type values meta { sum count } }
      }
    }
  }
}
"""


_PRICES = """
query Prices($input: QuantityPriceInput!) {
  quantityPrices(input: $input) {
    quantity price currency validFrom validTo
  }
}
"""

_NOTIFICATIONS = """
query Notifications($input: NotificationsInput!) {
  notifications(input: $input) {
    id createdAt resolvedAt
    alarmNotification {
      triggerValue
      alarm { id name quantity period enabled }
      evaluatedPeriod { startDate endDate }
    }
  }
}
"""

_ALARMS = """
query Alarms($forObjectId: ID!) {
  alarms(forObjectId: $forObjectId) {
    id name quantity period enabled excludedHere notApplicableHere
  }
}
"""


def main() -> int:
    email = os.environ.get("TECHEM_EMAIL") or input("Techem email: ").strip()
    password = os.environ.get("TECHEM_PASSWORD") or getpass.getpass("Techem password: ")

    out: dict = {
        "probedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "host": HOST,
    }

    print("logging in...", file=sys.stderr)
    login = post(LOGIN, {"credentials": {
        "username": email, "password": password, "targetResource": "tenant"}})
    try:
        creds = login["data"]["loginWithEmailAndPassword"]["ok"]
        token = creds["token"]
    except (KeyError, TypeError):
        print("login failed:", json.dumps(login)[:500], file=sys.stderr)
        return 1
    out["login"] = login
    # Does the JWT carry an expiry we can schedule refreshes against?
    try:
        import base64
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        out["tokenClaims"] = json.loads(base64.urlsafe_b64decode(payload))
    except Exception as err:  # noqa: BLE001
        out["tokenClaims"] = {"_error": repr(err)}

    def call(label: str, query: str, variables: dict | None = None) -> dict:
        print(f"  {label}", file=sys.stderr)
        time.sleep(0.5)  # be a polite client
        res = post(query, variables, token)
        out.setdefault("queries", {})[label] = {"variables": variables, "response": res}
        return res

    call("me", ME)
    units = call("tenantUnits", UNITS)

    try:
        unit_objs = units["data"]["tenantUnits"]
    except (KeyError, TypeError):
        unit_objs = []

    if not unit_objs:
        # Fall back to an objectId supplied by hand, so a failure to enumerate
        # units does not cost us the rest of the probe.
        manual = os.environ.get("TECHEM_OBJECT_ID")
        if manual:
            print(f"tenantUnits gave nothing; using TECHEM_OBJECT_ID={manual}",
                  file=sys.stderr)
            unit_objs = [{"id": manual, "treeInfo": {"quantities": [
                "ENERGY", "HOT_WATER", "COLD_WATER"]}}]
        else:
            print("could not read tenantUnits; see dump. Re-run with "
                  "TECHEM_OBJECT_ID=<id> to probe a known unit.", file=sys.stderr)

    for idx, u in enumerate(unit_objs):
        oid = str(u.get("id"))
        quantities = (u.get("treeInfo") or {}).get("quantities") or []
        print(f"unit {idx} id={oid} quantities={quantities}", file=sys.stderr)

        call(f"u{idx}.children", UNIT_CHILDREN, {"id": oid})
        call(f"u{idx}.meters", UNIT_METERS, {"id": oid})

        if not quantities:
            # Discovery failed; probe the three we care about anyway.
            quantities = ["ENERGY", "HOT_WATER", "COLD_WATER"]

        # Table: year to date vs last year, and the last full week.
        call(f"u{idx}.table.ytd", TABLE, {"table": {
            "aggregationLevel": "UNIT", "objectId": oid,
            "periodBegin": jan1(), "periodEnd": day(1),
            "compareWith": "previous-year"}})
        call(f"u{idx}.table.week", TABLE, {"table": {
            "aggregationLevel": "UNIT", "objectId": oid,
            "periodBegin": day(8), "periodEnd": day(1),
            "compareWith": "previous-period"}})
        # Does a finer aggregation level break the rows out per meter?
        call(f"u{idx}.table.mpoint", TABLE, {"table": {
            "aggregationLevel": "MPOINT", "objectId": oid,
            "periodBegin": day(8), "periodEnd": day(1),
            "compareWith": "previous-period"}})

        # Can a tenant read prices and alarm notifications, or are these
        # manager-only like the object tree?
        call(f"u{idx}.notifications", _NOTIFICATIONS, {"input": {
            "objectId": oid, "periodBegin": jan1(1), "periodEnd": day(0),
            "onlyUnresolved": False, "includeObjectChildren": True}})
        call(f"u{idx}.alarms", _ALARMS, {"forObjectId": oid})

        for q in quantities:
            call(f"u{idx}.prices.{q}", _PRICES, {"input": {
                "objectId": oid, "quantity": q,
                "periodBegin": jan1(1), "periodEnd": day(0)}})

            call(f"u{idx}.kpis.{q}", KPIS, {"input": {
                "objectId": oid, "quantity": q,
                "periodBegin": jan1(), "periodEnd": day(1),
                "compareWith": "previous-year"}})

            # The statistics-backfill question: how fine can we resolve, and
            # how far back does history go?
            for label, res, begin, end in (
                ("hour", "HOUR", day(5), day(0)),
                ("day", "DAY", day(35), day(0)),
                ("month", "MONTH", jan1(1), day(0)),
            ):
                call(f"u{idx}.graph.{q}.{label}", GRAPH, {"graph": {
                    "objectId": oid, "resolution": res,
                    "periodBegin": begin, "periodEnd": end,
                    "consumption": {"evaluateOperational": True, "series": [
                        {"quantityDescriptor": {"quantity": q, "normalized": False}}]},
                }})

    with open("techem-probe-raw.json", "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    scrubbed = redact(out)
    scrubbed.pop("login", None)
    scrubbed.pop("tokenClaims", None)
    scrubbed["tokenClaimKeys"] = sorted((out.get("tokenClaims") or {}).keys())
    with open("techem-probe-scrubbed.json", "w") as fh:
        json.dump(scrubbed, fh, indent=2, ensure_ascii=False)

    print("\nwrote techem-probe-raw.json (private) and "
          "techem-probe-scrubbed.json (shareable)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
