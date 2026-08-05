"""Tests for the register map and its decoders."""

from __future__ import annotations

import pytest

from custom_components.ninebot.pynebot.registers import (
    DYNAMIC_REGISTERS,
    REGISTERS,
    REGISTERS_BY_KEY,
    STATIC_REGISTERS,
    _cell_voltages,
    _s16,
    _string,
    _temperature_pair,
    _u16,
    _u32,
    _version,
)


def test_register_keys_are_unique() -> None:
    keys = [register.key for register in REGISTERS]

    assert len(keys) == len(set(keys))


def test_static_and_dynamic_partition_the_map() -> None:
    assert len(STATIC_REGISTERS) + len(DYNAMIC_REGISTERS) == len(REGISTERS)
    assert not set(STATIC_REGISTERS) & set(DYNAMIC_REGISTERS)


def test_every_register_declares_a_usable_length() -> None:
    for register in REGISTERS:
        assert register.length > 0, register.key
        assert register.length % 2 == 0, register.key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(b"\x00\x00", 0), (b"\x55\x00", 85), (b"\xff\xff", 65535)],
)
def test_u16(raw: bytes, expected: int) -> None:
    assert _u16(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(b"\x9c\xff", -100), (b"\x64\x00", 100)],
)
def test_s16(raw: bytes, expected: int) -> None:
    assert _s16(raw) == expected


def test_u32_reads_two_little_endian_words() -> None:
    assert _u32(b"\x20\x4e\x00\x00") == 20000
    assert _u32(b"\x00\x00\x01\x00") == 65536


def test_string_stops_at_the_first_nul() -> None:
    assert _string(b"N2GX2318000216") == "N2GX2318000216"
    assert _string(b"ABC\x00\xff\xff") == "ABC"


def test_version_unpacks_the_nibbles() -> None:
    assert _version(b"\x13\x02") == "2.1.3"


def test_temperature_pair_removes_the_bias() -> None:
    assert _temperature_pair(b"\x2b\x2c\x00\x00") == (23.0, 24.0)


def test_cell_voltages_drops_empty_slots() -> None:
    raw = (3900).to_bytes(2, "little") + (3902).to_bytes(2, "little") + b"\x00" * 4

    assert _cell_voltages(raw) == (3.9, 3.902)


def test_scaling_is_applied_and_rounded() -> None:
    register = REGISTERS_BY_KEY["battery_voltage"]

    assert register.convert(b"\x9c\x0f") == 39.96


def test_scaling_leaves_non_numeric_values_alone() -> None:
    register = REGISTERS_BY_KEY["serial_number"]

    assert register.convert(b"N2GX2318000216") == "N2GX2318000216"


def test_total_distance_uses_the_32_bit_decoder() -> None:
    register = REGISTERS_BY_KEY["total_distance"]

    assert register.convert(b"\x20\x4e\x00\x00") == 20.0


def test_lock_register_reads_a_single_bit() -> None:
    register = REGISTERS_BY_KEY["locked"]

    assert register.convert(b"\x00\x00") is False
    assert register.convert(b"\x01\x00") is True
