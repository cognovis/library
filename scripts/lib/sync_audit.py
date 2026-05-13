"""
sync_audit.py — Sync and audit implementations for the library CLI.

sync: Reads the lockfile and re-installs every entry via the matching primitive installer.
audit: Computes content checksums for installed entries and compares against lockfile.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .errors import InstallError, LibraryError
from .lockfile import (
    compute_checksum,
    find_lockfile,
    get_entry,
    load_lockfile,
)
from .output import dry_run_result, success


def cmd_sync_impl(
    catalog: dict,
    primitive: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    harness: str = "all",
) -> dict[str, Any]:
    """Sync: re-install all entries of a given primitive from the lockfile.

    Args:
        catalog: Parsed library.yaml dict.
        primitive: Primitive type to sync ('skill', 'agent', etc.), or 'all'.
        repo_root: Project root.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.
        harness: Target harness.

    Returns:
        Operation result dict with list of synced entries.
    """
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    lock_data = load_lockfile(lockfile_path)
    installed = lock_data.get("installed", [])

    # Filter to primitive if specified (not 'all')
    if primitive and primitive not in ("all", "search"):
        entries = [e for e in installed if e.get("type") == primitive]
    else:
        entries = list(installed)

    if dry_run:
        ops = []
        for entry in entries:
            ops.append({
                "operation": "reinstall",
                "path": entry.get("install_target", ""),
                "details": f"re-install {entry.get('type', '?')}:{entry.get('name', '?')}",
            })
        return dry_run_result(
            ops,
            summary=f"Would sync {len(entries)} entries from lockfile",
        )

    synced = []
    failed = []
    for entry in entries:
        entry_name = entry.get("name", "")
        entry_type = entry.get("type", "")
        try:
            _reinstall_entry(catalog, entry, repo_root, scope, harness)
            synced.append(f"{entry_type}:{entry_name}")
        except Exception as exc:
            failed.append({"name": entry_name, "type": entry_type, "error": str(exc)})

    return success(
        data={
            "synced": synced,
            "failed": failed,
            "total": len(entries),
        },
        message=f"Synced {len(synced)}/{len(entries)} entries.",
    )


def _reinstall_entry(
    catalog: dict,
    entry: dict,
    repo_root: Path,
    scope: str,
    harness: str,
) -> None:
    """Re-install a single lockfile entry."""
    entry_name = entry.get("name", "")
    entry_type = entry.get("type", "")

    if entry_type == "skill":
        from .installers.skill import install_skill
        install_skill(catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope)
    elif entry_type == "agent":
        from .installers.agent import install_agent
        install_agent(catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope, harness=harness)
    elif entry_type == "prompt":
        from .installers.simple_file import install_simple_file
        install_simple_file(catalog=catalog, primitive_name="prompt", name=entry_name,
                           repo_root=repo_root, scope=scope, harness=harness)
    elif entry_type == "standard":
        from .installers.standard import install_standard
        install_standard(catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope)
    elif entry_type == "model-standard":
        from .installers.simple_file import install_simple_file
        install_simple_file(catalog=catalog, primitive_name="model-standard", name=entry_name,
                           repo_root=repo_root, scope=scope, harness=harness)
    elif entry_type == "golden-prompt":
        from .installers.simple_file import install_simple_file
        install_simple_file(catalog=catalog, primitive_name="golden-prompt", name=entry_name,
                           repo_root=repo_root, scope=scope, harness=harness)
    elif entry_type == "mcp":
        from .installers.mcp_installer import install_mcp
        install_mcp(catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope, harness=harness)
    elif entry_type == "guardrail":
        from .installers.guardrail_installer import install_guardrail
        install_guardrail(catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope, harness=harness)
    # Unknown types are silently skipped


def cmd_audit_impl(
    catalog: dict,
    primitive: str,
    repo_root: Path,
    scope: str = "project",
) -> dict[str, Any]:
    """Audit: compute checksums for installed entries and compare against lockfile.

    Returns a result with status 'clean' or 'drift'.
    Schema: {"status": "clean"|"drift", "entries": [...]}

    Args:
        catalog: Parsed library.yaml dict.
        primitive: Primitive type to audit, or all if 'all'.
        repo_root: Project root.
        scope: 'project' or 'global'.

    Returns:
        Audit result dict with stable schema.
    """
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    lock_data = load_lockfile(lockfile_path)
    installed = lock_data.get("installed", [])

    # Filter to primitive
    if primitive and primitive not in ("all", "search"):
        entries = [e for e in installed if e.get("type") == primitive]
    else:
        entries = list(installed)

    if not entries:
        return {
            "status": "clean",
            "entries": [],
        }

    audit_entries = []
    any_drift = False

    for entry in entries:
        entry_name = entry.get("name", "")
        expected_sha = entry.get("checksum_sha256", "")
        cache_path_str = entry.get("cache_path", "").rstrip("/")
        install_target_str = entry.get("install_target", "")

        actual_sha = ""
        drift = False

        # Try to compute actual checksum from install target or cache
        for path_str in [install_target_str, cache_path_str]:
            if not path_str:
                continue
            p = Path(path_str)
            if p.is_symlink():
                p = p.resolve()
            if p.is_file():
                try:
                    actual_sha = compute_checksum(p)
                except OSError:
                    actual_sha = ""
                break
            elif p.is_dir():
                # For directories, compute hash of primary artifact
                primary = _find_primary_artifact(p, entry_name)
                if primary and primary.exists():
                    try:
                        actual_sha = compute_checksum(primary)
                    except OSError:
                        actual_sha = ""
                break

        if expected_sha and actual_sha and expected_sha != actual_sha:
            drift = True
            any_drift = True

        audit_entries.append({
            "name": entry_name,
            "primitive": entry.get("type", ""),
            "expected_sha": expected_sha,
            "actual_sha": actual_sha,
            "drift": drift,
        })

    return {
        "status": "drift" if any_drift else "clean",
        "entries": audit_entries,
    }


def _find_primary_artifact(cache_dir: Path, name: str) -> Path | None:
    """Find the primary artifact in a cache directory."""
    candidates = [
        cache_dir / f"{name}.md",
        cache_dir / "SKILL.md",
        cache_dir / "STANDARD.md",
        cache_dir / "agent.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    md_files = list(cache_dir.rglob("*.md"))
    return md_files[0] if md_files else None
