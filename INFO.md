# Techem for Home Assistant
Pulls cold water, hot water and district heating consumption from the Techem
tenant portal (beboer.techemadmin.no).

![Adding this repository as a custom repository in HACS](https://raw.githubusercontent.com/aunefyren/home-assistant-techem/main/.github/assets/add-custom-repo-example.png)

## Main features
* UI-based setup, no `configuration.yaml` editing and no object ID hunting
* Cold water, hot water and heating, discovered automatically
* Daily readings imported as long-term statistics with correct dates, so the
  Energy dashboard shows consumption on the day it happened
* Full consumption history backfilled on first setup
* Comparisons against last year, the previous period and the building average
* English and Norwegian (bokmål) translations

## Setup
1. Install via HACS and restart Home Assistant.
2. *Settings -> Devices & services -> Add integration -> Techem*.
3. Sign in with your beboer.techemadmin.no email and password.

Techem meters report once a day and readings arrive about two days late, so the
integration polls every six hours by default. See the README for Energy
dashboard setup and the full entity list.
