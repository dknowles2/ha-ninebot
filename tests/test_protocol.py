"""Tests for Proto2 frame encoding."""

from __future__ import annotations

import pytest

from custom_components.ninebot.pynebot.exceptions import NinebotProtocolError
from custom_components.ninebot.pynebot.protocol import (
    Command,
    DeviceId,
    Packet,
    expected_frame_length,
)


def test_pack_round_trip() -> None:
    packet = Packet(DeviceId.HOST, DeviceId.MCU, Command.READ, 0xB4, b"\x02")
    raw = packet.pack()

    assert raw == b"\x5a\xa5\x01\x3d\x20\x01\xb4\x02"
    assert Packet.unpack(raw) == packet


def test_pack_empty_data() -> None:
    raw = Packet(DeviceId.HOST, DeviceId.BLE, Command.PRE_COMM, 0).pack()

    assert raw == b"\x5a\xa5\x00\x3d\x21\x5b\x00"
    assert Packet.unpack(raw).data == b""


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        (b"\x5a\xa5\x00", "too short"),
        (b"\xde\xad\x00\x3d\x20\x01\x00", "Bad preamble"),
        (b"\x5a\xa5\x08\x3d\x20\x01\xb4\x02", "Truncated"),
        (b"\x5a\xa5\x00\x3d\x20\x99\x00", "Unknown field"),
    ],
)
def test_unpack_rejects_bad_frames(raw: bytes, match: str) -> None:
    with pytest.raises(NinebotProtocolError, match=match):
        Packet.unpack(raw)


def test_pack_rejects_oversized_data() -> None:
    packet = Packet(DeviceId.HOST, DeviceId.MCU, Command.READ, 0, b"\x00" * 256)

    with pytest.raises(NinebotProtocolError, match="too long"):
        packet.pack()


def test_read_is_answered_by_read_ack() -> None:
    request = Packet(DeviceId.HOST, DeviceId.MCU, Command.READ, 0xB4, b"\x02")
    response = Packet(DeviceId.MCU, DeviceId.HOST, Command.READ_ACK, 0xB4, b"\x55\x00")

    assert response.matches_request(request)


def test_response_for_a_different_index_does_not_match() -> None:
    request = Packet(DeviceId.HOST, DeviceId.MCU, Command.READ, 0xB4, b"\x02")
    response = Packet(DeviceId.MCU, DeviceId.HOST, Command.READ_ACK, 0xB5, b"\x00\x00")

    assert not response.matches_request(request)


def test_response_from_a_different_board_does_not_match() -> None:
    request = Packet(DeviceId.HOST, DeviceId.MCU, Command.READ, 0xB4, b"\x02")
    response = Packet(DeviceId.BMS, DeviceId.HOST, Command.READ_ACK, 0xB4, b"\x00\x00")

    assert not response.matches_request(request)


def test_handshake_responses_ignore_the_index() -> None:
    """SET_PWD and AUTH reuse the index field to carry a status code."""
    request = Packet(DeviceId.HOST, DeviceId.BLE, Command.SET_PWD, 0, b"\x00" * 16)
    response = Packet(DeviceId.BLE, DeviceId.HOST, Command.SET_PWD, 1)

    assert response.matches_request(request)


def test_expected_frame_length_covers_the_crypto_trailer() -> None:
    # 2 data bytes: 7 header + 2 data + 6 trailer.
    assert expected_frame_length(b"\x5a\xa5\x02") == 15
    assert expected_frame_length(b"\x5a") is None


def test_str_is_readable() -> None:
    packet = Packet(DeviceId.HOST, DeviceId.MCU, Command.READ, 0xB4, b"\x02")

    assert str(packet) == "HOST->MCU READ idx=0xB4 data=02"
