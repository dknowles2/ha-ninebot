"""Tests for the diagnostics dump."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ninebot.const import CONF_PASSWORD
from custom_components.ninebot.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .fake_scooter import FakeScooter
from .test_init import _setup, entry  # noqa: F401  (fixture import)


async def test_diagnostics_expose_raw_register_payloads(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    await _setup(hass, entry, scooter)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    voltage = diagnostics["registers"]["battery_voltage"]
    assert voltage["index"] == "0x8C"
    assert voltage["board"] == "BMS"
    assert voltage["raw"] == "9C0F"
    assert voltage["value"] == 39.96
    assert voltage["scale"] == 0.01


async def test_diagnostics_redact_identifiers(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    await _setup(hass, entry, scooter)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["data"][CONF_PASSWORD] == "**REDACTED**"
    assert diagnostics["device"]["serial_number"] == "**REDACTED**"
    assert diagnostics["registers"]["serial_number"] == "**REDACTED**"


async def test_diagnostics_report_failed_reads(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    scooter.unreadable.add((0x22, 0x8F))

    await _setup(hass, entry, scooter)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert "battery_level" in diagnostics["failures"]
    assert diagnostics["poll"]["last_poll_successful"] is True
