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
    compute_directory_hash,
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
            reinstall_entry(catalog, entry, repo_root, scope, harness)
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


def reinstall_entry(
    catalog: dict,
    entry: dict,
    repo_root: Path,
    scope: str,
    harness: str,
) -> None:
    """Re-install a single lockfile entry."""
    entry_name = entry.get("name", "")
    entry_type = entry.get("type", "")
    install_mode = entry.get("install_mode", "vendor")

    if entry_type == "skill":
        from .installers.skill import install_skill
        install_skill(
            catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope, install_mode=install_mode
        )
    elif entry_type == "agent":
        from .installers.agent import install_agent
        install_agent(catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope, harness=harness)
    elif entry_type == "prompt":
        from .installers.simple_file import install_simple_file
        install_simple_file(catalog=catalog, primitive_name="prompt", name=entry_name,
                           repo_root=repo_root, scope=scope, harness=harness, install_mode=install_mode)
    elif entry_type == "standard":
        from .installers.standard import install_standard
        install_standard(
            catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope, install_mode=install_mode
        )
    elif entry_type == "model-standard":
        from .installers.simple_file import install_simple_file
        install_simple_file(catalog=catalog, primitive_name="model-standard", name=entry_name,
                           repo_root=repo_root, scope=scope, harness=harness, install_mode=install_mode)
    elif entry_type == "golden-prompt":
        from .installers.simple_file import install_simple_file
        install_simple_file(catalog=catalog, primitive_name="golden-prompt", name=entry_name,
                           repo_root=repo_root, scope=scope, harness=harness, install_mode=install_mode)
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
    drift_only: bool = False,
) -> dict[str, Any]:
    """Audit: compute checksums for installed entries and compare against lockfile.

    Returns a result with status 'clean' or 'drift'.
    Schema: {"status": "clean"|"drift", "entries": [...]}

    Each entry has a "status" field:
      - "drift": checksum mismatch (directory or file, depending on checksum_type)
      - "clean": checksums match
      - "unknown": entry without checksum_type, or path not found

    With drift_only=True, only entries with status="drift" are included in output.

    Exit codes (returned as metadata for the CLI layer):
      - 0: all clean (or no entries)
      - 2: drift detected
      - 1: error

    Args:
        catalog: Parsed library.yaml dict.
        primitive: Primitive type to audit, or all if 'all'.
        repo_root: Project root.
        scope: 'project' or 'global'.
        drift_only: If True, filter output to only drifted entries.

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
        expected_sha = entry.get("content_sha256") or entry.get("checksum_sha256", "")
        checksum_type = entry.get("checksum_type", None)
        cache_path_str = entry.get("cache_path", "").rstrip("/")
        install_target_str = entry.get("install_target", "")

        actual_sha = ""
        drift = False
        entry_status = "unknown"

        # Entries without checksum_type report unknown, never drift.
        if checksum_type is None or checksum_type == "file":
            # For file-type: check single file
            if checksum_type is None:
                # Missing strategy: always report unknown (cannot verify intent)
                audit_entries.append({
                    "name": entry_name,
                    "primitive": entry.get("type", ""),
                    "expected_sha": expected_sha,
                    "actual_sha": "",
                    "drift": False,
                    "status": "unknown",
                })
                continue

            # checksum_type == "file": check single file
            for path_str in [install_target_str, cache_path_str]:
                if not path_str:
                    continue
                p = _entry_path(path_str, repo_root)
                if p.is_symlink():
                    p = p.resolve()
                if p.is_file():
                    try:
                        actual_sha = compute_checksum(p)
                    except OSError:
                        actual_sha = ""
                    break
                elif p.is_dir():
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
                entry_status = "drift"
            elif actual_sha:
                entry_status = "clean"
            else:
                entry_status = "unknown"

        elif checksum_type == "directory":
            # Directory-based checksum: hash the local installed directory first.
            # This detects drift in vendored project copies even when the cache
            # still matches upstream.
            dir_path = None
            for path_str in [install_target_str, cache_path_str]:
                if not path_str:
                    continue
                p = _entry_path(path_str, repo_root)
                if p.is_symlink():
                    p = p.resolve()
                if p.is_dir():
                    dir_path = p
                    break

            if dir_path is not None:
                try:
                    actual_sha = compute_directory_hash(dir_path)
                except (FileNotFoundError, OSError):
                    actual_sha = ""
                    entry_status = "unknown"

                if expected_sha and actual_sha and expected_sha != actual_sha:
                    drift = True
                    any_drift = True
                    entry_status = "drift"
                elif actual_sha:
                    entry_status = "clean"
                else:
                    entry_status = "unknown"
            else:
                entry_status = "unknown"
        else:
            # Unknown checksum_type: report unknown
            entry_status = "unknown"

        audit_entries.append({
            "name": entry_name,
            "primitive": entry.get("type", ""),
            "expected_sha": expected_sha,
            "actual_sha": actual_sha,
            "drift": drift,
            "status": entry_status,
        })

    # Apply drift_only filter: exclude non-drifted entries
    if drift_only:
        audit_entries = [e for e in audit_entries if e.get("drift") is True]

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


def _entry_path(path_str: str, repo_root: Path) -> Path:
    """Resolve a lockfile path relative to repo_root when needed."""
    path = Path(path_str.rstrip("/"))
    if path.is_absolute():
        return path
    return repo_root / path
