<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/techem/brand/dark_logo@2x.png">
    <img src="custom_components/techem/brand/logo@2x.png" alt="Techem" height="96">
  </picture>
</p>

# Techem Integration for Home Assistant
![GitHub Release](https://img.shields.io/github/v/release/aunefyren/home-assistant-techem?style=for-the-badge)
![GitHub issues](https://img.shields.io/github/issues/aunefyren/home-assistant-techem?style=for-the-badge)
![GitHub Repo stars](https://img.shields.io/github/stars/aunefyren/home-assistant-techem?style=for-the-badge)
![GitHub forks](https://img.shields.io/github/forks/aunefyren/home-assistant-techem?style=for-the-badge)

> [!NOTE]
> Parts of this integration were co-written with Claude (Anthropic AI).

Brings cold water, hot water and district heating consumption from the Techem
tenant portal ([beboer.techemadmin.no](https://beboer.techemadmin.no/)) into
Home Assistant: as sensors, and as properly dated long-term statistics you can
add to the Energy dashboard, with optional cost tracking.

> [!IMPORTANT]
> Techem has no public API. This integration uses the same private GraphQL
> endpoint the tenant portal uses. It works today, but Techem can change or
> close it without notice.

<br>

## Contents
* [Features](#features)
* [Installation](#installation)
* [Energy dashboard](#energy-dashboard)
* [Cost tracking](#cost-tracking)
* [Entities](#entities)
* [How often it updates](#how-often-it-updates)
* [Supported Techem servers](#supported-techem-servers)
* [Troubleshooting](#troubleshooting)
* [Development](#development)

<br>

## Features
* UI setup: sign in with your portal credentials. No `configuration.yaml`, and
  no digging through browser developer tools for an object ID.
* Your unit and the quantities it actually meters are discovered
  automatically.
* Daily readings are imported as **long-term statistics dated to the day they
  belong to**, not the day Home Assistant happened to fetch them.
* Your full consumption history is backfilled on first setup.
* Revised readings are corrected in place, never double-counted.
* Optional cost statistics for the Energy dashboard, from a price you set.
* Comparison sensors: versus last year, versus the previous period, and versus
  the average comparable unit in your building.
* English and Norwegian (bokmål) translations.

<br>

## Installation
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=aunefyren&repository=home-assistant-techem)

1. In HACS, add this repository as a custom repository of type
   *Integration* (or use the button above).
2. Install **Techem** and restart Home Assistant.
3. Go to *Settings → Devices & services → Add integration* and pick
   **Techem**.
4. Sign in with the email and password you use on beboer.techemadmin.no.

If your account has access to more than one unit you will be asked which one to
use. Add the integration again to set up another unit.

<br>

## Energy dashboard
The Energy dashboard reads **statistics**, not sensors. For every metered
quantity the integration writes an external statistic:

| Quantity | Statistic ID |
| --- | --- |
| Cold water | `techem:<unit>_cold_water_volume` (m³) |
| Hot water | `techem:<unit>_hot_water_volume` (m³) |
| District heating | `techem:<unit>_heat_energy` (kWh) |

The exact IDs are in the `statistic_id` attribute of every Techem sensor. The
sensors themselves are deliberately not offered to the Energy dashboard: they
would be stamped with the time Home Assistant polled, two days after the fact.

### Setting it up
1. Wait for the first update after setup. That is when the history is
   backfilled and the statistics are created. Until then the Energy pickers
   have nothing to show.
2. Go to *Settings → Dashboards → Energy*.
3. Under **Water consumption**, choose *Add water source* twice: once for
   cold water, once for hot water. They come from separate meters, so
   together they are your unit's total water use.
4. Under **Gas consumption**, add the heating statistic. See below for why.
5. Leave **flow rate** fields empty. Techem reports once a day, so there is no
   real-time rate to show.
6. For costs, see [Cost tracking](#cost-tracking).

### Where to put district heating
Home Assistant has no dedicated district-heating source, so heating needs a
home. **Gas consumption** is the recommended workaround: it accepts kWh,
supports costs, and keeps heating out of your electricity figures. The only
downside is that the dashboard labels it "Gas".

Avoid the alternatives:
* **Electricity grid consumption** counts heat as electricity you bought. This
  inflates your electricity totals and costs and skews any solar or
  self-consumption figures.
* **Individual devices** are meant to be parts of your electricity use. Heating
  is not part of it, so "untracked consumption" ends up negative or
  meaningless.

If your Home Assistant version offers a dedicated heat source, use that
instead.

### What to expect
* **The latest ~2 days are empty.** Techem readings arrive about two days
  late. When they do, they fill in under the correct day.
* **The day view shows one bar at midnight.** Each daily reading is stored in
  the hour starting at local midnight on the day it belongs to. The week,
  month and year views are unaffected. Hourly detail does not exist; the
  meters only report daily.
* **Revisions overwrite.** If Techem corrects a reading, the stored value is
  replaced rather than added to.

<br>

## Cost tracking
Home Assistant only calculates costs itself for sources that are entities. For
external statistics like these, the Energy dashboard greys out the fixed
price and price entity options. Instead, the integration can write a cost
statistic for you.

1. Go to *Settings → Devices & services → Techem → Configure*.
2. Enter a price for each quantity you want costed. Water is priced per m³ and
   heating per kWh, both in the currency set in Home Assistant (*Settings →
   System → General*). Leave a field empty to skip that quantity.
3. After the next update, a statistic named like the consumption one with
   `_cost` appended appears, e.g. `techem:<unit>_heat_energy_cost`.
4. In the Energy dashboard, edit the source, choose the option to use a
   statistic tracking the total costs, and pick the matching `_cost`
   statistic.

Limitations:
* **One flat price per quantity.** Standing charges, administration fees and
  tiered tariffs are not included. Treat the figure as variable cost only.
* **Price changes are not retroactive in full.** The new price applies to the
  roughly 35 most recent days, which are rewritten on every update, and to
  everything after. Older days keep the price they were costed at. Setting a
  price for the first time costs your entire history at that price.
* **Removing a price stops updates.** The existing cost statistic is kept.
  Remove it from the Energy dashboard, and delete it under *Developer tools →
  Statistics* if you no longer want it.

<br>

## Entities
For every quantity your unit meters, you get:

| Entity | Description |
| --- | --- |
| `… this year` | Consumption so far this calendar year |
| `… same period last year` | The same span last year |
| `… building average` | The average comparable unit in your building |
| `… daily average` | Average per day over the last seven days with data |
| `… last reading` | The most recent daily reading |
| `… reading date` | The date of the most recent reading (diagnostic) |

Every figure above comes from Techem directly. The following are plain
arithmetic on those figures and ship **disabled by default**. Enable them in
the entity settings if you would rather not write a template:

| Entity | Equivalent to |
| --- | --- |
| `… vs last year` | `this year` against `same period last year` |
| `… vs previous period` | `daily average` against `previous daily average` |
| `… vs building average` | `this year` against `building average` |
| `… previous daily average` | The seven days before the current average |

Each sensor also carries a `rooms` attribute with the per-room split, and a
`statistic_id` attribute pointing at its long-term statistic.

<br>

## How often it updates
Techem meters report **once per day**, and a reading typically appears about
**two days later**. The integration polls every six hours by default, which is
already more often than the data changes. You can change the interval under
the integration's *Configure* menu, but polling more often will not get you
fresher data.

<br>

## Supported Techem servers
Techem runs the same tenant platform under several country domains. You pick
yours during setup.

| Server | Status |
| --- | --- |
| `techemadmin.no` (Norway, beboer.techemadmin.no) | Verified against a real account |
| `techemadmin.dk` (Denmark) | Serves an identical API; untested with a real account |
| Other hostname | Can be typed in; must expose `/analytics/graphql` |

> [!WARNING]
> **`mieter.techem.de` is not supported.** Techem's German tenant portal is a
> separate application with no `/analytics/graphql` endpoint. It shares the
> Techem brand and nothing else.

If you are on another server and something does not work, please open an issue
with the output of `dev/probe_api.py`:

```bash
TECHEM_EMAIL=you@example.com TECHEM_HOST=techemadmin.dk python3 dev/probe_api.py
```

It writes a redacted, shareable dump alongside the private one. Share only the
redacted file.

<br>

## Troubleshooting
**No entities appear.** Your unit may not meter any quantity this integration
supports. Download diagnostics from the integration page to see what Techem
reported.

**The statistics are missing from the Energy dashboard.** The first import
runs in the background after setup and can take a while on accounts with long
history. Check *Developer tools → Statistics* for `techem:` entries.

**The cost statistic is missing.** It is only written once a price is set, and
only after the next update.

**Authentication keeps failing.** Confirm the credentials work at
beboer.techemadmin.no. Home Assistant will prompt you to re-enter the password
when Techem stops accepting the stored one.

**The numbers lag behind the portal.** Expected; see
[How often it updates](#how-often-it-updates). The `… reading date` sensor
shows how current the data is.

<br>

## Development
```bash
python3 -m pip install -r requirements_test.txt
pytest tests
ruff check custom_components tests dev
ruff format --check custom_components tests dev
```

Home Assistant needs Python 3.13. If your system Python is older,
[uv](https://github.com/astral-sh/uv) can provide one without root:

```bash
uv python install 3.13
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest tests
```

The test fixtures in `tests/fixtures/` are generated from a redacted
`dev/probe_api.py` run by `dev/make_fixtures.py`, so the suite exercises
response shapes the real API actually produced. To refresh them against your
own account, run the probe and then:

```bash
python3 dev/make_fixtures.py
```

`dev/docker-compose.yml` starts a throwaway Home Assistant with the integration
mounted, for testing against a real account.

<br>

## Credits
The private GraphQL endpoint was originally documented by
[@khaffner](https://github.com/khaffner)'s shell script and
[@andreas-bertelsen](https://github.com/andreas-bertelsen)'s
[ha-techem](https://github.com/andreas-bertelsen/ha-techem) script-and-template
setup. This integration is a from-scratch rewrite, not a fork.
