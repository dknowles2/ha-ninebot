"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ninebot.const import CONF_POLL_INTERVAL, DOMAIN

from .bluetooth import make_advertisement
from .conftest import SCOOTER_ADDRESS, SCOOTER_NAME

E2_PRO_ADVERTISEMENT = make_advertisement(
    SCOOTER_ADDRESS,
    SCOOTER_NAME,
    manufacturer_data={16974: bytes.fromhex("8d0200000070")},
    service_uuids=["6e400001-b5a3-f393-e0a9-e50e24dcca9e"],
)

OTHER_ADVERTISEMENT = make_advertisement(
    "AA:BB:CC:DD:EE:FF", "Some Sensor", manufacturer_data={76: b"\x01\x02"}
)


async def test_bluetooth_discovery_creates_an_entry(
    hass: HomeAssistant, mock_setup_entry: None
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=E2_PRO_ADVERTISEMENT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {
        "name": f"eKickScooter E2 Pro ({SCOOTER_NAME})"
    }

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"eKickScooter E2 Pro ({SCOOTER_NAME})"
    assert result["data"][CONF_ADDRESS] == SCOOTER_ADDRESS


async def test_bluetooth_discovery_rejects_other_manufacturers(
    hass: HomeAssistant,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=OTHER_ADVERTISEMENT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_bluetooth_discovery_ignores_a_configured_scooter(
    hass: HomeAssistant,
) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id=SCOOTER_ADDRESS, data={CONF_ADDRESS: SCOOTER_ADDRESS}
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=E2_PRO_ADVERTISEMENT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_lists_discovered_scooters(
    hass: HomeAssistant, mock_setup_entry: None
) -> None:
    with patch(
        "custom_components.ninebot.config_flow.async_discovered_service_info",
        return_value=[E2_PRO_ADVERTISEMENT, OTHER_ADVERTISEMENT],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: SCOOTER_ADDRESS}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ADDRESS] == SCOOTER_ADDRESS


async def test_user_flow_without_scooters_aborts(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.ninebot.config_flow.async_discovered_service_info",
        return_value=[OTHER_ADVERTISEMENT],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_options_flow_sets_the_poll_interval(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SCOOTER_ADDRESS,
        data={CONF_ADDRESS: SCOOTER_ADDRESS},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 300}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_POLL_INTERVAL] == 300
