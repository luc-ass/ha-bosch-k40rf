"""Binary sensor platform for the Bosch K 40 RF integration."""

from __future__ import annotations

from pyk40rf import NumericResource, StringResource

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .binary_resources import BY_TEMPLATE
from .coordinator import K40BaseCoordinator
from .devices import DeviceTree
from .entity import K40Entity
from .naming import english_name, signal_name, translation_key
from .signal_booleans import BOOLEAN_SIGNALS
from .types import K40ConfigEntry, K40RuntimeData

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: K40ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors this gateway has.

    A circuit the coordinator finds later brings its own, so the platform
    keeps adding what it has not seen yet rather than deciding once.
    """
    runtime = entry.runtime_data
    seen: set[str] = set()

    @callback
    def _add_new_sensors() -> None:
        entities = [
            entity
            for entity in (
                *_build_sensors(runtime),
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


def _build_sensors(runtime: K40RuntimeData) -> list[K40BinarySensor]:
    """Describe every two-state resource this gateway is known to answer."""
    return [
        K40BinarySensor(
            runtime.coordinator,
            BinarySensorEntityDescription(
                key=candidate.path.strip("/").replace("/", "_"),
                translation_key=translation_key(candidate.spec.path),
                name=english_name(candidate.spec.path),
                device_class=BY_TEMPLATE[candidate.spec.path].device_class,
            ),
            runtime.gateway_id,
            candidate.path,
            runtime.devices.for_candidate(candidate),
            BY_TEMPLATE[candidate.spec.path].on_values,
        )
        for candidate in runtime.coordinator.candidates
        if candidate.spec.path in BY_TEMPLATE
    ]


def _build_signal_sensors(
    runtime: K40RuntimeData, devices: DeviceTree
) -> list[K40SignalBinarySensor]:
    """Create the diagnostic flag entities, all disabled by default.

    Most of the ``/signals`` branch is flags the controller writes as the words
    "true" and "false". Reporting those as text would leave the user comparing
    strings in every automation, so they are binary sensors -- which the
    catalogue has to say in advance, because the branch is not polled at all
    until one of its entities is enabled.
    """
    coordinator = runtime.signal_coordinator
    return [
        K40SignalBinarySensor(
            coordinator,
            BinarySensorEntityDescription(
                key=path.strip("/").replace("/", "_").replace(".", "_"),
                # The id is the fallback: a name is better, but never at the
                # cost of an entity with none at all.
                name=signal_name(devices.signal_target(path)[1]) or path.rsplit("/", 1)[-1],
                device_class=BOOLEAN_SIGNALS[path],
                entity_category=EntityCategory.DIAGNOSTIC,
                entity_registry_enabled_default=False,
            ),
            runtime.gateway_id,
            path,
            devices.signal_target(path)[0],
        )
        for path in coordinator.paths
        if path in BOOLEAN_SIGNALS
    ]


class K40BinarySensor(K40Entity, BinarySensorEntity):
    """A two-state resource of the gateway."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: K40BaseCoordinator,
        description: BinarySensorEntityDescription,
        gateway_id: str,
        path: str,
        device_info: DeviceInfo,
        on_values: frozenset[str],
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, description, gateway_id, path, device_info)
        self._on_values = on_values

    @property
    def is_on(self) -> bool | None:
        """Whether the resource currently reads as one of its "on" values."""
        resource = self.resource
        value: str | float | None
        if isinstance(resource, StringResource):
            value = resource.value
        elif isinstance(resource, NumericResource):
            value = resource.label if resource.is_enum else resource.value
        else:
            return None
        if value is None:
            return None
        return str(value).strip().lower() in self._on_values


class K40SignalBinarySensor(K40Entity, BinarySensorEntity):
    """A controller flag from the ``/signals`` branch.

    Unlike the static two-state resources, which spell their states in words
    the installation chooses ("on"/"off", "online"/"offline"), a flag signal
    says "true" or "false" and the library decodes it. Anything else reads as
    unknown rather than false -- a signal that stops being a flag must not
    quietly report that it is off.
    """

    entity_description: BinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Whether the flag currently reads true."""
        resource = self.resource
        if not isinstance(resource, StringResource):
            return None
        return resource.boolean
