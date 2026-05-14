"""
cache.py — Layer-B cache path calculation and materialization.

Per ADR-0003, library items are deployed through three layers:
  Layer A — Source: GitHub URL or local path (catalog entry `source:`)
  Layer B — Cache:  ~/.local/share/library/<type>/<marketplace>/<name>@<14hex>/
  Layer C — Harness: .agents/skills/<name>/ (vendored copy by default)
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


def materialize_vendor_copy(
    source_path: Path,
    install_target: Path,
    *,
    dry_run: bool = False,
) -> str:
    """Copy a cache path into a harness install target.

    Directories are copied recursively and files are copied as single files. Any
    existing target is replaced first, whether it is a symlink, file, or
    directory.
    """
    op = f"vendor copy {source_path} -> {install_target}"
    if dry_run:
        return f"[dry-run] would create {op}"

    install_target.parent.mkdir(parents=True, exist_ok=True)

    if install_target.is_symlink():
        install_target.unlink()
    elif install_target.is_dir():
        shutil.rmtree(str(install_target))
    elif install_target.exists():
        install_target.unlink()

    if source_path.is_dir():
        shutil.copytree(str(source_path), str(install_target))
    else:
        shutil.copy2(str(source_path), str(install_target))

    return f"created {op}"


def materialize_install_target(
    install_target: Path,
    cache_path: Path,
    *,
    install_mode: str = "vendor",
    dry_run: bool = False,
) -> str:
    """Materialize a cache path into Layer C using vendor or symlink mode."""
    if install_mode == "vendor":
        return materialize_vendor_copy(cache_path, install_target, dry_run=dry_run)
    if install_mode == "symlink":
        return create_harness_symlink(install_target, cache_path, dry_run=dry_run)
    raise ValueError(f"Unknown install_mode: {install_mode}")


def plan_cache_writes(
    primitive_type: str,
    marketplace: str,
    name: str,
    source_commit: str,
    install_target: Path,
    bridge_path: Optional[Path],
    cache_base: Optional[Path] = None,
    install_mode: str = "vendor",
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

    install_operation = "vendor_copy" if install_mode == "vendor" else "create_symlink"
    install_details = (
        f"Layer-C vendored copy {install_target} <- {cache_path}"
        if install_mode == "vendor"
        else f"Layer-C symlink {install_target} -> {cache_path}"
    )

    ops = [
        {
            "operation": "materialize_cache",
            "path": str(cache_path),
            "details": f"copy source -> Layer-B cache at {cache_path}",
        },
        {
            "operation": install_operation,
            "path": str(install_target),
            "target": str(cache_path),
            "details": install_details,
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
