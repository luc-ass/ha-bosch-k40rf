"""Turn a user's diagnostics download into a list of what is new about it.

The integration was written against one installation. Everything else -- a
cascade, solar, a pool, a gas boiler, a second heating circuit -- follows the
published spec and has never been seen. A diagnostics file from such a system
is the only evidence we can get, and reading one by hand is an hour of JSON.

This reads it in a second and answers four questions:

* what kind of installation is it, and what hardware is in it
* which catalogue resources does it confirm that our test device never had
* what does it serve that the catalogue does not declare at all
* what does its /signals branch look like -- the half of the API that appears
  in no specification and differs per appliance

Usage:
    python tools/report_from_diagnostics.py path/to/diagnostics.json
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

HERE = Path(__file__).parent
COMPONENT = HERE / "../custom_components/bosch_k40rf"
sys.path.insert(0, str(COMPONENT.resolve()))

from catalog import CATALOG

#: Placeholder ids are expanded per installation, so comparing paths means
#: comparing them in their templated form.
_PLACEHOLDERS = {
    "heatSourceId": ("hs", 6),
    "heatingCircuitId": ("hc", 4),
    "dhwCircuitId": ("dhw", 2),
    "solarCircuitId": ("sc", 1),
    "ventilationZoneId": ("zone", 1),
    "zoneId": ("zone", 16),
    "deviceId": ("device", 32),
}


def main(argv: list[str]) -> int:
    """Report on one diagnostics file."""
    if len(argv) != 2:
        print(__doc__)
        return 2

    data = json.loads(Path(argv[1]).read_text())
    declared, by_concrete = _catalogue()

    print(_heading("Installation"))
    _describe(data)

    answered = set(data.get("polled_paths") or [])
    print(_heading("Confirms, and we had never seen it"))
    unseen = sorted(
        {
            by_concrete[path]
            for path in answered
            if path in by_concrete and not declared[by_concrete[path]]
        }
    )
    _bullets(unseen, "nothing the test device did not already have")

    print(_heading("Serves, and the catalogue does not declare it"))
    unknown = sorted(path for path in answered if path not in by_concrete)
    _bullets(unknown, "nothing outside the catalogue")

    print(_heading("Refused, though the catalogue declares it"))
    absent = data.get("absent_paths") or []
    print(f"  {len(absent)} of {len(absent) + len(answered)} paths -- normal; the spec")
    print("  covers every variant Bosch sells. Interesting only next to another")
    print("  installation of the same type.")

    print(_heading("Signals"))
    _signals(data)
    return 0


def _catalogue() -> tuple[dict[str, bool], dict[str, str]]:
    """Return live-confirmed by template path, and every concrete path's template."""
    declared: dict[str, bool] = {}
    by_concrete: dict[str, str] = {}
    for spec in CATALOG:
        declared[spec.path] = spec.live_confirmed
        for concrete in _expand(spec.path, spec.placeholder):
            by_concrete[concrete] = spec.path
    return declared, by_concrete


def _expand(path: str, placeholder: str | None) -> list[str]:
    """Every concrete path a catalogue entry can appear as."""
    if placeholder is None:
        return [path]
    prefix, count = _PLACEHOLDERS.get(placeholder, ("", 0))
    return [path.replace(f"{{{placeholder}}}", f"{prefix}{n}") for n in range(1, count + 1)]


def _describe(data: dict[str, Any]) -> None:
    """Print what kind of system this is."""
    resources = data.get("resources") or {}
    for path, label in (
        ("/system/type", "System"),
        ("/heatSources/hs1/heatPumpType", "Heat pump"),
        ("/system/bus", "Bus"),
        ("/gateway/brand", "Brand"),
        ("/gateway/versionFirmware", "Firmware"),
    ):
        if (resource := resources.get(path)) and (value := resource.get("value")):
            print(f"  {label + ':':12} {value}")

    installation = data.get("installation") or {}
    present = {
        key: value for key, value in installation.items() if isinstance(value, list) and value
    }
    print(f"  {'Circuits:':12} " + ", ".join(f"{k}={'+'.join(v)}" for k, v in present.items()))

    for module in (data.get("system_info") or {}).get("modules") or []:
        name = module.get("name") or module.get("hardware_id") or "?"
        print(f"  {'Module:':12} {name} ({module.get('hardware_id')}, {module.get('version')})")

    for device in data.get("devices") or []:
        print(f"  {'Device:':12} {device.get('name')} [{'/'.join(device.get('id') or [])}]")


def _signals(data: dict[str, Any]) -> None:
    """Print the shape of the /signals branch, which no spec describes."""
    signals = data.get("signals") or {}
    if error := signals.get("error"):
        print(f"  not readable: {error}")
        return

    resources = signals.get("resources") or {}
    print(f"  {signals.get('count', len(resources))} signals")

    prefixes: dict[str, int] = {}
    enums: list[str] = []
    for path, resource in sorted(resources.items()):
        signal_id = path.rsplit("/", 1)[-1]
        prefixes[signal_id.split(".")[0]] = prefixes.get(signal_id.split(".")[0], 0) + 1
        if isinstance(resource.get("state"), dict):
            enums.append(f"{signal_id} = {sorted(resource['state'])}")

    for prefix, count in sorted(prefixes.items(), key=lambda item: -item[1]):
        print(f"    {prefix:14} {count}")
    if enums:
        print(f"  {len(enums)} carry an enumeration:")
        for line in enums[:10]:
            print(f"    {line}")
        if len(enums) > 10:
            print(f"    ... and {len(enums) - 10} more")


def _heading(text: str) -> str:
    return f"\n{text}\n{'-' * len(text)}"


def _bullets(items: list[str], empty: str) -> None:
    if not items:
        print(f"  {empty}")
        return
    for item in items:
        print(f"  {item}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
