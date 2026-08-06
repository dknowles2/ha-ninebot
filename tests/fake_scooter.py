"""An in-memory scooter that speaks Proto2 with Encryption2, for tests.

The fake runs the real cipher, so the handshake it exercises is the one the
hardware performs: PRE_COMM in non-SN mode, then counter mode for SET_PWD and
AUTH, with the key re-derived at each phase.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import contextlib
from typing import Any
from unittest.mock import patch

from bleak.backends.device import BLEDevice

from custom_components.ninebot.pynebot.const import (
    NUS_RX_CHAR_UUID,
    NUS_TX_CHAR_UUID,
    PASSWORD_LENGTH,
)
from custom_components.ninebot.pynebot.crypto import FW_DATA, Encryption2
from custom_components.ninebot.pynebot.protocol import (
    Command,
    DeviceId,
    Packet,
    expected_frame_length,
)

TRAILER_SIZE = 6

AUTH_PARAM = bytes(16)
"""Real scooters have been seen returning an all-zero auth parameter."""

SERIAL_CHALLENGE = b"N2ABA2415P0216"

DEFAULT_REGISTERS: dict[tuple[int, int], bytes] = {
    # (board, index): payload
    (DeviceId.MCU, 0x10): b"N2GX2318000216",
    (DeviceId.MCU, 0x1A): b"\x13\x02",
    (DeviceId.MCU, 0x1B): b"\x00\x00",
    (DeviceId.MCU, 0x1C): b"\x00\x00",
    (DeviceId.MCU, 0x25): b"\x10\x27",  # 10000 -> 100.0 km
    (DeviceId.MCU, 0x3B): b"\xe8\x03",
    (DeviceId.MCU, 0x3E): b"\xf4\x01",  # 500 -> 50.0 C
    (DeviceId.MCU, 0x67): b"\x10\x02",
    (DeviceId.MCU, 0x68): b"\x09\x02",
    (DeviceId.MCU, 0x69): b"\x01\x00",
    (DeviceId.MCU, 0x75): b"\x01\x00",
    (DeviceId.MCU, 0x76): b"\x00\x00",
    (DeviceId.MCU, 0x77): b"\x00\x00",
    (DeviceId.MCU, 0x7A): b"\x01\x00",
    (DeviceId.MCU, 0x7C): b"\x00\x00",
    (DeviceId.MCU, 0x7F): b"\xd0\x07",
    (DeviceId.MCU, 0x95): b"\x01\x00",
    (DeviceId.MCU, 0xB4): b"\x55\x00",  # 85 %
    (DeviceId.MCU, 0xB5): b"\x00\x00",
    (DeviceId.MCU, 0xB7): b"\x20\x4e\x00\x00",  # 20000 -> 20.0 km
    (DeviceId.MCU, 0xB9): b"\xc8\x00",  # 200 -> 2.0 km
    (DeviceId.MCU, 0xDA): bytes(range(12)),
    (DeviceId.MCU, 0xF3): b"\x01\x00",
    (DeviceId.BMS, 0x02): b"BMS12345678901",
    (DeviceId.BMS, 0x0A): b"\x01\x00",
    (DeviceId.BMS, 0x0E): b"\x21\x01",
    (DeviceId.BMS, 0x59): b"\x2a\x00",  # 42 cycles
    (DeviceId.BMS, 0x5A): b"\x10\x0e",
    (DeviceId.BMS, 0x82): b"\x2c\x01",
    (DeviceId.BMS, 0x89): b"\x00\x00",
    (DeviceId.BMS, 0x8A): b"\xd0\x07",
    (DeviceId.BMS, 0x8C): b"\x9c\x0f",  # 3996 -> 39.96 V
    (DeviceId.BMS, 0x8D): b"\x9c\xff",  # -100 -> -1.00 A
    (DeviceId.BMS, 0x8F): b"\x52\x00",  # 82 %
    (DeviceId.BMS, 0x96): b"\x2b\x2c\x00\x00",  # 23 C, 24 C
    (DeviceId.BMS, 0xA0): b"".join(
        (3900 + index).to_bytes(2, "little") for index in range(13)
    ),
    (DeviceId.BMS, 0xE1): b"\x40\x1f\x00\x00",
    (DeviceId.BMS, 0xE3): b"\x88\x13\x00\x00",
    (DeviceId.BLE, 0x1C): b"\x00\x00",
    (DeviceId.BLE, 0x59): b"BLEPART000123",
}


class FakeCharacteristic:
    """Minimal stand-in for a BleakGATTCharacteristic."""

    def __init__(self, uuid: str, chunk_size: int = 20) -> None:
        """Initialize the characteristic."""
        self.uuid = uuid
        self.max_write_without_response_size = chunk_size


class FakeServices:
    """Minimal stand-in for a BleakGATTServiceCollection."""

    def __init__(self, chunk_size: int) -> None:
        """Initialize the collection."""
        self._chunk_size = chunk_size

    def get_characteristic(self, uuid: str) -> FakeCharacteristic | None:
        """Return the requested characteristic, if we model it."""
        if uuid in (NUS_RX_CHAR_UUID, NUS_TX_CHAR_UUID):
            return FakeCharacteristic(uuid, self._chunk_size)
        return None


class FakeScooter:
    """A scooter that answers Proto2 requests in memory."""

    def __init__(
        self,
        *,
        name: str = "E2 Pro 0216",
        paired_password: bytes | None = None,
        require_button_press: bool = False,
        chunk_size: int = 20,
        supports_bulk_reads: bool = True,
    ) -> None:
        """Configure the fake scooter's behaviour."""
        self.name = name
        self.paired_password = paired_password
        self.require_button_press = require_button_press
        self.chunk_size = chunk_size
        self.supports_bulk_reads = supports_bulk_reads
        self.registers = dict(DEFAULT_REGISTERS)
        self.unreadable: set[tuple[int, int]] = set()

        self.is_connected = False
        self.services = FakeServices(chunk_size)
        self.pair_attempts = 0
        self.requests: list[Packet] = []
        self.connect_count = 0

        self._crypto = Encryption2()
        self._crypto.set_key(name.encode(), FW_DATA)

        self._notify: Callable[[Any, bytearray], None] | None = None
        self._rx_buffer = bytearray()

    # -- BleakClient surface ------------------------------------------------

    async def start_notify(
        self, uuid: str, callback: Callable[[Any, bytearray], None]
    ) -> None:
        """Subscribe to the TX characteristic."""
        self._notify = callback

    async def stop_notify(self, uuid: str) -> None:
        """Unsubscribe."""
        self._notify = None

    async def disconnect(self) -> None:
        """Drop the link."""
        self.is_connected = False

    async def write_gatt_char(self, uuid: str, data: bytes) -> None:
        """Accept a chunk of a request and answer once a frame is complete."""
        assert uuid == NUS_RX_CHAR_UUID
        self._rx_buffer.extend(data)
        while True:
            total = expected_frame_length(self._rx_buffer)
            if total is None or len(self._rx_buffer) < total:
                return
            frame = bytes(self._rx_buffer[:total])
            del self._rx_buffer[:total]
            self._handle(frame)

    # -- Scooter behaviour --------------------------------------------------

    def _handle(self, frame: bytes) -> None:
        """Decode a request and emit the matching response."""
        request = Packet.unpack(self._crypto.decrypt(frame))
        self.requests.append(request)

        if request.command is Command.PRE_COMM:
            # The index tells the client whether a password is already stored.
            self._respond(
                Packet(
                    DeviceId.BLE_BOARD,
                    DeviceId.PHONE,
                    Command.PRE_COMM,
                    int(self.paired_password is not None),
                    AUTH_PARAM + SERIAL_CHALLENGE,
                )
            )
            self._crypto.set_auth(AUTH_PARAM)
            self._crypto.start_sn()
            if self.paired_password is not None:
                self._crypto.set_key(self.paired_password, AUTH_PARAM)
            else:
                self._crypto.set_key(self.name.encode(), AUTH_PARAM)
            return

        if request.command is Command.SET_PWD:
            self.pair_attempts += 1
            if self.require_button_press:
                self._respond(
                    Packet(DeviceId.BLE_BOARD, DeviceId.PHONE, Command.SET_PWD, 0)
                )
                return
            self.paired_password = request.data[:PASSWORD_LENGTH]
            self._respond(
                Packet(DeviceId.BLE_BOARD, DeviceId.PHONE, Command.SET_PWD, 1)
            )
            self._crypto.set_key(self.paired_password, AUTH_PARAM)
            return

        if request.command is Command.AUTH:
            accepted = request.data[: len(SERIAL_CHALLENGE)] == SERIAL_CHALLENGE
            self._respond(
                Packet(DeviceId.BLE_BOARD, DeviceId.PHONE, Command.AUTH, int(accepted))
            )
            return

        if request.command is Command.READ:
            self._handle_read(request)

    def _handle_read(self, request: Packet) -> None:
        """Answer a register read."""
        key = (request.target, request.index)
        if key in self.unreadable:
            return

        wanted = request.data[0] if request.data else 2
        payload = self.registers.get(key)

        if payload is None:
            # Walked reads land on an offset word of a longer register.
            for (board, index), value in self.registers.items():
                offset = (request.index - index) * 2
                if board == request.target and 0 < offset < len(value):
                    payload = value[offset:]
                    break

        if payload is None:
            return
        if wanted > 2 and not self.supports_bulk_reads:
            return

        self._respond(
            Packet(
                request.target,
                DeviceId.PHONE,
                Command.READ_ACK,
                request.index,
                payload[:wanted],
            )
        )

    def _respond(self, packet: Packet) -> None:
        """Send a response, split across notification-sized chunks."""
        assert self._notify is not None
        payload = self._crypto.encrypt(packet.pack())
        for offset in range(0, len(payload), self.chunk_size):
            self._notify(None, bytearray(payload[offset : offset + self.chunk_size]))


@contextlib.contextmanager
def patch_transport(scooter: FakeScooter) -> Iterator[FakeScooter]:
    """Route the client's BLE calls to a fake scooter."""

    async def _establish_connection(
        client_class: Any, device: Any, name: str, **kwargs: Any
    ) -> FakeScooter:
        scooter.is_connected = True
        scooter.connect_count += 1
        return scooter

    with patch(
        "custom_components.ninebot.pynebot.client.establish_connection",
        _establish_connection,
    ):
        yield scooter


def make_ble_device(address: str, name: str) -> Any:
    """Return a BLEDevice suitable for the client."""
    return BLEDevice(address=address, name=name, details={})


__all__ = [
    "AUTH_PARAM",
    "SERIAL_CHALLENGE",
    "FakeScooter",
    "make_ble_device",
    "patch_transport",
]
