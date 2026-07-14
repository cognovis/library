"""
status.py — Upstream status check for installed library entries.

Compares the installed commit SHA (from lockfile) against the remote HEAD SHA
using `git ls-remote`. Never clones; network-lightweight.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

from .catalog import get_entries
from .lockfile import find_lockfile, load_lockfile
from .primitives import get_primitive
from .source import get_local_commit_sha, parse_source


def _catalog_entries_by_name(catalog: dict, primitive: str) -> dict[str, dict]:
    try:
        return {
            str(entry.get("name", "")): entry
            for entry in get_entries(catalog, primitive)
            if entry.get("name")
        }
    except (KeyError, TypeError):
        return {}


def _supervised_runtime_status(
    catalog_entry: dict | None,
    installed_revision: str,
    *,
    offline: bool,
) -> tuple[str, str | None, str | None]:
    supervised = (catalog_entry or {}).get("supervised_local_service")
    if not supervised:
        return "not_applicable", None, None
    if offline:
        return "unknown", None, None

    health_check = supervised.get("health_check")
    if not health_check:
        return "unknown", None, "catalog entry is missing health_check"
    try:
        from .installers.mcp_supervised_service import service_status

        status = service_status(health_check)
    except Exception as exc:
        return "unknown", None, str(exc)

    runtime_revision = status.get("source_revision")
    if status.get("state") != "healthy":
        error = status.get("message") or status.get("stderr") or "service is not healthy"
        return "unhealthy", runtime_revision, str(error)
    if not runtime_revision:
        return "missing", None, "healthy runtime did not report source_revision"
    if runtime_revision == installed_revision:
        return "current", runtime_revision, None
    return "stale", runtime_revision, None


def get_remote_sha(
    clone_url: str,
    ref: str = "HEAD",
    cache: dict[tuple[str, str], Optional[str]] | None = None,
) -> Optional[str]:
    """Get remote HEAD SHA without cloning.

    Runs `git ls-remote <clone_url> <ref>` and parses the output.

    Args:
        clone_url: Remote repository URL (HTTPS or SSH).
        ref: Git ref to check (default: HEAD). Can be 'HEAD', a branch name,
             or a full ref like 'refs/heads/main'.

    Returns:
        40-character hex SHA string, or None on any failure (network error,
        timeout, invalid output, git not found).
    """
    cache_key = (clone_url, ref)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    try:
        result = subprocess.run(
            ["git", "ls-remote", clone_url, ref],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            if cache is not None:
                cache[cache_key] = None
            return None
        accepted = {ref, f"refs/heads/{ref}"}
        if ref == "HEAD":
            accepted.add("HEAD")
        for line in result.stdout.splitlines():
            if "\t" not in line:
                continue
            sha, name = line.split("\t", 1)
            if name.strip() in accepted:
                resolved = sha.strip()
                if cache is not None:
                    cache[cache_key] = resolved
                return resolved
    except (subprocess.TimeoutExpired, OSError):
        if cache is not None:
            cache[cache_key] = None
        return None
    if cache is not None:
        cache[cache_key] = None
    return None


def _is_remote_source(source: str) -> bool:
    """Return True if the source is a remote URL (not a local path)."""
    return source.startswith("https://") or source.startswith("git@") or source.startswith("ssh://")


def _clone_url_from_source(source: str) -> Optional[str]:
    """Extract a clonable URL from a source string.

    For GitHub blob URLs like https://github.com/org/repo/blob/main/path/file,
    returns https://github.com/org/repo.

    For plain GitHub repo URLs, returns them as-is.
    SSH URLs are passed through unchanged (git ls-remote supports them natively).
    """
    if source.startswith("ssh://") or source.startswith("git@"):
        return source
    if not source.startswith("https://github.com/"):
        if source.startswith("https://"):
            return source
        return None

    # GitHub URL: extract org/repo
    parts = source.replace("https://github.com/", "").split("/")
    if len(parts) >= 2:
        return f"https://github.com/{parts[0]}/{parts[1]}"
    return None


def cmd_status_impl(
    catalog: dict,
    primitive: str,
    repo_root: Path,
    scope: str = "project",
    offline: bool = False,
    remote_cache: dict[tuple[str, str], Optional[str]] | None = None,
) -> dict[str, Any]:
    """Check upstream status for all installed entries.

    Compares the installed commit SHA from the lockfile against the remote HEAD
    using `git ls-remote`. Does not clone.

    Args:
        catalog: Parsed library.yaml dict (unused currently, for interface parity).
        primitive: Primitive type to filter, or 'all'.
        repo_root: Project root.
        scope: 'project' or 'global'.

    Returns:
        Status result dict:
        {
            "status": "ok",
            "entries": [
                {
                    "name": str,
                    "primitive": str,
                    "installed_sha": str,
                    "remote_sha": str | None,
                    "upstream_status": "current" | "behind" | "unknown",
                    "behind": bool
                }
            ],
            "overall": "current" | "behind" | "unknown"
        }
    """
    primitive_info = (
        get_primitive(primitive)
        if primitive not in ("all", "search", "status", None)
        else None
    )
    if primitive_info is not None:
        primitive = primitive_info.name

    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    lock_data = load_lockfile(lockfile_path)
    installed = lock_data.get("installed", [])

    # Filter by primitive if specified
    if primitive and primitive not in ("all", "search", "status"):
        entries = [e for e in installed if e.get("type") == primitive]
    else:
        entries = list(installed)

    result_entries = []
    any_behind = False
    any_unknown = False
    mcp_catalog_entries = _catalog_entries_by_name(catalog, "mcp")

    for entry in entries:
        entry_name = entry.get("name", "")
        entry_type = entry.get("type", "")
        installed_sha = entry.get("source_commit", "")
        source = entry.get("source", "")

        remote_sha: Optional[str] = None
        upstream_status = "unknown"
        behind = False

        if offline:
            upstream_status = "unknown"
            any_unknown = True
        elif _is_remote_source(source) and installed_sha and installed_sha != "local":
            # For GitHub browser/raw URLs, extract branch to compare against the
            # correct ref rather than always defaulting to remote HEAD.
            parsed = parse_source(source)
            if parsed.kind in ("github_browser", "github_raw") and parsed.clone_url:
                clone_url = parsed.clone_url
                ref = parsed.branch or "HEAD"
            else:
                clone_url = _clone_url_from_source(source)
                ref = "HEAD"
            if clone_url:
                remote_sha = get_remote_sha(clone_url, ref, remote_cache)
                if remote_sha is not None:
                    if remote_sha == installed_sha:
                        upstream_status = "current"
                    else:
                        upstream_status = "behind"
                        behind = True
                        any_behind = True
                else:
                    upstream_status = "unknown"
                    any_unknown = True
            else:
                upstream_status = "unknown"
                any_unknown = True
        elif source and installed_sha and installed_sha != "local":
            parsed = parse_source(source)
            if parsed.is_local() and parsed.local_path:
                local_sha = get_local_commit_sha(parsed.local_path)
                if local_sha != "local":
                    remote_sha = local_sha
                    if local_sha == installed_sha:
                        upstream_status = "current"
                    else:
                        upstream_status = "behind"
                        behind = True
                        any_behind = True
                else:
                    upstream_status = "unknown"
                    any_unknown = True
            else:
                upstream_status = "unknown"
                any_unknown = True
        else:
            # Non-git local source or no source_commit: unknown
            upstream_status = "unknown"
            any_unknown = True

        runtime_status = "not_applicable"
        runtime_revision = None
        runtime_error = None
        if entry_type == "mcp":
            runtime_status, runtime_revision, runtime_error = _supervised_runtime_status(
                mcp_catalog_entries.get(entry_name),
                installed_sha,
                offline=offline,
            )
        runtime_needs_refresh = (
            not offline
            and runtime_status in {"stale", "missing", "unhealthy", "unknown"}
        )
        needs_refresh = behind or runtime_needs_refresh
        if runtime_needs_refresh:
            any_behind = True

        result_entry = {
            "name": entry_name,
            "primitive": entry_type,
            "scope": scope,
            "installed_sha": installed_sha,
            "remote_sha": remote_sha,
            "upstream_status": upstream_status,
            "behind": behind,
            "runtime_status": runtime_status,
            "runtime_revision": runtime_revision,
            "needs_refresh": needs_refresh,
        }
        if runtime_error:
            result_entry["runtime_error"] = runtime_error
        result_entries.append(result_entry)

    # Compute overall
    if any_behind:
        overall = "behind"
    elif any_unknown and not any_behind:
        overall = "unknown"
    else:
        overall = "current"

    # Edge case: no entries → current
    if not result_entries:
        overall = "current"

    return {
        "status": "ok",
        "entries": result_entries,
        "overall": overall,
    }
