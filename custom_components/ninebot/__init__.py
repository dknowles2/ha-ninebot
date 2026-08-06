"""The Ninebot scooter integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_PASSWORD, DOMAIN
from .coordinator import NinebotConfigEntry, NinebotCoordinator
from .pynebot import NinebotClient

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: NinebotConfigEntry) -> bool:
    """Set up a scooter from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(hass, address.upper(), True)
    if ble_device is None:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"address": address},
        )

    stored: str | None = entry.data.get(CONF_PASSWORD)
    client = NinebotClient(
        ble_device,
        password=bytes.fromhex(stored) if stored else None,
        name=entry.data.get(CONF_NAME) or ble_device.name,
    )

    coordinator = NinebotCoordinator(hass, entry, client)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_start())

    # Deliberately no update listener: the coordinator reads its poll interval
    # from the entry options on every advertisement, so options changes apply
    # without a reload. Reloading here would also fire when the pairing key is
    # written back to the entry, tearing down the connection that just
    # succeeded and forcing a fresh pairing every time.
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NinebotConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.disconnect()
    return unloaded
