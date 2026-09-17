"""Base entity for the Bosch K 40 RF integration."""

from __future__ import annotations

from pyk40rf import Resource

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import K40BaseCoordinator


class K40Entity(CoordinatorEntity[K40BaseCoordinator]):
    """An entity backed by one resource of the gateway."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: K40BaseCoordinator,
        description: EntityDescription,
        gateway_id: str,
        path: str,
        device_info: DeviceInfo,
    ) -> None:
        """Initialise the entity for one resource path."""
        super().__init__(coordinator, context=path)
        self.entity_description = description
        self._path = path
        self._attr_unique_id = f"{gateway_id}_{description.key}"
        self._attr_device_info = device_info

    @property
    def resource(self) -> Resource | None:
        """The last reading for this entity's resource, if there was one."""
        data = self.coordinator.data or {}
        return data.get(self._path)

    @property
    def available(self) -> bool:
        """Whether the last poll produced a reading for this resource.

        A resource can drop out of a poll on its own -- a circuit taken out of
        service answers 404 where it used to answer 200 -- so presence in the
        last result is the honest test, not just the coordinator's health.
        """
        return super().available and self.resource is not None


def build_device_info(gateway_id: str, model: str | None, sw_version: str | None) -> DeviceInfo:
    """Describe the gateway for the device registry."""
    return DeviceInfo(
        identifiers={(DOMAIN, gateway_id)},
        manufacturer=MANUFACTURER,
        model=model,
        name=model or "K 40 RF",
        serial_number=gateway_id,
        sw_version=sw_version,
    )
