"""Base entity for the Ninebot integration."""

from __future__ import annotations

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo, format_mac

from .const import MANUFACTURER
from .coordinator import NinebotCoordinator


class NinebotEntity(PassiveBluetoothCoordinatorEntity[NinebotCoordinator]):
    """Base class for entities backed by a Ninebot scooter."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NinebotCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        address = coordinator.client.address
        self._attr_unique_id = f"{format_mac(address)}_{key}"
        info = coordinator.info
        self._attr_device_info = DeviceInfo(
            connections={(dr.CONNECTION_BLUETOOTH, format_mac(address))},
            manufacturer=MANUFACTURER,
            model=info.model,
            model_id=str(info.hardware_id),
            name=info.name,
            serial_number=info.serial_number,
            sw_version=info.controller_firmware,
        )
