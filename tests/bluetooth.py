"""Bluetooth test helpers.

Home Assistant's own bluetooth test helpers live in its test suite, which is not
published to PyPI, so the small parts this integration needs are reimplemented
here against the same public APIs.
"""

from __future__ import annotations

from collections.abc import Iterator
import contextlib
import time
from typing import Any
from unittest.mock import patch

from bleak.backends.scanner import AdvertisementData, BLEDevice
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_get_advertisement_callback,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

LOCAL_SOURCE = "local"

ADAPTERS: dict[str, dict[str, Any]] = {
    "hci0": {
        "address": "00:00:00:00:00:01",
        "hw_version": "usb:v1D6Bp0246d053F",
        "passive_scan": False,
        "sw_version": "homeassistant",
        "manufacturer": "ACME",
        "product": "Bluetooth Adapter 5.0",
        "product_id": "aa01",
        "vendor_id": "cc01",
        "connection_slots": 5,
    }
}


@contextlib.contextmanager
def patch_adapters() -> Iterator[None]:
    """Pretend a Linux host with one Bluetooth adapter."""
    with (
        patch(
            "homeassistant.components.bluetooth.platform.system",
            return_value="Linux",
        ),
        patch("habluetooth.scanner.platform.system", return_value="Linux"),
        patch("bluetooth_adapters.systems.platform.system", return_value="Linux"),
        patch("bluetooth_adapters.systems.linux.LinuxAdapters.refresh"),
        patch(
            "bluetooth_adapters.systems.linux.LinuxAdapters.adapters",
            ADAPTERS,
        ),
        patch("habluetooth.scanner.OriginalBleakScanner.start"),
        patch("habluetooth.scanner.OriginalBleakScanner.stop"),
    ):
        yield


async def async_setup_bluetooth(hass: HomeAssistant) -> None:
    """Set up the bluetooth integration with a mocked adapter."""
    with patch_adapters():
        assert await async_setup_component(hass, "bluetooth", {})
        await hass.async_block_till_done()


def make_advertisement(
    address: str,
    name: str,
    *,
    manufacturer_data: dict[int, bytes] | None = None,
    service_uuids: list[str] | None = None,
    rssi: int = -60,
) -> BluetoothServiceInfoBleak:
    """Build a service info for a device advertising over Bluetooth."""
    advertisement = AdvertisementData(
        local_name=name,
        manufacturer_data=manufacturer_data or {},
        service_data={},
        service_uuids=service_uuids or [],
        rssi=rssi,
        tx_power=-127,
        platform_data=((),),
    )
    device = BLEDevice(address=address, name=name, details={})
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=rssi,
        manufacturer_data=advertisement.manufacturer_data,
        service_data=advertisement.service_data,
        service_uuids=advertisement.service_uuids,
        source=LOCAL_SOURCE,
        device=device,
        advertisement=advertisement,
        connectable=True,
        time=time.monotonic(),
        tx_power=advertisement.tx_power,
        raw=None,
    )


def inject_advertisement(
    hass: HomeAssistant, service_info: BluetoothServiceInfoBleak
) -> None:
    """Deliver an advertisement to the bluetooth manager."""
    async_get_advertisement_callback(hass)(service_info)
