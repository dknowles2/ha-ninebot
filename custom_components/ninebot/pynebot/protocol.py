"""Proto2 frame encoding and decoding.

Frame layout (before encryption)::

    5A A5 | LEN | SRC | DST | CMD | IDX | DATA[LEN]

``LEN`` counts only the data segment. The encryption layer appends a CRC and a
message counter, so an encrypted frame is 6 bytes longer than the plaintext one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import enum

from .const import PROTO2_MAGIC
from .exceptions import NinebotProtocolError

HEADER_LENGTH = 7
"""Magic (2) + length (1) + source (1) + target (1) + command (1) + index (1)."""

MAX_DATA_LENGTH = 0xFF
"""The length field is one byte."""

LENGTH_FIELD_OFFSET = 3
"""Bytes that must arrive before a frame's length is known."""

ENCRYPTION_OVERHEAD = 6
"""CRC (4) plus message counter (2), appended by the encryption layer.

The first three plaintext bytes (preamble and length) are sent in the clear, so
an encrypted frame is exactly six bytes longer than the plaintext frame.
"""


class Command(enum.IntEnum):
    """Proto2 command byte."""

    READ = 0x01
    WRITE = 0x02
    WRITE_NO_REPLY = 0x03
    READ_ACK = 0x04
    WRITE_ACK = 0x05
    PRE_COMM = 0x5B
    """Handshake phase 1: fetch the auth parameter and serial number."""
    SET_PWD = 0x5C
    """Handshake phase 2: establish a session password."""
    AUTH = 0x5D
    """Handshake phase 3: authenticate with the password and serial."""


#: Which command a request expects to see in its response.
RESPONSE_COMMANDS: dict[Command, Command] = {
    Command.READ: Command.READ_ACK,
    Command.WRITE: Command.WRITE_ACK,
}


class DeviceId(enum.IntEnum):
    """Board addresses within the vehicle."""

    BLE_BOARD = 0x04
    """The Bluetooth board, as addressed during the handshake."""
    MCU = 0x20
    """Main controller."""
    BLE = 0x21
    """Bluetooth module."""
    BMS = 0x22
    """Battery management system."""
    HOST = 0x3D
    """Us: a wired/IoT host. Preferred over PHONE, which the app uses."""
    PHONE = 0x3E
    """The official mobile app."""


@dataclass(slots=True)
class Packet:
    """A single Proto2 frame."""

    source: DeviceId
    target: DeviceId
    command: Command
    index: int
    data: bytes = field(default=b"")

    def pack(self) -> bytes:
        """Serialize to wire format, without encryption."""
        if len(self.data) > MAX_DATA_LENGTH:
            raise NinebotProtocolError(f"Data segment too long: {len(self.data)}")
        return (
            PROTO2_MAGIC
            + bytes(
                (
                    len(self.data),
                    self.source,
                    self.target,
                    self.command,
                    self.index & 0xFF,
                )
            )
            + self.data
        )

    @classmethod
    def unpack(cls, raw: bytes) -> Packet:
        """Parse a decrypted frame.

        Raises:
            NinebotProtocolError: if the frame is truncated or malformed.
        """
        if len(raw) < HEADER_LENGTH:
            raise NinebotProtocolError(f"Frame too short: {len(raw)} bytes")
        if raw[:2] != PROTO2_MAGIC:
            raise NinebotProtocolError(f"Bad preamble: {raw[:2].hex()}")

        length = raw[2]
        if len(raw) < HEADER_LENGTH + length:
            raise NinebotProtocolError(
                f"Truncated frame: want {HEADER_LENGTH + length}, got {len(raw)}"
            )

        try:
            source = DeviceId(raw[3])
            target = DeviceId(raw[4])
            command = Command(raw[5])
        except ValueError as err:
            raise NinebotProtocolError(f"Unknown field in frame: {err}") from err

        return cls(
            source=source,
            target=target,
            command=command,
            index=raw[6],
            data=bytes(raw[HEADER_LENGTH : HEADER_LENGTH + length]),
        )

    def matches_request(self, request: Packet) -> bool:
        """Return True if this packet is a valid response to ``request``."""
        if self.source is not request.target or self.target is not request.source:
            return False
        if self.command is not RESPONSE_COMMANDS.get(request.command, request.command):
            return False
        # Handshake commands reuse the index field to carry a status code, so
        # only register traffic is matched on it.
        if request.command < Command.PRE_COMM:
            return self.index == request.index
        return True

    def __str__(self) -> str:
        """Return a readable description, for debug logging."""
        suffix = f" data={self.data.hex().upper()}" if self.data else ""
        return (
            f"{self.source.name}->{self.target.name} {self.command.name}"
            f" idx=0x{self.index:02X}{suffix}"
        )


def expected_frame_length(raw: bytes) -> int | None:
    """Return the total encrypted length of the frame starting at ``raw``.

    Returns None while too few bytes have arrived to tell.
    """
    if len(raw) < LENGTH_FIELD_OFFSET:
        return None
    return raw[2] + HEADER_LENGTH + ENCRYPTION_OVERHEAD
