"""Map the gateway's units onto Home Assistant's.

The controller reports units the way EMS bus devices spell them ("C", "mins",
'rpm"' with a stray quote in the spec). Only units that map to a real Home
Assistant unit get a device class: guessing one wrong is worse than having
none, because Home Assistant then converts or rejects the value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfRatio,
    UnitOfSoundPressure,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)


@dataclass(frozen=True, slots=True)
class UnitMapping:
    """How one gateway unit becomes a Home Assistant sensor."""

    unit: str | None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT


#: Gateway unit -> Home Assistant unit, device class and state class.
UNIT_MAP: Final[dict[str, UnitMapping]] = {
    "C": UnitMapping(UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    "%": UnitMapping(PERCENTAGE),
    "bar": UnitMapping(UnitOfPressure.BAR, SensorDeviceClass.PRESSURE),
    "W": UnitMapping(UnitOfPower.WATT, SensorDeviceClass.POWER),
    "kW": UnitMapping(UnitOfPower.KILO_WATT, SensorDeviceClass.POWER),
    "Wh": UnitMapping(
        UnitOfEnergy.WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING
    ),
    "kWh": UnitMapping(
        UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING
    ),
    "l/h": UnitMapping(UnitOfVolumeFlowRate.LITERS_PER_HOUR, SensorDeviceClass.VOLUME_FLOW_RATE),
    "l/min": UnitMapping(
        UnitOfVolumeFlowRate.LITERS_PER_MINUTE, SensorDeviceClass.VOLUME_FLOW_RATE
    ),
    "ppm": UnitMapping(UnitOfRatio.PARTS_PER_MILLION, SensorDeviceClass.CO2),
    "dB": UnitMapping(UnitOfSoundPressure.DECIBEL, SensorDeviceClass.SOUND_PRESSURE),
    "rpm": UnitMapping(REVOLUTIONS_PER_MINUTE),
    "1/min": UnitMapping(REVOLUTIONS_PER_MINUTE),
    "s": UnitMapping(UnitOfTime.SECONDS, SensorDeviceClass.DURATION),
    "min": UnitMapping(UnitOfTime.MINUTES, SensorDeviceClass.DURATION),
    "mins": UnitMapping(UnitOfTime.MINUTES, SensorDeviceClass.DURATION),
    "day": UnitMapping(UnitOfTime.DAYS, SensorDeviceClass.DURATION),
    "month": UnitMapping(None),
    "year": UnitMapping(None),
}

#: A percentage is a humidity reading only where the path says so; everything
#: else in percent is a modulation or a fill level, which has no device class.
_HUMIDITY_HINTS: Final = ("humidity",)
_BATTERY_HINTS: Final = ("battery",)

#: Lifetime counters the gateway reports as plain numbers. They only ever go
#: up, and long-term statistics are the point of having them.
_TOTAL_HINTS: Final = ("numberofstarts", "runtime", "workingtime", "operatingtime")


def mapping_for(unit: str | None, path: str) -> UnitMapping:
    """Choose the mapping for one resource.

    Args:
        unit: the unit as the gateway spells it, if any.
        path: the resource path, used to disambiguate unitless counters and
            the several meanings of a percentage.

    """
    lowered = path.lower()

    if unit is None:
        if any(hint in lowered for hint in _TOTAL_HINTS):
            return UnitMapping(None, None, SensorStateClass.TOTAL_INCREASING)
        return UnitMapping(None, None, None)

    mapping = UNIT_MAP.get(unit)
    if mapping is None:
        # An unknown unit is still worth reporting; it just gets no class.
        return UnitMapping(unit, None, SensorStateClass.MEASUREMENT)

    if mapping.unit == PERCENTAGE:
        if any(hint in lowered for hint in _HUMIDITY_HINTS):
            return UnitMapping(PERCENTAGE, SensorDeviceClass.HUMIDITY)
        if any(hint in lowered for hint in _BATTERY_HINTS):
            return UnitMapping(PERCENTAGE, SensorDeviceClass.BATTERY)

    if mapping.device_class is SensorDeviceClass.DURATION and any(
        hint in lowered for hint in _TOTAL_HINTS
    ):
        # A run-time counter is a total, not a momentary duration.
        return UnitMapping(mapping.unit, mapping.device_class, SensorStateClass.TOTAL_INCREASING)

    return mapping
