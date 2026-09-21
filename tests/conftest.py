"""Fixtures for the Bosch K 40 RF integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from pyk40rf import Installation, SystemInfo, SystemInfoModule, Token, parse_resource
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bosch_k40rf.const import DOMAIN
from homeassistant.const import CONF_HOST, CONF_TOKEN, CONF_USERNAME

DEVICE_ID = "100000001"
HOST = "192.0.2.10"
TOKEN = "a-very-long-bearer-token"
PASSWORD = "aaaa-bbbb-cccc-dddd"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture(name="system_info")
def system_info_fixture() -> SystemInfo:
    """Return a distilled /system/basicInfo answer."""
    return SystemInfo(
        gateway_id=DEVICE_ID,
        modules=(
            SystemInfoModule(
                name="Compress CS5800iAW 12 MB",
                hardware_id="XCU_THH",
                version="9.7.0",
                serial_number="0" * 23,
            ),
            # The modules the real device lists alongside the appliance: only
            # the appliance carries a product name.
            SystemInfoModule(
                name=None, hardware_id="K40RF", version="15.00.01", serial_number="1" * 23
            ),
            SystemInfoModule(
                name=None, hardware_id="MV200", version="53.03", serial_number="2" * 23
            ),
            SystemInfoModule(
                name=None, hardware_id="RT 800", version="21.04", serial_number="3" * 23
            ),
        ),
    )


@pytest.fixture(name="installation")
def installation_fixture() -> Installation:
    """Return a single-circuit heat pump with ventilation, like the test device."""
    return Installation(
        heat_sources=("hs1",),
        heating_circuits=("hc1",),
        dhw_circuits=("dhw1",),
        ventilation_zones=("zone1",),
        has_ventilation=True,
        signals=(
            "/signals/SRC.OutdoorTemp",
            # A flag: the controller writes these as the words "true"/"false",
            # and they are the larger half of the branch.
            "/signals/SRC.CUHP.HP1.CompressorStatus",
        ),
    )


def resource(payload: dict[str, object]) -> object:
    """Parse one gateway payload the way the client would."""
    return parse_resource(payload)


@pytest.fixture(name="readings")
def readings_fixture() -> dict[str, object]:
    """Return a small but representative set of live readings."""
    return {
        "/heatSources/returnTemperature": resource(
            {
                "id": "/heatSources/returnTemperature",
                "type": "floatValue",
                "value": 36.0,
                "unitOfMeasure": "C",
                "state": [{"open": -32768.0}, {"short": 32767.0}],
            }
        ),
        "/heatSources/flameStatus": resource(
            {
                "id": "/heatSources/flameStatus",
                "type": "stringValue",
                "value": "on",
                "allowedValues": ["off", "on"],
            }
        ),
        "/heatSources/emon/totalConsumption": resource(
            {
                "id": "/heatSources/emon/totalConsumption",
                "type": "emonValue",
                "unit": "kWh",
                "values": [{"outputProduced": 18312.99}, {"compressor": 5185.09}],
            }
        ),
        "/gateway/versionFirmware": resource(
            {"id": "/gateway/versionFirmware", "type": "stringValue", "value": "15.00.01"}
        ),
        "/gateway/brand": resource(
            {"id": "/gateway/brand", "type": "stringValue", "value": "Bosch"}
        ),
    }


@pytest.fixture(name="config_entry")
def config_entry_fixture() -> MockConfigEntry:
    """Return a config entry for an already paired gateway."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE_ID,
        title=f"K 40 RF {DEVICE_ID}",
        data={CONF_HOST: HOST, CONF_USERNAME: DEVICE_ID, CONF_TOKEN: TOKEN},
    )


@pytest.fixture(name="mock_client")
def mock_client_fixture(
    system_info: SystemInfo, installation: Installation, readings: dict[str, object]
) -> Generator[AsyncMock]:
    """Patch the library client everywhere the integration builds one."""
    client = AsyncMock()
    client.async_get_system_info.return_value = system_info
    client.async_discover_installation.return_value = installation
    client.async_get_many.side_effect = lambda paths: {
        path: readings[path] for path in paths if path in readings
    }
    client.async_request_token.return_value = Token(access_token=TOKEN)

    with (
        patch("custom_components.bosch_k40rf.K40Client", return_value=client) as setup_factory,
        patch(
            "custom_components.bosch_k40rf.config_flow.K40Client", return_value=client
        ) as flow_factory,
    ):
        # The factories are exposed so tests can assert how the client was
        # built, not only what ended up in the entry. A port stored but never
        # passed to the client looks correct from the entry alone.
        client.setup_factory = setup_factory
        client.flow_factory = flow_factory
        yield client
