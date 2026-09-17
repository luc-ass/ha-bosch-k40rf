"""Entity behaviour: values, units, sentinels and energy components."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pyk40rf import parse_resource
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .test_init import setup_entry

#: Readings of the heat generator now sit on its own device.
PREFIX = "sensor.compress_cs5800iaw_12_mb"

#: Gateway resources, and every signal that names no part of the plant.
GATEWAY_PREFIX = "sensor.k_40_rf"


async def test_a_temperature_becomes_a_temperature_sensor(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)

    state = hass.states.get(f"{PREFIX}_return_temperature")
    assert state is not None
    assert state.state == "36.0"
    assert state.attributes["device_class"] == SensorDeviceClass.TEMPERATURE
    assert state.attributes["unit_of_measurement"] == UnitOfTemperature.CELSIUS
    assert state.attributes["state_class"] == SensorStateClass.MEASUREMENT


async def test_an_allowed_values_string_becomes_an_enum(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    readings["/heatSources/{heatSourceId}/heatPumpType".replace("{heatSourceId}", "hs1")] = (
        parse_resource(
            {
                "id": "/heatSources/hs1/heatPumpType",
                "type": "stringValue",
                "value": "airWater",
                "allowedValues": ["airWater", "brineWater", "waterWater"],
            }
        )
    )
    await setup_entry(hass, config_entry)

    state = hass.states.get(f"{PREFIX}_heat_pump_type")
    assert state is not None
    assert state.state == "airWater"
    assert state.attributes["device_class"] == SensorDeviceClass.ENUM
    assert state.attributes["options"] == ["airWater", "brineWater", "waterWater"]


async def test_an_energy_balance_becomes_one_sensor_per_component(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Separate counters are what makes the energy dashboard usable."""
    await setup_entry(hass, config_entry)

    produced = hass.states.get(f"{PREFIX}_system_total_energy_produced")
    compressor = hass.states.get(f"{PREFIX}_system_total_energy_compressor")

    assert produced is not None
    assert compressor is not None
    assert produced.state == "18312.99"
    assert compressor.state == "5185.09"
    for state in (produced, compressor):
        assert state.attributes["device_class"] == SensorDeviceClass.ENERGY
        assert state.attributes["state_class"] == SensorStateClass.TOTAL_INCREASING


@pytest.mark.parametrize("sentinel", [-32768.0, 32767.0])
async def test_a_sentinel_reading_is_unknown_not_a_number(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
    sentinel: float,
) -> None:
    """Reporting -32768 C would poison history and trigger automations."""
    readings["/heatSources/returnTemperature"] = parse_resource(
        {
            "id": "/heatSources/returnTemperature",
            "type": "floatValue",
            "value": sentinel,
            "unitOfMeasure": "C",
            "state": [{"open": -32768.0}, {"short": 32767.0}],
        }
    )
    await setup_entry(hass, config_entry)

    state = hass.states.get(f"{PREFIX}_return_temperature")
    assert state is not None
    assert state.state == STATE_UNKNOWN


async def test_a_signal_enum_reports_its_label(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    """A /signals label map is an enumeration; the raw code helps nobody."""
    readings["/signals/SRC.OutdoorTemp"] = parse_resource(
        {
            "id": "/signals/SC.SeasonOpt.Mode",
            "type": "integerValue",
            "value": 1,
            "state": {"IDLE": 2, "COOLING": 3, "HEATING": 1},
        }
    )
    await setup_entry(hass, config_entry)

    registry = er.async_get(hass)
    # The signal is named from its id, minus what the device already says.
    entry = registry.async_get(f"{PREFIX}_outdoor_temperature")
    assert entry is not None
    # Diagnostic signals are off until the user asks for them.
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry.entity_category is er.EntityCategory.DIAGNOSTIC


async def test_a_resource_that_stops_answering_goes_unavailable(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    """A circuit taken out of service 404s where it used to answer."""
    await setup_entry(hass, config_entry)
    assert hass.states.get(f"{PREFIX}_return_temperature").state == "36.0"

    del readings["/heatSources/returnTemperature"]
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(f"{PREFIX}_return_temperature").state == STATE_UNAVAILABLE


async def test_every_entity_has_a_unique_id(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    keys = [(entry.domain, entry.unique_id) for entry in entries]

    assert keys
    assert all(unique_id for _, unique_id in keys)
    assert len(set(keys)) == len(keys)


async def test_a_binary_sensor_resource_is_not_also_a_sensor(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """FlameStatus is a binary sensor; offering it twice is just confusing."""
    await setup_entry(hass, config_entry)

    assert hass.states.get("binary_sensor.compress_cs5800iaw_12_mb_flame") is not None
    assert hass.states.get(f"{PREFIX}_flame") is None


async def test_a_two_state_resource_becomes_a_binary_sensor(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)

    state = hass.states.get("binary_sensor.compress_cs5800iaw_12_mb_flame")
    assert state is not None
    assert state.state == "on"
    assert state.attributes["device_class"] == "heat"
