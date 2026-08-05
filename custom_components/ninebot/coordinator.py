"""Coordinator for the Ninebot integration."""

from __future__ import annotations

import logging
from typing import override

from bluetooth_data_tools import monotonic_time_coarse
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import CONF_APP_KEY, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
from .pynebot import (
    DEFAULT_HARDWARE_ID,
    MANUFACTURER_ID,
    NinebotClient,
    NinebotError,
    NinebotPairingRequiredError,
    ScooterInfo,
    ScooterState,
    parse_hardware_id,
)

_LOGGER = logging.getLogger(__name__)

type NinebotConfigEntry = ConfigEntry[NinebotCoordinator]


class NinebotCoordinator(ActiveBluetoothDataUpdateCoordinator[None]):
    """Polls a Ninebot scooter whenever it advertises and is due for a read."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NinebotConfigEntry,
        client: NinebotClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            address=client.address,
            mode=BluetoothScanningMode.PASSIVE,
            needs_poll_method=self._needs_poll,
            poll_method=self._async_update,
            connectable=True,
        )
        self.entry = entry
        self.client = client
        self.state = ScooterState()
        self.info = ScooterInfo(address=client.address, name=entry.title)
        self.pairing_required = False
        self._hardware_id: int | None = None

    @property
    def poll_interval(self) -> float:
        """Return the configured interval between polls, in seconds."""
        configured = self.entry.options.get(CONF_POLL_INTERVAL)
        if configured is None:
            return DEFAULT_POLL_INTERVAL.total_seconds()
        return float(configured)

    @callback
    def _needs_poll(
        self,
        service_info: BluetoothServiceInfoBleak,
        seconds_since_last_poll: float | None,
    ) -> bool:
        """Return True when the scooter is due for a read."""
        if self.hass.is_stopping:
            return False
        return (
            seconds_since_last_poll is None
            or seconds_since_last_poll >= self.poll_interval
        )

    async def _async_update(self, service_info: BluetoothServiceInfoBleak) -> None:
        """Connect if needed, then read the scooter's registers."""
        self.client.set_ble_device(service_info.device)

        first_poll = not self.state.values
        if not self.client.is_connected:
            await self.client.connect()
            self._persist_app_key()
            first_poll = True

        self.state.update(await self.client.async_poll(include_static=first_poll))
        self.pairing_required = False

        if first_poll:
            self.info = self.client.build_info(
                self.state, self._hardware_id or DEFAULT_HARDWARE_ID
            )

    def _persist_app_key(self) -> None:
        """Store the pairing key so restarts do not need a button press."""
        app_key = self.client.app_key.hex()
        if self.entry.data.get(CONF_APP_KEY) == app_key:
            return
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_APP_KEY: app_key}
        )
        _LOGGER.debug("Stored new pairing key for %s", self.entry.title)

    @override
    async def _async_poll(self) -> None:
        """Poll the scooter, tolerating the failures a sleepy device produces."""
        assert self._last_service_info

        try:
            await self._async_poll_data(self._last_service_info)
        except NinebotPairingRequiredError as err:
            self.pairing_required = True
            if self.last_poll_successful:
                _LOGGER.warning("%s needs pairing: %s", self.entry.title, err)
                self.last_poll_successful = False
            await self._async_drop_connection()
            return
        except NinebotError as err:
            if self.last_poll_successful:
                _LOGGER.info("%s is unavailable: %s", self.entry.title, err)
                self.last_poll_successful = False
            await self._async_drop_connection()
            return
        except Exception:
            if self.last_poll_successful:
                _LOGGER.exception(
                    "%s: unexpected error while polling", self.entry.title
                )
                self.last_poll_successful = False
            await self._async_drop_connection()
            return
        finally:
            self._last_poll = monotonic_time_coarse()

        if not self.last_poll_successful:
            _LOGGER.info("%s is back online", self.entry.title)
            self.last_poll_successful = True

        self._async_handle_bluetooth_poll()

    async def _async_drop_connection(self) -> None:
        """Close the link so the next poll starts from a clean handshake."""
        try:
            await self.client.disconnect()
        except Exception:
            _LOGGER.debug("%s: error while disconnecting", self.entry.title)

    @callback
    @override
    def _async_handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Track the freshest BLEDevice and the advertised hardware ID."""
        self.client.set_ble_device(service_info.device)
        if raw := service_info.manufacturer_data.get(MANUFACTURER_ID):
            self._hardware_id = parse_hardware_id(raw)
        super()._async_handle_bluetooth_event(service_info, change)
