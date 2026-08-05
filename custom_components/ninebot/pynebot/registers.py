"""Register map for the Ninebot eKickScooter E2 Pro (hardware ID 141 / 0x8D).

Indices and byte lengths come from the community protocol documentation at
https://nootnooot.codeberg.page/segway-ninebot-ble/devices/ninebot-ekickscooter-e2-pro/

Scaling factors are a different matter. The documentation records *what* each
register is, not the units its raw value is expressed in. Every ``scale`` below
carries a confidence marker:

``VERIFIED``
    Confirmed against a real scooter.
``ASSUMED``
    Follows the convention used by earlier Ninebot models. Plausible, unproven.

Nothing is ``VERIFIED`` yet. Until a register is confirmed, prefer the raw value
in the diagnostics dump over the scaled entity state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .protocol import DeviceId


def _u16(data: bytes) -> int:
    """Decode a little-endian unsigned 16-bit value."""
    return int.from_bytes(data[:2], "little", signed=False)


def _s16(data: bytes) -> int:
    """Decode a little-endian signed 16-bit value."""
    return int.from_bytes(data[:2], "little", signed=True)


def _u32(data: bytes) -> int:
    """Decode a 32-bit value stored as two little-endian 16-bit words."""
    return _u16(data[:2]) | (_u16(data[2:4]) << 16)


def _string(data: bytes) -> str:
    """Decode a NUL-padded ASCII string, ignoring undecodable trailing bytes."""
    return data.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()


def _hex(data: bytes) -> str:
    """Decode an opaque identifier as uppercase hex."""
    return data.hex().upper()


def _version(data: bytes) -> str:
    """Decode a packed firmware version (0x0213 -> "2.1.3")."""
    raw = _u16(data)
    return f"{raw >> 8}.{(raw >> 4) & 0x0F}.{raw & 0x0F}"


def _temperature_pair(data: bytes) -> tuple[float, float]:
    """Decode the two BMS temperature probes.

    Each probe is a byte biased by 20 degrees, matching earlier Ninebot models.
    """
    return (float(data[0] - 20), float(data[1] - 20))


def _cell_voltages(data: bytes) -> tuple[float, ...]:
    """Decode per-cell voltages, in volts. Trailing empty slots are dropped."""
    cells = [_u16(data[offset : offset + 2]) for offset in range(0, len(data) - 1, 2)]
    return tuple(cell / 1000 for cell in cells if cell)


def _bit(position: int) -> Callable[[bytes], bool]:
    """Return a decoder extracting a single bit from a 16-bit bitfield."""

    def decode(data: bytes) -> bool:
        return bool(_u16(data) & (1 << position))

    return decode


@dataclass(frozen=True, slots=True, kw_only=True)
class Register:
    """A readable register on one of the scooter's boards."""

    key: str
    """Stable identifier. Used for entity unique IDs, so never rename one."""

    board: DeviceId
    index: int
    length: int
    decode: Callable[[bytes], Any] = _u16
    scale: float = 1.0
    """Multiplier applied to numeric values after decoding."""

    static: bool = False
    """True for values that never change; read once per connection."""

    def convert(self, data: bytes) -> Any:
        """Decode and scale a raw register payload."""
        value = self.decode(data)
        if self.scale != 1.0 and isinstance(value, (int, float)):
            return round(value * self.scale, 4)
        return value


_MCU_REGISTERS: tuple[Register, ...] = (
    Register(
        key="serial_number",
        board=DeviceId.MCU,
        index=0x10,
        length=14,
        decode=_string,
        static=True,
    ),
    Register(
        key="controller_firmware",
        board=DeviceId.MCU,
        index=0x1A,
        length=2,
        decode=_version,
        static=True,
    ),
    Register(key="error_code", board=DeviceId.MCU, index=0x1B, length=2),
    Register(key="warning_code", board=DeviceId.MCU, index=0x1C, length=2),
    Register(
        key="remaining_range", board=DeviceId.MCU, index=0x25, length=2, scale=0.01
    ),  # ASSUMED: 10 m units -> km
    Register(
        key="uptime", board=DeviceId.MCU, index=0x3B, length=2
    ),  # ASSUMED: seconds
    Register(
        key="body_temperature", board=DeviceId.MCU, index=0x3E, length=2, scale=0.1
    ),  # ASSUMED: deci-degrees C
    Register(
        key="bms_firmware",
        board=DeviceId.MCU,
        index=0x67,
        length=2,
        decode=_version,
        static=True,
    ),
    Register(
        key="ble_firmware",
        board=DeviceId.MCU,
        index=0x68,
        length=2,
        decode=_version,
        static=True,
    ),
    Register(
        key="activation_date", board=DeviceId.MCU, index=0x69, length=2, static=True
    ),
    Register(key="gear_mode", board=DeviceId.MCU, index=0x75, length=2),
    Register(key="deceleration_mode", board=DeviceId.MCU, index=0x76, length=2),
    Register(key="pedestrian_mode", board=DeviceId.MCU, index=0x77, length=2),
    Register(key="light_mode", board=DeviceId.MCU, index=0x7A, length=2),
    Register(key="cruise_control", board=DeviceId.MCU, index=0x7C, length=2),
    Register(
        key="start_speed", board=DeviceId.MCU, index=0x7F, length=2, scale=0.001
    ),  # ASSUMED: milli-km/h
    Register(
        key="encryption_flag", board=DeviceId.MCU, index=0x95, length=2, static=True
    ),
    Register(
        key="battery_percent", board=DeviceId.MCU, index=0xB4, length=2
    ),  # ASSUMED: already a percentage
    Register(
        key="speed", board=DeviceId.MCU, index=0xB5, length=2, scale=0.001
    ),  # ASSUMED: milli-km/h
    Register(
        key="total_distance",
        board=DeviceId.MCU,
        index=0xB7,
        length=4,
        decode=_u32,
        scale=0.001,
    ),  # ASSUMED: metres -> km
    Register(
        key="trip_distance", board=DeviceId.MCU, index=0xB9, length=2, scale=0.01
    ),  # ASSUMED: 10 m units -> km
    Register(
        key="cpu_id",
        board=DeviceId.MCU,
        index=0xDA,
        length=12,
        decode=_hex,
        static=True,
    ),
    Register(key="traction_control", board=DeviceId.MCU, index=0xF3, length=2),
)

_BMS_REGISTERS: tuple[Register, ...] = (
    Register(
        key="bms_serial_number",
        board=DeviceId.BMS,
        index=0x02,
        length=14,
        decode=_string,
        static=True,
    ),
    Register(
        key="bms_manufacture_date",
        board=DeviceId.BMS,
        index=0x0A,
        length=2,
        static=True,
    ),
    Register(
        key="bms_version",
        board=DeviceId.BMS,
        index=0x0E,
        length=2,
        decode=_version,
        static=True,
    ),
    Register(key="battery_cycles", board=DeviceId.BMS, index=0x59, length=2),
    Register(
        key="battery_design_capacity",
        board=DeviceId.BMS,
        index=0x5A,
        length=2,
        static=True,
    ),  # ASSUMED: mAh
    Register(
        key="max_power", board=DeviceId.BMS, index=0x82, length=2, static=True
    ),  # ASSUMED: watts
    Register(key="battery_deep_discharges", board=DeviceId.BMS, index=0x89, length=2),
    Register(
        key="battery_remaining_capacity", board=DeviceId.BMS, index=0x8A, length=2
    ),  # ASSUMED: mAh
    Register(
        key="battery_voltage", board=DeviceId.BMS, index=0x8C, length=2, scale=0.01
    ),  # ASSUMED: centivolts
    Register(
        key="battery_current",
        board=DeviceId.BMS,
        index=0x8D,
        length=2,
        decode=_s16,
        scale=0.01,
    ),  # ASSUMED: centiamps
    Register(
        key="battery_level", board=DeviceId.BMS, index=0x8F, length=2
    ),  # ASSUMED: already a percentage
    Register(
        key="battery_temperatures",
        board=DeviceId.BMS,
        index=0x96,
        length=4,
        decode=_temperature_pair,
    ),
    Register(
        key="cell_voltages",
        board=DeviceId.BMS,
        index=0xA0,
        length=26,
        decode=_cell_voltages,
    ),
    Register(
        key="battery_capacity_throughput",
        board=DeviceId.BMS,
        index=0xE1,
        length=4,
        decode=_u32,
    ),
    Register(
        key="battery_energy_throughput",
        board=DeviceId.BMS,
        index=0xE3,
        length=4,
        decode=_u32,
    ),
)

_BLE_REGISTERS: tuple[Register, ...] = (
    Register(key="locked", board=DeviceId.BLE, index=0x1C, length=2, decode=_bit(0)),
    Register(
        key="ble_part_number",
        board=DeviceId.BLE,
        index=0x59,
        length=14,
        decode=_string,
        static=True,
    ),
)

REGISTERS: tuple[Register, ...] = _MCU_REGISTERS + _BMS_REGISTERS + _BLE_REGISTERS

REGISTERS_BY_KEY: dict[str, Register] = {reg.key: reg for reg in REGISTERS}

STATIC_REGISTERS: tuple[Register, ...] = tuple(reg for reg in REGISTERS if reg.static)
DYNAMIC_REGISTERS: tuple[Register, ...] = tuple(
    reg for reg in REGISTERS if not reg.static
)
