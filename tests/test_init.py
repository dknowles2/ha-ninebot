"""Tests for setting up and tearing down a config entry."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ninebot.const import CONF_PASSWORD, DOMAIN
from custom_components.ninebot.pynebot import NinebotClient

from .bluetooth import async_setup_bluetooth, inject_advertisement, make_advertisement
from .conftest import SCOOTER_ADDRESS, SCOOTER_NAME
from .fake_scooter import FakeScooter, make_ble_device, patch_transport

ADVERTISEMENT = make_advertisement(
    SCOOTER_ADDRESS,
    SCOOTER_NAME,
    manufacturer_data={16974: bytes.fromhex("8d0200000070")},
)


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a config entry added to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SCOOTER_ADDRESS,
        title=SCOOTER_NAME,
        data={CONF_ADDRESS: SCOOTER_ADDRESS, CONF_NAME: SCOOTER_NAME},
    )
    entry.add_to_hass(hass)
    return entry


def _fast_client(*args: object, **kwargs: object) -> NinebotClient:
    """Build a client with test-scale timeouts."""
    kwargs.setdefault("request_timeout", 0.05)
    kwargs.setdefault("pairing_timeout", 0.2)
    return NinebotClient(*args, **kwargs)


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, scooter: FakeScooter
) -> None:
    """Set up the integration with the fake scooter reachable."""
    await async_setup_bluetooth(hass)
    with (
        patch_transport(scooter),
        patch("custom_components.ninebot.NinebotClient", _fast_client),
        patch(
            "custom_components.ninebot.bluetooth.async_ble_device_from_address",
            return_value=make_ble_device(SCOOTER_ADDRESS, SCOOTER_NAME),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        inject_advertisement(hass, ADVERTISEMENT)
        # The poll runs as a background task, which plain async_block_till_done
        # does not wait for.
        await hass.async_block_till_done(wait_background_tasks=True)


async def test_setup_and_unload(
    hass: HomeAssistant, entry: MockConfigEntry, scooter: FakeScooter
) -> None:
    await _setup(hass, entry, scooter)

    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_without_a_reachable_scooter_retries(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await async_setup_bluetooth(hass)
    with patch(
        "custom_components.ninebot.bluetooth.async_ble_device_from_address",
        return_value=None,
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_poll_populates_state_and_stores_the_pairing_key(
    hass: HomeAssistant, entry: MockConfigEntry, scooter: FakeScooter
) -> None:
    await _setup(hass, entry, scooter)
    coordinator = entry.runtime_data

    assert coordinator.state.values["battery_level"] == 82
    assert coordinator.info.model == "eKickScooter E2 Pro"
    assert coordinator.info.serial_number == "N2GX2318000216"
    # The key is persisted so a restart does not need a button press.
    assert entry.data[CONF_PASSWORD] == coordinator.client.password.hex()


async def test_stored_password_is_reused(
    hass: HomeAssistant, scooter: FakeScooter
) -> None:
    password = bytes(range(16))
    scooter.paired_password = password
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SCOOTER_ADDRESS,
        title=SCOOTER_NAME,
        data={
            CONF_ADDRESS: SCOOTER_ADDRESS,
            CONF_NAME: SCOOTER_NAME,
            CONF_PASSWORD: password.hex(),
        },
    )
    entry.add_to_hass(hass)

    await _setup(hass, entry, scooter)

    assert entry.runtime_data.client.password == password
    # SET_PWD never runs when the vehicle already recognises us, so the
    # official app's pairing is left intact.
    assert scooter.pair_attempts == 0


async def test_hardware_id_comes_from_the_advertisement(
    hass: HomeAssistant, entry: MockConfigEntry, scooter: FakeScooter
) -> None:
    await _setup(hass, entry, scooter)

    assert entry.runtime_data.info.hardware_id == 141
