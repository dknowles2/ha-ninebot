"""Tests for the BLE client."""

from __future__ import annotations

import pytest

from custom_components.ninebot.pynebot.client import NinebotClient
from custom_components.ninebot.pynebot.exceptions import (
    NinebotConnectionError,
    NinebotPairingRequiredError,
    NinebotTimeoutError,
)
from custom_components.ninebot.pynebot.protocol import Command, DeviceId

from .conftest import SCOOTER_ADDRESS, SCOOTER_NAME
from .fake_scooter import FakeScooter, make_ble_device, patch_transport


def _client(password: bytes | None = None) -> NinebotClient:
    """Return a client with timeouts short enough to keep tests quick."""
    return NinebotClient(
        make_ble_device(SCOOTER_ADDRESS, SCOOTER_NAME),
        password=password,
        request_timeout=0.05,
        pairing_timeout=0.2,
    )


async def test_connect_pairs_and_reads(transport: FakeScooter) -> None:
    client = _client()

    await client.connect()

    assert client.is_connected
    commands = [request.command for request in transport.requests]
    assert Command.PRE_COMM in commands
    assert Command.SET_PWD in commands
    assert Command.AUTH in commands


async def test_poll_decodes_every_register(transport: FakeScooter) -> None:
    client = _client()
    await client.connect()

    state = await client.async_poll(include_static=True)

    assert state.failures == {}
    assert state.values["battery_level"] == 82
    assert state.values["battery_percent"] == 85
    assert state.values["battery_voltage"] == 39.96
    assert state.values["battery_current"] == -1.0
    assert state.values["total_distance"] == 20.0
    assert state.values["trip_distance"] == 2.0
    assert state.values["serial_number"] == "N2GX2318000216"
    assert state.values["controller_firmware"] == "2.1.3"
    assert state.values["battery_temperatures"] == (23.0, 24.0)
    assert state.values["locked"] is False


async def test_poll_keeps_raw_payloads_for_diagnostics(
    transport: FakeScooter,
) -> None:
    client = _client()
    await client.connect()

    state = await client.async_poll()

    assert state.raw["battery_voltage"] == "9C0F"


async def test_static_registers_are_skipped_unless_requested(
    transport: FakeScooter,
) -> None:
    client = _client()
    await client.connect()

    state = await client.async_poll()

    assert "serial_number" not in state.values
    assert "battery_level" in state.values


async def test_unreadable_register_is_recorded_not_raised(
    transport: FakeScooter,
) -> None:
    transport.unreadable.add((0x22, 0x8F))  # BMS state of charge
    client = _client()
    await client.connect()

    state = await client.async_poll()

    assert "battery_level" in state.failures
    assert state.values["battery_percent"] == 85


async def test_bulk_read_falls_back_to_walking_the_index(
    scooter: FakeScooter,
) -> None:
    scooter.supports_bulk_reads = False
    with patch_transport(scooter):
        client = _client()
        await client.connect()

        state = await client.async_poll(include_static=True)

    assert state.values["serial_number"] == "N2GX2318000216"
    assert state.values["total_distance"] == 20.0


async def test_stored_password_skips_pairing(scooter: FakeScooter) -> None:
    password = bytes(range(16))
    scooter.paired_password = password
    with patch_transport(scooter):
        client = _client(password=password)
        await client.connect()

    assert client.password == password
    # SET_PWD is skipped entirely when the vehicle already knows us.
    assert scooter.pair_attempts == 0


async def test_button_press_timeout_raises(scooter: FakeScooter) -> None:
    scooter.require_button_press = True
    with patch_transport(scooter):
        client = _client()
        with pytest.raises(NinebotPairingRequiredError):
            await client.connect()


async def test_poll_requires_a_connection() -> None:
    client = _client()

    with pytest.raises(NinebotConnectionError):
        await client.async_poll()


async def test_disconnect_is_idempotent(transport: FakeScooter) -> None:
    client = _client()
    await client.connect()

    await client.disconnect()
    await client.disconnect()

    assert not client.is_connected


async def test_chunked_responses_are_reassembled(scooter: FakeScooter) -> None:
    """A 14-byte serial does not fit one notification at a 20-byte MTU."""
    scooter.chunk_size = 8
    with patch_transport(scooter):
        client = _client()
        await client.connect()
        serial = await client.async_read("serial_number")

    assert serial == "N2GX2318000216"


async def test_build_info_summarizes_static_values(transport: FakeScooter) -> None:
    client = _client()
    await client.connect()
    state = await client.async_poll(include_static=True)

    info = client.build_info(state, 141)

    assert info.model == "eKickScooter E2 Pro"
    assert info.serial_number == "N2GX2318000216"
    assert info.controller_firmware == "2.1.3"


async def test_handshake_falls_back_to_the_other_board(scooter: FakeScooter) -> None:
    """Some vehicles answer the handshake on 0x21 rather than the documented 0x04."""
    scooter.handshake_board = DeviceId.BLE
    with patch_transport(scooter):
        client = _client()
        await client.connect()
        state = await client.async_poll(include_static=True)

    assert client.is_connected
    assert state.values["serial_number"] == "N2GX2318000216"


async def test_handshake_gives_up_when_no_board_answers(scooter: FakeScooter) -> None:
    scooter.handshake_board = DeviceId.MCU  # neither address the client tries
    with patch_transport(scooter):
        client = _client()
        with pytest.raises(NinebotTimeoutError, match="No PRE_COMM response"):
            await client.connect()
