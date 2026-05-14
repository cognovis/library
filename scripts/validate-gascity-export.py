#!/usr/bin/env python3
"""
Validate Library catalog entries that declare Gas City pack export metadata.

This is a pre-export contract check. It does not generate PackV2 files; it
ensures exportable entries contain enough structured metadata for a later
`library gascity export` implementation to avoid guessing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("FAIL: PyYAML is not installed. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(1)


def find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "library.yaml").exists():
            return current
        current = current.parent
    cwd = Path.cwd()
    if (cwd / "library.yaml").exists():
        return cwd
    return Path(__file__).resolve().parent.parent


def main() -> int:
    repo_root = find_repo_root()
    parser = argparse.ArgumentParser(
        description="Validate metadata.library.gascity export declarations."
    )
    parser.add_argument(
        "--yaml",
        default=str(repo_root / "library.yaml"),
        help="Path to library.yaml",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON envelope")
    parser.add_argument("--quiet", action="store_true", help="Only print PASS/FAIL")
    args = parser.parse_args()

    yaml_path = Path(args.yaml)
    try:
        data = yaml.safe_load(yaml_path.read_text()) or {}
    except OSError as exc:
        return _finish(args, "error", [f"Cannot read {yaml_path}: {exc}"])
    except yaml.YAMLError as exc:
        return _finish(args, "error", [f"Invalid YAML in {yaml_path}: {exc}"])

    errors = validate_catalog(data)
    status = "ok" if not errors else "error"
    return _finish(args, status, errors)


def validate_catalog(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    standards = {
        entry.get("name")
        for entry in (data.get("library", {}) or {}).get("standards", []) or []
        if entry.get("name")
    }

    for section, entry in _iter_entries(data):
        name = entry.get("name", "<unnamed>")
        location = f"{section}:{name}"
        gascity = (
            ((entry.get("metadata") or {}).get("library") or {}).get("gascity")
            or {}
        )
        if gascity.get("exportable") is True:
            _validate_exportable(location, section, gascity, standards, errors)

        for script in entry.get("scripts") or []:
            _validate_script_asset(location, script, errors)

        if section == "script":
            _validate_script_entry(location, entry, errors)

    return errors


def _iter_entries(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    library = data.get("library", {}) or {}
    nested_sections = [
        "skills",
        "agents",
        "prompts",
        "scripts",
        "standards",
    ]
    entries: list[tuple[str, dict[str, Any]]] = []
    for section in nested_sections:
        for entry in library.get(section, []) or []:
            entries.append((section[:-1] if section.endswith("s") else section, entry))

    top_level = [
        ("guardrail", "guardrails"),
        ("mcp", "mcp_servers"),
        ("model-standard", "model_standards"),
        ("golden-prompt", "golden_prompts"),
    ]
    for primitive, key in top_level:
        for entry in data.get(key, []) or []:
            entries.append((primitive, entry))

    return entries


def _validate_exportable(
    location: str,
    section: str,
    gascity: dict[str, Any],
    standards: set[str],
    errors: list[str],
) -> None:
    for field in ("target", "pack", "scope"):
        if not gascity.get(field):
            errors.append(f"{location} exportable metadata missing '{field}'")

    target = gascity.get("target")
    session_class = gascity.get("session_class", "none")
    if target == "agent" and session_class not in {"polecat", "crew"}:
        errors.append(
            f"{location} target=agent must declare session_class polecat or crew"
        )
    if section == "script" and target not in {"script", "asset", "command", "doctor", "formula"}:
        errors.append(f"{location} script export target is not script-compatible: {target}")

    target_path = gascity.get("target_path")
    if target_path and (str(target_path).startswith("/") or ".." in Path(str(target_path)).parts):
        errors.append(f"{location} target_path must be pack-relative and stay inside the pack")

    missing_standards = []
    requires = gascity.get("requires") or {}
    for standard in requires.get("standards") or []:
        if standard not in standards:
            missing_standards.append(standard)
    if missing_standards:
        errors.append(
            f"{location} references unknown Gas City export standards: "
            + ", ".join(sorted(missing_standards))
        )


def _validate_script_asset(
    location: str, script: dict[str, Any], errors: list[str]
) -> None:
    path = str(script.get("path", ""))
    if not path.endswith(".py"):
        errors.append(f"{location} bundled script path must end in .py: {path}")
    if script.get("language", "python") != "python":
        errors.append(f"{location} bundled scripts are Python-only: {path}")
    if script.get("role") in {"command", "doctor", "formula-step"} and not script.get("entrypoint"):
        errors.append(f"{location} script role {script.get('role')} must set entrypoint: true")


def _validate_script_entry(
    location: str, entry: dict[str, Any], errors: list[str]
) -> None:
    source = str(entry.get("source") or "")
    entrypoint = str(entry.get("entrypoint") or source)
    if entry.get("language", "python") != "python":
        errors.append(f"{location} must use language: python")
    if entrypoint and not entrypoint.endswith(".py"):
        errors.append(f"{location} entrypoint/source must end in .py")


def _finish(args: argparse.Namespace, status: str, errors: list[str]) -> int:
    code = 0 if status == "ok" else 1
    if args.json:
        print(
            json.dumps(
                {
                    "status": status,
                    "summary": "Gas City export metadata valid" if code == 0 else "Gas City export metadata invalid",
                    "data": {"error_count": len(errors)},
                    "errors": errors,
                    "next_steps": [] if code == 0 else ["Fix the reported metadata before exporting packs."],
                },
                indent=2,
            )
        )
    elif args.quiet:
        print("PASS" if code == 0 else f"FAIL: {len(errors)} Gas City export metadata error(s)")
    elif code == 0:
        print("PASS: Gas City export metadata is valid")
    else:
        print(f"FAIL: {len(errors)} Gas City export metadata error(s):")
        for error in errors:
            print(f"  - {error}")
    return code


if __name__ == "__main__":
    sys.exit(main())
