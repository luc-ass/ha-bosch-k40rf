"""Binary sensor platform for the Bosch K 40 RF integration."""

from __future__ import annotations

from pyk40rf import NumericResource, StringResource

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .binary_resources import BY_TEMPLATE
from .coordinator import K40BaseCoordinator
from .entity import K40Entity, build_device_info
from .naming import english_name, translation_key
from .types import K40ConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: K40ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors this gateway has."""
    runtime = entry.runtime_data
    device_info = build_device_info(runtime.gateway_id, runtime.system_info.product_name, None)

    entities = [
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
            device_info,
            BY_TEMPLATE[candidate.spec.path].on_values,
        )
        for candidate in runtime.coordinator.candidates
        if candidate.spec.path in BY_TEMPLATE
    ]
    async_add_entities(entities)


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
