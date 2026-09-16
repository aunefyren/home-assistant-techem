# Techem for Home Assistant
Pulls cold water, hot water and district heating consumption from the Techem
tenant portal (beboer.techemadmin.no).

## Main features
* UI-based setup, no `configuration.yaml` editing and no object ID hunting
* Cold water, hot water and heating, discovered automatically
* Daily readings imported as long-term statistics with correct dates, so the
  Energy dashboard shows consumption on the day it happened
* Full consumption history backfilled on first setup
* Comparisons against last year, the previous period and the building average
