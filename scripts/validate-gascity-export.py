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

from lib.primitives import all_primitive_names, get_primitive, resolve_yaml_section

TARGET_SECTION_REQUIREMENTS = {
    "agent": "agent",
    "script": "script",
    "skill": "skill",
}


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
    parser.add_argument(
        "--pack",
        help=(
            "Strictly validate entries that target this Gas City pack, even when "
            "metadata.library.gascity.exportable is not true"
        ),
    )
    args = parser.parse_args()

    yaml_path = Path(args.yaml)
    try:
        data = yaml.safe_load(yaml_path.read_text()) or {}
    except OSError as exc:
        return _finish(args, "error", [f"Cannot read {yaml_path}: {exc}"])
    except yaml.YAMLError as exc:
        return _finish(args, "error", [f"Invalid YAML in {yaml_path}: {exc}"])

    errors = validate_catalog(data, target_pack=args.pack)
    status = "ok" if not errors else "error"
    return _finish(args, status, errors)


def validate_catalog(data: dict[str, Any], target_pack: str | None = None) -> list[str]:
    errors: list[str] = []
    standards = {
        entry.get("name")
        for entry in (data.get("library", {}) or {}).get("standards", []) or []
        if entry.get("name")
    }

    for section, entry in _iter_entries(data):
        name = entry.get("name", "<unnamed>")
        location = f"{section}:{name}"
        library_meta = (entry.get("metadata") or {}).get("library") or {}
        plane = library_meta.get("plane", "dev")
        if plane != "dev":
            errors.append(
                f"{location} metadata.library.plane must be 'dev'; "
                "product-plane artifacts belong in metadata.library.product_counterpart"
            )

        gascity = library_meta.get("gascity") or {}
        if gascity.get("exportable") is True:
            _validate_gascity(
                location,
                section,
                gascity,
                standards,
                errors,
                target_pack=target_pack,
            )
        elif target_pack and _gascity_targets_pack(gascity, target_pack):
            _validate_gascity(
                location,
                section,
                gascity,
                standards,
                errors,
                target_pack=target_pack,
            )

        for script in entry.get("scripts") or []:
            _validate_script_asset(location, script, errors)

        if section == "script":
            _validate_script_entry(location, entry, errors)

    return errors


def _iter_entries(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    section_labels = {
        "skill": "skill",
        "agent": "agent",
        "prompt": "prompt",
        "script": "script",
        "standard": "standard",
        "guardrail": "guardrail",
        "mcp": "mcp",
        "model-standard": "model-standard",
        "agent-base": "agent-base",
        "workflow": "workflow",
        "runtime-config": "runtime-config",
    }
    entries: list[tuple[str, dict[str, Any]]] = []
    for primitive_name in all_primitive_names():
        primitive = get_primitive(primitive_name)
        if primitive is None:
            continue
        section_label = section_labels.get(primitive.name, primitive.name)
        for entry in resolve_yaml_section(data, primitive):
            entries.append((section_label, entry))

    return entries


def _gascity_targets_pack(gascity: dict[str, Any], target_pack: str) -> bool:
    if not gascity:
        return False
    if gascity.get("pack") == target_pack:
        return True
    for projection in gascity.get("projections") or []:
        if isinstance(projection, dict) and projection.get("pack") == target_pack:
            return True
    return False


def _validate_gascity(
    location: str,
    section: str,
    gascity: dict[str, Any],
    standards: set[str],
    errors: list[str],
    target_pack: str | None = None,
) -> None:
    projections = gascity.get("projections") or []
    if projections:
        validated_projection = False
        for index, projection in enumerate(projections):
            projection_location = f"{location} projections[{index}]"
            if not isinstance(projection, dict):
                errors.append(f"{projection_location} must be an object")
                continue
            if target_pack and projection.get("pack") != target_pack:
                continue
            validated_projection = True
            _validate_projection(
                projection_location,
                section,
                projection,
                standards,
                errors,
                defaults=gascity,
            )
        if (
            validated_projection
            or not target_pack
            or gascity.get("pack") != target_pack
        ):
            return

    _validate_projection(location, section, gascity, standards, errors)


def _validate_projection(
    location: str,
    section: str,
    projection: dict[str, Any],
    standards: set[str],
    errors: list[str],
    defaults: dict[str, Any] | None = None,
) -> None:
    for field in ("target", "pack", "scope"):
        if not projection.get(field):
            errors.append(f"{location} exportable metadata missing '{field}'")

    target = projection.get("target")
    _validate_target_section(location, section, target, errors)
    session_class = projection.get("session_class") or (defaults or {}).get(
        "session_class",
        "none",
    )
    if target == "agent" and session_class not in {"polecat", "crew"}:
        errors.append(
            f"{location} target=agent must declare session_class polecat or crew"
        )
    if section == "script" and target not in {
        "script",
        "asset",
        "command",
        "doctor",
        "formula",
    }:
        errors.append(
            f"{location} script export target is not script-compatible: {target}"
        )

    target_path = projection.get("target_path")
    if target_path and (
        str(target_path).startswith("/")
        or ".." in Path(str(target_path)).parts
    ):
        errors.append(
            f"{location} target_path must be pack-relative and stay inside the pack"
        )

    missing_standards = []
    requires = projection.get("requires") or (defaults or {}).get("requires") or {}
    for standard in requires.get("standards") or []:
        if standard not in standards:
            missing_standards.append(standard)
    if missing_standards:
        errors.append(
            f"{location} references unknown Gas City export standards: "
            + ", ".join(sorted(missing_standards))
        )


def _validate_target_section(
    location: str, section: str, target: Any, errors: list[str]
) -> None:
    required_section = TARGET_SECTION_REQUIREMENTS.get(str(target))
    if required_section and section != required_section:
        errors.append(
            f"{location} target={target} is only valid for {required_section} "
            f"catalog entries, not {section}"
        )


def _validate_script_asset(
    location: str, script: dict[str, Any], errors: list[str]
) -> None:
    path = str(script.get("path", ""))
    if not path.endswith(".py"):
        errors.append(f"{location} bundled script path must end in .py: {path}")
    if script.get("language", "python") != "python":
        errors.append(f"{location} bundled scripts are Python-only: {path}")
    if script.get("role") in {"command", "doctor", "formula-step"} and not script.get(
        "entrypoint"
    ):
        errors.append(
            f"{location} script role {script.get('role')} must set entrypoint: true"
        )


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
