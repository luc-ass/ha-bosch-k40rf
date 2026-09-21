"""Binary sensor polarity and the shapes a two-state resource can arrive in."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pyk40rf import parse_resource
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

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


class TestAFlagSignal:
    """The larger half of the /signals branch, and the shape it arrives in.

    The controller writes its flags as the words "true" and "false" in a
    stringValue -- 52 of the 119 signals on the widest installation seen so
    far. They used to be sensors whose state was the literal text "true",
    which works and reads badly: every automation had to compare strings.

    The platform has to be decided before the branch has ever been polled,
    because it is not polled at all while all of its entities are disabled.
    So the answer comes from a generated list rather than from a reading,
    and what the list does not know stays a sensor.
    """

    PATH = "/signals/SRC.CUHP.HP1.CompressorStatus"
    ENTITY = "binary_sensor.compress_cs5800iaw_12_mb_cuhp_compressor_status"

    @staticmethod
    async def _enable(hass: HomeAssistant, config_entry: MockConfigEntry, entity: str) -> None:
        """Switch the flag entity on, the way the user does."""
        registry = er.async_get(hass)
        entry = registry.async_get(entity)
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION

        registry.async_update_entity(entity, disabled_by=None)
        await hass.async_block_till_done()
        await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done()

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("true", STATE_ON), ("false", STATE_OFF), ("", STATE_UNKNOWN)],
    )
    async def test_it_reads_the_flag_words(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        readings: dict[str, object],
        value: str,
        expected: str,
    ) -> None:
        """A word that is not a flag is unknown, never false."""
        readings[self.PATH] = parse_resource(
            {"id": self.PATH, "type": "stringValue", "value": value}
        )
        await setup_entry(hass, config_entry)
        await self._enable(hass, config_entry, self.ENTITY)

        state = hass.states.get(self.ENTITY)
        assert state is not None
        assert state.state == expected

    async def test_it_carries_the_device_class_the_catalogue_gives_it(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        readings: dict[str, object],
    ) -> None:
        readings[self.PATH] = parse_resource(
            {"id": self.PATH, "type": "stringValue", "value": "true"}
        )
        await setup_entry(hass, config_entry)
        await self._enable(hass, config_entry, self.ENTITY)

        state = hass.states.get(self.ENTITY)
        assert state is not None
        assert state.attributes["device_class"] == "running"

    async def test_it_is_not_also_a_sensor(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
    ) -> None:
        """One reading, one entity: the sensor platform has to stand back."""
        await setup_entry(hass, config_entry)
        registry = er.async_get(hass)

        assert registry.async_get(self.ENTITY) is not None
        assert registry.async_get("sensor.compress_cs5800iaw_12_mb_cuhp_compressor_status") is None

    async def test_a_signal_that_is_not_a_flag_stays_a_sensor(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
    ) -> None:
        """The catalogue decides, so a measurement is never caught by it."""
        await setup_entry(hass, config_entry)
        registry = er.async_get(hass)

        assert registry.async_get("sensor.compress_cs5800iaw_12_mb_outdoor_temperature") is not None
        assert (
            registry.async_get("binary_sensor.compress_cs5800iaw_12_mb_outdoor_temperature") is None
        )

    async def test_a_flag_that_arrives_as_a_number_is_unknown(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        readings: dict[str, object],
    ) -> None:
        """The list says which signals are flags; the gateway can still differ."""
        readings[self.PATH] = parse_resource({"id": self.PATH, "type": "integerValue", "value": 1})
        await setup_entry(hass, config_entry)
        await self._enable(hass, config_entry, self.ENTITY)

        state = hass.states.get(self.ENTITY)
        assert state is not None
        assert state.state == STATE_UNKNOWN
