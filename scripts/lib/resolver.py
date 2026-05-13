"""
resolver.py — Transitive dependency resolver for library items.

Resolves `requires:` lists from catalog entries depth-first, detects cycles,
and respects the lockfile (skips already-installed entries at the same SHA).
Works cross-primitive: agent:X can require skill:Y and vice versa.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .catalog import lookup_entry, get_entries
from .errors import DependencyMissingError, EXIT_DEPENDENCY_MISSING, LibraryError
from .lockfile import find_lockfile, get_entry, load_lockfile


class CycleError(LibraryError):
    """Raised when a dependency cycle is detected."""

    def __init__(self, cycle_path: list[str]) -> None:
        cycle_str = " -> ".join(cycle_path)
        super().__init__(
            f"Dependency cycle detected: {cycle_str}",
            exit_code=EXIT_DEPENDENCY_MISSING,
        )
        self.cycle_path = cycle_path


def resolve_requires(
    catalog: dict,
    primitive: str,
    name: str,
    repo_root: Path,
    scope: str = "project",
) -> list[tuple[str, str]]:
    """Return an ordered install list for `name` and all its transitive deps.

    Returns a list of (primitive, name) tuples in dependency-first order
    (deps before the item that requires them). The item itself is last.

    Already-installed entries (present in lockfile) are still included so
    the caller can skip them efficiently using `is_already_installed`.

    Raises:
        CycleError: If a dependency cycle is detected.
        DependencyMissingError: If a required dep is not in the catalog.
    """
    order: list[tuple[str, str]] = []
    visited: set[str] = set()
    in_stack: set[str] = set()

    def _visit(prim: str, item_name: str, stack: list[str]) -> None:
        key = f"{prim}:{item_name}"
        if key in in_stack:
            cycle = stack + [key]
            raise CycleError(cycle)
        if key in visited:
            return

        in_stack.add(key)
        stack = stack + [key]

        # Lookup entry in catalog
        try:
            entry = lookup_entry(catalog, prim, item_name, fuzzy=False)
        except LibraryError:
            raise DependencyMissingError(key, stack[-2] if len(stack) > 1 else "root")

        requires = entry.get("requires") or []
        for dep in requires:
            dep_prim, dep_name = _parse_dep(dep, key)
            _visit(dep_prim, dep_name, stack)

        in_stack.discard(key)
        visited.add(key)
        order.append((prim, item_name))

    _visit(primitive, name, [])
    return order


def _parse_dep(dep: str, required_by: str) -> tuple[str, str]:
    """Parse a dep string like 'agent:name' or 'skill:name' into (primitive, name)."""
    if ":" not in dep:
        raise DependencyMissingError(dep, required_by)
    primitive, name = dep.split(":", 1)
    return primitive.strip(), name.strip()


def is_already_installed(
    name: str,
    repo_root: Path,
    scope: str = "project",
) -> bool:
    """Return True if `name` is present in the lockfile."""
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    if not lockfile_path.exists():
        return False
    lock_data = load_lockfile(lockfile_path)
    entry = get_entry(lock_data, name)
    return entry is not None
