"""Config flow for the Ninebot integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
import voluptuous as vol

from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .pynebot import HARDWARE_IDS, MANUFACTURER_ID, parse_hardware_id


def _title(service_info: BluetoothServiceInfoBleak) -> str:
    """Return a display name for a discovered scooter."""
    if raw := service_info.manufacturer_data.get(MANUFACTURER_ID):
        hardware_id = parse_hardware_id(raw)
        if hardware_id is not None and hardware_id in HARDWARE_IDS:
            return f"{HARDWARE_IDS[hardware_id]} ({service_info.name})"
    return service_info.name or service_info.address


def _is_ninebot(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if this advertisement looks like a Ninebot vehicle."""
    return MANUFACTURER_ID in service_info.manufacturer_data


class NinebotConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ninebot scooters."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> NinebotOptionsFlow:
        """Return the options flow."""
        return NinebotOptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a scooter discovered over Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not _is_ninebot(discovery_info):
            return self.async_abort(reason="not_supported")

        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info)}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm adding a discovered scooter."""
        assert self._discovery is not None
        title = _title(self._discovery)

        if user_input is not None:
            return self.async_create_entry(
                title=title,
                data={
                    CONF_ADDRESS: self._discovery.address,
                    CONF_NAME: self._discovery.name,
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm", description_placeholders={"name": title}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick from the scooters currently advertising."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            service_info = self._discovered[address]
            return self.async_create_entry(
                title=_title(service_info),
                data={CONF_ADDRESS: address, CONF_NAME: service_info.name},
            )

        configured = self._async_current_ids(include_ignore=False)
        self._discovered = {
            service_info.address: service_info
            for service_info in async_discovered_service_info(self.hass, True)
            if service_info.address not in configured and _is_ninebot(service_info)
        }
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: _title(service_info)
                            for address, service_info in self._discovered.items()
                        }
                    )
                }
            ),
        )


class NinebotOptionsFlow(OptionsFlow):
    """Handle Ninebot options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the poll interval."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL.total_seconds()
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POLL_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_POLL_INTERVAL,
                            max=MAX_POLL_INTERVAL,
                            step=10,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
