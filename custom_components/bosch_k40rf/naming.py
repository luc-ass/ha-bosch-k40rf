"""Derive entity keys and English names from API resource paths.

Used both at runtime by the platforms and by tools/generate_catalog.py, which
writes the same names into strings.json.

The catalogue has 200-odd resources named the way an embedded HVAC controller
names things (``chConsumption``, ``dhwSetTemp``, ``RTSD``). Users see these, so
the abbreviations are expanded and the branch is turned into a readable prefix.
Anything the rules get wrong is corrected in NAME_OVERRIDES rather than by
hand-editing generated output.
"""

from __future__ import annotations

from collections.abc import Sequence
import re

#: Leading path segment -> how it reads in an entity name.
BRANCH_LABELS: dict[str, str] = {
    "dhwCircuits": "Hot water",
    "heatSources": "Heat source",
    "heatingCircuits": "Heating circuit",
    "solarCircuits": "Solar circuit",
    "ventilation": "Ventilation",
    "zones": "Zone",
    "devices": "Device",
    "gateway": "Gateway",
    "system": "System",
    "notifications": "Notifications",
    "signals": "Signal",
}

#: Branches that became devices of their own: the device page already says
#: "Heizkreis", so the entity on it must not repeat it. The gateway keeps its
#: labels -- /gateway/update/status and /system/update/status share a device,
#: and without the branch they would share a name too.
DEVICE_BRANCHES = frozenset(
    {"heatSources", "heatingCircuits", "dhwCircuits", "solarCircuits", "ventilation"}
)

#: Placeholder -> the word that keeps a per-circuit key apart from the
#: system-wide resource of the same name.
PLACEHOLDER_SLUGS: dict[str, str] = {
    "heatSourceId": "source",
    "heatingCircuitId": "circuit",
    "dhwCircuitId": "circuit",
    "solarCircuitId": "circuit",
    "ventilationZoneId": "zone",
    "zoneId": "zone",
    "deviceId": "device",
}

#: Abbreviations as the controller spells them.
WORD_EXPANSIONS: dict[str, str] = {
    "ch": "heating",
    "dhw": "hot water",
    "hc": "heating circuit",
    "hs": "heat source",
    "hp": "heat pump",
    "vent": "ventilation",
    "emon": "energy",
    "temp": "temperature",
    "temps": "temperatures",
    "setp": "setpoint",
    "sup": "supply",
    "exh": "exhaust",
    "el": "electrical",
    "elec": "electrical",
    "aux": "auxiliary",
    "vol": "volume",
    "mins": "minutes",
    "rf": "radio",
    "sw": "software",
    "hw": "hardware",
    "ap": "access point",
    "eheater": "electric heater",
    "odu": "outdoor unit",
    "idu": "indoor unit",
    "timeof": "time of",
    "tz": "timezone",
    "roomtemperature": "room temperature",
    "setpt": "setpoint",
    "modul": "modulation",
    "config": "configuration",
    "info": "information",
    "uhc": "underfloor heating controller",
    "rhc": "room heating controller",
    "mvhr": "heat recovery",
    "wrg": "heat recovery",
    "suwi": "summer/winter",
    "gso": "system operating state",
    # As the /signals ids spell them. Same controller, same abbreviations.
    "add": "additional",
    "circ": "circulation",
    "comp": "compressor",
    "ctrl": "control",
    "cur": "current",
    "cyl": "cylinder",
    "damp": "damped",
    "ext": "external",
    "extern": "external",
    "int": "internal",
    "loc": "local",
    "op": "operating",
    "opt": "optimization",
    "outd": "outdoor",
    "prot": "protection",
    "req": "requested",
    "stats": "statistics",
    "td": "thermal disinfection",
    "jaz": "performance factor",
    "eebus": "EEBUS",
    "cop": "COP",
    "pv": "PV",
    "id": "ID",
    "ip": "IP",
    "mac": "MAC",
    "ssid": "SSID",
    "dns": "DNS",
    "url": "URL",
    "t1": "T1",
    "tl1": "TL1",
    "tl2": "TL2",
}

#: Path segments that group resources without describing them. The branch is
#: gone from the name, so "Ventilation sensors supply temperature" would now
#: read "Sensors supply temperature" -- the grouping, and nothing else.
STRUCTURAL_SEGMENTS = frozenset({"sensors"})

#: Fixes that only make sense once the words are joined, mostly where the
#: controller's camelCase splits a term in two ("eHeater" -> "e heater").
PHRASE_FIXES: dict[str, str] = {
    "e heater": "electric heater",
    "timezone information": "timezone",
    "power electrical actual": "electrical power",
    "power electrical desired": "desired electrical power",
    "number of starts": "starts",
}

#: Words that should keep their capitalisation in the middle of a name.
KEEP_UPPER = {
    "EEBUS",
    "COP",
    "PV",
    "ID",
    "IP",
    "MAC",
    "SSID",
    "DNS",
    "URL",
    "T1",
    "TL1",
    "TL2",
    # Acronyms of the /signals ids that the API never spells out. Guessing at
    # them would be worse than leaving them as the controller writes them.
    # CUHP is the heat pump's control unit -- its SRC.CUHP.Stats.ControlUnit
    # counter matches the installation date to the day, and everything under it
    # is the generator's own internals. It stays an acronym anyway: it is what
    # the controller logs show, and "control unit" adds a word, not a meaning.
    "CUHP",
    "EM",
    "EMS",
    "FPD",
    "HMI",
    "LIN",
    "PC0",
    "PC1",
    "PC2",
    "RTSD",
    "SD",
}

#: Where the rules read badly. Keyed by catalogue path.
NAME_OVERRIDES: dict[str, str] = {
    # The unqualified balance is the whole plant's, the templated one is a
    # single generator's ("of heat source 2 (hs2)" in the spec). With one heat
    # source both sit on the same device, so they cannot share a name.
    "/heatSources/emon/totalConsumption": "System total energy",
    "/heatSources/emon/chConsumption": "System heating energy",
    "/heatSources/emon/dhwConsumption": "System hot water energy",
    "/heatSources/emon/coolingConsumption": "System cooling energy",
    "/heatSources/emon/poolConsumption": "System pool energy",
    "/heatSources/externalInputs/input1/state": "External input 1",
    "/heatSources/externalInputs/input2/state": "External input 2",
    "/heatSources/externalInputs/input3/state": "External input 3",
    "/heatSources/externalInputs/input4/state": "External input 4",
    "/heatSources/externalInputs/status/coolingBlock": "External cooling block",
    # Two resources, one meaning, and only the device knows which it answers.
    "/ventilation/{ventilationZoneId}/elAuxHeaterPower": "Auxiliary heater power",
    "/heatSources/{heatSourceId}/emon/totalConsumption": "Total energy",
    "/heatSources/{heatSourceId}/emon/chConsumption": "Heating energy",
    "/heatSources/{heatSourceId}/emon/dhwConsumption": "Hot water energy",
    "/heatSources/returnTemperature": "Return temperature",
    "/heatSources/actualSupplyTemperature": "Supply temperature",
    "/heatSources/systemPressure": "System pressure",
    "/heatSources/flameStatus": "Flame",
    "/heatSources/numberOfStarts": "Burner starts",
    "/heatSources/{heatSourceId}/numberOfStarts": "Compressor starts",
    "/system/sensors/temperatures/outdoor_t1": "Outdoor temperature",
    "/gateway/versionFirmware": "Firmware version",
    "/heatSources/{heatSourceId}/heatPumpType": "Heat pump type",
    "/gateway/versionHardware": "Hardware version",
    "/notifications": "Notifications",
    "/gateway/tzInfo/timeZone": "Time zone",
    "/gateway/tzInfo/dstActive": "Daylight saving time",
    "/gateway/eth/ip/ipv4": "Ethernet IPv4 address",
    "/gateway/wifi/ip/ipv4": "Wi-Fi IPv4 address",
    "/gateway/eth/mac": "Ethernet MAC address",
    "/gateway/wifi/mac": "Wi-Fi MAC address",
    "/heatSources/emStatus": "Energy manager status",
    "/heatSources/Source/eHeater/status": "Electric heater status",
    "/heatSources/workingTimeTotalSystem": "System working time",
    "/dhwCircuits/{dhwCircuitId}/tdrunningStatus": "Thermal disinfection",
    "/heatingCircuits/{heatingCircuitId}/currentSuWiMode": "Summer/winter mode",
    "/system/iSRC/installationStatus": "Internal source installation status",
    "/system/iSRC/supportStatus": "Internal source support status",
    "/heatingCircuits/{heatingCircuitId}/pumpStatus": "Circulation pump",
    "/devices/{deviceId}/rfConnectionStatus": "Radio connection",
    "/system/powerLimitation/active": "Power limitation",
    "/system/powerConstraints/silentMode/status": "Silent mode",
    "/heatSources/smartFunction/active": "Smart function",
}

#: Component names of a multi-counter resource, and how they should read.
COMPONENT_NAMES: dict[str, str] = {
    "outputProduced": "produced",
    "eheater": "electric heater",
    "compressor": "compressor",
    "burner": "burner",
    "electricity": "electricity",
    "solar": "solar",
    "ventilation": "ventilation",
    "ventilationHeatRecovered": "heat recovered",
    "ch": "heating",
    "dhw": "hot water",
    "cooling": "cooling",
    "pool": "pool",
    "total": "total",
}

#: camelCase boundaries, both kinds: "supplyTemp" and the run of capitals in
#: "CHPumpSpeed" or "DHWValve", which the /signals ids are full of.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_NON_WORD = re.compile(r"[^a-z0-9]+")

#: An abbreviation with its number attached, as the /signals ids write them:
#: HC4, DHW1, HP2. Expanded like the bare word, with the number kept.
_NUMBERED_WORD = re.compile(r"^([a-z]+)(\d+)$")


def split_words(segment: str) -> list[str]:
    """Break one path segment into lower-case words."""
    spaced = _CAMEL_BOUNDARY.sub(" ", segment)
    spaced = spaced.replace("_", " ").replace("-", " ")
    return [word for word in spaced.lower().split() if word]


def translation_key(path: str) -> str:
    """Build a stable, unique key for one catalogue path."""
    parts: list[str] = []
    for segment in path.strip("/").split("/"):
        placeholder = _PLACEHOLDER.fullmatch(segment)
        if placeholder:
            parts.append(PLACEHOLDER_SLUGS.get(placeholder.group(1), "item"))
            continue
        parts.extend(split_words(segment))
    key = "_".join(parts)
    return _NON_WORD.sub("_", key).strip("_")


def english_name(path: str) -> str:
    """Render a readable English entity name for one catalogue path."""
    if path in NAME_OVERRIDES:
        return NAME_OVERRIDES[path]

    segments = [s for s in path.strip("/").split("/") if not _PLACEHOLDER.fullmatch(s)]
    branch = BRANCH_LABELS.get(segments[0], "") if segments else ""
    rest = [s for s in (segments[1:] if branch else segments) if s not in STRUCTURAL_SEGMENTS]

    words = _expand(rest)

    # Drop the branch only where the tail repeats it whole ("Ventilation
    # ventilation mode"). Dropping word by word would eat the "heat" out of
    # "heatPumpType" and the "heat" out of "heatCarrierPump".
    branch_words = branch.lower().split()
    lowered = [word.lower() for word in words]
    if branch_words and lowered[: len(branch_words)] == branch_words:
        words = words[len(branch_words) :]

    # The device carries the branch for everything that has a device.
    prefix = "" if segments and segments[0] in DEVICE_BRANCHES else branch
    return _render([*prefix.lower().split(), *words]) or branch or path


def _expand(segments: Sequence[str]) -> list[str]:
    """Break path or id segments into words, spelling out the abbreviations."""
    words: list[str] = []
    for segment in segments:
        for word in split_words(segment):
            if (expansion := WORD_EXPANSIONS.get(word)) is not None:
                words.extend(expansion.split())
            elif (numbered := _NUMBERED_WORD.match(word)) and (
                expansion := WORD_EXPANSIONS.get(numbered.group(1))
            ):
                words.extend([*expansion.split(), numbered.group(2)])
            else:
                words.append(word)
    return words


def _render(words: Sequence[str]) -> str:
    """Join expanded words into a name, fixing phrases and capitalisation."""
    name = re.sub(r"\s+", " ", " ".join(words)).strip()
    for wrong, right in PHRASE_FIXES.items():
        name = name.replace(wrong, right)
    if not name:
        return ""

    rendered = [word.upper() if word.upper() in KEEP_UPPER else word for word in name.split()]
    first = rendered[0]
    rendered[0] = first if first in KEEP_UPPER else first.capitalize()
    return " ".join(rendered)


def signal_name(parts: Sequence[str]) -> str:
    """Render a readable name for one /signals id.

    Signals are per-device and never reach strings.json, so this is the only
    place their names are made. ``parts`` is what the device did not already
    say: DeviceTree.signal_target strips the leading SRC/SC/VENTILATION and the
    circuit segment, because the device page carries both.
    """
    return _render(_expand(parts))


def component_key(component: str) -> str:
    """Slugify a component name for use in a translation key."""
    return _CAMEL_BOUNDARY.sub("_", component).lower()


def component_name(component: str) -> str:
    """Render a component name readably."""
    return COMPONENT_NAMES.get(component, component)
