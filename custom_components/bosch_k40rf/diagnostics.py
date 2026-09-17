"""Diagnostics for the Bosch K 40 RF integration.

This file is also the project's feedback channel. The integration covers every
installation the published spec describes, but only one of them has ever been
tested on real hardware -- a single air-to-water heat pump with one heating
circuit, hot water and ventilation. A cascade, a solar circuit, a pool, a gas
boiler, a second heating circuit: all of that is written against the spec and
unproven.

So the download is written to be worth attaching to an issue. It carries what
we cannot guess from here: the raw answers, the resources this gateway refused,
and the /signals branch, which appears in no specification at all and differs
per appliance. tools/report_from_diagnostics.py turns such a file back into a
list of what is new about that installation.
"""

from __future__ import annotations

from typing import Any

from pyk40rf import K40Error, Resource

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .resources import candidates_for
from .types import K40ConfigEntry, K40RuntimeData

#: The token is a permanent credential and the login is printed on the device.
TO_REDACT = {CONF_TOKEN, CONF_USERNAME, "gatewayId", "serial_number", "ProductSerialNumber"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: K40ConfigEntry
) -> dict[str, Any]:
    """Return what is useful for debugging one gateway, minus its credentials."""
    runtime = entry.runtime_data
    installation = runtime.installation
    coordinator = runtime.coordinator

    answered = set(coordinator.paths)
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "installation": {
            "heat_sources": list(installation.heat_sources),
            "heating_circuits": list(installation.heating_circuits),
            "dhw_circuits": list(installation.dhw_circuits),
            "solar_circuits": list(installation.solar_circuits),
            "ventilation_zones": list(installation.ventilation_zones),
            "zones": list(installation.zones),
            "devices": list(installation.devices),
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
        "devices": _devices(runtime),
        "resources": {
            path: async_redact_data(dict(resource.raw), TO_REDACT)
            for path, resource in (coordinator.data or {}).items()
        },
        "polled_paths": coordinator.paths,
        # The other half of the story: what the catalogue offered and this
        # gateway would not serve. A resource absent here but present at
        # another installation is how the catalogue learns it is real. The
        # coordinator keeps only what answered, so the full list is expanded
        # again rather than kept around twice.
        "absent_paths": sorted(
            candidate.path
            for candidate in candidates_for(installation)
            if candidate.path not in answered
        ),
        "signals": await _signals(runtime),
    }


def _devices(runtime: K40RuntimeData) -> list[dict[str, Any]]:
    """Describe the device tree this installation was split into.

    Every identifier starts with the gateway id, which is the login printed on
    the device -- so only the part that says which circuit it is survives.
    """
    gateway_id = runtime.gateway_id
    return [
        {
            "id": sorted(
                identifier.removeprefix(gateway_id).lstrip("_") or "gateway"
                for _, identifier in device["identifiers"]
            ),
            "name": device.get("name") or device.get("translation_key"),
            "model": device.get("model"),
            "model_id": device.get("model_id"),
            "sw_version": device.get("sw_version"),
        }
        for device in runtime.devices.all_devices
    ]


async def _signals(runtime: K40RuntimeData) -> dict[str, Any]:
    """Read every signal, not just the ones with an entity switched on.

    The signal branch is polled only while at least one of its entities is
    enabled, and they are all disabled by default -- so on most installations
    the coordinator holds nothing. Reading them here costs one burst of small
    requests, on an explicit user action, and it is the single most useful
    thing in the file: these ids, their units and their enumerations exist in
    no specification.
    """
    coordinator = runtime.signal_coordinator
    paths: list[str] = coordinator.paths
    if not paths:
        return {"count": 0, "resources": {}}

    try:
        readings: dict[str, Resource] = await coordinator.client.async_get_many(paths)
    except K40Error as err:
        # A diagnostics download must not fail on the optional half of it.
        return {"count": len(paths), "ids": paths, "error": str(err)}

    return {
        "count": len(paths),
        "resources": {
            path: async_redact_data(dict(resource.raw), TO_REDACT)
            for path, resource in readings.items()
        },
    }
