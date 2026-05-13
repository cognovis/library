"""
cache.py — Layer-B cache path calculation and materialization.

Per ADR-0003, library items are deployed through three layers:
  Layer A — Source: GitHub URL or local path (catalog entry `source:`)
  Layer B — Cache:  ~/.local/share/library/<type>/<marketplace>/<name>@<14hex>/
  Layer C — Harness: .agents/skills/<name>/ (symlink -> Layer B)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional


# XDG-compliant base for the Layer-B cache
_LIBRARY_HOME = Path(
    os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
) / "library"


def compute_cache_path(
    primitive_type: str,
    marketplace: str,
    name: str,
    source_commit: str,
) -> Path:
    """Compute the Layer-B cache path for a library item.

    Format: ~/.local/share/library/<type>/<marketplace>/<name>@<14hex>/

    Args:
        primitive_type: 'skill', 'agent', 'prompt', 'standard', etc.
        marketplace: Marketplace identifier (e.g. 'cognovis-core', 'local').
        name: Item name.
        source_commit: Full or short commit SHA. 'local' uses a fixed tag.

    Returns:
        Absolute Path to the Layer-B cache directory.
    """
    if source_commit in ("local", "") or len(source_commit) < 7:
        commit_tag = source_commit or "local"
    else:
        commit_tag = source_commit[:14]

    return _LIBRARY_HOME / f"{primitive_type}s" / marketplace / f"{name}@{commit_tag}"


def materialize_cache(
    source_dir: Path,
    cache_path: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Copy source_dir into cache_path (idempotent: skip if already present).

    Args:
        source_dir: Directory to copy from (resolved from source).
        cache_path: Target Layer-B cache directory.
        overwrite: If True, re-copy even if cache_path already exists.

    Returns:
        The cache_path.
    """
    if cache_path.exists() and not overwrite:
        return cache_path

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        shutil.rmtree(str(cache_path))
    shutil.copytree(str(source_dir), str(cache_path))
    return cache_path


def create_harness_symlink(
    install_target: Path,
    cache_path: Path,
    *,
    dry_run: bool = False,
) -> str:
    """Create (or replace) a Layer-C harness symlink pointing at the Layer-B cache.

    If install_target is a real directory (not a symlink), it is removed first.
    The parent directory is created if needed.

    Args:
        install_target: Layer-C harness path (e.g. .agents/skills/dolt/).
        cache_path: Layer-B cache path (absolute).
        dry_run: If True, return the planned operation without mutating.

    Returns:
        Human-readable description of the operation performed/planned.
    """
    op = f"symlink {install_target} -> {cache_path}"
    if dry_run:
        return f"[dry-run] would create {op}"

    install_target.parent.mkdir(parents=True, exist_ok=True)

    if install_target.is_symlink():
        install_target.unlink()
    elif install_target.is_dir():
        shutil.rmtree(str(install_target))
    elif install_target.exists():
        install_target.unlink()

    install_target.symlink_to(cache_path)
    return f"created {op}"


def plan_cache_writes(
    primitive_type: str,
    marketplace: str,
    name: str,
    source_commit: str,
    install_target: Path,
    bridge_path: Optional[Path],
    cache_base: Optional[Path] = None,
) -> list[dict]:
    """Return a list of planned write operations without mutating anything.

    Used by --dry-run mode.

    Returns:
        List of operation dicts with keys: operation, path, details.
    """
    cache_path = compute_cache_path(primitive_type, marketplace, name, source_commit)
    if cache_base is not None:
        # Override for tests
        cache_path = cache_base / f"{name}@{source_commit[:14] if len(source_commit) >= 14 else source_commit}"

    ops = [
        {
            "operation": "materialize_cache",
            "path": str(cache_path),
            "details": f"copy source -> Layer-B cache at {cache_path}",
        },
        {
            "operation": "create_symlink",
            "path": str(install_target),
            "target": str(cache_path),
            "details": f"Layer-C symlink {install_target} -> {cache_path}",
        },
    ]

    if bridge_path:
        ops.append(
            {
                "operation": "create_bridge_symlink",
                "path": str(bridge_path),
                "target": str(cache_path),
                "details": f"Claude bridge symlink {bridge_path} -> {cache_path}",
            }
        )

    return ops
