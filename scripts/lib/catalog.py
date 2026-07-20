"""
catalog.py — Load library.yaml, source registries, primitive mapping, entry lookup.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

try:
    import yaml
except ImportError as exc:
    raise ImportError("PyYAML is required: pip install PyYAML") from exc

from .errors import AmbiguousMatchError, CatalogError, NotFoundError
from .primitives import (
    PrimitiveInfo,
    all_primitive_names,
    get_primitive,
    resolve_yaml_list,
    resolve_yaml_section,
)


@dataclass(frozen=True)
class SourceRegistryInfo:
    """Metadata for a non-primitive source registry in library.yaml."""

    name: str
    """Canonical registry name returned by get_sources(), e.g. 'marketplaces'."""

    yaml_section: str
    """Canonical section in library.yaml, e.g. 'sources.marketplaces'."""

    yaml_key: str
    """Canonical slash-separated key path, e.g. 'sources/marketplaces'."""

    legacy_yaml_keys: list[str] = field(default_factory=list)
    """Deprecated root key paths still accepted when the canonical key is absent."""


SOURCE_REGISTRIES: tuple[SourceRegistryInfo, ...] = (
    SourceRegistryInfo(
        name="catalogs",
        yaml_section="sources.catalogs",
        yaml_key="sources/catalogs",
        legacy_yaml_keys=["catalog"],
    ),
    SourceRegistryInfo(
        name="marketplaces",
        yaml_section="sources.marketplaces",
        yaml_key="sources/marketplaces",
        legacy_yaml_keys=["marketplaces"],
    ),
)


_RUNTIME_CATALOG_IDENTITY = "_library_catalog_identity"


def normalize_catalog_identity(value: str) -> str:
    """Return a stable, credential-free catalog identity string."""
    identity = value.strip().rstrip("/")
    if identity.startswith("git@github.com:"):
        identity = f"https://github.com/{identity.removeprefix('git@github.com:')}"
    elif identity.startswith("ssh://git@github.com/"):
        identity = f"https://github.com/{identity.removeprefix('ssh://git@github.com/')}"

    parsed = urlparse(identity)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        host = parsed.hostname.lower()
        port = f":{parsed.port}" if parsed.port else ""
        path = parsed.path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        identity = urlunparse((parsed.scheme.lower(), f"{host}{port}", path, "", "", ""))
    elif identity.endswith(".git"):
        identity = identity[:-4]
    return identity


def get_catalog_identity(data: dict[str, Any]) -> str | None:
    """Return the provenance identity bound to a parsed catalog.

    Catalogs loaded from disk carry a runtime identity derived by
    :func:`load_catalog`. Direct in-memory callers can declare
    ``catalog_identity``. Unbound in-memory catalogs return ``None`` so audit
    treats their installs as legacy provenance rather than inventing identity.
    """
    declared = data.get(_RUNTIME_CATALOG_IDENTITY) or data.get("catalog_identity")
    if isinstance(declared, str) and declared.strip():
        return normalize_catalog_identity(declared)

    return None


def _catalog_identity_from_root(repo_root: Path) -> str:
    """Resolve catalog identity from its Git origin, then its file URI."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return normalize_catalog_identity(result.stdout)
    return (repo_root.resolve() / "library.yaml").as_uri()


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

    declared_identity = data.get("catalog_identity")
    if declared_identity is not None and (
        not isinstance(declared_identity, str) or not declared_identity.strip()
    ):
        raise CatalogError("catalog_identity must be a non-empty string when present.")
    data[_RUNTIME_CATALOG_IDENTITY] = (
        normalize_catalog_identity(declared_identity)
        if declared_identity
        else _catalog_identity_from_root(repo_root)
    )

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


def get_sources(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return canonical source registries with legacy root fallbacks.

    The canonical library.yaml shape stores source registries under
    `sources.catalogs` and `sources.marketplaces`. Older catalog files used
    top-level `catalog` and `marketplaces` keys; those remain readable when the
    canonical key is absent.
    """
    return {
        registry.name: resolve_source_registry(data, registry)
        for registry in SOURCE_REGISTRIES
    }


def resolve_source_registry(
    data: dict[str, Any], registry: SourceRegistryInfo
) -> list[dict[str, Any]]:
    """Return source registry entries using canonical-first legacy fallback."""
    return resolve_yaml_list(data, registry.yaml_key, registry.legacy_yaml_keys)


def get_catalogs(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return first-party source catalogs from library.yaml."""
    return get_sources(data)["catalogs"]


def get_marketplaces(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return third-party source marketplaces from library.yaml."""
    return get_sources(data)["marketplaces"]


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
        List of dicts with keys: primitive, name, description, source, tags.
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
            tags = [str(tag) for tag in entry.get("tags", []) if tag is not None]
            searchable = [name, desc, *tags]
            if any(query_lower in value.lower() for value in searchable):
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
                        "tags": tags,
                        "status": "unknown",
                    }
                )
    return results
