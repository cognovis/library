#!/usr/bin/env python3
"""
check-coverage.py — Verify that all migrated artefacts are registered in library.yaml

Compares the artefacts listed in docs/audit/skills-origin.json (filtered by
migration_action in ['move_to_cognovis_library_core', 'move_to_sussdorff_library_core'])
against the entries in library.yaml library.skills, library.agents, and library.prompts.

Exit codes:
    0 — All migrated artefacts are registered
    1 — One or more artefacts are missing from library.yaml

Usage:
    python3 scripts/check-coverage.py
    python3 scripts/check-coverage.py --audit PATH --yaml PATH
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


try:
    import yaml
except ImportError:
    print("FAIL: PyYAML is not installed. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def find_repo_root() -> Path:
    """Walk up from this script to find the repo root (contains library.yaml)."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "library.yaml").exists():
            return current
        current = current.parent
    cwd = Path.cwd()
    if (cwd / "library.yaml").exists():
        return cwd
    raise FileNotFoundError(
        "Could not find library.yaml in any parent directory. "
        "Run this script from within the cognovis-library repository."
    )


def extract_canonical_name(path: str, current_type: str) -> str | None:
    """Extract the canonical name of an artefact from its audit path."""
    parts = path.split("/")

    if current_type == "skill":
        # path: <category>/skills/<name>/SKILL.md
        if len(parts) >= 3 and parts[-1].lower() in ("skill.md",):
            return parts[-2]
        # path: <category>/skills/<name>/SKILL.md
        for i, p in enumerate(parts):
            if p == "skills" and i + 1 < len(parts):
                return parts[i + 1]
        return None

    elif current_type == "agent":
        # path: <category>/agents/<filename>.md
        filename = parts[-1]
        if filename.endswith(".md"):
            return filename[:-3]
        return None

    elif current_type == "command":
        # path: .claude/commands/<filename>.md
        filename = parts[-1]
        if filename.endswith(".md"):
            return filename[:-3]
        return None

    return None


def get_registered_names(library_data: dict) -> tuple[set, set, set]:
    """Return sets of registered names for skills, agents, prompts."""
    lib = library_data.get("library", {})
    skills = {e["name"] for e in lib.get("skills", []) if "name" in e}
    agents = {e["name"] for e in lib.get("agents", []) if "name" in e}
    prompts = {e["name"] for e in lib.get("prompts", []) if "name" in e}
    return skills, agents, prompts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", help="Path to audit JSON (default: docs/audit/skills-origin.json)")
    parser.add_argument("--yaml", help="Path to library.yaml (default: library.yaml in repo root)")
    args = parser.parse_args(argv)

    repo_root = find_repo_root()

    audit_path = Path(args.audit) if args.audit else repo_root / "docs" / "audit" / "skills-origin.json"
    yaml_path = Path(args.yaml) if args.yaml else repo_root / "library.yaml"

    if not audit_path.exists():
        print(f"FAIL: Audit JSON not found: {audit_path}", file=sys.stderr)
        return 1

    if not yaml_path.exists():
        print(f"FAIL: library.yaml not found: {yaml_path}", file=sys.stderr)
        return 1

    with open(audit_path) as f:
        audit_data = json.load(f)

    with open(yaml_path) as f:
        library_data = yaml.safe_load(f)

    artifacts = audit_data.get("artifacts", [])
    registered_skills, registered_agents, registered_prompts = get_registered_names(library_data)

    # Filter to items that should be in library-core
    target_actions = {
        "move_to_cognovis_library_core",
        "move_to_sussdorff_library_core",
    }
    migrated = [a for a in artifacts if a.get("migration_action") in target_actions]

    missing = []
    for artifact in migrated:
        path = artifact.get("path", "")
        current_type = artifact.get("current_type", "")
        action = artifact.get("migration_action", "")

        name = extract_canonical_name(path, current_type)
        if not name:
            # Cannot determine canonical name — skip silently
            continue

        if current_type == "skill":
            if name not in registered_skills:
                missing.append(f"MISSING: skill '{name}' (from {action}) — path: {path}")
        elif current_type == "agent":
            if name not in registered_agents:
                missing.append(f"MISSING: agent '{name}' (from {action}) — path: {path}")
        elif current_type == "command":
            if name not in registered_prompts:
                missing.append(f"MISSING: prompt '{name}' (command, from {action}) — path: {path}")

    if missing:
        for line in sorted(missing):
            print(line)
        print(f"\n{len(missing)} artefact(s) not registered in library.yaml")
        return 1

    total = len(migrated)
    print(f"PASS: All {total} migrated artefacts are registered in library.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
