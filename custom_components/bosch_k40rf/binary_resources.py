"""Which resources are modelled as binary sensors rather than sensors.

Kept apart from the platform so the sensor platform can consult it without
importing another platform module: a resource listed here must not also
appear as a sensor.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorDeviceClass


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
