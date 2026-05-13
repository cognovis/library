"""
status.py — Upstream status check for installed library entries.

Compares the installed commit SHA (from lockfile) against the remote HEAD SHA
using `git ls-remote`. Never clones; network-lightweight.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

from .lockfile import find_lockfile, load_lockfile


def get_remote_sha(clone_url: str, ref: str = "HEAD") -> Optional[str]:
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
    try:
        result = subprocess.run(
            ["git", "ls-remote", clone_url, ref],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            if "\t" not in line:
                continue
            sha, name = line.split("\t", 1)
            if name in (ref, f"refs/heads/{ref}", "HEAD"):
                return sha.strip()
    except (subprocess.TimeoutExpired, OSError):
        return None
    return None


def _is_remote_source(source: str) -> bool:
    """Return True if the source is a remote URL (not a local path)."""
    return source.startswith("https://") or source.startswith("git@") or source.startswith("ssh://")


def _clone_url_from_source(source: str) -> Optional[str]:
    """Extract a clonable URL from a source string.

    For GitHub blob URLs like https://github.com/org/repo/blob/main/path/file,
    returns https://github.com/org/repo.

    For plain GitHub repo URLs, returns them as-is.
    """
    if not source.startswith("https://github.com/"):
        if source.startswith("https://") or source.startswith("git@"):
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

    for entry in entries:
        entry_name = entry.get("name", "")
        entry_type = entry.get("type", "")
        installed_sha = entry.get("source_commit", "")
        source = entry.get("source", "")

        remote_sha: Optional[str] = None
        upstream_status = "unknown"
        behind = False

        if _is_remote_source(source) and installed_sha and installed_sha != "local":
            clone_url = _clone_url_from_source(source)
            if clone_url:
                remote_sha = get_remote_sha(clone_url, "HEAD")
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
        else:
            # Local source or no source_commit: unknown
            upstream_status = "unknown"
            any_unknown = True

        result_entries.append({
            "name": entry_name,
            "primitive": entry_type,
            "installed_sha": installed_sha,
            "remote_sha": remote_sha,
            "upstream_status": upstream_status,
            "behind": behind,
        })

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
