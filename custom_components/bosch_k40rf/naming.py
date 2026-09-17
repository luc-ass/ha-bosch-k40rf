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
    "tl2": "TL2",
}

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
KEEP_UPPER = {"EEBUS", "COP", "PV", "ID", "IP", "MAC", "SSID", "DNS", "URL", "T1", "TL2"}

#: Where the rules read badly. Keyed by catalogue path.
NAME_OVERRIDES: dict[str, str] = {
    "/heatSources/emon/totalConsumption": "Total energy",
    "/heatSources/emon/chConsumption": "Heating energy",
    "/heatSources/emon/dhwConsumption": "Hot water energy",
    "/heatSources/emon/coolingConsumption": "Cooling energy",
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

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_NON_WORD = re.compile(r"[^a-z0-9]+")


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
    rest = segments[1:] if branch else segments

    words: list[str] = []
    for segment in rest:
        for word in split_words(segment):
            words.extend(WORD_EXPANSIONS.get(word, word).split())

    # Drop the branch only where the tail repeats it whole ("Ventilation
    # ventilation mode"). Dropping word by word would eat the "heat" out of
    # "heatPumpType" and the "heat" out of "heatCarrierPump".
    branch_words = branch.lower().split()
    lowered = [word.lower() for word in words]
    if branch_words and lowered[: len(branch_words)] == branch_words:
        words = words[len(branch_words) :]

    name = " ".join([branch.lower(), *words]) if branch else " ".join(words)
    name = re.sub(r"\s+", " ", name).strip()
    for wrong, right in PHRASE_FIXES.items():
        name = name.replace(wrong, right)
    if not name:
        return branch or path

    rendered = [word.upper() if word.upper() in KEEP_UPPER else word for word in name.split()]
    first = rendered[0]
    rendered[0] = first if first in KEEP_UPPER else first.capitalize()
    return " ".join(rendered)


def component_key(component: str) -> str:
    """Slugify a component name for use in a translation key."""
    return _CAMEL_BOUNDARY.sub("_", component).lower()


def component_name(component: str) -> str:
    """Render a component name readably."""
    return COMPONENT_NAMES.get(component, component)
