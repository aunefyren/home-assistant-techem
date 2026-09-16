"""Sensor platform for the Techem integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TechemConfigEntry
from .const import DOMAIN, QUANTITIES, TechemQuantity
from .coordinator import QuantityData, TechemCoordinator
from .statistics_import import statistic_id_for


@dataclass(frozen=True, kw_only=True)
class TechemSensorDescription(SensorEntityDescription):
    """Describes one sensor derived from a quantity's data."""

    value_fn: Callable[[QuantityData], float | date | None]
    # True when the sensor reports the quantity itself (m3, kWh) rather than a
    # derived figure such as a percentage.
    native: bool = False


# Raw figures from Techem are enabled by default; the percentage sensors below
# are plain arithmetic on those figures and ship disabled, so the numbers you
# see are the ones Techem actually reported.
#
# The cumulative sensors deliberately carry no state class. They are display
# values fetched hours after the fact, so letting Home Assistant derive
# statistics from them would offer the energy dashboard a misdated rival to the
# properly dated statistics this integration imports itself.
SENSORS: tuple[TechemSensorDescription, ...] = (
    TechemSensorDescription(
        key="year_to_date",
        translation_key="year_to_date",
        native=True,
        value_fn=lambda data: data.year_to_date,
    ),
    TechemSensorDescription(
        key="previous_year",
        translation_key="previous_year",
        native=True,
        value_fn=lambda data: data.previous_year,
    ),
    TechemSensorDescription(
        key="building_average",
        translation_key="building_average",
        native=True,
        value_fn=lambda data: data.property_comparison,
    ),
    TechemSensorDescription(
        key="daily_average",
        translation_key="daily_average",
        state_class=SensorStateClass.MEASUREMENT,
        native=True,
        value_fn=lambda data: data.daily_average,
    ),
    TechemSensorDescription(
        key="last_reading",
        translation_key="last_reading",
        native=True,
        value_fn=lambda data: data.last_reading_value,
    ),
    TechemSensorDescription(
        key="previous_daily_average",
        translation_key="previous_daily_average",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        native=True,
        value_fn=lambda data: data.previous_daily_average,
    ),
    TechemSensorDescription(
        key="year_change",
        translation_key="year_change",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
        value_fn=lambda data: data.year_change_percent,
    ),
    TechemSensorDescription(
        key="average_change",
        translation_key="average_change",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
        value_fn=lambda data: data.average_change_percent,
    ),
    TechemSensorDescription(
        key="property_comparison",
        translation_key="property_comparison",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
        value_fn=lambda data: data.property_comparison_percent,
    ),
)

# Not tied to a quantity's unit; reported once per quantity so you can see how
# stale Techem's data currently is.
READING_DATE = TechemSensorDescription(
    key="last_reading_date",
    translation_key="last_reading_date",
    device_class=SensorDeviceClass.DATE,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda data: data.last_reading_day,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TechemConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Techem sensors."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = []
    for key in coordinator.quantities:
        quantity = QUANTITIES[key]
        for description in (*SENSORS, READING_DATE):
            entities.append(
                TechemSensor(coordinator, entry, quantity, description)
            )

    async_add_entities(entities)


class TechemSensor(CoordinatorEntity[TechemCoordinator], SensorEntity):
    """A single derived value for one Techem quantity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TechemCoordinator,
        entry: TechemConfigEntry,
        quantity: TechemQuantity,
        description: TechemSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._quantity = quantity

        self._attr_unique_id = f"{entry.unique_id}_{quantity.key}_{description.key}"
        self._attr_translation_key = f"{quantity.translation_key}_{description.key}"

        if description.native:
            self._attr_device_class = quantity.device_class
            self._attr_native_unit_of_measurement = quantity.unit

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(entry.unique_id))},
            name=entry.title,
            manufacturer="Techem",
            model="Tenant metering",
            configuration_url="https://beboer.techemadmin.no/",
        )

    @property
    def _data(self) -> QuantityData | None:
        return (self.coordinator.data or {}).get(self._quantity.key)

    @property
    def available(self) -> bool:
        """Available while the coordinator has data for this quantity."""
        return super().available and self._data is not None

    @property
    def native_value(self) -> float | date | None:
        """Return the sensor value."""
        if (data := self._data) is None:
            return None
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Expose the per-room split and the statistics id for reference."""
        if (data := self._data) is None:
            return None

        attributes: dict[str, object] = {
            "statistic_id": statistic_id_for(
                self.coordinator.object_id, self._quantity
            )
        }
        if data.rooms:
            attributes["rooms"] = data.rooms
        if data.last_reading_day:
            attributes["last_reading_date"] = data.last_reading_day.isoformat()
        return attributes
