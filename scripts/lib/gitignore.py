"""Reconcile project-scoped Library installs with a managed Git ignore block."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from lib.errors import LibraryError

BEGIN_MARKER = "# BEGIN Library-managed project installs"
END_MARKER = "# END Library-managed project installs"
LOCK_ARTIFACTS = (
    ".library.lock.lock",
    ".library.lock.workspace-journal.json",
    ".library.lock.workspace-lock",
    ".library.lock.workspace-rollback",
)


def _require_git_top_level(project_root: Path) -> Path:
    """Return project_root only when it is exactly one Git worktree top-level."""
    root = project_root.expanduser().resolve()
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise LibraryError("Managed project ignores require a Git worktree top-level")
    git_root = Path(result.stdout.strip()).resolve()
    if root != git_root:
        raise LibraryError(
            f"Project root must equal the Git worktree top-level: {git_root}"
        )
    return root


def _project_path(
    value: object, project_root: Path, *, planned: bool = False
) -> str | None:
    """Validate and normalize one receipt or planned project target."""
    raw = str(value or "")
    if not raw:
        raise LibraryError(".library.lock receipt target path must not be empty")
    if "\n" in raw or "\r" in raw:
        raise LibraryError(
            ".library.lock contains a managed path with a line break; one path "
            "cannot be represented as exactly one .gitignore rule"
        )
    if "\x00" in raw:
        raise LibraryError(
            ".library.lock contains a managed path with NUL; Git paths and "
            "pathspec arguments cannot represent NUL bytes"
        )
    raw_path = Path(raw)
    if raw_path.is_absolute() and not planned:
        raise LibraryError(
            ".library.lock receipt target paths must be repository-relative"
        )
    trailing_slash = raw.endswith("/")
    path_value = raw[:-1] if trailing_slash else raw
    if not path_value:
        return None
    candidate = Path(path_value)
    if planned:
        planned_path = candidate if candidate.is_absolute() else project_root / candidate
        absolute = Path(os.path.abspath(planned_path))
        root = Path(os.path.abspath(project_root))
        try:
            relative = absolute.relative_to(root)
        except ValueError as exc:
            raise LibraryError(
                f"Planned project target escapes the Git worktree root: {raw}"
            ) from exc
        candidate = relative
    if not candidate.parts or candidate == Path(".") or ".." in candidate.parts:
        raise LibraryError(
            ".library.lock receipt target path escapes the repository root"
        )
    rendered = PurePosixPath(*candidate.parts).as_posix()
    return f"{rendered}/" if trailing_slash else rendered


def validate_planned_project_target(value: object, project_root: Path) -> str:
    """Return one safe repository-relative target derived by an installer plan."""
    normalized = _project_path(value, project_root, planned=True)
    if normalized is None:
        raise LibraryError("Planned project target must not be empty")
    root = project_root.resolve()
    lexical_target = root / normalized.rstrip("/")
    existing = lexical_target
    missing_suffix: list[str] = []
    while not existing.exists() and not existing.is_symlink():
        if existing == root:
            break
        missing_suffix.append(existing.name)
        existing = existing.parent
    effective = existing.resolve()
    for component in reversed(missing_suffix):
        effective /= component
    try:
        effective.relative_to(root)
    except ValueError as exc:
        raise LibraryError(
            f"Planned project target resolves outside the Git worktree root: {value}"
        ) from exc
    return normalized


def managed_project_paths(project_root: Path) -> list[str]:
    """Derive lock artifacts, install targets, and bridges from the project lock."""
    lockfile = project_root / ".library.lock"
    try:
        lock = yaml.safe_load(lockfile.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LibraryError(f"Could not read authoritative {lockfile}: {exc}") from exc
    if not isinstance(lock, dict) or lock.get("schema_version") != 2:
        raise LibraryError(
            ".library.lock must use schema_version 2 for managed project ignores"
        )
    receipts = lock.get("receipts")
    if not isinstance(receipts, list):
        raise LibraryError(
            ".library.lock schema_version 2 requires a receipts list for managed project ignores"
        )
    paths = list(LOCK_ARTIFACTS)
    seen = set(paths)

    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise LibraryError(".library.lock receipts must contain mappings")
        scope = receipt.get("scope")
        if scope not in {"project", "global"}:
            raise LibraryError(
                ".library.lock receipts must declare project or global scope"
            )
        if scope != "project":
            continue
        targets = receipt.get("targets")
        if not isinstance(targets, list):
            raise LibraryError(
                ".library.lock project receipts must contain a targets list"
            )
        for target in targets:
            if not isinstance(target, dict) or not isinstance(target.get("path"), str):
                raise LibraryError(
                    ".library.lock receipt targets must be mappings with a string path"
                )
            relative = _project_path(target["path"], project_root)
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
    project_root = _require_git_top_level(project_root)
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
