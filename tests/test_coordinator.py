"""Polling behaviour: failures, recovery, and the slow signal channel."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from pyk40rf import K40AuthError, K40ConnectionError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bosch_k40rf.const import SCAN_INTERVAL
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from .test_init import setup_entry
from .test_sensor import PREFIX


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
