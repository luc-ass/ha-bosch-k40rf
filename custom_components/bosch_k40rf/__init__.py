"""The Bosch K 40 RF integration."""

from __future__ import annotations

import logging

from pyk40rf import AUTH_PORT, DATA_PORT, K40AuthError, K40Client, K40Error

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_AUTH_PORT, DOMAIN, MAX_CONCURRENT_REQUESTS
from .coordinator import K40DataCoordinator, K40SignalCoordinator
from .types import K40ConfigEntry, K40RuntimeData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: K40ConfigEntry) -> bool:
    """Set up a gateway from a config entry."""
    client = K40Client(
        entry.data[CONF_HOST],
        async_get_clientsession(hass, verify_ssl=False),
        token=entry.data[CONF_TOKEN],
        # Entries created before discovery published the ports carry neither.
        data_port=entry.data.get(CONF_PORT, DATA_PORT),
        auth_port=entry.data.get(CONF_AUTH_PORT, AUTH_PORT),
        concurrency=MAX_CONCURRENT_REQUESTS,
    )

    try:
        system_info = await client.async_get_system_info()
        # Zones and devices are the expensive half of the probe and have no
        # entities yet; asking about 48 more ids on every start is not worth it.
        installation = await client.async_discover_installation(
            include_zones=False, include_devices=False
        )
    except K40AuthError as err:
        # The user-facing message has to stay short, but without the gateway's
        # own words a rejection is undiagnosable from a log.
        _LOGGER.error("Gateway %s rejected the token: %s", entry.data[CONF_HOST], err)
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err
    except K40Error as err:
        _LOGGER.debug("Gateway %s not ready: %s", entry.data[CONF_HOST], err)
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err

    coordinator = K40DataCoordinator(hass, entry, client)
    signal_coordinator = K40SignalCoordinator(hass, entry, client)
    signal_coordinator.set_signals(installation.signals)

    # The first read doubles as the presence probe, so it has to happen before
    # the platforms ask which entities to create.
    await coordinator.async_resolve(installation)
    await coordinator.async_config_entry_first_refresh()

    gateway_id = system_info.gateway_id or entry.unique_id or entry.entry_id
    entry.runtime_data = K40RuntimeData(
        coordinator=coordinator,
        signal_coordinator=signal_coordinator,
        installation=installation,
        system_info=system_info,
        gateway_id=gateway_id,
    )

    _LOGGER.debug(
        "Gateway %s: %s live resources, %s signals",
        gateway_id,
        len(coordinator.paths),
        len(installation.signals),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: K40ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
