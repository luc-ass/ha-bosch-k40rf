"""Polling behaviour: failures, recovery, and the slow signal channel."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from pyk40rf import Installation, K40AuthError, K40ConnectionError, parse_resource
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bosch_k40rf.const import DOMAIN, INSTALLATION_PROBE_INTERVAL, SCAN_INTERVAL
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import DEVICE_ID
from .test_init import setup_entry
from .test_sensor import PREFIX

#: A reading only a second heating circuit answers.
HC2_PATH = "/heatingCircuits/hc2/maxFlowTemp"

#: What that reading becomes once the circuit is its own device.
CIRCUIT_2_ENTITY = "sensor.heating_circuit_2_max_flow_temperature"


async def test_a_failed_poll_makes_entities_unavailable(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Silver rule entity-unavailable: a dead gateway must not look alive."""
    await setup_entry(hass, config_entry)
    assert hass.states.get(f"{PREFIX}_return_temperature").state == "36.0"

    mock_client.async_get_many.side_effect = K40ConnectionError("gateway restarting")
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(f"{PREFIX}_return_temperature").state == STATE_UNAVAILABLE


async def test_entities_come_back_after_the_gateway_does(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, config_entry)

    mock_client.async_get_many.side_effect = K40ConnectionError("gateway restarting")
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(f"{PREFIX}_return_temperature").state == STATE_UNAVAILABLE

    mock_client.async_get_many.side_effect = lambda paths: {
        path: readings[path] for path in paths if path in readings
    }
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(f"{PREFIX}_return_temperature").state == "36.0"


async def test_a_revoked_token_during_polling_triggers_reauth(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A token the gateway stops accepting is not a transient failure."""
    await setup_entry(hass, config_entry)

    mock_client.async_get_many.side_effect = K40AuthError("revoked")
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )


async def test_the_signal_channel_stays_quiet_while_nothing_listens(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Signal entities are disabled by default; polling them would be waste."""
    await setup_entry(hass, config_entry)

    coordinator = config_entry.runtime_data.signal_coordinator
    assert coordinator.paths == ["/signals/SRC.OutdoorTemp"]

    before = mock_client.async_get_many.call_count
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert mock_client.async_get_many.call_count == before


async def test_a_poll_only_asks_for_what_exists(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
    freezer: FrozenDateTimeFactory,
) -> None:
    """The setup probe is wide; every poll after it is narrow."""
    await setup_entry(hass, config_entry)

    mock_client.async_get_many.reset_mock()
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    asked = mock_client.async_get_many.call_args.args[0]
    assert set(asked) == set(readings)


class TestInstallationProbe:
    """Gold rule dynamic-devices: a circuit added later has to turn up.

    The plumbing changes while Home Assistant runs -- a second heating circuit
    is fitted, a hot water cylinder comes off -- and the gateway answers for a
    different installation than the one the entry was set up against.
    """

    @staticmethod
    def _second_circuit(installation: Installation) -> Installation:
        """Fit a second heating circuit to the same installation."""
        return replace(installation, heating_circuits=("hc1", "hc2"))

    async def test_a_new_circuit_brings_its_entities(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        installation: Installation,
        readings: dict[str, object],
        freezer: FrozenDateTimeFactory,
    ) -> None:
        await setup_entry(hass, config_entry)
        assert hass.states.get(CIRCUIT_2_ENTITY) is None

        mock_client.async_discover_installation.return_value = self._second_circuit(installation)
        readings[HC2_PATH] = parse_resource(
            {
                "id": HC2_PATH,
                "type": "floatValue",
                "value": 40.0,
                "unitOfMeasure": "C",
            }
        )

        freezer.tick(INSTALLATION_PROBE_INTERVAL + timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        state = hass.states.get(CIRCUIT_2_ENTITY)
        assert state is not None
        assert state.state == "40.0"

    async def test_the_new_circuit_gets_its_own_device(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        installation: Installation,
        readings: dict[str, object],
        freezer: FrozenDateTimeFactory,
    ) -> None:
        """The reading is only half of it; it has to land on the right device."""
        await setup_entry(hass, config_entry)
        registry = er.async_get(hass)
        device_registry = dr.async_get(hass)

        mock_client.async_discover_installation.return_value = self._second_circuit(installation)
        readings[HC2_PATH] = parse_resource(
            {"id": HC2_PATH, "type": "floatValue", "value": 40.0, "unitOfMeasure": "C"}
        )
        freezer.tick(INSTALLATION_PROBE_INTERVAL + timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        entity = registry.async_get(CIRCUIT_2_ENTITY)
        assert entity is not None and entity.device_id is not None
        device = device_registry.async_get(entity.device_id)
        assert device is not None
        assert (DOMAIN, f"{DEVICE_ID}_heatingcircuits_hc2") in device.identifiers

    async def test_the_probe_does_not_run_on_every_poll(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        freezer: FrozenDateTimeFactory,
    ) -> None:
        """Thirty requests a minute for something that changes yearly."""
        await setup_entry(hass, config_entry)
        probes = mock_client.async_discover_installation.call_count

        for _ in range(3):
            freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

        assert mock_client.async_discover_installation.call_count == probes

    async def test_a_failed_probe_leaves_the_poll_alone(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        freezer: FrozenDateTimeFactory,
    ) -> None:
        """Not knowing about a new circuit is no reason to drop the readings."""
        await setup_entry(hass, config_entry)

        mock_client.async_discover_installation.side_effect = K40ConnectionError("busy")
        freezer.tick(INSTALLATION_PROBE_INTERVAL + timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        assert hass.states.get(f"{PREFIX}_return_temperature").state == "36.0"

    async def test_an_unchanged_installation_costs_one_probe_and_nothing_else(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        freezer: FrozenDateTimeFactory,
    ) -> None:
        """The usual case: nothing was rebuilt, so nothing is re-read."""
        await setup_entry(hass, config_entry)
        entities = len(hass.states.async_entity_ids())
        reads = mock_client.async_get_many.call_count

        freezer.tick(INSTALLATION_PROBE_INTERVAL + timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        assert mock_client.async_discover_installation.call_count == 2
        # One read for the poll itself, and none for presence.
        assert mock_client.async_get_many.call_count == reads + 1
        assert len(hass.states.async_entity_ids()) == entities

    async def test_a_circuit_that_goes_away_stops_being_polled(
        self,
        hass: HomeAssistant,
        mock_client: AsyncMock,
        config_entry: MockConfigEntry,
        installation: Installation,
        readings: dict[str, object],
        freezer: FrozenDateTimeFactory,
    ) -> None:
        """Its entities stay and go unavailable; the device waits for a reload."""
        await setup_entry(hass, config_entry)
        mock_client.async_discover_installation.return_value = self._second_circuit(installation)
        readings[HC2_PATH] = parse_resource(
            {"id": HC2_PATH, "type": "floatValue", "value": 40.0, "unitOfMeasure": "C"}
        )
        freezer.tick(INSTALLATION_PROBE_INTERVAL + timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert hass.states.get(CIRCUIT_2_ENTITY).state == "40.0"

        # The circuit is taken back out of the heating system.
        mock_client.async_discover_installation.return_value = installation
        del readings[HC2_PATH]
        freezer.tick(INSTALLATION_PROBE_INTERVAL + timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        coordinator = config_entry.runtime_data.coordinator
        assert HC2_PATH not in coordinator.paths
        # The entity is not removed behind the user's back -- it says so.
        assert hass.states.get(CIRCUIT_2_ENTITY).state == STATE_UNAVAILABLE


async def test_the_signal_channel_polls_at_once_for_the_first_listener(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """An enabled signal must not wait out an interval it did not start.

    The platforms listen without a context from setup on, so the interval is
    already running when the first entity appears -- and enabling an entity
    reloads the entry, which starts that interval over. Ten minutes of
    ``unavailable`` after switching something on reads as broken, not slow.
    """
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data.signal_coordinator
    assert coordinator.data is None

    calls = mock_client.async_get_many.call_count
    coordinator.async_add_listener(lambda: None, "/signals/SRC.OutdoorTemp")
    await hass.async_block_till_done()

    assert mock_client.async_get_many.call_count > calls
    assert coordinator.data is not None

    # The next listeners cost nothing: eighty-odd entities arrive at once.
    calls = mock_client.async_get_many.call_count
    coordinator.async_add_listener(lambda: None, "/signals/SRC.OutdoorTemp")
    await hass.async_block_till_done()
    assert mock_client.async_get_many.call_count == calls
