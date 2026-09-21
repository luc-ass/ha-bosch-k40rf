"""Which resources are modelled as binary sensors rather than sensors.

Kept apart from the platform so the sensor platform can consult it without
importing another platform module: a resource listed here must not also
appear as a sensor.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyk40rf import Resource, StringResource

from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from .signal_booleans import BOOLEAN_SIGNALS

__all__ = ["BINARY_RESOURCES", "BOOLEAN_SIGNALS", "BY_TEMPLATE", "BinaryResource", "is_flag_signal"]


@dataclass(frozen=True, slots=True)
class BinaryResource:
    """A resource whose two states are worth modelling as a binary sensor."""

    path: str
    on_values: frozenset[str]
    device_class: BinarySensorDeviceClass | None = None


#: Chosen rather than derived: a two-valued string is not automatically a
#: binary sensor, and getting the polarity wrong is worse than a plain sensor.
BINARY_RESOURCES: tuple[BinaryResource, ...] = (
    BinaryResource("/heatSources/flameStatus", frozenset({"on"}), BinarySensorDeviceClass.HEAT),
    BinaryResource(
        "/dhwCircuits/{dhwCircuitId}/tdrunningStatus",
        frozenset({"on"}),
        BinarySensorDeviceClass.RUNNING,
    ),
    BinaryResource(
        "/heatingCircuits/{heatingCircuitId}/pumpStatus",
        frozenset({"on"}),
        BinarySensorDeviceClass.RUNNING,
    ),
    BinaryResource(
        "/devices/{deviceId}/rfConnectionStatus",
        frozenset({"online"}),
        BinarySensorDeviceClass.CONNECTIVITY,
    ),
    BinaryResource("/system/powerLimitation/active", frozenset({"on"}), None),
    BinaryResource("/system/powerConstraints/silentMode/status", frozenset({"active"}), None),
    BinaryResource("/heatSources/smartFunction/active", frozenset({"on"}), None),
)

BY_TEMPLATE = {resource.path: resource for resource in BINARY_RESOURCES}


def is_flag_signal(path: str, resource: Resource | None) -> bool:
    """Whether a ``/signals`` reading belongs to the binary sensor platform.

    :data:`BOOLEAN_SIGNALS` decides while there is no reading, because the
    entity has to exist before the branch is ever polled. But that list is
    generalised from the installations we hold, and an appliance nobody has
    contributed a file for may answer one of those ids with something that is
    not a flag -- several of them are named like measurements
    (``HighestPermittedTemp``, ``LowestPermittedFlowTemp``). Believing the
    list over the gateway would put such a reading nowhere at all: no sensor
    built for it, and a binary sensor that can only ever read unknown.

    So once there is a reading it wins. Both platforms are re-consulted on
    every poll, so the sensor turns up at the one after the branch is first
    read, rather than never.
    """
    if path not in BOOLEAN_SIGNALS:
        return False
    if resource is None:
        return True
    return isinstance(resource, StringResource) and resource.is_boolean
