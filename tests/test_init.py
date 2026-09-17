"""Setup, teardown and failure handling."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

from pyk40rf import Installation, K40AuthError, K40ConnectionError, parse_resource
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bosch_k40rf.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import DEVICE_ID


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up the entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entry_sets_up(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED


async def test_entry_unloads(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_the_gateway_becomes_a_device(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, DEVICE_ID), config_entry.entry_id
    )
    assert device is not None
    assert device.manufacturer == "Bosch"
    # The gateway is the K 40 RF itself. The appliance it talks to is a device
    # of its own, and carries the product name.
    assert device.model == "K 40 RF"
    # The firmware version comes out of the first poll, not a second request.
    assert device.sw_version == "15.00.01"


async def test_each_branch_becomes_a_device_under_the_gateway(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    """One device per circuit, zone and heat source, all via the gateway.

    A device appears only where a resource of that branch answered, so the
    poll has to carry one reading per branch for all four to show up.
    """
    readings.update(
        {
            path: parse_resource(
                {"id": path, "type": "floatValue", "value": 21.5, "unitOfMeasure": "C"}
            )
            for path in (
                "/heatingCircuits/hc1/roomtemperature",
                "/dhwCircuits/dhw1/actualTemp",
                "/ventilation/zone1/sensors/supplyTemp",
            )
        }
    )
    await setup_entry(hass, config_entry)

    registry = dr.async_get(hass)
    gateway = registry.async_get_device_by_identifier((DOMAIN, DEVICE_ID), config_entry.entry_id)
    assert gateway is not None

    expected = {
        f"{DEVICE_ID}_heatsources_hs1": "Compress CS5800iAW 12 MB",
        f"{DEVICE_ID}_heatingcircuits_hc1": "Heating circuit",
        f"{DEVICE_ID}_dhwcircuits_dhw1": "Hot water",
        f"{DEVICE_ID}_ventilation_zone1": "Ventilation",
    }
    for identifier, name in expected.items():
        device = registry.async_get_device_by_identifier(
            (DOMAIN, identifier), config_entry.entry_id
        )
        assert device is not None, identifier
        assert device.name == name
        assert device.via_device_id == gateway.id


async def test_readings_land_on_the_device_they_describe(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The branch decides the device; everything else stays on the gateway."""
    devices = dr.async_get(hass)
    await setup_entry(hass, config_entry)
    entities = er.async_get(hass)

    def device_of(entity_id: str) -> str | None:
        entry = entities.async_get(entity_id)
        assert entry is not None and entry.device_id is not None
        device = devices.async_get(entry.device_id)
        return device.name if device else None

    # An unqualified /heatSources reading belongs to the only heat source.
    assert device_of("sensor.compress_cs5800iaw_12_mb_return_temperature") == (
        "Compress CS5800iAW 12 MB"
    )
    assert device_of("sensor.k_40_rf_firmware_version") == "K 40 RF"
    # A signal names the part it reports on, and SRC is the heat generator.
    assert device_of("sensor.compress_cs5800iaw_12_mb_outdoor_temperature") == (
        "Compress CS5800iAW 12 MB"
    )


async def test_an_unreachable_gateway_is_retried_not_failed(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_system_info.side_effect = K40ConnectionError("down")
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_rejected_token_asks_the_user_to_reauthenticate(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_system_info.side_effect = K40AuthError("revoked")
    await setup_entry(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )


async def test_only_present_resources_are_polled(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    """The catalogue declares 200 resources; this gateway answers four."""
    await setup_entry(hass, config_entry)

    coordinator = config_entry.runtime_data.coordinator
    assert set(coordinator.paths) == set(readings)

    # The first call is the probe over every candidate; later polls are narrow.
    probe_call, *_ = mock_client.async_get_many.call_args_list
    assert len(probe_call.args[0]) > 100


async def test_a_circuit_the_gateway_stopped_reporting_is_removed(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
    installation: Installation,
) -> None:
    """A circuit taken out of the heating system loses its device on reload."""
    path = "/heatingCircuits/hc1/roomtemperature"
    readings[path] = parse_resource(
        {"id": path, "type": "floatValue", "value": 21.5, "unitOfMeasure": "C"}
    )
    await setup_entry(hass, config_entry)

    registry = dr.async_get(hass)
    identifier = (DOMAIN, f"{DEVICE_ID}_heatingcircuits_hc1")
    assert registry.async_get_device_by_identifier(identifier, config_entry.entry_id) is not None

    # The installation loses the circuit, and with it the reading.
    del readings[path]
    mock_client.async_discover_installation.return_value = replace(
        installation, heating_circuits=()
    )
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get_device_by_identifier(identifier, config_entry.entry_id) is None
    # The gateway itself is never collected.
    assert (
        registry.async_get_device_by_identifier((DOMAIN, DEVICE_ID), config_entry.entry_id)
        is not None
    )
