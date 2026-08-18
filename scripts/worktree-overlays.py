#!/usr/bin/env python3
"""Resolve and link the overlay paths a fresh Git worktree does not inherit.

A linked worktree contains only tracked content. The overlay directories that
make an agent session behave like the main checkout — installed skills under
`.agents/` and `.claude/skills/`, plus the local `.env` — are gitignored, so a
fresh worktree starts without them. Hygiene review, standards resolution, and
session-close gates then behave differently from the main checkout.

The harness launchers (now owned by the `harness-cli` repository) bootstrap
the same overlay set through this module:

* `cdx` calls ``link`` after its own ``git worktree add``, because Codex has
  no worktree bootstrap of its own.
* `cld` calls ``resolve --from-index --directories-only --json`` before
  launch and hands the result to Claude Code's native
  ``worktree.symlinkDirectories`` setting, which does the linking during its
  native ``--worktree`` creation.

Resolution rule (one rule, two presence probes):

* A source that is absent from the main checkout is skipped, so no dangling
  symlink is ever created.
* An overlay path that will be absent from the worktree is emitted whole.
* An overlay path the worktree already owns is never replaced. When it is a
  directory, resolution descends into it and emits the children that are still
  missing; otherwise it is left alone.

The two probes differ only in how "the worktree owns this path" is answered:
`cdx` inspects the worktree it just created, `cld` inspects the Git index of the
main checkout because its worktree does not exist yet.

Standard library only: the launchers invoke it with the ambient `python3`
before any project environment is available.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import NamedTuple

# The overlay set every launcher bootstraps. Keep this the single source of
# truth: a launcher that carries its own list silently drifts from the other.
DEFAULT_OVERLAYS: tuple[str, ...] = (".agents", ".claude/skills", ".env")


class Probe(NamedTuple):
    """How resolution answers two questions about the destination worktree.

    ``owns`` answers whether the worktree will already have the path, and
    ``can_descend`` whether resolution may look inside it for missing children.
    They differ: a symlinked directory is owned but must not be descended into,
    because its children resolve against the link target rather than the
    worktree.
    """

    owns: Callable[[str], bool]
    can_descend: Callable[[str], bool]


def _validate_overlay(overlay: str) -> str:
    """Return a normalized relative overlay path or raise on an unsafe one."""
    if not overlay or not overlay.strip():
        raise ValueError("overlay path must not be empty")
    if os.path.isabs(overlay):
        raise ValueError(f"overlay path must be relative: {overlay}")
    parts = [part for part in overlay.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError(f"overlay path must not traverse upwards: {overlay}")
    if not parts:
        raise ValueError("overlay path must not be empty")
    return "/".join(parts)


def worktree_probe(worktree: Path) -> Probe:
    """Probe an existing worktree: does the path exist on disk?"""

    def owns(relative_path: str) -> bool:
        return os.path.lexists(worktree / relative_path)

    def can_descend(relative_path: str) -> bool:
        destination = worktree / relative_path
        return destination.is_dir() and not destination.is_symlink()

    return Probe(owns=owns, can_descend=can_descend)


def index_probe(tracked_paths: Iterable[str]) -> Probe:
    """Probe a worktree that does not exist yet.

    A fresh worktree contains exactly the tracked paths of the checkout it
    branches from, so the Git index answers the same question ahead of time.
    Git tracks no directories, so an owned path is always descendable here.
    """
    tracked = {path.strip() for path in tracked_paths if path.strip()}

    def owns(relative_path: str) -> bool:
        prefix = f"{relative_path}/"
        return any(path == relative_path or path.startswith(prefix) for path in tracked)

    return Probe(owns=owns, can_descend=lambda _relative_path: True)


def git_tracked_paths(main: Path) -> list[str]:
    """Tracked paths of the main checkout, or an empty list when git is unusable."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(main), "ls-files"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if completed.returncode != 0:
        return []
    return completed.stdout.splitlines()


def resolve_overlays(
    main: Path,
    overlays: Sequence[str],
    probe: Probe,
) -> list[str]:
    """Resolve the overlay paths that should be linked from `main`."""
    resolved: list[str] = []
    for overlay in overlays:
        _collect(main, _validate_overlay(overlay), probe, resolved)
    return resolved


def _collect(main: Path, relative_path: str, probe: Probe, out: list[str]) -> None:
    source = main / relative_path
    # os.path.exists, not lexists: a source symlink that does not resolve would
    # otherwise be linked and reproduce the dangling link as a worktree entry.
    if not os.path.exists(source):
        return
    if not probe.owns(relative_path):
        out.append(relative_path)
        return
    # The worktree owns this path already. Never replace it; descend into a real
    # directory so a partly tracked overlay root still gets its missing children.
    if source.is_dir() and not source.is_symlink() and probe.can_descend(relative_path):
        for child in sorted(os.listdir(source)):
            _collect(main, f"{relative_path}/{child}", probe, out)


def _stays_inside(worktree: Path, destination: Path) -> bool:
    """Would writing `destination` land inside `worktree` as it exists on disk?

    A lexical check is not enough. `mkdir` and `symlink` both follow an existing
    symlinked ancestor, so a worktree path such as `.agents` that is itself a
    symlink would place `.agents/skills` wherever that link points. Resolve the
    nearest ancestor that exists and require the real path to stay contained.
    """
    root = worktree.resolve()
    ancestor = destination.parent
    while not ancestor.exists():
        parent = ancestor.parent
        if parent == ancestor:
            return False
        ancestor = parent
    real_ancestor = ancestor.resolve()
    return real_ancestor == root or root in real_ancestor.parents


def link_overlays(main: Path, worktree: Path, resolved: Sequence[str]) -> list[str]:
    """Create relative symlinks in `worktree` for already-resolved overlay paths."""
    created: list[str] = []
    for relative_path in resolved:
        destination = worktree / relative_path
        if os.path.lexists(destination):
            continue
        if not _stays_inside(worktree, destination):
            print(
                f"warning: refusing to link {relative_path}: destination escapes the worktree",
                file=sys.stderr,
            )
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        # A relative link keeps working when the worktree pair is relocated.
        target = os.path.relpath(main / relative_path, destination.parent)
        try:
            os.symlink(target, destination)
        except OSError as error:
            print(f"warning: could not link {relative_path}: {error}", file=sys.stderr)
            continue
        created.append(relative_path)
    return created


def _build_probe(args: argparse.Namespace, main: Path) -> Probe:
    if args.from_index:
        return index_probe(git_tracked_paths(main))
    return worktree_probe(Path(args.worktree))


def _filter_directories(main: Path, resolved: Sequence[str]) -> list[str]:
    return [path for path in resolved if (main / path).is_dir()]


def _resolved_paths(args: argparse.Namespace, main: Path) -> list[str]:
    overlays = args.overlay or list(DEFAULT_OVERLAYS)
    resolved = resolve_overlays(main, overlays, _build_probe(args, main))
    if getattr(args, "directories_only", False):
        resolved = _filter_directories(main, resolved)
    return resolved


def _cmd_resolve(args: argparse.Namespace) -> int:
    main = Path(args.main)
    resolved = _resolved_paths(args, main)
    if args.json:
        print(json.dumps(resolved))
    else:
        for path in resolved:
            print(path)
    return 0


def _cmd_link(args: argparse.Namespace) -> int:
    main = Path(args.main).resolve()
    worktree = Path(args.worktree).resolve()
    if main == worktree:
        print("warning: refusing to link a checkout into itself", file=sys.stderr)
        return 0
    for path in link_overlays(main, worktree, _resolved_paths(args, main)):
        print(f"linked {path}")
    return 0


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--main", required=True, help="path to the main checkout")
    parser.add_argument(
        "--overlay",
        action="append",
        help=f"overlay path to bootstrap (default: {' '.join(DEFAULT_OVERLAYS)})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser(
        "resolve", help="print the overlay paths that should be linked"
    )
    _add_common_arguments(resolve_parser)
    source = resolve_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--worktree", help="existing worktree to probe")
    source.add_argument(
        "--from-index",
        action="store_true",
        help="probe the main checkout's Git index instead of an existing worktree",
    )
    resolve_parser.add_argument(
        "--directories-only",
        action="store_true",
        help="emit directories only (Claude Code's symlinkDirectories takes no files)",
    )
    resolve_parser.add_argument("--json", action="store_true", help="emit a JSON array")
    resolve_parser.set_defaults(func=_cmd_resolve)

    link_parser = subparsers.add_parser(
        "link", help="create the overlay symlinks inside a worktree"
    )
    _add_common_arguments(link_parser)
    link_parser.add_argument("--worktree", required=True, help="worktree to bootstrap")
    link_parser.set_defaults(from_index=False, directories_only=False)
    link_parser.set_defaults(func=_cmd_link)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
