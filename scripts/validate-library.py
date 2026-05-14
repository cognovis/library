#!/usr/bin/env python3
"""
validate-library.py — Validate library.yaml against library.schema.json

Usage:
    python3 scripts/validate-library.py [--yaml PATH] [--schema PATH]

Exit codes:
    0 — PASS: library.yaml is valid
    1 — FAIL: validation errors found or file not found
"""

import argparse
import json
import re
import sys
from pathlib import Path

from lib.primitives import all_primitive_names, get_primitive, resolve_yaml_section

try:
    import yaml
except ImportError:
    print("FAIL: PyYAML is not installed. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(1)

try:
    import jsonschema
    from jsonschema import validate, ValidationError, SchemaError
except ImportError:
    print("FAIL: jsonschema is not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(1)


def find_repo_root() -> Path:
    """Walk up from this script to find the repo root (contains library.yaml)."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "library.yaml").exists():
            return current
        current = current.parent
    # Fallback: try cwd
    cwd = Path.cwd()
    if (cwd / "library.yaml").exists():
        return cwd
    return Path(__file__).resolve().parent.parent


_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9-]*$')


def _validate_agentskills_rules(data: dict) -> list:
    """Enforce agentskills.io name/description constraints on all catalog entries.

    Rules (apply to skills, agents, prompts, standards, scripts):
    - name: max 64 chars
    - name: must match [a-z][a-z0-9-]* (lowercase letters, digits, hyphens only)
    - name: must not end with hyphen
    - name: must not contain consecutive hyphens (--)
    - description: max 1024 chars

    Returns a list of formatted error strings.
    """
    errors = []
    for primitive_name in all_primitive_names():
        primitive = get_primitive(primitive_name)
        if primitive is None:
            continue
        for i, entry in enumerate(resolve_yaml_section(data, primitive)):
            name = entry.get('name', f'<entry {i}>')
            desc = entry.get('description', '')

            # If name is missing or not a non-empty string, skip agentskills checks
            # to avoid confusing errors from the placeholder value.
            if not isinstance(name, str) or not name or name.startswith('<entry '):
                continue

            prefix = f"  [{primitive.yaml_section}[{i}] '{name}']"

            if len(name) > 64:
                errors.append(f"{prefix} name exceeds 64 chars (got {len(name)})")

            if not _NAME_PATTERN.match(name):
                errors.append(
                    f"{prefix} name must match [a-z][a-z0-9-]* "
                    "(lowercase letters, digits, hyphens only)"
                )

            if name.endswith('-'):
                errors.append(f"{prefix} name must not have a trailing hyphen")

            if '--' in name:
                errors.append(f"{prefix} name must not contain consecutive hyphens (--)")

            if len(desc) > 1024:
                errors.append(
                    f"{prefix} description exceeds 1024 chars (got {len(desc)})"
                )

    return errors


def main() -> int:
    repo_root = find_repo_root()

    parser = argparse.ArgumentParser(
        description="Validate library.yaml against library.schema.json"
    )
    parser.add_argument(
        "--yaml",
        default=str(repo_root / "library.yaml"),
        help="Path to library.yaml (default: <repo-root>/library.yaml)",
    )
    parser.add_argument(
        "--schema",
        default=str(repo_root / "docs" / "schema" / "library.schema.json"),
        help="Path to library.schema.json (default: <repo-root>/docs/schema/library.schema.json)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output except PASS/FAIL summary",
    )
    args = parser.parse_args()

    yaml_path = Path(args.yaml)
    schema_path = Path(args.schema)

    # --- Load schema ---
    if not schema_path.exists():
        print(f"FAIL: Schema file not found: {schema_path}", file=sys.stderr)
        return 1

    try:
        with schema_path.open() as f:
            schema = json.load(f)
    except json.JSONDecodeError as e:
        print(f"FAIL: Schema JSON is invalid: {e}", file=sys.stderr)
        return 1

    # --- Load library.yaml ---
    if not yaml_path.exists():
        print(f"FAIL: library.yaml not found: {yaml_path}", file=sys.stderr)
        return 1

    try:
        with yaml_path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"FAIL: library.yaml is not valid YAML: {e}", file=sys.stderr)
        return 1

    if data is None:
        data = {}

    # --- Validate ---
    try:
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    except SchemaError as e:
        print(f"FAIL: Schema itself is invalid: {e.message}", file=sys.stderr)
        return 1

    if errors:
        if not args.quiet:
            print(f"FAIL: {yaml_path} has {len(errors)} validation error(s):\n")
            for err in errors:
                path = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
                print(f"  [{path}] {err.message}")
        else:
            print(f"FAIL: {len(errors)} validation error(s) in {yaml_path}")
        return 1

    # Additional semantic check: each catalog entry must have a resolvable source
    semantic_errors = []
    for section in ('skill', 'agent', 'prompt', 'script'):
        primitive = get_primitive(section)
        if primitive is None:
            continue
        for i, entry in enumerate(resolve_yaml_section(data, primitive)):
            name = entry.get('name', f'<entry {i}>')
            has_source = bool(entry.get('source'))
            has_sources_map = bool(entry.get('sources'))  # per-harness map (CL-l0c)
            has_marketplace_ref = bool(entry.get('from_marketplace') and entry.get('repo') and entry.get('path'))
            if not has_source and not has_sources_map and not has_marketplace_ref:
                semantic_errors.append(
                    f"  [{primitive.yaml_section}[{i}] '{name}'] Entry has no resolvable source: "
                    "provide either 'source' or 'from_marketplace + repo + path'"
                )
            if section == 'script':
                source = entry.get('source') or ''
                entrypoint = entry.get('entrypoint') or source
                if entry.get('language', 'python') != 'python':
                    semantic_errors.append(
                        f"  [{primitive.yaml_section}[{i}] '{name}'] Scripts are Python-only: "
                        "set language: python"
                    )
                if entrypoint and not str(entrypoint).endswith('.py'):
                    semantic_errors.append(
                        f"  [{primitive.yaml_section}[{i}] '{name}'] Script entrypoint/source must end in .py"
                    )
    if semantic_errors:
        if not args.quiet:
            print(f"FAIL: {yaml_path} has {len(semantic_errors)} semantic error(s):\n")
            for err in semantic_errors:
                print(err)
        else:
            print(f"FAIL: {len(semantic_errors)} semantic error(s) in {yaml_path}")
        return 1

    agentskills_errors = _validate_agentskills_rules(data)
    if agentskills_errors:
        if not args.quiet:
            print(f"FAIL: {yaml_path} has {len(agentskills_errors)} agentskills rule violation(s):\n")
            for err in agentskills_errors:
                print(err)
        else:
            print(f"FAIL: {len(agentskills_errors)} agentskills rule violation(s) in {yaml_path}")
        return 1

    if not args.quiet:
        print(f"PASS: {yaml_path} is valid against {schema_path}")
    else:
        print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
