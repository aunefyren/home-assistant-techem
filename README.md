# Techem Integration for Home Assistant
![GitHub Release](https://img.shields.io/github/v/release/aunefyren/home-assistant-techem?style=for-the-badge)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/aunefyren/home-assistant-techem/total?style=for-the-badge)
![GitHub issues](https://img.shields.io/github/issues/aunefyren/home-assistant-techem?style=for-the-badge)
![GitHub Repo stars](https://img.shields.io/github/stars/aunefyren/home-assistant-techem?style=for-the-badge)
![GitHub forks](https://img.shields.io/github/forks/aunefyren/home-assistant-techem?style=for-the-badge)

> [!NOTE]
> Parts of this integration were co-written with Claude (Anthropic AI).

This integration reads cold water, hot water and district heating consumption
from the Techem tenant portal at [beboer.techemadmin.no](https://beboer.techemadmin.no/)
and exposes it to Home Assistant, including the Energy dashboard.

<br>
<br>

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=aunefyren&repository=home-assistant-techem)  
Must be added as a custom repository.

<br>
<br>

> [!IMPORTANT]
> Techem has no public API. This integration uses the same private GraphQL
> endpoint the tenant portal uses. It works today, but Techem can change or
> close it without notice.

<br>
<br>

## Main features
* UI-based setup, no `configuration.yaml` editing required
* Your unit and its meters are discovered automatically, no digging through
  browser developer tools for an object ID
* Daily readings are imported as **long-term statistics dated to the day they
  belong to**, not the day Home Assistant happened to fetch them
* Your full consumption history is backfilled the first time it runs
* Comparison sensors: versus last year, versus the previous period, and versus
  the average comparable unit in your building
* English and Norwegian (bokmål) translations

<br>
<br>

## Installation
1. Add this repository to HACS as a custom repository of type *Integration*.
2. Install **Techem** and restart Home Assistant.
3. Go to *Settings -> Devices & services -> Add integration* and pick **Techem**.
4. Sign in with the email and password you use on beboer.techemadmin.no.

If your account has access to more than one unit you will be asked which one to
use. Add the integration again to set up a second unit.

<br>
<br>

## Supported Techem servers
Techem runs the same tenant platform under several country domains. During
setup you pick which one your portal uses.

| Server | Status |
| --- | --- |
| `techemadmin.no` (Norway, beboer.techemadmin.no) | Verified against a real account |
| `techemadmin.dk` (Denmark) | Serves an identical API, but untested with a real account |
| Other hostname | You can type one in; it must expose `/analytics/graphql` |

> [!WARNING]
> **`mieter.techem.de` is not supported.** Techem's German tenant portal is a
> completely separate application with no `/analytics/graphql` endpoint. It
> shares the Techem brand and nothing else, and no amount of configuration
> will make this integration talk to it.

If you are on the Danish server, or another one, and something does not work,
please open an issue with the output of `dev/probe_api.py`:

```bash
TECHEM_EMAIL=you@example.com TECHEM_HOST=techemadmin.dk python3 dev/probe_api.py
```

It writes a redacted, shareable dump alongside the private one.

<br>
<br>

## Entities
For every quantity your unit actually meters, you get:

| Entity | Description |
| --- | --- |
| `... this year` | Consumption so far this calendar year |
| `... same period last year` | The same span last year (disabled by default) |
| `... daily average` | Average per day over the last seven days with data |
| `... last reading` | The most recent daily reading |
| `... vs last year` | Year to date against last year, in percent |
| `... vs previous period` | Recent daily average against the preceding week |
| `... vs building average` | Year to date against the average comparable unit |
| `... reading date` | The date of the most recent reading (diagnostic) |

Each also carries a `rooms` attribute with the per-room split, and a
`statistic_id` attribute pointing at its long-term statistics.

<br>
<br>

## Energy dashboard
The integration writes external statistics named
`techem:<unit>_cold_water_volume`, `techem:<unit>_hot_water_volume` and
`techem:<unit>_heat_energy`.

Add them under *Settings -> Dashboards -> Energy*:
* water statistics as **Water consumption**
* the heating statistic as an individual device under **Electricity grid** or
  as a gas/heat source, depending on how you prefer to account for it

You can find the exact IDs in the `statistic_id` attribute of any Techem sensor.

<br>
<br>

## How often it updates
Techem meters report **once per day**, and a reading typically appears about
**two days later**. The integration polls every six hours by default, which is
already more often than the data changes. You can adjust it under the
integration's *Configure* menu, but raising it will not get you fresher data.

This delay is also why consumption is imported as statistics rather than
tracked with a live sensor: statistics can be dated to the day the water was
actually used, and a revised reading overwrites the old one instead of being
counted twice.

<br>
<br>

## Troubleshooting
**No entities appear.** Your unit may not meter the quantities this integration
supports. Download diagnostics from the integration page to see what Techem
reported.

**Authentication keeps failing.** Confirm the credentials work at
beboer.techemadmin.no. Home Assistant will prompt you to re-enter the password
when Techem stops accepting the stored one.

**The numbers lag behind the portal.** Expected; see above. The
`... reading date` sensor tells you how current the data actually is.

<br>
<br>

## Credits
The private GraphQL endpoint was originally documented by
[@khaffner](https://github.com/khaffner)'s shell script and
[@andreas-bertelsen](https://github.com/andreas-bertelsen)'s
[ha-techem](https://github.com/andreas-bertelsen/ha-techem) script-and-template
setup. This integration is a from-scratch rewrite, not a fork.
