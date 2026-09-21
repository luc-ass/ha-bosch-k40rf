"""Sensor platform for the Bosch K 40 RF integration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from pyk40rf import EnergyResource, NumericResource, Resource, StringResource

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .binary_resources import BY_TEMPLATE as BINARY_RESOURCE_PATHS
from .coordinator import K40BaseCoordinator
from .devices import DeviceTree
from .entity import K40Entity
from .naming import component_key, component_name, english_name, signal_name, translation_key
from .resources import ResourceCandidate
from .signal_booleans import BOOLEAN_SIGNALS
from .types import K40ConfigEntry, K40RuntimeData
from .units import mapping_for

#: The coordinator fans its own requests out; the platform must not multiply
#: that by the number of entities.
PARALLEL_UPDATES = 0

#: Branches that describe the installation rather than report on it.
_DIAGNOSTIC_PREFIXES = ("/gateway/", "/system/update", "/devices/", "/notifications")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: K40ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors that this gateway actually has.

    The set is not fixed for the life of the entry: the coordinator probes the
    installation again now and then, and a circuit added to the heating system
    brings its own resources with it. So every poll is a chance to add what is
    new -- and only what is new, which is what the seen ids are for.
    """
    runtime = entry.runtime_data
    seen: set[str] = set()

    @callback
    def _add_new_sensors() -> None:
        entities = [
            entity
            for entity in (
                *_build_resource_sensors(runtime, runtime.devices),
                *_build_signal_sensors(runtime, runtime.devices),
            )
            if entity.unique_id not in seen
        ]
        if not entities:
            return
        seen.update(str(entity.unique_id) for entity in entities)
        async_add_entities(entities)

    _add_new_sensors()
    entry.async_on_unload(runtime.coordinator.async_add_listener(_add_new_sensors))
    entry.async_on_unload(runtime.signal_coordinator.async_add_listener(_add_new_sensors))


def _build_resource_sensors(runtime: K40RuntimeData, devices: DeviceTree) -> Iterable[SensorEntity]:
    """Create one entity per present resource, several for energy balances."""
    coordinator = runtime.coordinator
    gateway_id = runtime.gateway_id

    for candidate in coordinator.candidates:
        if candidate.spec.path in BINARY_RESOURCE_PATHS:
            # Modelled as a binary sensor; showing it twice helps nobody.
            continue
        resource = (coordinator.data or {}).get(candidate.path)
        device_info = devices.for_candidate(candidate)

        if isinstance(resource, EnergyResource):
            # An energy balance is several counters in one resource; each one
            # is its own sensor so the energy dashboard can use them.
            for component in sorted(resource.components):
                yield K40EnergySensor(
                    coordinator,
                    _energy_description(candidate, component),
                    gateway_id,
                    candidate.path,
                    device_info,
                    component,
                )
            continue

        yield K40Sensor(
            coordinator,
            _description(candidate, resource),
            gateway_id,
            candidate.path,
            device_info,
        )


def _build_signal_sensors(runtime: K40RuntimeData, devices: DeviceTree) -> Iterable[SensorEntity]:
    """Create the diagnostic signal entities, all disabled by default."""
    coordinator = runtime.signal_coordinator
    gateway_id = runtime.gateway_id
    for path in coordinator.paths:
        if path in BOOLEAN_SIGNALS:
            # A flag is a binary sensor; showing it twice helps nobody.
            continue
        device_info, name_parts = devices.signal_target(path)
        resource = (coordinator.data or {}).get(path)
        description = SensorEntityDescription(
            key=_key_for(path),
            # The id is the fallback: a name is better, but never at the cost
            # of an entity with none at all.
            name=signal_name(name_parts) or path.rsplit("/", 1)[-1],
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
        )
        if isinstance(resource, NumericResource):
            description = _apply_numeric(description, resource, path)
        yield K40Sensor(coordinator, description, gateway_id, path, device_info)


def _key_for(path: str) -> str:
    """Build a stable unique-id fragment for one resource path."""
    return path.strip("/").replace("/", "_").replace(".", "_")


def _description(
    candidate: ResourceCandidate, resource: Resource | None
) -> SensorEntityDescription:
    """Build the entity description for one resource."""
    spec = candidate.spec
    description = SensorEntityDescription(
        key=_key_for(candidate.path),
        translation_key=translation_key(spec.path),
        name=_display_name(candidate),
        entity_category=(
            EntityCategory.DIAGNOSTIC if candidate.path.startswith(_DIAGNOSTIC_PREFIXES) else None
        ),
    )

    if isinstance(resource, NumericResource):
        return _apply_numeric(description, resource, candidate.path)

    if isinstance(resource, StringResource) and resource.options:
        return replace(
            description, device_class=SensorDeviceClass.ENUM, options=list(resource.options)
        )
    if spec.options:
        return replace(description, device_class=SensorDeviceClass.ENUM, options=list(spec.options))

    return description


def _apply_numeric(
    description: SensorEntityDescription, resource: NumericResource, path: str
) -> SensorEntityDescription:
    """Fill in unit, device class and state class from a live reading.

    A resource whose ``state`` is a label map is an enumeration, not a number,
    even though it arrives as an integer -- reporting the raw code would be
    useless where the gateway has told us what the codes mean.
    """
    if resource.is_enum:
        # An enumeration carries neither: Home Assistant rejects a sensor that
        # claims a unit or a state class alongside a set of options.
        return replace(
            description,
            device_class=SensorDeviceClass.ENUM,
            options=list(resource.options),
            native_unit_of_measurement=None,
            state_class=None,
        )

    mapping = mapping_for(resource.unit, path)
    return replace(
        description,
        native_unit_of_measurement=mapping.unit,
        device_class=mapping.device_class,
        state_class=mapping.state_class,
    )


def _energy_description(candidate: ResourceCandidate, component: str) -> SensorEntityDescription:
    """Build the description for one component of a multi-counter resource.

    Not every ``emonValue`` is energy: the gateway reports start counts and
    working times in the same shape, and calling those kilowatt-hours would put
    nonsense on the energy dashboard. The unit decides, as it does everywhere
    else.
    """
    mapping = mapping_for(candidate.spec.unit, candidate.path)
    return SensorEntityDescription(
        key=f"{_key_for(candidate.path)}_{component}",
        translation_key=f"{translation_key(candidate.spec.path)}_{component_key(component)}",
        name=f"{_display_name(candidate)} {component_name(component)}",
        native_unit_of_measurement=mapping.unit,
        device_class=mapping.device_class,
        state_class=mapping.state_class or SensorStateClass.TOTAL_INCREASING,
    )


def _display_name(candidate: ResourceCandidate) -> str:
    """Render the entity name, adding the circuit id where there can be several."""
    name = english_name(candidate.spec.path)
    if candidate.circuit_id and candidate.circuit_id not in {"hs1", "hc1", "dhw1", "sc1"}:
        return f"{name} {candidate.circuit_id}"
    return name


class K40Sensor(K40Entity, SensorEntity):
    """A sensor backed by one gateway resource."""

    entity_description: SensorEntityDescription

    @property
    def _described(self) -> SensorEntityDescription:
        """The description, completed from the live reading where it is blank.

        A signal's entity is built before its branch has ever been polled --
        the readings are what say whether a signal is a temperature, a
        duration or an enumeration, and there are none yet. Reading that off
        the description alone would leave every signal a bare number for the
        life of the entry, because the description is written once and the
        entity is never rebuilt. So where the description says nothing, the
        current reading does.

        Static resources are unaffected: their descriptions are written after
        the setup poll and already carry all of this.
        """
        description = self.entity_description
        if (
            description.device_class is not None
            or description.native_unit_of_measurement is not None
        ):
            return description

        resource = self.resource
        if isinstance(resource, NumericResource):
            return _apply_numeric(description, resource, self._path)
        if isinstance(resource, StringResource) and resource.options:
            return replace(
                description, device_class=SensorDeviceClass.ENUM, options=list(resource.options)
            )
        return description

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """The device class, which a signal only learns once it has a value."""
        return self._described.device_class

    @property
    def native_unit_of_measurement(self) -> str | None:
        """The unit, which a signal only learns once it has a value."""
        return self._described.native_unit_of_measurement

    @property
    def state_class(self) -> SensorStateClass | None:
        """The state class, which a signal only learns once it has a value."""
        return self._described.state_class

    @property
    def options(self) -> list[str] | None:
        """The labels of an enumeration, which the gateway reports with it.

        An entity that has lost its reading keeps none: an empty list beside
        ``device_class: enum`` would make Home Assistant reject the next
        state that arrives.
        """
        return self._described.options

    @property
    def native_value(self) -> float | int | str | None:
        """The current reading, or None where the gateway reported a fault."""
        resource = self.resource
        if isinstance(resource, NumericResource):
            return resource.label if resource.is_enum else resource.value
        if isinstance(resource, StringResource):
            return resource.value
        return None


class K40EnergySensor(K40Entity, SensorEntity):
    """One component of an energy balance resource."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: K40BaseCoordinator,
        description: SensorEntityDescription,
        gateway_id: str,
        path: str,
        device_info: DeviceInfo,
        component: str,
    ) -> None:
        """Initialise the sensor for one component."""
        super().__init__(coordinator, description, gateway_id, path, device_info)
        self._component = component

    @property
    def native_value(self) -> float | None:
        """The component's lifetime counter."""
        resource = self.resource
        if isinstance(resource, EnergyResource):
            return resource.components.get(self._component)
        return None

    @property
    def available(self) -> bool:
        """Whether this component is present in the latest balance."""
        resource = self.resource
        return (
            super().available
            and isinstance(resource, EnergyResource)
            and self._component in resource.components
        )
