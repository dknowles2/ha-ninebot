"""Binary sensor platform for the Ninebot integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NinebotConfigEntry, NinebotCoordinator
from .entity import NinebotEntity
from .pynebot import ScooterState


@dataclass(frozen=True, kw_only=True)
class NinebotBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Ninebot binary sensor."""

    value_fn: Callable[[ScooterState], bool | None]


def _problem(state: ScooterState) -> bool | None:
    """Return True when the scooter reports an error or a warning."""
    error = state.get("error_code")
    warning = state.get("warning_code")
    if error is None and warning is None:
        return None
    return bool(error) or bool(warning)


BINARY_SENSORS: tuple[NinebotBinarySensorEntityDescription, ...] = (
    NinebotBinarySensorEntityDescription(
        key="locked",
        translation_key="locked",
        device_class=BinarySensorDeviceClass.LOCK,
        # The lock device class reports "unlocked" when on, so invert.
        value_fn=lambda state: (
            None if (locked := state.get("locked")) is None else not locked
        ),
    ),
    NinebotBinarySensorEntityDescription(
        key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_problem,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinebotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Ninebot binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        NinebotBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class NinebotBinarySensor(NinebotEntity, BinarySensorEntity):
    """A binary sensor reading one value from the scooter."""

    entity_description: NinebotBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: NinebotCoordinator,
        description: NinebotBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the current state."""
        return self.entity_description.value_fn(self.coordinator.state)

    @property
    @override
    def available(self) -> bool:
        """Return True once the scooter has reported this value."""
        return super().available and self.is_on is not None
