"""Binary sensor polarity and the shapes a two-state resource can arrive in."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pyk40rf import parse_resource
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bosch_k40rf.const import DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import DEVICE_ID
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


class TestAListedSignalThatIsNotAFlag:
    """The list is generalised from three installations; a fourth may differ.

    Several of the listed ids are named like measurements --
    HighestPermittedTemp, LowestPermittedFlowTemp. If an appliance answers one
    of those with a number, believing the list over the gateway would put that
    reading nowhere: no sensor built for it, and a binary sensor that can only
    ever read unknown.
    """

    PATH = "/signals/SRC.CUHP.HP1.CompressorStatus"
    SENSOR = "sensor.compress_cs5800iaw_12_mb_cuhp_compressor_status"
    BINARY = "binary_sensor.compress_cs5800iaw_12_mb_cuhp_compressor_status"

    async def test_the_reading_wins_over_the_list(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        readings: dict[str, object],
    ) -> None:
        """A number at a listed id becomes a sensor, not a dead binary sensor."""
        readings[self.PATH] = parse_resource(
            {"id": self.PATH, "type": "floatValue", "value": 42.5, "unitOfMeasure": "C"}
        )
        await setup_entry(hass, config_entry)
        registry = er.async_get(hass)

        registry.async_update_entity(self.BINARY, disabled_by=None)
        await hass.async_block_till_done()
        await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done()

        assert registry.async_get(self.SENSOR) is not None
        assert registry.async_get(self.BINARY) is None

    async def test_its_sensor_is_not_deleted_by_the_cleanup(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        readings: dict[str, object],
    ) -> None:
        """Deleting a sensor that is still the right entity loses real data.

        The poll has to actually happen for the cleanup to run at all, so a
        different signal is enabled to make the branch be read.
        """
        readings[self.PATH] = parse_resource(
            {"id": self.PATH, "type": "floatValue", "value": 42.5, "unitOfMeasure": "C"}
        )
        config_entry.add_to_hass(hass)
        registry = er.async_get(hass)
        kept = registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{DEVICE_ID}_signals_SRC_CUHP_HP1_CompressorStatus",
            config_entry=config_entry,
        )

        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        registry.async_update_entity(
            "sensor.compress_cs5800iaw_12_mb_outdoor_temperature", disabled_by=None
        )
        await hass.async_block_till_done()
        await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done()

        assert (config_entry.runtime_data.signal_coordinator.data or {}).get(self.PATH) is not None
        assert registry.async_get(kept.entity_id) is not None


class TestTheSensorAFlagUsedToBe:
    """Before 0.1.15 every signal was a sensor, flags included.

    A unique id is scoped per platform, so the binary sensor is created
    without conflict -- and nothing touches the sensor's registry entry. An
    entity no integration provides any more does not disappear: it restores as
    unavailable and fills searches and pickers for good.

    It is removed once a poll has confirmed the signal really is a flag, and
    not before: the list that would otherwise decide is generalised from three
    installations, and deleting a live entity on a guess is not recoverable.
    """

    PATH = "/signals/SRC.CUHP.HP1.CompressorStatus"
    UNIQUE_ID = f"{DEVICE_ID}_signals_SRC_CUHP_HP1_CompressorStatus"
    BINARY = "binary_sensor.compress_cs5800iaw_12_mb_cuhp_compressor_status"

    async def test_it_survives_a_setup_that_never_reads_the_branch(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
    ) -> None:
        """Nothing is deleted on the strength of the list alone."""
        config_entry.add_to_hass(hass)
        registry = er.async_get(hass)
        stale = registry.async_get_or_create(
            "sensor", DOMAIN, self.UNIQUE_ID, config_entry=config_entry
        )

        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        assert registry.async_get(stale.entity_id) is not None

    async def test_the_poll_that_confirms_the_flag_removes_it(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        readings: dict[str, object],
    ) -> None:
        """Enabling a signal is what reads the branch, and what cleans up."""
        readings[self.PATH] = parse_resource(
            {"id": self.PATH, "type": "stringValue", "value": "true"}
        )
        config_entry.add_to_hass(hass)
        registry = er.async_get(hass)
        stale = registry.async_get_or_create(
            "sensor", DOMAIN, self.UNIQUE_ID, config_entry=config_entry
        )

        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        registry.async_update_entity(self.BINARY, disabled_by=None)
        await hass.async_block_till_done()
        await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done()

        assert registry.async_get(stale.entity_id) is None
        assert registry.async_get(self.BINARY) is not None
