"""
catalog.py — Load/validate library.yaml, primitive section mapping, entry lookup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError as exc:
    raise ImportError("PyYAML is required: pip install PyYAML") from exc

from .errors import AmbiguousMatchError, CatalogError, NotFoundError
from .primitives import PrimitiveInfo, all_primitive_names, get_primitive, resolve_yaml_section


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Walk up from start (or cwd) to find the repo root (directory containing library.yaml)."""
    current = (start or Path.cwd()).resolve()
    while current != current.parent:
        if (current / "library.yaml").exists():
            return current
        current = current.parent
    # Fallback: cwd
    cwd = Path.cwd()
    if (cwd / "library.yaml").exists():
        return cwd
    raise CatalogError(
        "Could not find library.yaml in any parent directory. "
        "Run this command from within a library project."
    )


def load_catalog(repo_root: Optional[Path] = None) -> dict[str, Any]:
    """Load and return the parsed library.yaml data.

    Args:
        repo_root: Project root containing library.yaml. Auto-detected if None.

    Returns:
        Parsed YAML dict.

    Raises:
        CatalogError: If library.yaml is missing or invalid YAML.
    """
    if repo_root is None:
        repo_root = find_repo_root()

    yaml_path = repo_root / "library.yaml"
    if not yaml_path.exists():
        raise CatalogError(f"library.yaml not found at {yaml_path}")

    try:
        with yaml_path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise CatalogError(f"library.yaml is invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise CatalogError("library.yaml must be a YAML mapping at the top level.")

    return data


def get_entries(
    data: dict[str, Any], primitive_name: str
) -> list[dict[str, Any]]:
    """Return catalog entries for the given primitive name.

    Args:
        data: Parsed library.yaml dict.
        primitive_name: Canonical primitive name (e.g. 'skill', 'mcp').

    Returns:
        List of entry dicts (may be empty).

    Raises:
        CatalogError: If the primitive name is unrecognized.
    """
    prim = get_primitive(primitive_name)
    if prim is None:
        valid = ", ".join(all_primitive_names())
        raise CatalogError(
            f"Unknown primitive '{primitive_name}'. Valid primitives: {valid}"
        )
    return resolve_yaml_section(data, prim)


def lookup_entry(
    data: dict[str, Any],
    primitive_name: str,
    name_or_query: str,
    *,
    fuzzy: bool = True,
) -> dict[str, Any]:
    """Find exactly one catalog entry by name or fuzzy description match.

    Args:
        data: Parsed library.yaml dict.
        primitive_name: Primitive section to search.
        name_or_query: Exact name or keyword for fuzzy search.
        fuzzy: If True, also match against description (case-insensitive substring).

    Returns:
        The matching entry dict.

    Raises:
        NotFoundError: If no entry matches.
        AmbiguousMatchError: If multiple entries match (fuzzy only).
    """
    entries = get_entries(data, primitive_name)

    # Exact name match first
    for entry in entries:
        if entry.get("name") == name_or_query:
            return entry

    if not fuzzy:
        raise NotFoundError(name_or_query, primitive_name)

    # Fuzzy: case-insensitive substring in name or description
    query_lower = name_or_query.lower()
    matches = [
        e
        for e in entries
        if query_lower in (e.get("name") or "").lower()
        or query_lower in (e.get("description") or "").lower()
    ]

    if len(matches) == 0:
        raise NotFoundError(name_or_query, primitive_name)
    if len(matches) > 1:
        raise AmbiguousMatchError(
            name_or_query,
            primitive_name,
            [m.get("name", "?") for m in matches],
        )
    return matches[0]


def search_all(
    data: dict[str, Any], query: str
) -> list[dict[str, Any]]:
    """Search across ALL primitive sections for a keyword.

    Args:
        data: Parsed library.yaml dict.
        query: Keyword to search (case-insensitive substring).

    Returns:
        List of dicts with keys: primitive, name, description, source.
    """
    results = []
    query_lower = query.lower()

    for prim_name in all_primitive_names():
        prim = get_primitive(prim_name)
        if prim is None:
            continue
        entries = resolve_yaml_section(data, prim)
        for entry in entries:
            name = entry.get("name") or ""
            desc = entry.get("description") or ""
            if query_lower in name.lower() or query_lower in desc.lower():
                source = (
                    entry.get("source")
                    or entry.get("sources", {}).get("claude")
                    or "(no source)"
                )
                results.append(
                    {
                        "primitive": prim_name,
                        "name": name,
                        "description": desc,
                        "source": source,
                        "status": "unknown",
                    }
                )
    return results
