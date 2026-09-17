"""Write strings.json from the catalogue plus the hand-written flow text.

Entity names are derived in custom_components/bosch_k40rf/naming.py, so the
same rules produce the names the platforms use and the names the translation
file declares. The config-flow half is hand-written in strings.base.json and
merged in unchanged.

Usage:
    python tools/generate_strings.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).parent
COMPONENT = HERE / "../custom_components/bosch_k40rf"
sys.path.insert(0, str(COMPONENT.resolve()))

from catalog import CATALOG
from naming import component_key, component_name, english_name, translation_key

BASE = HERE / "strings.base.json"
STRINGS = COMPONENT / "strings.json"
TRANSLATIONS = COMPONENT / "translations"

#: Types that become entities; the rest never need a name.
ENTITY_TYPES = frozenset({"floatValue", "integerValue", "stringValue", "emonValue"})


def main() -> int:
    """Write strings.json and the English translation copy."""
    strings = json.loads(BASE.read_text())

    sensors: dict[str, dict[str, str]] = {}
    for spec in CATALOG:
        if spec.value_type not in ENTITY_TYPES:
            continue
        name = english_name(spec.path)
        sensors[translation_key(spec.path)] = {"name": name}

        # A multi-counter resource becomes one entity per component.
        for component in spec.components:
            key = f"{translation_key(spec.path)}_{component_key(component)}"
            sensors[key] = {"name": f"{name} {component_name(component)}"}

    strings["entity"] = {"sensor": dict(sorted(sensors.items()))}

    rendered = json.dumps(strings, indent=2, ensure_ascii=False) + "\n"
    STRINGS.write_text(rendered)

    # Core reads strings.json and ships other languages through Lokalise, but a
    # custom (HACS) install reads translations/<lang>.json instead, so the
    # English file has to exist there too.
    TRANSLATIONS.mkdir(exist_ok=True)
    (TRANSLATIONS / "en.json").write_text(rendered)

    print(f"{len(sensors)} entity names written to {STRINGS.name} and translations/en.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
