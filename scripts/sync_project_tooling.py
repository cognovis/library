#!/usr/bin/env python3
"""
sync_project_tooling.py — Apply project_tooling entries from library.yaml to the current project.

Reads the `project_tooling` section of cognovis-library's library.yaml and applies
each registered target to the current project directory. Called from the SessionStart
hook in place of the old hardcoded PRIME.md distribution block.

Usage:
    python3 /path/to/cognovis-library/scripts/sync_project_tooling.py [--project-root DIR]

Exit codes:
    0 — completed (with or without changes)
    1 — fatal error (library or schema not found, YAML parse failure)

See docs/project-tooling.md for full documentation.
"""

import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("[sync_project_tooling] SKIP: PyYAML not installed. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Library root discovery
# ---------------------------------------------------------------------------

_SEARCH_PATHS = [
    Path.home() / "code" / "cognovis-library",
    Path.home() / "cognovis-library",
]


def find_library_root() -> Path | None:
    """Find the cognovis-library root directory.

    Checks (in order):
    1. COGNOVIS_LIBRARY environment variable
    2. Common well-known paths

    Returns the Path if found and library.yaml exists, else None.
    """
    env_path = os.environ.get("COGNOVIS_LIBRARY")
    if env_path:
        candidate = Path(env_path)
        if (candidate / "library.yaml").exists():
            return candidate

    for candidate in _SEARCH_PATHS:
        if (candidate / "library.yaml").exists():
            return candidate

    return None


def find_project_root() -> Path:
    """Return the current working directory as the project root."""
    return Path.cwd()


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

def evaluate_condition(condition: dict[str, str], project_root: Path) -> bool:
    """Evaluate a single tooling condition dict (exactly one key).

    Supported keys:
    - dir_exists: path relative to project_root
    - file_exists: path relative to project_root
    - command_available: command name (looked up in PATH)
    - env_set: environment variable name
    """
    if len(condition) != 1:
        return False

    key, value = next(iter(condition.items()))

    if key == "dir_exists":
        return (project_root / value).is_dir()
    elif key == "file_exists":
        return (project_root / value).is_file()
    elif key == "command_available":
        return shutil.which(value) is not None
    elif key == "env_set":
        return bool(os.environ.get(value))
    else:
        # Unknown condition key — conservative: return False
        return False


def evaluate_conditions(conditions: list[dict[str, str]], project_root: Path) -> bool:
    """Return True only if ALL conditions are satisfied."""
    return all(evaluate_condition(c, project_root) for c in conditions)


# ---------------------------------------------------------------------------
# Sync strategies
# ---------------------------------------------------------------------------

def sync_file(
    entry: dict[str, Any],
    library_root: Path,
    project_root: Path,
) -> str:
    """Handle target_kind=file with overwrite_if_source_newer or overwrite_always.

    Returns: 'synced', 'skipped', or 'error:<msg>'
    """
    source_rel = entry.get("source")
    if not source_rel:
        return "error:missing source field"

    source_path = library_root / source_rel
    if not source_path.is_file():
        return f"error:source not found: {source_path}"

    target_path = project_root / entry["target_path"]
    target_path.parent.mkdir(parents=True, exist_ok=True)

    source_content = source_path.read_bytes()
    strategy = entry.get("sync_strategy", "overwrite_if_source_newer")

    if strategy == "overwrite_always":
        target_path.write_bytes(source_content)
        return "synced"

    # overwrite_if_source_newer: compare content, copy if different
    if target_path.is_file():
        existing = target_path.read_bytes()
        if existing == source_content:
            return "skipped"

    target_path.write_bytes(source_content)
    return "synced"


def sync_git_hook(
    entry: dict[str, Any],
    library_root: Path,
    project_root: Path,
) -> str:
    """Handle target_kind=git_hook.

    Writes the hook file to .git/hooks/<hook_name> and makes it executable.
    Returns: 'synced', 'skipped', or 'error:<msg>'
    """
    source_rel = entry.get("source")
    if not source_rel:
        return "error:missing source field"

    source_path = library_root / source_rel
    if not source_path.is_file():
        return f"error:source not found: {source_path}"

    target_path = project_root / entry["target_path"]
    target_path.parent.mkdir(parents=True, exist_ok=True)

    source_content = source_path.read_bytes()
    strategy = entry.get("sync_strategy", "overwrite_if_source_newer")

    if strategy != "overwrite_always" and target_path.is_file():
        existing = target_path.read_bytes()
        if existing == source_content:
            # Still ensure executable bit is set
            _ensure_executable(target_path)
            return "skipped"

    target_path.write_bytes(source_content)
    _ensure_executable(target_path)
    return "synced"


def _ensure_executable(path: Path) -> None:
    """Add executable bits to a file (owner + group + other)."""
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def sync_json_field_enforce(
    entry: dict[str, Any],
    project_root: Path,
) -> str:
    """Handle target_kind=json_field_enforce with repair_fields strategy.

    Reads the target JSON, applies 'ensure' fields (set if absent or wrong value),
    removes 'remove' fields, and writes back only if something changed.
    Returns: 'synced', 'skipped', or 'error:<msg>'
    """
    target_path = project_root / entry["target_path"]
    if not target_path.is_file():
        return "skipped"  # condition file_exists should have caught this

    fields = entry.get("fields", {})
    ensure = fields.get("ensure", {})
    remove = fields.get("remove", [])

    try:
        data = json.loads(target_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return f"error:cannot parse {target_path}: {exc}"

    changed = False

    for key, value in ensure.items():
        if data.get(key) != value:
            data[key] = value
            changed = True

    for key in remove:
        if key in data:
            del data[key]
            changed = True

    if not changed:
        return "skipped"

    try:
        target_path.write_text(json.dumps(data, indent=2) + "\n")
    except OSError as exc:
        return f"error:cannot write {target_path}: {exc}"

    return "synced"


# ---------------------------------------------------------------------------
# Entry dispatcher
# ---------------------------------------------------------------------------

def apply_entry(
    entry: dict[str, Any],
    library_root: Path,
    project_root: Path,
) -> str:
    """Apply a single project_tooling entry. Returns status string."""
    target_kind = entry.get("target_kind", "file")
    conditions = entry.get("conditions", [])

    if not evaluate_conditions(conditions, project_root):
        return "conditions-not-met"

    if target_kind == "file":
        return sync_file(entry, library_root, project_root)
    elif target_kind == "git_hook":
        return sync_git_hook(entry, library_root, project_root)
    elif target_kind == "json_field_enforce":
        return sync_json_field_enforce(entry, project_root)
    else:
        # file_section, gitignore_patch — not yet implemented
        return f"skipped:target_kind={target_kind} not yet implemented"


# ---------------------------------------------------------------------------
# Public API (also callable from tests)
# ---------------------------------------------------------------------------

def sync_entries(
    entries: list[dict[str, Any]],
    library_root: Path,
    project_root: Path,
    verbose: bool = False,
) -> dict[str, int]:
    """Apply a list of project_tooling entries. Returns summary counts.

    Args:
        entries: list of project_tooling_entry dicts (from library.yaml)
        library_root: root of cognovis-library (source files resolved from here)
        project_root: root of the project to sync into (target paths resolved from here)
        verbose: if True, print one line per entry

    Returns:
        dict with keys: synced, skipped, errors, conditions_not_met
    """
    summary: dict[str, int] = {"synced": 0, "skipped": 0, "errors": 0, "conditions_not_met": 0}

    for entry in entries:
        name = entry.get("name", "<unnamed>")
        status = apply_entry(entry, library_root, project_root)

        if status == "synced":
            summary["synced"] += 1
            if verbose:
                print(f"[sync_project_tooling] synced: {name}")
        elif status == "conditions-not-met":
            summary["conditions_not_met"] += 1
            if verbose:
                print(f"[sync_project_tooling] skipped (conditions not met): {name}")
        elif status.startswith("error:"):
            summary["errors"] += 1
            print(f"[sync_project_tooling] ERROR {name}: {status[6:]}", file=sys.stderr)
        else:
            summary["skipped"] += 1
            if verbose:
                print(f"[sync_project_tooling] skipped: {name} ({status})")

    return summary


def load_entries(library_root: Path) -> list[dict[str, Any]]:
    """Load project_tooling entries from library.yaml."""
    library_yaml = library_root / "library.yaml"
    if not library_yaml.is_file():
        raise FileNotFoundError(f"library.yaml not found: {library_yaml}")

    with library_yaml.open() as f:
        data = yaml.safe_load(f) or {}

    return data.get("project_tooling", [])


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Sync project_tooling entries from library.yaml into the current project."
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root directory (default: current working directory)",
    )
    parser.add_argument(
        "--library-root",
        default=None,
        help="cognovis-library root directory (default: auto-detected via COGNOVIS_LIBRARY env or well-known paths)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print one line per entry processed",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root) if args.project_root else find_project_root()
    library_root = Path(args.library_root) if args.library_root else find_library_root()

    if library_root is None:
        print(
            "[sync_project_tooling] SKIP: cognovis-library not found. "
            "Set COGNOVIS_LIBRARY env var or clone to ~/code/cognovis-library.",
            file=sys.stderr,
        )
        return 0  # Non-fatal: not every machine has the library checked out

    try:
        entries = load_entries(library_root)
    except FileNotFoundError as exc:
        print(f"[sync_project_tooling] FAIL: {exc}", file=sys.stderr)
        return 1
    except yaml.YAMLError as exc:
        print(f"[sync_project_tooling] FAIL: YAML parse error: {exc}", file=sys.stderr)
        return 1

    if not entries:
        if args.verbose:
            print("[sync_project_tooling] No project_tooling entries found in library.yaml")
        return 0

    summary = sync_entries(entries, library_root=library_root, project_root=project_root, verbose=args.verbose)

    if args.verbose:
        print(
            f"[sync_project_tooling] Done: "
            f"{summary['synced']} synced, "
            f"{summary['skipped']} skipped, "
            f"{summary['conditions_not_met']} conditions-not-met, "
            f"{summary['errors']} errors"
        )

    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
