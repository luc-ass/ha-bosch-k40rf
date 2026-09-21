"""Diagnostics output, including what must never appear in it."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pyk40rf import K40ConnectionError, parse_resource
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from homeassistant.components.diagnostics import REDACTED
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
    assert result["installation"]["signal_count"] == 2
    assert "/heatSources/returnTemperature" in result["resources"]
    assert result["polled_paths"]


async def test_diagnostics_name_what_the_gateway_refused(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
) -> None:
    """A path absent here and present elsewhere is how the catalogue learns."""
    await setup_entry(hass, config_entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    absent = result["absent_paths"]
    assert "/heatSources/systemPressure" in absent
    assert not set(absent) & set(result["polled_paths"])


async def test_diagnostics_read_every_signal(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    """Signals are disabled by default, so the coordinator holds none of them.

    They are the half of the API that no specification covers, so the download
    reads them itself rather than reporting what happens to be switched on.
    """
    signal = "/signals/SRC.OutdoorTemp"
    readings[signal] = parse_resource(
        {"id": signal, "type": "floatValue", "value": 11.5, "unitOfMeasure": "C"}
    )
    await setup_entry(hass, config_entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    assert result["signals"]["count"] == 2
    assert result["signals"]["resources"][signal]["value"] == 11.5


async def test_a_gateway_that_will_not_answer_still_yields_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
) -> None:
    """The optional half of the file must not take the whole file down."""
    await setup_entry(hass, config_entry)
    mock_client.async_get_many.side_effect = K40ConnectionError("gone")
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    assert "error" in result["signals"]
    assert result["installation"]["heat_sources"] == ["hs1"]


async def test_diagnostics_describe_the_device_tree(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
) -> None:
    await setup_entry(hass, config_entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    devices = {device["id"][0]: device for device in result["devices"]}
    assert devices["gateway"]["model"] == "K 40 RF"
    assert devices["heatsources_hs1"]["model"] == "Compress CS5800iAW 12 MB"


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


async def test_the_gateway_mac_addresses_are_redacted(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    """These files get attached to public issues; a MAC follows the box.

    Redaction elsewhere goes by key, which cannot reach this one: every
    resource carries its reading under "value", so only the path says that
    this particular value identifies the hardware.
    """
    for path in ("/gateway/eth/mac", "/gateway/wifi/mac"):
        readings[path] = parse_resource(
            {"id": path, "type": "stringValue", "value": "f0:4a:3d:0b:a2:6f"}
        )
    await setup_entry(hass, config_entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    assert "f0:4a:3d:0b:a2:6f" not in str(result)
    for path in ("/gateway/eth/mac", "/gateway/wifi/mac"):
        assert result["resources"][path]["value"] == REDACTED
        # The resource still has to be visible, or its absence reads as a
        # gateway that does not serve it.
        assert result["resources"][path]["id"] == path


async def test_the_lan_address_is_kept(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    readings: dict[str, object],
) -> None:
    """It is private space, it changes, and it is the first thing to check."""
    readings["/gateway/eth/ip/ipv4"] = parse_resource(
        {"id": "/gateway/eth/ip/ipv4", "type": "stringValue", "value": "192.168.147.55"}
    )
    await setup_entry(hass, config_entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    assert result["resources"]["/gateway/eth/ip/ipv4"]["value"] == "192.168.147.55"
