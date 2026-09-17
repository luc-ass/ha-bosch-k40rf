"""Setup, teardown and failure handling."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pyk40rf import K40AuthError, K40ConnectionError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bosch_k40rf.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

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
    assert device.model == "Compress CS5800iAW 12 MB"
    # The firmware version comes out of the first poll, not a second request.
    assert device.sw_version == "15.00.01"


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
