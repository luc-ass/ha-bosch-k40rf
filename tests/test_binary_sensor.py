"""Binary sensor polarity and the shapes a two-state resource can arrive in."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pyk40rf import parse_resource
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from .test_init import setup_entry

ENTITY = "binary_sensor.compress_cs5800iaw_12_mb_flame"


@pytest.mark.parametrize(("value", "expected"), [("on", STATE_ON), ("off", STATE_OFF)])
async def test_a_string_resource_maps_to_on_and_off(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
    value: str,
    expected: str,
) -> None:
    readings["/heatSources/flameStatus"] = parse_resource(
        {
            "id": "/heatSources/flameStatus",
            "type": "stringValue",
            "value": value,
            "allowedValues": ["off", "on"],
        }
    )
    await setup_entry(hass, config_entry)
    assert hass.states.get(ENTITY).state == expected


async def test_an_enum_signal_is_read_through_its_label(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    """Some two-state resources arrive as an integer with a label map."""
    readings["/heatSources/flameStatus"] = parse_resource(
        {
            "id": "/heatSources/flameStatus",
            "type": "integerValue",
            "value": 1,
            "state": {"on": 1, "off": 0},
        }
    )
    await setup_entry(hass, config_entry)
    assert hass.states.get(ENTITY).state == STATE_ON


async def test_a_plain_number_is_compared_as_text(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    readings["/heatSources/flameStatus"] = parse_resource(
        {"id": "/heatSources/flameStatus", "type": "integerValue", "value": 1}
    )
    await setup_entry(hass, config_entry)
    # "1" is not one of the declared on-values, so this reads as off.
    assert hass.states.get(ENTITY).state == STATE_OFF


async def test_a_sentinel_reading_is_unknown(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    """A faulted sensor must not read as "off"."""
    readings["/heatSources/flameStatus"] = parse_resource(
        {
            "id": "/heatSources/flameStatus",
            "type": "floatValue",
            "value": -32768.0,
            "state": [{"open": -32768.0}],
        }
    )
    await setup_entry(hass, config_entry)
    assert hass.states.get(ENTITY).state == STATE_UNKNOWN


async def test_an_unexpected_resource_type_is_unavailable(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    readings["/heatSources/flameStatus"] = parse_resource(
        {"id": "/heatSources/flameStatus", "type": "errorList", "values": []}
    )
    await setup_entry(hass, config_entry)
    assert hass.states.get(ENTITY).state == STATE_UNKNOWN


async def test_a_missing_resource_is_unavailable(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    await setup_entry(hass, config_entry)
    del readings["/heatSources/flameStatus"]
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY).state == STATE_UNAVAILABLE
