"""Write signal_booleans.py from every signal harvest we hold.

The /signals branch is not in the published spec -- it is whatever the
controller of one appliance happens to expose -- so the only source for which
signals are flags is the readings themselves. This walks the recon corpus
(our own device plus every contributed diagnostics) and keeps the ids whose
``stringValue`` was one of the gateway's two flag words on every installation
that reported them.

Run it from the package root after a new diagnostics file lands:

    ../../.venv/bin/python tools/generate_signal_booleans.py

Its input lives in the k40-recon monorepo, not in this repository, so unlike
generate_strings.py it cannot run in CI. Only the output ships.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).parent
REPO = HERE / "../../.."
#: Globbed rather than listed, so a contribution that lands in the corpus is
#: picked up by running this -- a hardcoded list would go on producing the old
#: answer, in silence, which is the one failure mode a generator must not have.
HARVEST_GLOBS = ("recon/responses/*/signals", "recon/responses/*/*/signals")
TARGET = HERE / "../custom_components/bosch_k40rf/signal_booleans.py"

FLAG_WORDS = frozenset({"true", "false"})

#: Device classes, by the tail of the signal id. Deliberately sparse: a wrong
#: class is worse than none, because it paints the wrong colour on a reading
#: nobody can check against the appliance. So only where the id says plainly
#: what the flag is -- a relay is running or not, a heater heats or not, a
#: link is up or not, an alarm is a fault or not.
#:
#: Left classless on purpose: everything that reports a *condition* rather
#: than a state. A blocked compressor, a permitted-temperature limit or a
#: pressure switch is not a "problem" in Home Assistant's sense -- those are
#: the controller protecting itself, and painting them red would cry wolf on
#: a heat pump doing its job.
DEVICE_CLASSES: tuple[tuple[str, str], ...] = (
    # Faults, and only the two that are unambiguously faults.
    ("InverterOverheated", "PROBLEM"),
    ("Additional.AlarmInput", "PROBLEM"),
    # Links to the inverter boards.
    ("ConnectedToLIN", "CONNECTIVITY"),
    # Anything that makes heat when it is on.
    ("CrankcaseHeater", "HEAT"),
    ("DHWHeater", "HEAT"),
    ("DripPanHeater", "HEAT"),
    ("HeatingCable", "HEAT"),
    ("ElectricalHeaterStep1", "HEAT"),
    ("ElectricalHeaterStep2", "HEAT"),
    ("ElectricalHeaterStep3", "HEAT"),
    ("ElectricalHeaterStep4", "HEAT"),
    ("AddElectricActive", "HEAT"),
    # Relays, pumps, valves and the compressor: energised or not.
    ("CompressorStatus", "RUNNING"),
    ("CompressorActive", "RUNNING"),
    ("CircPumpStatus", "RUNNING"),
    ("DHURunning", "RUNNING"),
    ("HeatUpSequence", "RUNNING"),
    ("AirPurgeModeActive", "RUNNING"),
    ("Cooling.Active", "RUNNING"),
    ("CHPumpRelay", "RUNNING"),
    ("HC1PumpRelay", "RUNNING"),
    ("G3Relay", "RUNNING"),
    ("RelayStatus.CHPump", "RUNNING"),
    ("RelayStatus.Fan", "RUNNING"),
    ("RelayStatus.GasValve1", "RUNNING"),
    ("RelayStatus.GasValve2", "RUNNING"),
    ("RelayStatus.3WayValve", "RUNNING"),
    ("FourwayValve", "RUNNING"),
    ("DHWValve", "RUNNING"),
)


def device_class(signal_id: str) -> str | None:
    """Return the device class for one signal id, longest suffix rule winning."""
    matches = [(suffix, name) for suffix, name in DEVICE_CLASSES if signal_id.endswith(suffix)]
    if not matches:
        return None
    return max(matches, key=lambda match: len(match[0]))[1]


def harvests() -> list[Path]:
    """Every signal harvest in the corpus, ours and the contributed ones."""
    found = {
        directory.resolve()
        for pattern in HARVEST_GLOBS
        for directory in REPO.glob(pattern)
        if directory.is_dir()
    }
    return sorted(found)


def collect(directories: list[Path]) -> dict[str, list[str]]:
    """Index every harvested string signal by id, keeping the values seen.

    A harvest entry without a value says nothing about the id -- the earliest
    contributions were bare ids, because one unreadable field used to sink the
    whole poll. Those are skipped rather than read as the word "none", which
    would silently demote a genuine flag the moment such a harvest is added.
    """
    seen: dict[str, set[str]] = {}
    for harvest in directories:
        for path in harvest.glob("*.json"):
            if path.stem.startswith("_"):
                continue
            payload = json.loads(path.read_text())
            if payload.get("type") != "stringValue":
                continue
            value = payload.get("value")
            if value is None:
                continue
            seen.setdefault(str(payload["id"]), set()).add(str(value).strip().lower())
    return {key: sorted(values) for key, values in sorted(seen.items())}


def render(flags: dict[str, str | None]) -> str:
    """Render the module."""
    lines = [
        '"""Which ``/signals`` readings are flags, and what they mean.',
        "",
        "Generated by tools/generate_signal_booleans.py from the signal harvests",
        "of every installation we hold. Do not edit by hand.",
        "",
        "A signal entity is built before the signal branch has ever been polled --",
        "the branch is not read at all while every one of its entities is disabled,",
        "which is the normal case. So unlike a unit or a state class, which the",
        "sensor fills in from the first reading, the *platform* a signal belongs to",
        "has to be known before there is a reading. Hence a list rather than a",
        "check against the live value.",
        "",
        "A flag absent here stays a sensor reporting the word ``true`` or",
        "``false``, which is how this list learns: a contributed diagnostics file",
        "carries every signal with its value, and the coordinator logs any string",
        "signal reading a flag word that this list does not name.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from homeassistant.components.binary_sensor import BinarySensorDeviceClass",
        "",
        "#: Signal id -> device class, or ``None`` where the id does not say",
        "#: plainly enough what the flag means.",
        "BOOLEAN_SIGNALS: dict[str, BinarySensorDeviceClass | None] = {",
    ]
    for signal_id, class_name in flags.items():
        rendered = f"BinarySensorDeviceClass.{class_name}" if class_name else "None"
        lines.append(f'    "{signal_id}": {rendered},')
    lines += ["}", ""]
    return "\n".join(lines)


def main() -> int:
    """Write the module and format it."""
    directories = harvests()
    for directory in directories:
        print(f"harvest: {directory.relative_to(REPO.resolve())}", file=sys.stderr)
    harvested = collect(directories)
    flags: dict[str, str | None] = {}
    for signal_id, values in harvested.items():
        if set(values) <= FLAG_WORDS:
            flags[signal_id] = device_class(signal_id)
        else:
            print(f"not a flag, left a sensor: {signal_id} = {values}", file=sys.stderr)

    TARGET.write_text(render(flags))
    # Through this interpreter, so it works without ruff being on PATH.
    try:
        subprocess.run(
            [sys.executable, "-m", "ruff", "format", "--quiet", str(TARGET)],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as err:
        print(f"  could not run ruff format ({err}); run it yourself", file=sys.stderr)
    print(f"{len(flags)} flag signals -> {TARGET}")
    classed = sum(1 for value in flags.values() if value)
    print(f"{classed} with a device class, {len(flags) - classed} without")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
