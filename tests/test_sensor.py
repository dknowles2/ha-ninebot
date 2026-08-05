"""Tests for the sensor and binary sensor platforms."""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .fake_scooter import FakeScooter
from .test_init import _setup, entry  # noqa: F401  (fixture import)


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.e2_pro_0216_battery", "82"),
        ("sensor.e2_pro_0216_speed", "0.0"),
        ("sensor.e2_pro_0216_total_distance", "20.0"),
        ("sensor.e2_pro_0216_trip_distance", "2.0"),
        ("sensor.e2_pro_0216_remaining_range", "100.0"),
        ("sensor.e2_pro_0216_body_temperature", "50.0"),
        ("sensor.e2_pro_0216_battery_temperature_1", "23.0"),
        ("sensor.e2_pro_0216_battery_temperature_2", "24.0"),
        ("sensor.e2_pro_0216_voltage", "39.96"),
        ("sensor.e2_pro_0216_current", "-1.0"),
        ("sensor.e2_pro_0216_battery_charge_cycles", "42"),
        ("sensor.e2_pro_0216_error_code", "0"),
    ],
)
async def test_sensor_states(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
    entity_id: str,
    expected: str,
) -> None:
    await _setup(hass, entry, scooter)

    state = hass.states.get(entity_id)

    assert state is not None, f"{entity_id} was never created"
    assert state.state == expected


async def test_cell_voltage_sensors_summarize_the_pack(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    await _setup(hass, entry, scooter)

    minimum = hass.states.get("sensor.e2_pro_0216_cell_voltage_minimum")
    maximum = hass.states.get("sensor.e2_pro_0216_cell_voltage_maximum")
    delta = hass.states.get("sensor.e2_pro_0216_cell_voltage_delta")

    assert minimum is not None and minimum.state == "3.9"
    assert maximum is not None and maximum.state == "3.912"
    assert delta is not None and delta.state == "0.012"
    assert len(minimum.attributes["cells"]) == 13


async def test_binary_sensors(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    await _setup(hass, entry, scooter)

    lock = hass.states.get("binary_sensor.e2_pro_0216_lock")
    problem = hass.states.get("binary_sensor.e2_pro_0216_problem")

    # The lock device class is "on" when unlocked.
    assert lock is not None and lock.state == "on"
    assert problem is not None and problem.state == "off"


async def test_problem_follows_the_error_code(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    scooter.registers[(0x20, 0x1B)] = b"\x0a\x00"

    await _setup(hass, entry, scooter)

    problem = hass.states.get("binary_sensor.e2_pro_0216_problem")
    assert problem is not None and problem.state == "on"
    assert hass.states.get("sensor.e2_pro_0216_error_code").state == "10"


async def test_unreadable_register_leaves_its_sensor_unavailable(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    scooter.unreadable.add((0x22, 0x8F))  # BMS state of charge

    await _setup(hass, entry, scooter)

    assert hass.states.get("sensor.e2_pro_0216_battery").state == STATE_UNAVAILABLE
    # The rest of the scooter still reports.
    assert hass.states.get("sensor.e2_pro_0216_total_distance").state == "20.0"


async def test_entities_are_tied_to_one_device(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    await _setup(hass, entry, scooter)
    registry = er.async_get(hass)

    entries = er.async_entries_for_config_entry(registry, entry.entry_id)

    assert entries
    device_ids = {registry_entry.device_id for registry_entry in entries}
    assert len(device_ids) == 1


async def test_diagnostic_entities_are_disabled_by_default(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    await _setup(hass, entry, scooter)
    registry = er.async_get(hass)

    uptime = registry.async_get("sensor.e2_pro_0216_uptime")

    assert uptime is not None
    assert uptime.disabled_by is er.RegistryEntryDisabler.INTEGRATION
