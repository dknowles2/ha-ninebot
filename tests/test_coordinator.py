"""Tests for how the coordinator handles a scooter that misbehaves."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ninebot.const import CONF_POLL_INTERVAL

from .fake_scooter import FakeScooter
from .test_init import _setup, entry  # noqa: F401  (fixture import)


async def test_pairing_timeout_marks_the_scooter_unavailable(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    scooter.require_button_press = True

    await _setup(hass, entry, scooter)
    coordinator = entry.runtime_data

    assert coordinator.pairing_required is True
    assert coordinator.last_poll_successful is False
    # The link is dropped so the next attempt starts from a clean handshake.
    assert coordinator.client.is_connected is False
    assert hass.states.get("sensor.e2_pro_0216_battery").state == "unavailable"


async def test_a_silent_scooter_aborts_the_poll(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    """Registers going quiet in a row means the link died, not missing support."""
    for index in (0x1B, 0x1C, 0x25, 0x3B, 0x3E):
        scooter.unreadable.add((0x20, index))

    await _setup(hass, entry, scooter)
    coordinator = entry.runtime_data

    assert coordinator.last_poll_successful is False
    assert coordinator.client.is_connected is False


async def test_poll_interval_comes_from_the_options(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    await _setup(hass, entry, scooter)
    coordinator = entry.runtime_data

    assert coordinator.poll_interval == 120.0

    hass.config_entries.async_update_entry(entry, options={CONF_POLL_INTERVAL: 45})
    await hass.async_block_till_done()

    # Read live, so a change applies without reloading and re-pairing.
    assert coordinator.poll_interval == 45.0


async def test_reconnect_is_skipped_while_the_link_is_up(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    scooter: FakeScooter,
) -> None:
    await _setup(hass, entry, scooter)

    assert scooter.connect_count == 1
    # A first-time pairing runs SET_PWD once. A second connect would repeat it.
    assert scooter.pair_attempts == 1
