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
import sys
from pathlib import Path

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

    if not args.quiet:
        print(f"PASS: {yaml_path} is valid against {schema_path}")
    else:
        print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
