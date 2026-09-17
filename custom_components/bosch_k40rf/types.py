"""Typed config entry for the Bosch K 40 RF integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from pyk40rf import Installation, SystemInfo

    from .coordinator import K40DataCoordinator, K40SignalCoordinator


@dataclass(slots=True)
class K40RuntimeData:
    """What a set-up entry keeps at runtime."""

    coordinator: K40DataCoordinator
    signal_coordinator: K40SignalCoordinator
    installation: Installation
    system_info: SystemInfo
    gateway_id: str


type K40ConfigEntry = ConfigEntry[K40RuntimeData]
