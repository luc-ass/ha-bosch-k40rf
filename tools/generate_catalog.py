"""Generate the resource catalogue from the Bosch API spec plus a live harvest.

The published spec declares 261 paths covering every installation variant --
six heat sources, four heating circuits, solar, pool, sixteen zones. The test
device implements a fraction of them. Hard-coding what one house happens to
have would leave every other installation half-supported, so the catalogue is
generated from the spec and the integration probes at runtime which entries
actually answer (see docs/00-PLAN.md, rule A6).

The live harvest is used only to correct the spec where the device disagrees
with it -- units and value types are more trustworthy from a real answer.

Usage:
    python tools/generate_catalog.py [path/to/responses/owner]
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import yaml

HERE = Path(__file__).parent
REPO = HERE / "../../.."
SPEC = REPO / "recon/api/k-40-rf.yaml"
DEFAULT_HARVEST = REPO / "recon/responses/owner"
TARGET = HERE / "../custom_components/bosch_k40rf/catalog.py"

#: History is read on demand, never polled, so it gets no entities.
SKIP_PREFIXES = ("/recordings/",)
#: The signals branch is device specific and resolved at runtime instead.
SKIP_PATHS = frozenset({"/signals", "/signals/{signalId}"})

#: The spec spells units inconsistently ('rpm"' is a literal typo in it).
UNIT_FIXES = {
    'rpm"': "rpm",
    "db": "dB",
    "wh": "Wh",
    "C": "C",
    "mins": "min",
}

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def spec_example(operation: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the 200 example payload out of a path's GET operation."""
    responses = operation.get("responses") or {}
    content = ((responses.get("200") or {}).get("content") or {}).get("application/json")
    example = (content or {}).get("example")
    return example if isinstance(example, dict) else None


def load_live(harvest: Path) -> dict[str, dict[str, Any]]:
    """Index a harvest by resource id, so the spec can be corrected from it."""
    live: dict[str, dict[str, Any]] = {}
    if not harvest.is_dir():
        return live
    for file in harvest.glob("*.json"):
        if file.name.startswith("_"):
            continue
        try:
            payload = json.loads(file.read_text())
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("id"), str):
            live[payload["id"].split("?")[0]] = payload
    return live


def generalise(resource_id: str) -> str:
    """Turn a concrete resource id back into its spec template."""
    for concrete, variable in (
        (r"/heatSources/hs\d+/", "/heatSources/{heatSourceId}/"),
        (r"/heatingCircuits/hc\d+/", "/heatingCircuits/{heatingCircuitId}/"),
        (r"/dhwCircuits/dhw\d+/", "/dhwCircuits/{dhwCircuitId}/"),
        (r"/solarCircuits/sc\d+/", "/solarCircuits/{solarCircuitId}/"),
        (r"/ventilation/zone\d+/", "/ventilation/{ventilationZoneId}/"),
        (r"/zones/zone\d+/", "/zones/{zoneId}/"),
        (r"/devices/device\d+/", "/devices/{deviceId}/"),
    ):
        resource_id = re.sub(concrete, variable, resource_id)
    return resource_id


def main() -> int:
    """Write the catalogue module."""
    harvest = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HARVEST
    live_by_template: dict[str, dict[str, Any]] = {}
    for resource_id, payload in load_live(harvest.resolve()).items():
        live_by_template.setdefault(generalise(resource_id), payload)

    spec = yaml.safe_load(SPEC.read_text())
    entries: list[dict[str, Any]] = []

    for path, methods in sorted(spec["paths"].items()):
        if path in SKIP_PATHS or path.startswith(SKIP_PREFIXES):
            continue
        operation = methods.get("get")
        if not operation:
            continue

        example = spec_example(operation) or {}
        live = live_by_template.get(path)
        source = live or example

        value_type = source.get("type") or example.get("type")
        if not value_type:
            continue

        unit = source.get("unitOfMeasure") or source.get("unit") or ""
        unit = UNIT_FIXES.get(unit, unit)

        allowed = source.get("allowedValues")
        placeholders = PLACEHOLDER.findall(path)

        # An emonValue is several counters in one resource. The component names
        # come from the spec so their entities can be named ahead of time.
        # Spec and device are merged rather than one overriding the other: the
        # spec lists components this house has no hardware for (a gas boiler's
        # "burner"), and the device occasionally reports one the spec forgot.
        components: list[str] = []
        if value_type == "emonValue":
            for payload in (example, live or {}):
                for item in payload.get("values") or []:
                    if isinstance(item, dict):
                        components.extend(str(name) for name in item)

        entries.append(
            {
                "path": path,
                "placeholder": placeholders[0] if placeholders else None,
                "type": value_type,
                "unit": unit or None,
                "options": tuple(str(v) for v in allowed) if isinstance(allowed, list) else (),
                "components": tuple(dict.fromkeys(components)),
                "description": (operation.get("description") or "").strip(),
                "writeable": bool(source.get("writeable", 0)),
                "live": live is not None,
            }
        )

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(entries))
    reformat(TARGET)
    live_count = sum(1 for e in entries if e["live"])
    print(f"{len(entries)} resources written to {TARGET} ({live_count} confirmed on a live device)")
    return 0


def reformat(target: Path) -> None:
    """Hand the generated file to ruff, so regenerating never dirties the diff.

    Reproducing ruff's line-wrapping here would be a second, worse formatter.
    If ruff is not installed the file is still valid Python, just wrapped
    differently, so this is a warning rather than a failure.
    """
    # Through this interpreter, so it works without ruff being on PATH.
    try:
        subprocess.run(
            [sys.executable, "-m", "ruff", "format", "--quiet", str(target)],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as err:
        print(f"  could not run ruff format ({err}); run it yourself", file=sys.stderr)


def literal(value: Any) -> str:
    """Render a Python literal the way ruff format wants it: double quotes.

    ``repr`` emits single quotes, which makes every regeneration dirty the file
    and fail ``ruff format --check``.
    """
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, tuple):
        if len(value) == 1:
            return f"({literal(value[0])},)"
        return "(" + ", ".join(literal(item) for item in value) + ")"
    return repr(value)


def render(entries: list[dict[str, Any]]) -> str:
    """Render the catalogue module source."""
    lines = [
        '"""Every resource the K 40 RF API declares.',
        "",
        "Generated by tools/generate_catalog.py from the published Bosch API spec,",
        "corrected against a live harvest where the device disagreed with it. Do not",
        "edit by hand.",
        "",
        "Presence is not implied: the spec covers every installation variant, and a",
        "given gateway answers 404 for whatever it does not have. The coordinator",
        "probes once at setup and only polls what answered.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "",
        "",
        "@dataclass(frozen=True, slots=True)",
        "class ResourceSpec:",
        '    """One declared resource, before it is known to exist."""',
        "",
        "    path: str",
        "    value_type: str",
        "    placeholder: str | None = None",
        "    unit: str | None = None",
        "    options: tuple[str, ...] = ()",
        "    components: tuple[str, ...] = ()",
        '    description: str = ""',
        "    live_confirmed: bool = False",
        "",
        "    @property",
        "    def is_templated(self) -> bool:",
        '        """Whether this path needs an id substituted before use."""',
        "        return self.placeholder is not None",
        "",
        "",
        "CATALOG: tuple[ResourceSpec, ...] = (",
    ]

    for entry in entries:
        parts = [
            f"        path={literal(entry['path'])},",
            f"        value_type={literal(entry['type'])},",
        ]
        if entry["placeholder"]:
            parts.append(f"        placeholder={literal(entry['placeholder'])},")
        if entry["unit"]:
            parts.append(f"        unit={literal(entry['unit'])},")
        if entry["options"]:
            parts.append(f"        options={literal(entry['options'])},")
        if entry["components"]:
            parts.append(f"        components={literal(entry['components'])},")
        if entry["description"]:
            parts.append(f"        description={literal(entry['description'])},")
        if entry["live"]:
            parts.append("        live_confirmed=True,")
        lines.append("    ResourceSpec(")
        lines.extend(parts)
        lines.append("    ),")

    lines += [
        ")",
        "",
        "#: Indexed by path template, for lookups during discovery.",
        "BY_PATH: dict[str, ResourceSpec] = {spec.path: spec for spec in CATALOG}",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
