"""Write QUALITY.md from the integration's quality_scale.yaml.

The scale is what Home Assistant Core grades an integration by. The YAML file
is the source of truth -- hassfest reads the same one -- so the overview is
generated from it rather than kept alongside it, where the two would drift.

Usage:
    python tools/quality_report.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).parent
YAML = HERE / "../custom_components/bosch_k40rf/quality_scale.yaml"
REPORT = HERE / "../QUALITY.md"
DOCS = "https://developers.home-assistant.io/docs/core/integration-quality-scale/rules"

#: Which tier each rule belongs to, as Core's hassfest declares it
#: (script/hassfest/quality_scale.py, ALL_RULES). Copied rather than imported:
#: the Core checkout is a local clone, and this has to run in CI too. A rule
#: Core adds shows up as a mismatch the moment it reaches the YAML file.
TIERS: dict[str, tuple[str, ...]] = {
    "Bronze": (
        "action-setup",
        "appropriate-polling",
        "brands",
        "common-modules",
        "config-flow",
        "config-flow-test-coverage",
        "dependency-transparency",
        "docs-actions",
        "docs-conditions",
        "docs-high-level-description",
        "docs-installation-instructions",
        "docs-removal-instructions",
        "docs-triggers",
        "entity-event-setup",
        "entity-unique-id",
        "has-entity-name",
        "runtime-data",
        "test-before-configure",
        "test-before-setup",
        "unique-config-entry",
    ),
    "Silver": (
        "action-exceptions",
        "config-entry-unloading",
        "docs-configuration-parameters",
        "docs-installation-parameters",
        "entity-unavailable",
        "integration-owner",
        "log-when-unavailable",
        "parallel-updates",
        "reauthentication-flow",
        "test-coverage",
    ),
    "Gold": (
        "devices",
        "diagnostics",
        "discovery",
        "discovery-update-info",
        "docs-data-update",
        "docs-examples",
        "docs-known-limitations",
        "docs-supported-devices",
        "docs-supported-functions",
        "docs-troubleshooting",
        "docs-use-cases",
        "dynamic-devices",
        "entity-category",
        "entity-device-class",
        "entity-disabled-by-default",
        "entity-translations",
        "exception-translations",
        "icon-translations",
        "reconfiguration-flow",
        "repair-issues",
        "stale-devices",
    ),
    "Platinum": ("async-dependency", "inject-websession", "strict-typing"),
}

MARK = {"done": "✅", "exempt": "➖", "todo": "⬜"}


def load_rules() -> dict[str, tuple[str, str]]:
    """Read the YAML file as {rule: (status, comment)}.

    Hand-parsed: the file is a flat mapping of rules to a status or to a
    status/comment pair, and pulling PyYAML in for that is not worth it.
    """
    rules: dict[str, tuple[str, str]] = {}
    rule = status = ""
    comment: list[str] = []

    def flush() -> None:
        if rule:
            rules[rule] = (status, " ".join(comment).strip())

    for raw in YAML.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line == "rules:":
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 2 and line.endswith(":"):
            flush()
            rule, status, comment = line[:-1], "", []
        elif indent == 2:
            flush()
            name, _, value = line.partition(":")
            rule, status, comment = name, value.strip(), []
        elif line.startswith("status:"):
            status = line.partition(":")[2].strip()
        elif line.startswith("comment:"):
            text = line.partition(":")[2].strip()
            comment = [] if text in {">-", ">", "|"} else [text]
        else:
            comment.append(line)
    flush()
    return rules


def main() -> int:
    """Write QUALITY.md, or explain why it cannot be written."""
    rules = load_rules()

    declared = {name for names in TIERS.values() for name in names}
    if missing := sorted(declared - rules.keys()):
        print(f"quality_scale.yaml does not rate: {', '.join(missing)}", file=sys.stderr)
        return 1
    if unknown := sorted(rules.keys() - declared):
        print(
            f"quality_scale.yaml rates rules this script does not know: {', '.join(unknown)}\n"
            "Core has changed its list; update TIERS from script/hassfest/quality_scale.py.",
            file=sys.stderr,
        )
        return 1

    manifest = json.loads((HERE / "../custom_components/bosch_k40rf/manifest.json").read_text())
    counts = {
        tier: {
            status: sum(1 for name in names if rules[name][0] == status)
            for status in ("done", "exempt", "todo")
        }
        for tier, names in TIERS.items()
    }

    lines = [
        "# Quality scale",
        "",
        "<!-- Generated by tools/quality_report.py from quality_scale.yaml. Do not edit. -->",
        "",
        "How Home Assistant Core grades an integration. A tier is reached when every",
        "one of its rules is `done` or `exempt` **and** every tier below it is reached;",
        "`exempt` means the rule cannot apply here, not that it was skipped.",
        "",
        f"The manifest declares **{manifest['quality_scale']}**.",
        "",
        "| Tier | ✅ done | ➖ exempt | ⬜ todo | reached |",
        "|---|---:|---:|---:|---|",
    ]

    reached = True
    for tier, count in counts.items():
        clear = count["todo"] == 0
        reached = reached and clear
        # A tier with nothing of its own open is still not reached while a tier
        # below it has work left -- worth telling apart from having work here.
        mark = "✅" if reached else "⛔ blocked below" if clear else "—"
        lines.append(f"| {tier} | {count['done']} | {count['exempt']} | {count['todo']} | {mark} |")

    open_rules = [
        (tier, name, rules[name][1])
        for tier, names in TIERS.items()
        for name in names
        if rules[name][0] == "todo"
    ]

    lines += ["", "## What is missing", ""]
    if open_rules:
        for tier, name, comment in open_rules:
            lines.append(f"- **{tier} · [{name}]({DOCS}/{name})** — {comment or 'no note yet.'}")
    else:
        lines.append("Nothing: every rule is `done` or `exempt`.")

    for tier, names in TIERS.items():
        lines += ["", f"## {tier}", "", "| Rule | | Note |", "|---|:-:|---|"]
        for name in names:
            status, comment = rules[name]
            lines.append(f"| [{name}]({DOCS}/{name}) | {MARK[status]} | {comment} |")

    REPORT.write_text("\n".join(lines) + "\n")
    total = sum(c["todo"] for c in counts.values())
    print(f"{REPORT.name} written; {total} rule(s) open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
