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
    raw = str(value or "")
    if not raw:
        return None
    trailing_slash = raw.endswith("/")
    path_value = raw[:-1] if trailing_slash else raw
    if not path_value:
        return None
    candidate = Path(path_value).expanduser()
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

    receipt_paths: list[str] = []
    for receipt in lock.get("receipts") or []:
        if not isinstance(receipt, dict) or receipt.get("scope") != "project":
            continue
        for target in receipt.get("targets") or []:
            if isinstance(target, dict):
                relative = _project_path(target.get("path"), project_root)
                if relative and relative not in seen:
                    seen.add(relative)
                    receipt_paths.append(relative)

    legacy_candidates: list[object] = []
    for entry in lock.get("installed") or []:
        if not isinstance(entry, dict) or entry.get("scope") != "project":
            continue
        legacy_candidates.append(entry.get("install_target"))
        legacy_candidates.extend(
            str(bridge).partition(" -> ")[0]
            for bridge in (entry.get("bridge_symlinks") or [])
        )

    if receipt_paths:
        paths.extend(receipt_paths)
        return paths

    for candidate in legacy_candidates:
        relative = _project_path(candidate, project_root)
        if relative and relative not in seen:
            seen.add(relative)
            paths.append(relative)
    return paths


def _managed_block(paths: list[str]) -> str:
    lines = [
        BEGIN_MARKER,
        *(f"/{_escape_gitignore_path(path)}" for path in paths),
        END_MARKER,
    ]
    return "\n".join(lines)


def _escape_gitignore_path(path: str) -> str:
    """Escape a repository-relative path as one literal Git ignore pattern."""
    escaped: list[str] = []
    for index, character in enumerate(path):
        trailing_name_whitespace = character in {" ", "\t"} and path[index + 1 :] in {
            "",
            "/",
        }
        if (
            character in {"\\", "*", "?", "[", "]", "!", "#"}
            or trailing_name_whitespace
        ):
            escaped.append("\\")
        escaped.append(character)
    return "".join(escaped)


def _line_ending(content: str) -> str:
    """Return the first line ending used by content, defaulting to LF."""
    for index, character in enumerate(content):
        if character == "\n":
            return "\r\n" if index > 0 and content[index - 1] == "\r" else "\n"
        if character == "\r":
            return (
                "\r\n"
                if index + 1 < len(content) and content[index + 1] == "\n"
                else "\r"
            )
    return "\n"


def _replace_managed_block(content: str, block: str) -> str:
    """Replace one valid standalone managed block, preserving all other bytes."""
    markers: list[tuple[str, int, int]] = []
    offset = 0
    for line in content.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if body in {BEGIN_MARKER, END_MARKER}:
            markers.append((body, offset, offset + len(body)))
        offset += len(line)
    if offset < len(content):
        body = content[offset:]
        if body in {BEGIN_MARKER, END_MARKER}:
            markers.append((body, offset, len(content)))

    if markers and [marker for marker, _, _ in markers] != [BEGIN_MARKER, END_MARKER]:
        raise LibraryError(
            ".gitignore contains malformed Library-managed markers; expected "
            "exactly one standalone BEGIN line followed by one standalone END line"
        )

    newline = _line_ending(content)
    rendered_block = block.replace("\n", newline)
    if markers:
        _, begin, _ = markers[0]
        _, _, end = markers[1]
        return content[:begin] + rendered_block + content[end:]
    if not content:
        return f"{rendered_block}{newline}"
    separator = newline if content.endswith(("\n", "\r")) else newline * 2
    return f"{content}{separator}{rendered_block}{newline}"


def _literal_pathspec(path: str) -> str:
    """Return one repository-rooted Git pathspec with magic disabled."""
    return f":(top,literal){path.rstrip('/')}"


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
    command.extend(_literal_pathspec(path) for path in managed_paths)
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
    if gitignore.exists():
        with gitignore.open(encoding="utf-8", newline="") as handle:
            old_content = handle.read()
    else:
        old_content = ""
    new_content = _replace_managed_block(old_content, _managed_block(managed_paths))
    updated = old_content != new_content
    if updated:
        with gitignore.open("w", encoding="utf-8", newline="") as handle:
            handle.write(new_content)

    tracked = _tracked_managed_paths(project_root, managed_paths)
    untracked: list[str] = []
    if tracked and untrack:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "rm",
                "--cached",
                "-r",
                "--",
                *(_literal_pathspec(path) for path in tracked),
            ],
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
