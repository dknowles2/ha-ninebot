"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

from homeassistant.const import CONF_ADDRESS, CONF_NAME
import pytest

from .fake_scooter import FakeScooter, patch_transport

pytest_plugins = ["pytest_homeassistant_custom_component"]

SCOOTER_ADDRESS = "DC:30:0D:30:4E:F5"
SCOOTER_NAME = "E2 Pro 0216"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Make the custom integration importable in every test."""
    yield


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Allow the bluetooth stack's timers to outlive a test.

    Setting up homeassistant.components.bluetooth starts manager timers that a
    custom component cannot tear down from its own test.
    """
    return True


@pytest.fixture
def scooter() -> FakeScooter:
    """Return a fake scooter that speaks Proto2."""
    return FakeScooter(name=SCOOTER_NAME)


@pytest.fixture
def transport(scooter: FakeScooter) -> Generator[FakeScooter]:
    """Route BLE connections to the fake scooter."""
    with patch_transport(scooter):
        yield scooter


@pytest.fixture
def mock_setup_entry() -> Generator[None]:
    """Skip the real integration setup during config flow tests."""
    with patch(
        "custom_components.ninebot.async_setup_entry", return_value=True
    ) as mocked:
        yield mocked


@pytest.fixture
def config_entry_data() -> dict[str, str]:
    """Return the data stored on a config entry."""
    return {CONF_ADDRESS: SCOOTER_ADDRESS, CONF_NAME: SCOOTER_NAME}
