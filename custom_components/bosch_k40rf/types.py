"""Typed config entry for the Bosch K 40 RF integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from pyk40rf import SystemInfo

    from homeassistant.helpers.device_registry import DeviceInfo

    from .coordinator import K40DataCoordinator, K40SignalCoordinator
    from .devices import DeviceTree


@dataclass(slots=True)
class K40RuntimeData:
    """What a set-up entry keeps at runtime.

    ``devices`` is rebuilt rather than fixed: a circuit that appears while
    Home Assistant runs needs a device, and building one needs the gateway it
    hangs off -- hence the hub and its registry id are kept here too.
    """

    coordinator: K40DataCoordinator
    signal_coordinator: K40SignalCoordinator
    system_info: SystemInfo
    gateway_id: str
    devices: DeviceTree
    hub: DeviceInfo
    hub_device_id: str


type K40ConfigEntry = ConfigEntry[K40RuntimeData]
