"""Turn the declared catalogue into the concrete paths one gateway answers."""

from __future__ import annotations

from dataclasses import dataclass

from pyk40rf import Installation

from .catalog import CATALOG, ResourceSpec

#: Which installation ids fill which placeholder.
_ID_SOURCES: dict[str, str] = {
    "heatSourceId": "heat_sources",
    "heatingCircuitId": "heating_circuits",
    "dhwCircuitId": "dhw_circuits",
    "solarCircuitId": "solar_circuits",
    "ventilationZoneId": "ventilation_zones",
    "zoneId": "zones",
    "deviceId": "devices",
}

#: Types that can become an entity. The rest are structures, and belong in
#: diagnostics rather than in the state machine.
ENTITY_TYPES = frozenset({"floatValue", "integerValue", "stringValue", "emonValue"})


@dataclass(frozen=True, slots=True)
class ResourceCandidate:
    """A catalogue entry with its placeholder filled in."""

    path: str
    spec: ResourceSpec
    circuit_id: str | None = None

    @property
    def value_type(self) -> str:
        """The declared value type."""
        return self.spec.value_type


def candidates_for(installation: Installation) -> list[ResourceCandidate]:
    """Expand the catalogue against the ids this installation reported.

    Templated paths are expanded only for ids that answered during discovery,
    which is what keeps a single-circuit house from being asked about six heat
    sources on every poll.
    """
    expanded: list[ResourceCandidate] = []
    for spec in CATALOG:
        if spec.value_type not in ENTITY_TYPES:
            continue
        if not spec.is_templated:
            expanded.append(ResourceCandidate(path=spec.path, spec=spec))
            continue

        attribute = _ID_SOURCES.get(spec.placeholder or "")
        if attribute is None:
            continue
        expanded.extend(
            ResourceCandidate(
                path=spec.path.replace(f"{{{spec.placeholder}}}", circuit_id),
                spec=spec,
                circuit_id=circuit_id,
            )
            for circuit_id in getattr(installation, attribute, ())
        )

    return expanded
