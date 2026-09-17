"""Diagnostics output, including what must never appear in it."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from homeassistant.core import HomeAssistant

from .conftest import DEVICE_ID, TOKEN
from .test_init import setup_entry


async def test_diagnostics_describe_the_installation(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
) -> None:
    await setup_entry(hass, config_entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    assert result["installation"]["heat_sources"] == ["hs1"]
    assert result["installation"]["heating_circuits"] == ["hc1"]
    assert result["installation"]["signal_count"] == 1
    assert "/heatSources/returnTemperature" in result["resources"]
    assert result["polled_paths"]


async def test_the_token_never_appears_in_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
) -> None:
    """Diagnostics get pasted into public issue reports."""
    await setup_entry(hass, config_entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    rendered = str(result)
    assert TOKEN not in rendered
    assert DEVICE_ID not in rendered
