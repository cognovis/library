"""
installed.py - Unified installed-entry view for the library CLI.

Reads project and global lockfiles, decorates entries with upstream status, and
optionally compares the installed set to the catalog.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .catalog import get_entries
from .lockfile import find_lockfile, load_lockfile
from .primitives import all_primitive_names
from .source import parse_source
from .status import cmd_status_impl


INSTALLED_COLUMNS = [
    "primitive",
    "name",
    "scope",
    "source",
    "commit",
    "installed_at",
    "upstream",
    "precedence",
]


def cmd_installed_impl(
    *,
    repo_root: Path | None,
    scope: str = "both",
    primitive_filter: str | None = None,
    catalog: dict[str, Any] | None = None,
    include_catalog_diff: bool = False,
    offline: bool = False,
) -> dict[str, Any]:
    """Build the installed-entry result for human or JSON output."""
    visible_scopes = _scopes_for(scope)
    conflict_index = _build_conflict_index(repo_root, primitive_filter)
    status_index = _build_status_index(repo_root, visible_scopes, primitive_filter, offline)

    entries: list[dict[str, Any]] = []
    for current_scope in visible_scopes:
        for lock_entry in _load_scope_entries(repo_root, current_scope, primitive_filter):
            key = _entry_key(lock_entry)
            status_entry = status_index.get((current_scope, *key), {})
            entries.append(
                _format_entry(
                    lock_entry=lock_entry,
                    repo_root=repo_root,
                    scope=current_scope,
                    upstream_status=status_entry.get("upstream_status", "unknown"),
                    precedence=_precedence_for_scope(current_scope, key, conflict_index),
                )
            )

    entries.sort(key=lambda e: (e["primitive"], e["name"], e["scope"]))

    result: dict[str, Any] = {
        "entries": entries,
        "precedence_conflicts": _format_precedence_conflicts(conflict_index, primitive_filter),
    }

    if include_catalog_diff and catalog is not None:
        result["catalog_diff"] = build_catalog_diff(
            catalog=catalog,
            installed_entries=_load_all_scope_entries(repo_root, primitive_filter),
            primitive_filter=primitive_filter,
        )

    return result


def format_installed_output(result: dict[str, Any]) -> str:
    """Format installed command output for humans."""
    rows = [
        {column: str(entry.get(column, "")) for column in INSTALLED_COLUMNS}
        for entry in result["entries"]
    ]
    sections = [_format_installed_table(rows)]

    catalog_diff = result.get("catalog_diff")
    if catalog_diff is not None and (
        catalog_diff.get("available_not_installed")
        or catalog_diff.get("installed_not_in_catalog")
    ):
        sections.append("")
        sections.append(_format_catalog_diff_section(
            "Available in catalog but not installed",
            catalog_diff.get("available_not_installed", {}),
        ))
        sections.append("")
        sections.append(_format_catalog_diff_section(
            "Installed but not in catalog",
            catalog_diff.get("installed_not_in_catalog", {}),
        ))

    warnings = result.get("warnings", [])
    for warning in warnings:
        sections.append("")
        sections.append(f"Warning: {warning}")

    return "\n".join(sections)


def build_catalog_diff(
    *,
    catalog: dict[str, Any],
    installed_entries: list[dict[str, Any]],
    primitive_filter: str | None = None,
) -> dict[str, dict[str, list[str]]]:
    """Compare visible installed entries against catalog entries."""
    catalog_keys = _catalog_keys(catalog, primitive_filter)
    installed_keys = {
        (entry.get("primitive") or entry.get("type", ""), entry.get("name", ""))
        for entry in installed_entries
        if (entry.get("primitive") or entry.get("type")) and entry.get("name")
    }

    available_not_installed = _group_keys(catalog_keys - installed_keys)
    installed_not_in_catalog = _group_keys(installed_keys - catalog_keys)

    return {
        "available_not_installed": available_not_installed,
        "installed_not_in_catalog": installed_not_in_catalog,
    }


def _scopes_for(scope: str) -> list[str]:
    if scope == "both":
        return ["project", "global"]
    return [scope]


def _load_scope_entries(
    repo_root: Path | None,
    scope: str,
    primitive_filter: str | None,
) -> list[dict[str, Any]]:
    if scope == "project" and repo_root is None:
        return []
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    lock_data = load_lockfile(lockfile_path)
    entries = lock_data.get("installed", [])
    if primitive_filter:
        return [entry for entry in entries if entry.get("type") == primitive_filter]
    return list(entries)


def _load_all_scope_entries(
    repo_root: Path | None,
    primitive_filter: str | None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for scope in ["project", "global"]:
        entries.extend(_load_scope_entries(repo_root, scope, primitive_filter))
    return entries


def _build_status_index(
    repo_root: Path | None,
    scopes: list[str],
    primitive_filter: str | None,
    offline: bool,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    status_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    primitive = primitive_filter or "all"
    remote_cache: dict[tuple[str, str], str | None] = {}
    for scope in scopes:
        if scope == "project" and repo_root is None:
            continue
        result = cmd_status_impl(
            {},
            primitive,
            repo_root or Path.cwd(),
            scope=scope,
            offline=offline,
            remote_cache=remote_cache,
        )
        for entry in result.get("entries", []):
            key = (scope, entry.get("primitive", ""), entry.get("name", ""))
            status_index[key] = entry
    return status_index


def _build_conflict_index(
    repo_root: Path | None,
    primitive_filter: str | None,
) -> dict[tuple[str, str], set[str]]:
    index: dict[tuple[str, str], set[str]] = {}
    for scope in ["project", "global"]:
        for entry in _load_scope_entries(repo_root, scope, primitive_filter):
            key = _entry_key(entry)
            if all(key):
                index.setdefault(key, set()).add(scope)
    return {
        key: scopes
        for key, scopes in index.items()
        if "project" in scopes and "global" in scopes
    }


def _format_precedence_conflicts(
    conflict_index: dict[tuple[str, str], set[str]],
    primitive_filter: str | None,
) -> list[dict[str, str]]:
    conflicts = []
    for primitive, name in sorted(conflict_index):
        if primitive_filter and primitive != primitive_filter:
            continue
        conflicts.append(
            {
                "name": name,
                "primitive": primitive,
                "active_scope": "project",
                "shadowed_scope": "global",
            }
        )
    return conflicts


def _precedence_for_scope(
    scope: str,
    key: tuple[str, str],
    conflict_index: dict[tuple[str, str], set[str]],
) -> str:
    if key in conflict_index and scope == "global":
        return "shadowed"
    return "active"


def _format_entry(
    *,
    lock_entry: dict[str, Any],
    repo_root: Path | None,
    scope: str,
    upstream_status: str,
    precedence: str,
) -> dict[str, str]:
    source_commit = str(lock_entry.get("source_commit") or "")
    return {
        "primitive": str(lock_entry.get("type") or ""),
        "name": str(lock_entry.get("name") or ""),
        "scope": scope,
        "source": _short_source(str(lock_entry.get("source") or ""), repo_root),
        "commit": _short_commit(source_commit),
        "installed_at": _date_only(str(lock_entry.get("install_timestamp") or "")),
        "upstream": upstream_status or "unknown",
        "precedence": precedence,
    }


def _entry_key(entry: dict[str, Any]) -> tuple[str, str]:
    return (str(entry.get("type") or ""), str(entry.get("name") or ""))


def _short_commit(source_commit: str) -> str:
    if not source_commit:
        return "unknown"
    if source_commit == "local":
        return "local"
    return source_commit[:8]


def _date_only(timestamp: str) -> str:
    if not timestamp:
        return "unknown"
    return timestamp[:10]


def _short_source(source: str, repo_root: Path | None) -> str:
    if not source:
        return "unknown"

    try:
        parsed = parse_source(source)
    except Exception:
        parsed = None

    if parsed and parsed.is_github() and parsed.org and parsed.repo:
        branch = parsed.branch or "HEAD"
        return f"{parsed.org}/{parsed.repo}@{branch}"

    if parsed and parsed.is_local() and parsed.local_path:
        path = parsed.local_path.expanduser()
        if repo_root is not None:
            try:
                rel = path.resolve().relative_to(repo_root.resolve())
                return f"local:./{rel}"
            except (OSError, ValueError):
                pass
        home = Path.home()
        try:
            rel_home = path.resolve().relative_to(home.resolve())
            return f"local:~/{rel_home}"
        except (OSError, ValueError):
            return f"local:{path}"

    return source


def _catalog_keys(
    catalog: dict[str, Any],
    primitive_filter: str | None,
) -> set[tuple[str, str]]:
    primitives = [primitive_filter] if primitive_filter else all_primitive_names()
    keys: set[tuple[str, str]] = set()
    for primitive in primitives:
        if primitive is None:
            continue
        for entry in get_entries(catalog, primitive):
            name = entry.get("name")
            if name:
                keys.add((primitive, str(name)))
    return keys


def _group_keys(keys: set[tuple[str, str]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for primitive, name in sorted(keys):
        grouped.setdefault(primitive, []).append(name)
    return grouped


def _format_catalog_diff_section(title: str, grouped: dict[str, list[str]]) -> str:
    lines = [f"{title}:"]
    if not grouped:
        lines.append("  (none)")
        return "\n".join(lines)
    for primitive, names in sorted(grouped.items()):
        lines.append(f"  {primitive}:")
        for name in names:
            lines.append(f"    {name}")
    return "\n".join(lines)


def _format_installed_table(rows: list[dict[str, str]]) -> str:
    widths = {column: len(column) for column in INSTALLED_COLUMNS}
    for row in rows:
        for column in INSTALLED_COLUMNS:
            widths[column] = max(widths[column], len(row.get(column, "")))

    lines = [
        "  ".join(column.ljust(widths[column]) for column in INSTALLED_COLUMNS),
        "  ".join("-" * widths[column] for column in INSTALLED_COLUMNS),
    ]
    for row in rows:
        lines.append(
            "  ".join(
                row.get(column, "").ljust(widths[column])
                for column in INSTALLED_COLUMNS
            )
        )
    return "\n".join(lines)
