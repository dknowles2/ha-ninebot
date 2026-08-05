"""pynebot: a client for Segway-Ninebot scooters speaking the Proto2 BLE protocol.

This package is vendored inside the Home Assistant integration for now. It has
no Home Assistant imports and is intended to be split out into a standalone
library once the register scalings have been confirmed against real hardware.
"""

from __future__ import annotations

from .client import NinebotClient
from .const import (
    APP_KEY_LENGTH,
    DEFAULT_HARDWARE_ID,
    HARDWARE_IDS,
    MANUFACTURER_ID,
    NUS_SERVICE_UUID,
)
from .exceptions import (
    NinebotAuthError,
    NinebotConnectionError,
    NinebotError,
    NinebotPairingRequiredError,
    NinebotProtocolError,
    NinebotTimeoutError,
)
from .models import ScooterInfo, ScooterState, parse_hardware_id
from .protocol import Command, DeviceId, Packet
from .registers import (
    DYNAMIC_REGISTERS,
    REGISTERS,
    REGISTERS_BY_KEY,
    STATIC_REGISTERS,
    Register,
)

__all__ = [
    "APP_KEY_LENGTH",
    "DEFAULT_HARDWARE_ID",
    "DYNAMIC_REGISTERS",
    "HARDWARE_IDS",
    "MANUFACTURER_ID",
    "NUS_SERVICE_UUID",
    "REGISTERS",
    "REGISTERS_BY_KEY",
    "STATIC_REGISTERS",
    "Command",
    "DeviceId",
    "NinebotAuthError",
    "NinebotClient",
    "NinebotConnectionError",
    "NinebotError",
    "NinebotPairingRequiredError",
    "NinebotProtocolError",
    "NinebotTimeoutError",
    "Packet",
    "Register",
    "ScooterInfo",
    "ScooterState",
    "parse_hardware_id",
]
