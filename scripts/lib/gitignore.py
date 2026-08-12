"""Reconcile project-scoped Library installs with a managed Git ignore block."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from lib.errors import LibraryError
from lib.lockfile import load_lockfile

BEGIN_MARKER = "# BEGIN Library-managed project installs"
END_MARKER = "# END Library-managed project installs"
LOCK_ARTIFACTS = (
    ".library.lock",
    ".library.lock.lock",
    ".library.lock.workspace-lock",
)


def _project_path(value: object, project_root: Path) -> str | None:
    """Return a normalized repository-relative path without following symlinks."""
    raw = str(value or "").strip()
    if not raw:
        return None
    trailing_slash = raw.rstrip().endswith("/")
    candidate = Path(raw.rstrip("/")).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    normalized_root = Path(os.path.abspath(project_root))
    normalized_candidate = Path(os.path.abspath(candidate))
    try:
        relative = normalized_candidate.relative_to(normalized_root)
    except ValueError:
        return None
    if not relative.parts or relative == Path(".") or ".." in relative.parts:
        return None
    rendered = PurePosixPath(*relative.parts).as_posix()
    return f"{rendered}/" if trailing_slash else rendered


def managed_project_paths(project_root: Path) -> list[str]:
    """Derive lock artifacts, install targets, and bridges from the project lock."""
    lock = load_lockfile(project_root / ".library.lock")
    paths = list(LOCK_ARTIFACTS)
    seen = set(paths)
    for entry in lock.get("installed") or []:
        if not isinstance(entry, dict) or entry.get("scope") != "project":
            continue
        candidates: list[object] = [entry.get("install_target")]
        candidates.extend(
            str(bridge).partition(" -> ")[0]
            for bridge in (entry.get("bridge_symlinks") or [])
        )
        for candidate in candidates:
            relative = _project_path(candidate, project_root)
            if relative and relative not in seen:
                seen.add(relative)
                paths.append(relative)
    return paths


def _managed_block(paths: list[str]) -> str:
    lines = [BEGIN_MARKER, *(f"/{path}" for path in paths), END_MARKER]
    return "\n".join(lines)


def _replace_managed_block(content: str, block: str) -> str:
    """Replace all complete managed blocks while preserving every other byte."""
    remaining = content
    insertion_at: int | None = None
    while True:
        begin = remaining.find(BEGIN_MARKER)
        if begin < 0:
            break
        end = remaining.find(END_MARKER, begin + len(BEGIN_MARKER))
        if end < 0:
            raise LibraryError(
                f"{BEGIN_MARKER!r} has no matching {END_MARKER!r} in .gitignore"
            )
        end += len(END_MARKER)
        if insertion_at is None:
            insertion_at = begin
        remaining = remaining[:begin] + remaining[end:]
    if insertion_at is not None:
        return remaining[:insertion_at] + block + remaining[insertion_at:]
    if not remaining:
        return f"{block}\n"
    separator = "\n" if remaining.endswith("\n") else "\n\n"
    return f"{remaining}{separator}{block}\n"


def _tracked_managed_paths(project_root: Path, managed_paths: list[str]) -> list[str]:
    worktree = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    if worktree.returncode != 0 or worktree.stdout.strip() != "true":
        return []
    command = ["git", "-C", str(project_root), "ls-files", "-z", "--"]
    command.extend(path.rstrip("/") for path in managed_paths)
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        raise LibraryError(
            "Could not inspect tracked Library-managed paths: "
            + result.stderr.decode(errors="replace").strip()
        )
    return sorted(
        path.decode(errors="surrogateescape")
        for path in result.stdout.split(b"\0")
        if path
    )


def reconcile_project_gitignore(
    project_root: Path, *, untrack: bool = False
) -> dict[str, Any]:
    """Write the managed block and optionally remove managed paths from the index."""
    project_root = project_root.absolute()
    managed_paths = managed_project_paths(project_root)
    gitignore = project_root / ".gitignore"
    old_content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    new_content = _replace_managed_block(old_content, _managed_block(managed_paths))
    updated = old_content != new_content
    if updated:
        gitignore.write_text(new_content, encoding="utf-8")

    tracked = _tracked_managed_paths(project_root, managed_paths)
    untracked: list[str] = []
    if tracked and untrack:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rm", "--cached", "-r", "--", *tracked],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise LibraryError(
                "Could not untrack Library-managed paths: " + result.stderr.strip()
            )
        untracked = tracked
        tracked = []

    return {
        "path": str(gitignore),
        "updated": updated,
        "managed_paths": managed_paths,
        "tracked_paths": tracked,
        "untracked_paths": untracked,
    }
