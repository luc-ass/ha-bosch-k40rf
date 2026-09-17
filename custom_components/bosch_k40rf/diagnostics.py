"""Diagnostics for the Bosch K 40 RF integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .types import K40ConfigEntry

#: The token is a permanent credential and the login is printed on the device.
TO_REDACT = {CONF_TOKEN, CONF_USERNAME, "gatewayId", "serial_number", "ProductSerialNumber"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: K40ConfigEntry
) -> dict[str, Any]:
    """Return what is useful for debugging one gateway, minus its credentials."""
    runtime = entry.runtime_data
    installation = runtime.installation

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "installation": {
            "heat_sources": list(installation.heat_sources),
            "heating_circuits": list(installation.heating_circuits),
            "dhw_circuits": list(installation.dhw_circuits),
            "solar_circuits": list(installation.solar_circuits),
            "ventilation_zones": list(installation.ventilation_zones),
            "signal_count": len(installation.signals),
        },
        "system_info": async_redact_data(
            {
                "product_name": runtime.system_info.product_name,
                "modules": [
                    {
                        "name": module.name,
                        "hardware_id": module.hardware_id,
                        "version": module.version,
                    }
                    for module in runtime.system_info.modules
                ],
            },
            TO_REDACT,
        ),
        "resources": {
            path: async_redact_data(dict(resource.raw), TO_REDACT)
            for path, resource in (runtime.coordinator.data or {}).items()
        },
        "polled_paths": runtime.coordinator.paths,
    }
