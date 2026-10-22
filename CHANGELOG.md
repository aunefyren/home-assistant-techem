# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Optional cost tracking. Set a price per quantity under *Configure* and the
  integration writes a matching `techem:<unit>_<quantity>_cost` statistic in
  your Home Assistant currency. Pick it in the Energy dashboard as the
  statistic tracking total costs. Home Assistant cannot derive costs itself
  for external statistics.

### Changed
- README rewritten, with a step-by-step Energy dashboard guide. District
  heating is now recommended under Gas consumption rather than Electricity
  grid, which counted it as purchased electricity.
- Requires Home Assistant 2026.3 or newer, the first release that shows
  the brand assets shipped with the integration.

### Fixed
- The daily average sensors no longer trigger Home Assistant's "impossible
  state class" warning. They are rates rather than totals, so they now carry
  no water or energy device class; unit and history are unchanged.
- The HACS validation no longer skips the brands check, since the icon and
  logo now ship in `custom_components/techem/brand/`.

## [0.1.2] - 2026-10-05

### Fixed
- Setup failed with "Cannot query field 'treeInfo' on type 'NObjectType'"
  after Techem removed `treeInfo` and `UnitType.size` from their API. Units
  are now listed without them, and every supported quantity is probed for
  data instead of relying on the list Techem used to advertise.
- Adding the integration and re-authenticating failed, because Techem also
  removed the `me` profile query. Credentials are now verified by logging in.

## [0.1.0] - 2026-09-16

First release. A from-scratch Home Assistant integration for the Techem tenant
portal, replacing the shell-script-and-template approach it grew out of.

### Added
- UI config flow: sign in with your portal credentials, units discovered
  automatically. No object ID hunting in browser developer tools.
- Cold water, hot water and district heating, each discovered per unit.
- Daily readings imported as **long-term statistics dated to the day they
  belong to**, so the Energy dashboard is not skewed by Techem's ~2 day
  reporting delay. Re-importing a window corrects revised readings instead of
  double-counting them.
- Full consumption history backfilled on first setup, walking back a year at a
  time until Techem runs out of data.
- Ten sensors per quantity. The figures Techem reports are enabled by default;
  the percentages derived from them ship disabled.
- Comparisons against last year, the previous period and the building average.
- Re-authentication flow, and a configurable poll interval.
- Diagnostics, with credentials and unit identifiers redacted.
- English and Norwegian (bokmål) translations.
- Support for the Norwegian and Danish Techem servers, plus a free-text host
  for any other server running the same platform.

### Notes
- Techem publishes no API. This uses the private GraphQL endpoint behind the
  tenant portal, which can change without warning.
- `mieter.techem.de` is a different application entirely and is not supported.
- Techem meters report once per day. The API offers an hourly resolution, but
  it returns the daily total in the 23:00 bucket and nulls elsewhere, so daily
  is the real resolution.
- Per-meter breakdowns are not available to tenant accounts: the object tree
  returns `incorrect-role-for-resource`, and `radioMeterId` expects a numeric
  id that tenants never see.
- Consumption prices and leak/anomaly alarms exist in the API but return no
  data, or are denied, for tenant accounts.
