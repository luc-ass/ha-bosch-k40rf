"""Group the gateway's resources into devices.

The API has no device list. What it has are functional branches -- heat
sources, heating circuits, hot water, solar, ventilation -- whose ids come out
of the discovery probe. Those branches are the backbone of the device tree,
because they are the one thing every installation reports: a cascade simply
answers for six heat sources where this house answers for one.

``/system/basicInfo`` does enumerate the physical modules, with product name,
firmware and serial number. It does not say which module serves which branch,
so it is used for enrichment only, and only where the mapping cannot be wrong:
with a single heat source, the module that carries a product name is that heat
source. With a cascade, nothing is claimed.

Anything that is not branch-bound -- ``/system``, ``/gateway``, ``/pool``,
``/notifications``, the diagnostic signals -- stays on the gateway itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from string import ascii_letters

from pyk40rf import Installation, Resource, StringResource, SystemInfo, SystemInfoModule

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DEFAULT_MANUFACTURER, DOMAIN
from .resources import ResourceCandidate

#: How the gateway names itself among the modules of /system/basicInfo, and
#: the name it is sold under. One module, two brands: a Buderus installation
#: has never heard of a "K 40 RF", and its modules say MX400 instead.
_GATEWAY_HARDWARE_IDS = {"K40RF": "K 40 RF", "MX400": "MX 400"}

#: Shown as the hub's model where the modules name no gateway at all.
_GATEWAY_MODEL = "K 40 RF"

#: Ventilation modules identify themselves as MV<number>.
_VENTILATION_HARDWARE_PREFIX = "MV"

_FIRMWARE_PATH = "/gateway/versionFirmware"

_BRAND_PATH = "/gateway/brand"


@dataclass(frozen=True, slots=True)
class _Family:
    """One branch of the API that becomes a device per id."""

    #: Attribute of :class:`Installation` holding this branch's ids.
    attribute: str
    #: Device name translation key, declared in strings.json. A second key
    #: with a ``{number}`` placeholder is used where there are several.
    translation_key: str


#: Leading path segment -> the branch it stands for. A path whose branch is
#: absent here belongs to the gateway.
_FAMILIES: dict[str, _Family] = {
    "heatSources": _Family("heat_sources", "heat_source"),
    "heatingCircuits": _Family("heating_circuits", "heating_circuit"),
    "dhwCircuits": _Family("dhw_circuits", "hot_water"),
    "solarCircuits": _Family("solar_circuits", "solar_circuit"),
    "ventilation": _Family("ventilation_zones", "ventilation"),
}

#: Suffix of the translation key used when a branch has more than one id.
_NUMBERED = "_numbered"

#: Leading segment of a /signals id -> the branch it reports on, and how that
#: segment reads when it has to stay in the name because the reading ended up
#: on the gateway after all. SC is the system controller and GWEEBUS the bus;
#: neither is a device, but SC.HC1.* still names a circuit.
_SIGNAL_HEADS: dict[str, tuple[str | None, str]] = {
    "SRC": ("heatSources", "heat source"),
    "SC": (None, "system"),
    "VENTILATION": ("ventilation", "ventilation"),
    "GWEEBUS": (None, "EMS bus"),
}

#: A segment of a /signals id that names a circuit: SC.HC1.FlowTempSetp is the
#: first heating circuit's, SRC.CUHP.HP1.ReturnTemp the first heat source's.
#: Bare words never match -- SRC.CUHP.DHW.ExternBlocked is the heat pump's own
#: hot-water block, not the hot water circuit's.
_SIGNAL_CIRCUITS: dict[str, tuple[str, str]] = {
    "HC": ("heatingCircuits", "hc"),
    "DHW": ("dhwCircuits", "dhw"),
    "HP": ("heatSources", "hs"),
    "VENT": ("ventilation", "zone"),
}

#: A mixed circuit is driven by its own module, and that module heads its
#: signals itself instead of hanging them under the system controller:
#: HC2MOD.FlowTemp next to SC.HC2.FlowTempSetp. It reports on the circuit, so
#: it belongs on the circuit's device -- but it is a separate box, and the
#: readings are its own, so the name keeps saying so.
_SIGNAL_MODULE = "MOD"

_SIGNAL_CIRCUIT_SEGMENT = re.compile(rf"^({'|'.join(_SIGNAL_CIRCUITS)})(\d+)({_SIGNAL_MODULE})?$")


@dataclass(frozen=True, slots=True)
class DeviceTree:
    """The devices one gateway is split into, and which one a resource joins."""

    hub: DeviceInfo
    #: (branch, id) -> the device for that circuit, zone or heat source.
    branches: Mapping[tuple[str, str], DeviceInfo]
    #: The heat source that unqualified ``/heatSources`` readings describe,
    #: set only where there is exactly one and the attribution is certain.
    lone_heat_source: str | None = None

    @property
    def all_devices(self) -> tuple[DeviceInfo, ...]:
        """Every device this installation has, the gateway first."""
        return (self.hub, *self.branches.values())

    def for_resource(self, path: str, circuit_id: str | None = None) -> DeviceInfo:
        """Return the device a resource path belongs on."""
        branch = path.strip("/").partition("/")[0]
        if branch not in _FAMILIES:
            return self.hub
        if circuit_id is None:
            # /heatSources/actualSupplyTemperature and its like name no id.
            # With one heat source they are that heat source's readings; with
            # a cascade they describe the whole plant and belong to the hub.
            if branch != "heatSources" or self.lone_heat_source is None:
                return self.hub
            circuit_id = self.lone_heat_source
        return self.branches.get((branch, circuit_id), self.hub)

    def for_candidate(self, candidate: ResourceCandidate) -> DeviceInfo:
        """Return the device an expanded catalogue entry belongs on."""
        return self.for_resource(candidate.path, candidate.circuit_id)

    def for_signal(self, path: str) -> DeviceInfo:
        """Return the device a /signals reading belongs on."""
        return self.signal_target(path)[0]

    def signal_target(self, path: str) -> tuple[DeviceInfo, tuple[str, ...]]:
        """Return the device a /signals reading belongs on, and its name parts.

        Signals are raw controller variables, and unlike the catalogue they
        carry no path structure -- but their ids do: VENTILATION.FrostProt
        .PreHeatPower is the ventilation unit's, SC.HC1.FlowTempSetp the first
        heating circuit's. Whatever cannot be placed stays on the gateway.

        Whatever the device ends up saying is dropped from the name parts, so
        the ventilation unit shows "Frost protection pre heat power" instead of
        repeating itself. A segment naming something this installation does not
        have is kept, so the entity still says which circuit it meant.
        """
        segments = path.rsplit("/", 1)[-1].split(".")
        head, label = _SIGNAL_HEADS.get(segments[0], (None, ""))
        rest = segments[1:] if segments[0] in _SIGNAL_HEADS else segments

        device: DeviceInfo | None = None
        kept: list[str] = []
        for segment in rest:
            match = _SIGNAL_CIRCUIT_SEGMENT.match(segment)
            if device is None and match is not None:
                branch, prefix = _SIGNAL_CIRCUITS[match.group(1)]
                device = self.branches.get((branch, f"{prefix}{match.group(2)}"))
                if device is not None:
                    if match.group(3):
                        kept.append("Module")
                    continue
            kept.append(segment)

        if device is None and head is not None:
            # An unnumbered signal belongs to the branch's device where there
            # is only one of it; with a cascade it names none of them.
            candidates = [device for (name, _), device in self.branches.items() if name == head]
            if len(candidates) == 1:
                device = candidates[0]

        if device is not None:
            return device, tuple(kept)
        # On the gateway the head has to carry its own weight: without it,
        # SRC.OutdoorTemp would read like the system's own outdoor reading.
        return self.hub, tuple([label, *kept] if label else kept)


def build_hub(
    gateway_id: str,
    system_info: SystemInfo,
    firmware: str | None = None,
    brand: str | None = None,
) -> DeviceInfo:
    """Describe the gateway itself, the device every other one hangs off.

    The gateway is one product under several brands, and it says which one it
    was sold as: ``/gateway/brand`` answers "Bosch" on one house and "Buderus"
    on the next. Naming every installation after the Bosch box would be wrong
    on the owner's own wall, so the reported brand decides.
    """
    gateway_module = _gateway_module(system_info)
    return DeviceInfo(
        identifiers={(DOMAIN, gateway_id)},
        manufacturer=brand or DEFAULT_MANUFACTURER,
        model=_gateway_model(gateway_module),
        model_id=gateway_module.hardware_id if gateway_module else None,
        name=_gateway_model(gateway_module),
        serial_number=gateway_id,
        sw_version=firmware or (gateway_module.version if gateway_module else None),
    )


def build_device_tree(
    gateway_id: str,
    system_info: SystemInfo,
    installation: Installation,
    hub: DeviceInfo,
    hub_device_id: str,
) -> DeviceTree:
    """Describe this installation as a hub plus one device per branch id.

    ``hub_device_id`` is the registry id of the already-registered gateway:
    a child device names its parent by id, so the parent has to exist first.
    """
    manufacturer = hub.get("manufacturer") or DEFAULT_MANUFACTURER
    heat_sources = tuple(installation.heat_sources)
    # A product name can only be pinned on a heat source if there is one.
    appliance = _appliance_module(system_info) if len(heat_sources) == 1 else None
    ventilation = _ventilation_module(system_info)

    branches: dict[tuple[str, str], DeviceInfo] = {}
    for branch, family in _FAMILIES.items():
        ids = tuple(getattr(installation, family.attribute, ()) or ())
        module = {"heatSources": appliance, "ventilation": ventilation}.get(branch)
        for circuit_id in ids:
            branches[(branch, circuit_id)] = _subdevice(
                gateway_id,
                branch,
                circuit_id,
                family,
                len(ids),
                module,
                hub_device_id,
                manufacturer,
            )

    return DeviceTree(
        hub=hub,
        branches=branches,
        lone_heat_source=heat_sources[0] if len(heat_sources) == 1 else None,
    )


def firmware_version(readings: Mapping[str, Resource]) -> str | None:
    """Return the gateway's firmware as the last poll reported it, if it did."""
    resource = readings.get(_FIRMWARE_PATH)
    return resource.value if isinstance(resource, StringResource) else None


def brand(readings: Mapping[str, Resource]) -> str | None:
    """Return the brand the gateway was sold under, if it reported one."""
    resource = readings.get(_BRAND_PATH)
    return resource.value if isinstance(resource, StringResource) else None


def _subdevice(
    gateway_id: str,
    branch: str,
    circuit_id: str,
    family: _Family,
    count: int,
    module: SystemInfoModule | None,
    hub_device_id: str,
    manufacturer: str,
) -> DeviceInfo:
    """Describe one circuit, zone or heat source as a device under the hub."""
    device = DeviceInfo(
        identifiers={(DOMAIN, f"{gateway_id}_{branch.lower()}_{circuit_id}")},
        manufacturer=manufacturer,
        # ModuleHwIdentStr is a module id (MV200, XCU_THH), not a product name:
        # the unit it sits in is sold as a Vent 5000 C. Only a ProductName may
        # be shown as the model; the rest is what it is, a model id.
        model=module.name if module else None,
        model_id=module.hardware_id if module else None,
        serial_number=module.serial_number if module else None,
        sw_version=module.version if module else None,
        via_device_id=hub_device_id,
    )
    return device | _naming(family, circuit_id, count, module)


def _naming(
    family: _Family, circuit_id: str, count: int, module: SystemInfoModule | None
) -> DeviceInfo:
    """Name a branch device, preferring what the appliance calls itself.

    A translated name is used wherever the API has no name of its own, and it
    is numbered only where there can be several: a house with one heating
    circuit gets "Heating circuit", not "Heating circuit 1".
    """
    if count == 1:
        if module is not None and module.name:
            return DeviceInfo(name=module.name)
        return DeviceInfo(translation_key=family.translation_key)
    return DeviceInfo(
        translation_key=f"{family.translation_key}{_NUMBERED}",
        translation_placeholders={"number": _ordinal(circuit_id)},
    )


def _ordinal(circuit_id: str) -> str:
    """Return the number in an id like ``hs1`` or ``zone2``, or the id itself."""
    digits = circuit_id.lstrip(ascii_letters)
    return digits or circuit_id


def _gateway_module(system_info: SystemInfo) -> SystemInfoModule | None:
    """Return the module the gateway reports for itself, whatever it calls it."""
    return next((m for m in system_info.modules if m.hardware_id in _GATEWAY_HARDWARE_IDS), None)


def _gateway_model(module: SystemInfoModule | None) -> str:
    """Return the name this gateway is sold under."""
    if module is None:
        return _GATEWAY_MODEL
    return _GATEWAY_HARDWARE_IDS.get(module.hardware_id or "", _GATEWAY_MODEL)


def _appliance_module(system_info: SystemInfo) -> SystemInfoModule | None:
    """Return the module that names the heat generator.

    Only the appliance controllers carry a ``ProductName``; the gateway, the
    room controller and the bus modules leave it empty.
    """
    return next((m for m in system_info.modules if m.name), None)


def _ventilation_module(system_info: SystemInfo) -> SystemInfoModule | None:
    """Return the ventilation module, if exactly one module looks like one."""
    matches = [
        m
        for m in system_info.modules
        if (m.hardware_id or "").startswith(_VENTILATION_HARDWARE_PREFIX)
    ]
    return matches[0] if len(matches) == 1 else None
