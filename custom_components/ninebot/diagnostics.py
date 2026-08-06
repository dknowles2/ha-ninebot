"""Diagnostics for the Ninebot integration.

The raw register payloads are the point of this dump. Every scaling factor in
``pynebot.registers`` is currently an assumption, and comparing a raw value here
against what the scooter's display shows is how those assumptions get settled.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD
from .coordinator import NinebotConfigEntry
from .pynebot import REGISTERS_BY_KEY

TO_REDACT = {CONF_PASSWORD, "serial_number", "bms_serial_number", "cpu_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NinebotConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    state = coordinator.state

    registers = {
        key: {
            "index": f"0x{REGISTERS_BY_KEY[key].index:02X}",
            "board": REGISTERS_BY_KEY[key].board.name,
            "length": REGISTERS_BY_KEY[key].length,
            "scale": REGISTERS_BY_KEY[key].scale,
            "raw": raw,
            "value": state.values.get(key),
        }
        for key, raw in sorted(state.raw.items())
        if key in REGISTERS_BY_KEY
    }

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "device": async_redact_data(asdict(coordinator.info), TO_REDACT),
        "poll": {
            "interval_seconds": coordinator.poll_interval,
            "last_poll_successful": coordinator.last_poll_successful,
            "pairing_required": coordinator.pairing_required,
            "connected": coordinator.client.is_connected,
        },
        "registers": async_redact_data(registers, TO_REDACT),
        "failures": state.failures,
    }
