"""Data models returned by the Ninebot client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import DEFAULT_HARDWARE_ID, HARDWARE_IDS


@dataclass(slots=True)
class ScooterInfo:
    """Immutable facts about a scooter, read once per connection."""

    address: str
    name: str | None = None
    hardware_id: int = DEFAULT_HARDWARE_ID
    serial_number: str | None = None
    controller_firmware: str | None = None
    ble_firmware: str | None = None
    bms_firmware: str | None = None
    bms_serial_number: str | None = None

    @property
    def model(self) -> str:
        """Return a human readable model name."""
        return HARDWARE_IDS.get(self.hardware_id, f"Unknown model {self.hardware_id}")


@dataclass(slots=True)
class ScooterState:
    """A snapshot of every register read during one poll."""

    values: dict[str, Any] = field(default_factory=dict)
    """Decoded and scaled values, keyed by register key."""

    raw: dict[str, str] = field(default_factory=dict)
    """Undecoded register payloads as hex, keyed by register key.

    Kept so that scaling assumptions can be checked against reality without
    reading the scooter again.
    """

    failures: dict[str, str] = field(default_factory=dict)
    """Registers that could not be read this poll, keyed by register key."""

    def get(self, key: str) -> Any:
        """Return a decoded value, or None if the register was not read."""
        return self.values.get(key)

    def update(self, other: ScooterState) -> None:
        """Merge another snapshot into this one, in place."""
        self.values.update(other.values)
        self.raw.update(other.raw)
        # A register that succeeded this time is no longer failing.
        for key in other.values:
            self.failures.pop(key, None)
        self.failures.update(other.failures)


def parse_hardware_id(manufacturer_data: bytes) -> int | None:
    """Extract the hardware ID from Ninebot manufacturer advertisement data.

    The hardware ID is the first byte. Returns None if the payload is empty.
    """
    if not manufacturer_data:
        return None
    return manufacturer_data[0]
