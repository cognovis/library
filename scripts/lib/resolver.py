"""
resolver.py — Transitive dependency resolver for library items.

Resolves `requires:` lists from catalog entries depth-first, detects cycles,
and respects the lockfile (skips already-installed entries at the same SHA).
Works cross-primitive: agent:X can require skill:Y and vice versa.
"""

from __future__ import annotations

from pathlib import Path
from .catalog import get_entries, lookup_entry
from .errors import DependencyMissingError, EXIT_DEPENDENCY_MISSING, LibraryError
from .lockfile import find_lockfile, get_entry, load_lockfile, resolve_lockfile_path


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


def resolve_requires_bound(
    catalog: dict,
    primitive: str,
    name: str,
    *,
    source_catalog: str,
) -> list[tuple[str, str, str]]:
    """Resolve dependencies while retaining an unambiguous source binding.

    A dependency prefers the catalog of the entry that declared it. If that
    catalog does not publish the dependency, the dependency must be globally
    unique by primitive and name.
    """
    order: list[tuple[str, str, str]] = []
    visited: set[tuple[str, str, str]] = set()
    in_stack: set[tuple[str, str, str]] = set()

    def entry_source(entry: dict) -> str:
        return str(
            (entry.get("metadata") or {}).get("library", {}).get("source_catalog") or ""
        )

    def bound_entry(prim: str, item_name: str, preferred: str) -> tuple[dict, str]:
        exact = [
            entry
            for entry in get_entries(catalog, prim)
            if entry.get("name") == item_name
        ]
        preferred_entries = [
            entry for entry in exact if entry_source(entry) == preferred
        ]
        if len(preferred_entries) == 1:
            return preferred_entries[0], preferred
        if len(preferred_entries) > 1:
            raise LibraryError(
                f"Duplicate {prim}:{item_name} entries in source catalog {preferred}"
            )
        if len(exact) == 1:
            return exact[0], entry_source(exact[0])
        if not exact:
            raise DependencyMissingError(f"{prim}:{item_name}", "Workspace closure")
        catalogs = sorted({entry_source(entry) or "unbound" for entry in exact})
        raise LibraryError(
            f"Ambiguous dependency {prim}:{item_name}; qualify its catalog contract "
            f"by publishing it in the requiring catalog or remove duplicates: {catalogs}"
        )

    def visit(prim: str, item_name: str, preferred: str, stack: list[str]) -> None:
        entry, resolved_source = bound_entry(prim, item_name, preferred)
        key = (prim, item_name, resolved_source)
        label = f"{resolved_source}:{prim}:{item_name}"
        if key in in_stack:
            raise CycleError(stack + [label])
        if key in visited:
            return
        in_stack.add(key)
        next_stack = stack + [label]
        for dependency in entry.get("requires") or []:
            dep_primitive, dep_name = _parse_dep(dependency, label)
            visit(dep_primitive, dep_name, resolved_source, next_stack)
        in_stack.remove(key)
        visited.add(key)
        order.append(key)

    visit(primitive, name, source_catalog, [])
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
    primitive_type: str | None = None,
) -> bool:
    """Return True if `name`/`primitive_type` is present and materialized."""
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    if not lockfile_path.exists():
        return False
    lock_data = load_lockfile(lockfile_path)
    entry = get_entry(lock_data, name, primitive_type)
    if entry is None:
        return False
    install_target = entry.get("install_target")
    if not install_target:
        return False
    return resolve_lockfile_path(str(install_target), repo_root).exists()
