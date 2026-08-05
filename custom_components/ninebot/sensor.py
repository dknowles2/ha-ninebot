"""Sensor platform for the Ninebot integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import NinebotConfigEntry, NinebotCoordinator
from .entity import NinebotEntity
from .pynebot import ScooterState

PARALLEL_UPDATES = 0

UNIT_MILLIAMP_HOURS = "mAh"


def _value(key: str) -> Callable[[ScooterState], StateType]:
    """Return a getter for a plain register value."""

    def getter(state: ScooterState) -> StateType:
        value = state.get(key)
        # Registers decoding to tuples get their own getters; anything else
        # reaching here would be unpresentable as a state, so drop it.
        if isinstance(value, (str, int, float)):
            return value
        return None

    return getter


def _temperature(index: int) -> Callable[[ScooterState], StateType]:
    """Return a getter for one of the two BMS temperature probes."""

    def getter(state: ScooterState) -> StateType:
        temperatures: tuple[float, ...] | None = state.get("battery_temperatures")
        if not temperatures or index >= len(temperatures):
            return None
        return temperatures[index]

    return getter


def _cell_stat(stat: str) -> Callable[[ScooterState], StateType]:
    """Return a getter summarizing the per-cell voltages."""

    def getter(state: ScooterState) -> StateType:
        cells: tuple[float, ...] | None = state.get("cell_voltages")
        if not cells:
            return None
        if stat == "min":
            return round(min(cells), 3)
        if stat == "max":
            return round(max(cells), 3)
        return round(max(cells) - min(cells), 3)

    return getter


@dataclass(frozen=True, kw_only=True)
class NinebotSensorEntityDescription(SensorEntityDescription):
    """Describes a Ninebot sensor."""

    value_fn: Callable[[ScooterState], StateType]
    attributes_fn: Callable[[ScooterState], dict[str, Any]] | None = None


SENSORS: tuple[NinebotSensorEntityDescription, ...] = (
    NinebotSensorEntityDescription(
        key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("battery_level"),
    ),
    NinebotSensorEntityDescription(
        key="battery_percent",
        translation_key="battery_percent",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("battery_percent"),
    ),
    NinebotSensorEntityDescription(
        key="speed",
        translation_key="speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_value("speed"),
    ),
    NinebotSensorEntityDescription(
        key="total_distance",
        translation_key="total_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=_value("total_distance"),
    ),
    NinebotSensorEntityDescription(
        key="trip_distance",
        translation_key="trip_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_value("trip_distance"),
    ),
    NinebotSensorEntityDescription(
        key="remaining_range",
        translation_key="remaining_range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_value("remaining_range"),
    ),
    NinebotSensorEntityDescription(
        key="body_temperature",
        translation_key="body_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_value("body_temperature"),
    ),
    NinebotSensorEntityDescription(
        key="battery_temperature_1",
        translation_key="battery_temperature_1",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_temperature(0),
    ),
    NinebotSensorEntityDescription(
        key="battery_temperature_2",
        translation_key="battery_temperature_2",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_temperature(1),
    ),
    NinebotSensorEntityDescription(
        key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_value("battery_voltage"),
    ),
    NinebotSensorEntityDescription(
        key="battery_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_value("battery_current"),
    ),
    NinebotSensorEntityDescription(
        key="battery_remaining_capacity",
        translation_key="battery_remaining_capacity",
        native_unit_of_measurement=UNIT_MILLIAMP_HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("battery_remaining_capacity"),
    ),
    NinebotSensorEntityDescription(
        key="battery_design_capacity",
        translation_key="battery_design_capacity",
        native_unit_of_measurement=UNIT_MILLIAMP_HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("battery_design_capacity"),
    ),
    NinebotSensorEntityDescription(
        key="battery_cycles",
        translation_key="battery_cycles",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("battery_cycles"),
    ),
    NinebotSensorEntityDescription(
        key="battery_deep_discharges",
        translation_key="battery_deep_discharges",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("battery_deep_discharges"),
    ),
    NinebotSensorEntityDescription(
        key="cell_voltage_min",
        translation_key="cell_voltage_min",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_cell_stat("min"),
        attributes_fn=lambda state: {
            "cells": list(state.get("cell_voltages") or ()),
        },
    ),
    NinebotSensorEntityDescription(
        key="cell_voltage_max",
        translation_key="cell_voltage_max",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_cell_stat("max"),
    ),
    NinebotSensorEntityDescription(
        key="cell_voltage_delta",
        translation_key="cell_voltage_delta",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_cell_stat("delta"),
    ),
    NinebotSensorEntityDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("uptime"),
    ),
    NinebotSensorEntityDescription(
        key="max_power",
        translation_key="max_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("max_power"),
    ),
    NinebotSensorEntityDescription(
        key="error_code",
        translation_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("error_code"),
    ),
    NinebotSensorEntityDescription(
        key="warning_code",
        translation_key="warning_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("warning_code"),
    ),
    NinebotSensorEntityDescription(
        key="gear_mode",
        translation_key="gear_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("gear_mode"),
    ),
    NinebotSensorEntityDescription(
        key="light_mode",
        translation_key="light_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("light_mode"),
    ),
    NinebotSensorEntityDescription(
        key="traction_control",
        translation_key="traction_control",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("traction_control"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinebotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Ninebot sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        NinebotSensor(coordinator, description) for description in SENSORS
    )


class NinebotSensor(NinebotEntity, SensorEntity):
    """A sensor reading one value from the scooter."""

    entity_description: NinebotSensorEntityDescription

    def __init__(
        self,
        coordinator: NinebotCoordinator,
        description: NinebotSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    @override
    def native_value(self) -> StateType:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator.state)

    @property
    @override
    def available(self) -> bool:
        """Return True once the scooter has reported this value."""
        return super().available and self.native_value is not None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return supplementary detail, when the description provides any."""
        if (attributes_fn := self.entity_description.attributes_fn) is None:
            return None
        return attributes_fn(self.coordinator.state)
