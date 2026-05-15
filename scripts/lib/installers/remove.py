"""
installers/remove.py — Skill and standard remove logic.

Implements `skill remove` and `standard remove` which were stubbed in CL-0bl.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..catalog import lookup_entry
from ..errors import InstallError
from ..lockfile import (
    find_lockfile,
    get_entry,
    load_lockfile,
    remove_entry,
    save_lockfile,
)
from ..output import dry_run_result, success
from ..paths import resolve_install_paths
from ..primitives import get_primitive


def remove_skill(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove an installed skill.

    Removes:
    - Canonical symlink (.agents/skills/<name>/ or ~/.agents/skills/<name>/)
    - Claude bridge symlink (.claude/skills/<name>/ or ~/.claude/skills/<name>/)
    - Lockfile entry

    Args:
        catalog: Parsed library.yaml dict.
        name: Skill name.
        repo_root: Project root.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.

    Returns:
        Operation result dict.
    """
    prim = get_primitive("skill")
    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]
    bridge_base = install_paths["bridge"]

    if canonical_base is None:
        raise InstallError(f"Cannot determine install path for skill '{name}' (scope={scope}).")

    canonical_dir = canonical_base / name
    bridge_dir = (bridge_base / name) if bridge_base else None
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))

    if dry_run:
        ops = []
        if canonical_dir.exists() or canonical_dir.is_symlink():
            ops.append({"operation": "delete", "path": str(canonical_dir), "details": "remove canonical install"})
        if bridge_dir and (bridge_dir.exists() or bridge_dir.is_symlink()):
            ops.append({"operation": "delete", "path": str(bridge_dir), "details": f"remove Claude bridge symlink"})
        ops.append({"operation": "remove_lockfile_entry", "path": str(lockfile_path), "details": f"remove '{name}'"})
        return dry_run_result(ops, summary=f"Would remove skill '{name}'")

    removed_files = []

    def _remove_path(p: Path) -> None:
        if p.is_symlink():
            p.unlink()
            removed_files.append(str(p))
        elif p.is_dir():
            shutil.rmtree(str(p))
            removed_files.append(str(p))
        elif p.exists():
            p.unlink()
            removed_files.append(str(p))

    _remove_path(canonical_dir)
    if bridge_dir:
        _remove_path(bridge_dir)

    lock_data = load_lockfile(lockfile_path)
    remove_entry(lock_data, name, primitive_type="skill")
    save_lockfile(lockfile_path, lock_data)

    return success(
        data={"name": name, "removed_files": removed_files},
        message=f"Skill '{name}' removed.",
    )


def remove_standard(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    tool_root: Path | None = None,
) -> dict[str, Any]:
    """Remove an installed standard.

    Removes:
    - Canonical install directory (.agents/standards/<name>/ or ~/.agents/standards/<name>/)
    - Lockfile entry

    Args:
        catalog: Parsed library.yaml dict.
        name: Standard name.
        repo_root: Project root.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.
        tool_root: Repository root that provides helper scripts.

    Returns:
        Operation result dict.
    """
    prim = get_primitive("standard")
    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]

    if canonical_base is None:
        raise InstallError(f"Cannot determine install path for standard '{name}' (scope={scope}).")

    canonical_dir = canonical_base / name
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))

    if dry_run:
        ops = []
        if canonical_dir.exists() or canonical_dir.is_symlink():
            ops.append({"operation": "delete", "path": str(canonical_dir), "details": "remove canonical install"})
        ops.append({"operation": "remove_lockfile_entry", "path": str(lockfile_path), "details": f"remove '{name}'"})
        return dry_run_result(ops, summary=f"Would remove standard '{name}'")

    removed_files = []

    if canonical_dir.is_symlink():
        canonical_dir.unlink()
        removed_files.append(str(canonical_dir))
    elif canonical_dir.is_dir():
        shutil.rmtree(str(canonical_dir))
        removed_files.append(str(canonical_dir))
    elif canonical_dir.exists():
        canonical_dir.unlink()
        removed_files.append(str(canonical_dir))

    lock_data = load_lockfile(lockfile_path)
    remove_entry(lock_data, name, primitive_type="standard")
    save_lockfile(lockfile_path, lock_data)

    return success(
        data={
            "name": name,
            "removed_files": removed_files,
        },
        message=f"Standard '{name}' removed.",
    )
