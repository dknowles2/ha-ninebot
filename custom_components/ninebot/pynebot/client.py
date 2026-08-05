"""Asyncio BLE client for Proto2 Ninebot scooters."""

from __future__ import annotations

import asyncio
import logging
import secrets
from types import TracebackType
from typing import Any, Self

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from miauth.nb.nbcrypto import NbCrypto

from .const import (
    APP_KEY_LENGTH,
    NUS_RX_CHAR_UUID,
    NUS_TX_CHAR_UUID,
    PAIRING_TIMEOUT,
    REQUEST_TIMEOUT,
)
from .exceptions import (
    NinebotAuthError,
    NinebotConnectionError,
    NinebotError,
    NinebotPairingRequiredError,
    NinebotProtocolError,
    NinebotTimeoutError,
)
from .models import ScooterInfo, ScooterState
from .protocol import (
    Command,
    DeviceId,
    Packet,
    expected_frame_length,
)
from .registers import (
    DYNAMIC_REGISTERS,
    REGISTERS_BY_KEY,
    STATIC_REGISTERS,
    Register,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 20
"""Fallback MTU payload size when the characteristic does not report one."""

PAIRING_RETRY_INTERVAL = 1.0
"""How often to re-send the pairing request while waiting for a button press."""

MAX_CONSECUTIVE_TIMEOUTS = 3
"""Abort a poll after this many registers in a row fail to answer."""

WORD_SIZE = 2
"""Registers are addressed in 16-bit words."""


class NinebotClient:
    """Talks to a single scooter over BLE.

    The client owns one connection at a time and is not safe to use from
    multiple tasks concurrently; callers should serialize their polls.
    """

    def __init__(
        self,
        device: BLEDevice,
        *,
        app_key: bytes | None = None,
        name: str | None = None,
        request_timeout: float = REQUEST_TIMEOUT,
        pairing_timeout: float = PAIRING_TIMEOUT,
    ) -> None:
        """Initialize the client.

        Args:
            device: The scooter, as discovered by bleak or Home Assistant.
            app_key: A previously negotiated application key. Reusing the key
                from an earlier pairing avoids asking the user to press the
                power button again. A fresh key is generated when omitted.
            name: Overrides the advertised name used to derive the initial
                handshake key. Defaults to the device's advertised name.
            request_timeout: How long to wait for a response to one request.
            pairing_timeout: How long to wait for the user to press the
                scooter's power button.
        """
        self._device = device
        self._name = name or device.name or "Unnamed"
        self._request_timeout = request_timeout
        self._pairing_timeout = pairing_timeout
        self._app_key = app_key or secrets.token_bytes(APP_KEY_LENGTH)
        self._app_key_was_supplied = app_key is not None

        self._crypto = NbCrypto()
        self._client: BleakClient | None = None
        self._responses: asyncio.Queue[Packet] = asyncio.Queue(maxsize=64)
        self._buffer = bytearray()
        self._chunk_size = DEFAULT_CHUNK_SIZE
        self._serial_challenge = b""
        self._lock = asyncio.Lock()

    @property
    def app_key(self) -> bytes:
        """Return the application key in use. Persist this between sessions."""
        return self._app_key

    @property
    def address(self) -> str:
        """Return the scooter's BLE address."""
        return self._device.address

    @property
    def is_connected(self) -> bool:
        """Return True while the BLE link is up."""
        return self._client is not None and self._client.is_connected

    def set_ble_device(self, device: BLEDevice) -> None:
        """Point the client at a refreshed BLEDevice.

        Home Assistant hands out a new BLEDevice on every advertisement; using
        the latest one keeps connections routed through the nearest adapter.
        """
        self._device = device

    async def __aenter__(self) -> Self:
        """Connect on entry to an async context."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Disconnect on exit from an async context."""
        await self.disconnect()

    async def connect(self) -> None:
        """Connect and complete the encrypted handshake.

        Raises:
            NinebotConnectionError: the BLE link could not be established.
            NinebotPairingRequiredError: the user must press the power button.
            NinebotAuthError: the handshake completed but produced an
                unusable session key.
        """
        await self._connect_transport()
        try:
            await self._handshake()
        except NinebotAuthError:
            # A stored key the scooter has since forgotten (factory reset, or
            # pairing cleared in the app) leaves us with a session key that
            # encrypts but does not decrypt. Discard it and pair from scratch.
            if not self._app_key_was_supplied:
                raise
            _LOGGER.info(
                "%s: stored pairing key rejected, re-pairing from scratch", self._name
            )
            self._app_key = secrets.token_bytes(APP_KEY_LENGTH)
            self._app_key_was_supplied = False
            await self.disconnect()
            await self._connect_transport()
            await self._handshake()

    async def _connect_transport(self) -> None:
        """Open the BLE link and subscribe to notifications."""
        self._crypto = NbCrypto()
        self._crypto.set_name(self._name.encode())
        self._buffer.clear()
        while not self._responses.empty():
            self._responses.get_nowait()

        _LOGGER.debug("%s: connecting to %s", self._name, self._device.address)
        try:
            self._client = await establish_connection(
                BleakClient, self._device, self._name
            )
            await self._client.start_notify(NUS_TX_CHAR_UUID, self._on_notify)
        except (BleakError, TimeoutError, OSError) as err:
            self._client = None
            raise NinebotConnectionError(f"Could not connect: {err}") from err

        rx_char = self._client.services.get_characteristic(NUS_RX_CHAR_UUID)
        if rx_char is None:
            await self.disconnect()
            raise NinebotConnectionError(
                "Device does not expose the Nordic UART RX characteristic"
            )
        self._chunk_size = rx_char.max_write_without_response_size or DEFAULT_CHUNK_SIZE

    async def _handshake(self) -> None:
        """Run the INIT/PING/PAIR sequence and derive the session key."""
        init = await self._request(Packet(DeviceId.HOST, DeviceId.BLE, Command.INIT, 0))
        if len(init.data) < APP_KEY_LENGTH:
            raise NinebotAuthError(f"INIT response too short: {len(init.data)} bytes")
        ble_key = init.data[:APP_KEY_LENGTH]
        self._serial_challenge = init.data[APP_KEY_LENGTH:]
        self._crypto.set_ble_data(ble_key)

        ping = await self._request(
            Packet(DeviceId.HOST, DeviceId.BLE, Command.PING, 0, self._app_key)
        )
        if ping.index == 0:
            await self._await_pairing()

        # Switch to the session key derived from the application key. The
        # scooter does this on its side the moment pairing is accepted, so it
        # must happen on both the freshly-paired and already-paired paths.
        self._crypto.set_app_data(self._app_key)

        await self._request(
            Packet(
                DeviceId.HOST,
                DeviceId.BLE,
                Command.PAIR,
                0,
                self._serial_challenge,
            )
        )
        await self._verify_session()

    async def _await_pairing(self) -> None:
        """Re-send pairing requests until the user accepts, or time out."""
        _LOGGER.info("%s: press the scooter's power button to pair", self._name)
        deadline = asyncio.get_running_loop().time() + self._pairing_timeout
        while asyncio.get_running_loop().time() < deadline:
            await self._send(
                Packet(
                    DeviceId.HOST,
                    DeviceId.BLE,
                    Command.PAIR,
                    0,
                    self._serial_challenge,
                )
            )
            try:
                response = await self._receive(timeout=PAIRING_RETRY_INTERVAL)
            except NinebotTimeoutError:
                continue
            if response.command in (Command.PING, Command.PAIR) and response.index == 1:
                _LOGGER.debug("%s: pairing accepted", self._name)
                return
        raise NinebotPairingRequiredError(
            "Scooter did not accept pairing. Press its power button while"
            " Home Assistant is connecting, then try again."
        )

    async def _verify_session(self) -> None:
        """Read a known-good register to confirm the session key works."""
        register = REGISTERS_BY_KEY["serial_number"]
        try:
            await self._read_register(register)
        except (NinebotTimeoutError, NinebotProtocolError) as err:
            raise NinebotAuthError(f"Session key rejected: {err}") from err

    async def disconnect(self) -> None:
        """Tear down the BLE link. Safe to call when already disconnected."""
        client, self._client = self._client, None
        if client is None or not client.is_connected:
            return
        try:
            await client.stop_notify(NUS_TX_CHAR_UUID)
        except (BleakError, OSError) as err:  # pragma: no cover - best effort
            _LOGGER.debug("%s: stop_notify failed: %s", self._name, err)
        try:
            await client.disconnect()
        except (BleakError, OSError) as err:  # pragma: no cover - best effort
            _LOGGER.debug("%s: disconnect failed: %s", self._name, err)

    async def async_poll(self, *, include_static: bool = False) -> ScooterState:
        """Read every register and return a snapshot.

        Individual register failures are recorded in ``ScooterState.failures``
        rather than aborting the poll, so one unsupported register cannot hide
        the rest of the scooter's state.

        Args:
            include_static: Also read registers that never change. Worth doing
                on the first poll of a connection and not much else.
        """
        async with self._lock:
            if not self.is_connected:
                raise NinebotConnectionError("Not connected")

            registers: tuple[Register, ...] = DYNAMIC_REGISTERS
            if include_static:
                registers = STATIC_REGISTERS + DYNAMIC_REGISTERS

            state = ScooterState()
            consecutive_timeouts = 0
            for register in registers:
                try:
                    payload = await self._read_register(register)
                except NinebotTimeoutError as err:
                    consecutive_timeouts += 1
                    state.failures[register.key] = str(err)
                    if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                        # A handful of registers in a row going quiet means the
                        # link is gone, not that the scooter lacks them. Bail
                        # out rather than spending a timeout on each remaining
                        # register.
                        raise NinebotConnectionError(
                            f"Scooter stopped responding after {register.key}"
                        ) from err
                    continue
                except NinebotError as err:
                    _LOGGER.debug(
                        "%s: reading %s failed: %s", self._name, register.key, err
                    )
                    state.failures[register.key] = str(err)
                    continue
                consecutive_timeouts = 0
                state.raw[register.key] = payload.hex().upper()
                try:
                    state.values[register.key] = register.convert(payload)
                except (ValueError, IndexError) as err:
                    state.failures[register.key] = f"Could not decode: {err}"
            return state

    async def async_read(self, key: str) -> Any:
        """Read and decode a single register by key."""
        register = REGISTERS_BY_KEY[key]
        async with self._lock:
            return register.convert(await self._read_register(register))

    def build_info(self, state: ScooterState, hardware_id: int) -> ScooterInfo:
        """Assemble device metadata from a snapshot containing static values."""
        return ScooterInfo(
            address=self._device.address,
            name=self._name,
            hardware_id=hardware_id,
            serial_number=state.get("serial_number"),
            controller_firmware=state.get("controller_firmware"),
            ble_firmware=state.get("ble_firmware"),
            bms_firmware=state.get("bms_firmware"),
            bms_serial_number=state.get("bms_serial_number"),
        )

    async def _read_register(self, register: Register) -> bytes:
        """Read a register's raw payload.

        Tries one bulk read first. Some boards only answer two-byte reads, so
        fall back to walking the index one word at a time.
        """
        try:
            response = await self._request(
                Packet(
                    DeviceId.HOST,
                    register.board,
                    Command.READ,
                    register.index,
                    bytes((register.length,)),
                )
            )
            if len(response.data) >= register.length:
                return response.data[: register.length]
            _LOGGER.debug(
                "%s: short bulk read of %s (%d of %d bytes), walking instead",
                self._name,
                register.key,
                len(response.data),
                register.length,
            )
        except NinebotTimeoutError:
            if register.length <= WORD_SIZE:
                raise

        payload = bytearray()
        for word in range((register.length + 1) // 2):
            response = await self._request(
                Packet(
                    DeviceId.HOST,
                    register.board,
                    Command.READ,
                    register.index + word,
                    b"\x02",
                )
            )
            payload.extend(response.data[:2])
        return bytes(payload[: register.length])

    async def _request(self, packet: Packet, timeout: float | None = None) -> Packet:
        """Send a packet and wait for its matching response."""
        await self._send(packet)
        deadline = asyncio.get_running_loop().time() + (
            self._request_timeout if timeout is None else timeout
        )
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise NinebotTimeoutError(f"No response to {packet}")
            response = await self._receive(timeout=remaining)
            if response.matches_request(packet):
                return response
            _LOGGER.debug("%s: ignoring unsolicited %s", self._name, response)

    async def _send(self, packet: Packet) -> None:
        """Encrypt and write a packet, chunked to the negotiated MTU."""
        if self._client is None or not self._client.is_connected:
            raise NinebotConnectionError("Not connected")

        _LOGGER.debug("%s: >>> %s", self._name, packet)
        payload = bytes(self._crypto.encrypt(bytearray(packet.pack())))
        try:
            for offset in range(0, len(payload), self._chunk_size):
                await self._client.write_gatt_char(
                    NUS_RX_CHAR_UUID, payload[offset : offset + self._chunk_size]
                )
        except (BleakError, TimeoutError, OSError) as err:
            raise NinebotConnectionError(f"Write failed: {err}") from err

    async def _receive(self, timeout: float) -> Packet:
        """Wait for the next decoded packet."""
        try:
            async with asyncio.timeout(timeout):
                return await self._responses.get()
        except TimeoutError as err:
            raise NinebotTimeoutError("Timed out waiting for a response") from err

    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        """Reassemble notification chunks into whole frames.

        Frames arrive split across notifications of at most one MTU each. A
        frame is only handed to the decryption layer once every byte of it has
        arrived; decrypting a partial frame corrupts the cipher's counter.
        """
        self._buffer.extend(data)
        while True:
            start = self._buffer.find(b"\x5a\xa5")
            if start < 0:
                # Nothing that looks like a frame; keep only a possible split
                # preamble so the next notification can complete it.
                del self._buffer[: max(0, len(self._buffer) - 1)]
                return
            if start:
                _LOGGER.debug("%s: discarding %d stray bytes", self._name, start)
                del self._buffer[:start]

            total = expected_frame_length(bytes(self._buffer))
            if total is None or len(self._buffer) < total:
                return

            frame = bytes(self._buffer[:total])
            del self._buffer[:total]
            self._dispatch(frame)

    def _dispatch(self, frame: bytes) -> None:
        """Decrypt one complete frame and queue the packet it contains."""
        try:
            plaintext = bytes(self._crypto.decrypt(bytearray(frame)))
            packet = Packet.unpack(plaintext)
        except NinebotProtocolError as err:
            _LOGGER.debug("%s: dropping malformed frame: %s", self._name, err)
            return
        except Exception as err:
            _LOGGER.debug("%s: could not decrypt frame: %s", self._name, err)
            return

        _LOGGER.debug("%s: <<< %s", self._name, packet)
        try:
            self._responses.put_nowait(packet)
        except asyncio.QueueFull:  # pragma: no cover - defensive
            _LOGGER.warning("%s: response queue full, dropping packet", self._name)
