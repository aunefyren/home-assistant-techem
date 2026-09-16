"""Constants for the Techem integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfEnergy, UnitOfVolume

DOMAIN = "techem"

API_PATH = "/analytics/graphql"

# Techem runs the same tenant platform under a few country domains; the
# Norwegian and Danish hosts serve a byte-identical GraphQL schema. Other
# Techem portals (mieter.techem.de, for one) are unrelated applications and
# will not work here.
DEFAULT_API_HOST = "techemadmin.no"

# Tenant portal for each known API host, sent as Origin/Referer where we know
# it. None means we do not know the portal domain; the API does not require
# these headers, so they are simply omitted.
KNOWN_HOSTS: dict[str, str | None] = {
    "techemadmin.no": "https://beboer.techemadmin.no",
    "techemadmin.dk": None,
}

CONF_OBJECT_ID = "object_id"

# Techem meters report once per day and the reading lands roughly two days
# late, so polling more often than this only wastes their bandwidth.
DEFAULT_SCAN_INTERVAL_HOURS = 6
MIN_SCAN_INTERVAL_HOURS = 1
MAX_SCAN_INTERVAL_HOURS = 24

# How far back to look for history on first setup. The backfill walks back a
# year at a time and stops early once a year returns nothing.
MAX_BACKFILL_YEARS = 10

# Refresh the access token this long before it actually expires.
TOKEN_EXPIRY_MARGIN_SECONDS = 120


@dataclass(frozen=True, kw_only=True)
class TechemQuantity:
    """A consumption quantity Techem can report for a unit."""

    key: str
    translation_key: str
    device_class: SensorDeviceClass
    unit: str
    # Recorder unit conversion class for long-term statistics; see
    # homeassistant.util.unit_conversion.
    unit_class: str


# Keyed by the strings Techem returns in `treeInfo.quantities`. Anything not
# listed here is ignored -- `total-water-volume` is advertised but returns no
# data, and unknown quantities are safer skipped than guessed at.
QUANTITIES: dict[str, TechemQuantity] = {
    "cold-water-volume": TechemQuantity(
        key="cold-water-volume",
        translation_key="cold_water",
        device_class=SensorDeviceClass.WATER,
        unit=UnitOfVolume.CUBIC_METERS,
        unit_class="volume",
    ),
    "hot-water-volume": TechemQuantity(
        key="hot-water-volume",
        translation_key="hot_water",
        device_class=SensorDeviceClass.WATER,
        unit=UnitOfVolume.CUBIC_METERS,
        unit_class="volume",
    ),
    "heat-energy": TechemQuantity(
        key="heat-energy",
        translation_key="heating",
        device_class=SensorDeviceClass.ENERGY,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        unit_class="energy",
    ),
}
