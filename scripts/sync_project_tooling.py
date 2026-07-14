#!/usr/bin/env python3
"""
sync_project_tooling.py — Apply project_tooling entries from library.yaml to the current project.

Reads the `project_tooling` section of cognovis-library's library.yaml and applies
each registered target to the current project directory. Called from the SessionStart
hook in place of the old hardcoded PRIME.md distribution block.

Usage:
    python3 /path/to/cognovis-library/scripts/sync_project_tooling.py [--project-root DIR] [--profile consumer|marketplace]

Exit codes:
    0 — completed (with or without changes)
    1 — fatal error (library or schema not found, YAML parse failure)

See docs/project-tooling.md for full documentation.
"""

import json
import os
import shutil
import stat
import subprocess
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

_CHAIN_EXISTING_MARKER = b"# managed-by: cognovis-library chain_existing (CL-rkww)"


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


def resolve_hooks_dir(project_root: Path) -> Path | None:
    """Resolve the effective git hooks directory for project_root.

    `git rev-parse --git-path hooks` honors core.hooksPath and worktree-specific
    gitdir layouts. Returns the resolved hooks Path, or None if Git cannot
    resolve an effective hooks directory for project_root.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )
        if result.returncode == 0:
            hooks_dir = result.stdout.strip()
            if not hooks_dir:
                return None
            hooks_path = Path(hooks_dir)
            if not hooks_path.is_absolute():
                hooks_path = (project_root / hooks_path).resolve()
            return hooks_path
    except (OSError, subprocess.SubprocessError):
        pass
    return None


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
        print(
            f"[sync_project_tooling] WARN: unknown condition key '{key}' — skipping entry",
            file=sys.stderr,
        )
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

    Writes the hook file to the effective git hooks directory and makes it executable.
    When chain_existing is true, a non-managed hook at the target path is moved
    aside once to <hook_name>.local before installing the managed wrapper.
    Returns: 'synced', 'skipped', or 'error:<msg>'
    """
    source_rel = entry.get("source")
    if not source_rel:
        return "error:missing source field"

    source_path = library_root / source_rel
    if not source_path.is_file():
        return f"error:source not found: {source_path}"

    # Resolve the real hooks directory, handling worktrees where .git is a file.
    hooks_dir = resolve_hooks_dir(project_root)
    if hooks_dir is None:
        return "error:cannot resolve effective git hooks directory"

    # Derive hook filename from the target_path basename and place it in hooks_dir.
    hook_name = entry.get("hook_name") or Path(entry["target_path"]).name
    target_path = hooks_dir / hook_name

    source_content = source_path.read_bytes()
    strategy = entry.get("sync_strategy", "overwrite_if_source_newer")
    chain_existing = bool(entry.get("chain_existing", False))

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"error:cannot create hooks directory {target_path.parent}: {exc}"

    if not target_path.parent.is_dir():
        return f"error:hooks path is not a directory: {target_path.parent}"

    if chain_existing:
        if _CHAIN_EXISTING_MARKER not in source_content:
            return "error:chain_existing hook source missing managed marker"
        status = _prepare_chained_hook_target(target_path, hook_name)
        if status.startswith("error:"):
            return status

    if strategy != "overwrite_always" and (target_path.exists() or target_path.is_symlink()):
        try:
            existing = target_path.read_bytes()
        except OSError as exc:
            return f"error:cannot read existing hook {target_path}: {exc}"
        if existing == source_content:
            try:
                _ensure_executable(target_path)
            except OSError as exc:
                return f"error:cannot chmod hook {target_path}: {exc}"
            return "skipped"

    try:
        target_path.write_bytes(source_content)
        _ensure_executable(target_path)
    except OSError as exc:
        return f"error:cannot write hook {target_path}: {exc}"

    return "synced"


def _prepare_chained_hook_target(target_path: Path, hook_name: str) -> str:
    """Move a foreign hook aside once so a managed wrapper can chain it."""
    if not (target_path.exists() or target_path.is_symlink()):
        return "skipped"

    try:
        existing = target_path.read_bytes()
    except OSError as exc:
        return f"error:cannot read existing hook {target_path}: {exc}"

    if _CHAIN_EXISTING_MARKER in existing:
        return "skipped"

    sidecar_path = target_path.with_name(f"{hook_name}.local")
    if sidecar_path.exists() or sidecar_path.is_symlink():
        return (
            "error:foreign hook exists at target and preserved sidecar already exists: "
            f"{target_path} -> {sidecar_path}"
        )

    try:
        target_path.rename(sidecar_path)
    except OSError as exc:
        return f"error:cannot preserve existing hook {target_path}: {exc}"

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


def sync_gitignore_patch(
    entry: dict[str, Any],
    project_root: Path,
) -> str:
    """Handle target_kind=gitignore_patch.

    The patch is intentionally simple and idempotent: remove exact lines listed
    in fields.remove_lines, then append exact lines from fields.ensure_lines if
    missing. This supports the consumer/marketplace .agents gitignore profile
    without owning the user's whole .gitignore file.
    """
    target_path = project_root / entry["target_path"]
    fields = entry.get("fields", {})
    remove_lines = set(fields.get("remove_lines", []) or [])
    ensure_lines = list(fields.get("ensure_lines", []) or [])

    if not remove_lines and not ensure_lines:
        return "skipped"

    if target_path.exists():
        original_lines = target_path.read_text().splitlines()
    else:
        original_lines = []

    lines = [line for line in original_lines if line not in remove_lines]

    for line in ensure_lines:
        if line not in lines:
            lines.append(line)

    if lines == original_lines:
        return "skipped"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(lines).rstrip() + "\n")
    return "synced"


# ---------------------------------------------------------------------------
# Entry dispatcher
# ---------------------------------------------------------------------------

def apply_entry(
    entry: dict[str, Any],
    library_root: Path,
    project_root: Path,
    profile: str = "consumer",
) -> str:
    """Apply a single project_tooling entry. Returns status string."""
    target_kind = entry.get("target_kind", "file")
    conditions = entry.get("conditions", [])
    profiles = entry.get("profiles")

    if profiles and profile not in profiles:
        return "profile-not-applicable"

    if not evaluate_conditions(conditions, project_root):
        return "conditions-not-met"

    if target_kind == "file":
        return sync_file(entry, library_root, project_root)
    elif target_kind == "git_hook":
        return sync_git_hook(entry, library_root, project_root)
    elif target_kind == "json_field_enforce":
        return sync_json_field_enforce(entry, project_root)
    elif target_kind == "gitignore_patch":
        return sync_gitignore_patch(entry, project_root)
    else:
        # file_section — not yet implemented
        entry_name = entry.get("name", "<unnamed>")
        print(
            f"[sync_project_tooling] WARN: target_kind='{target_kind}' not yet implemented "
            f"(entry '{entry_name}'). Registered but no-op.",
            file=sys.stderr,
        )
        return "skipped:not_implemented"


# ---------------------------------------------------------------------------
# Public API (also callable from tests)
# ---------------------------------------------------------------------------

def sync_entries(
    entries: list[dict[str, Any]],
    library_root: Path,
    project_root: Path,
    verbose: bool = False,
    profile: str = "consumer",
) -> dict[str, int]:
    """Apply a list of project_tooling entries. Returns summary counts.

    Args:
        entries: list of project_tooling_entry dicts (from library.yaml)
        library_root: root of cognovis-library (source files resolved from here)
        project_root: root of the project to sync into (target paths resolved from here)
        verbose: if True, print one line per entry
        profile: project profile, either 'consumer' or 'marketplace'

    Returns:
        dict with keys: synced, skipped, errors, conditions_not_met
    """
    summary: dict[str, int] = {
        "synced": 0,
        "skipped": 0,
        "errors": 0,
        "conditions_not_met": 0,
        "profile_skipped": 0,
    }

    for entry in entries:
        name = entry.get("name", "<unnamed>")
        status = apply_entry(entry, library_root, project_root, profile=profile)

        if status == "synced":
            summary["synced"] += 1
            if verbose:
                print(f"[sync_project_tooling] synced: {name}")
        elif status == "conditions-not-met":
            summary["conditions_not_met"] += 1
            if verbose:
                print(f"[sync_project_tooling] skipped (conditions not met): {name}")
        elif status == "profile-not-applicable":
            summary["profile_skipped"] += 1
            if verbose:
                print(f"[sync_project_tooling] skipped (profile {profile}): {name}")
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
    parser.add_argument(
        "--profile",
        choices=["consumer", "marketplace"],
        default="consumer",
        help="Project profile for profile-scoped tooling entries (default: consumer)",
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

    summary = sync_entries(
        entries,
        library_root=library_root,
        project_root=project_root,
        verbose=args.verbose,
        profile=args.profile,
    )

    if args.verbose:
        print(
            f"[sync_project_tooling] Done: "
            f"{summary['synced']} synced, "
            f"{summary['skipped']} skipped, "
            f"{summary['conditions_not_met']} conditions-not-met, "
            f"{summary['profile_skipped']} profile-skipped, "
            f"{summary['errors']} errors"
        )

    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
