"""
output.py — Human and JSON result envelopes for the library CLI.

Provides stable, machine-readable output structures and human-friendly
table formatting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Result envelope types
# ---------------------------------------------------------------------------


def success(data: Any = None, message: str = "") -> dict[str, Any]:
    """Build a success result envelope."""
    result: dict[str, Any] = {"status": "ok"}
    if message:
        result["message"] = message
    if data is not None:
        result["data"] = data
    return result


def error_result(message: str, exit_code: int = 1) -> dict[str, Any]:
    """Build an error result envelope."""
    return {
        "status": "error",
        "message": message,
        "exit_code": exit_code,
    }


def dry_run_result(
    operations: list[dict[str, Any]],
    summary: str = "",
    *,
    target_paths: list[str | Path] | None = None,
    harness_routing: str | None = None,
    conflict_policy: str = "overwrite",
    lockfile_changes: list[dict[str, Any]] | None = None,
    requires_user_confirmation: bool = False,
) -> dict[str, Any]:
    """Build a dry-run result envelope."""
    normalized_targets = [str(path) for path in (target_paths or [])]
    _annotate_existing_targets(operations, normalized_targets)
    result: dict[str, Any] = {
        "status": "dry-run",
        "operations": operations,
        "summary": summary,
        "target_paths": normalized_targets,
        "harness_routing": harness_routing,
        "conflict_policy": conflict_policy,
        "lockfile_changes": lockfile_changes or [],
        "requires_user_confirmation": requires_user_confirmation,
    }
    return result


def _annotate_existing_targets(
    operations: list[dict[str, Any]],
    target_paths: list[str],
) -> None:
    """Mark dry-run operations whose planned target already exists."""
    target_set = set(target_paths)
    for operation in operations:
        path = operation.get("path")
        if not isinstance(path, str) or path not in target_set:
            continue
        if Path(path).expanduser().exists():
            operation["existing_target"] = True
            details = operation.get("details", "")
            suffix = "existing target detected; conflict_policy=overwrite"
            operation["details"] = f"{details}; {suffix}" if details else suffix


def blocked_result(reason: str, suggestion: str = "") -> dict[str, Any]:
    """Build a blocked result envelope (feature not yet implemented)."""
    result: dict[str, Any] = {
        "status": "blocked",
        "reason": reason,
    }
    if suggestion:
        result["suggestion"] = suggestion
    return result


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def print_json(data: Any) -> None:
    """Print data as stable JSON to stdout."""
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


# ---------------------------------------------------------------------------
# Human-readable table formatting
# ---------------------------------------------------------------------------


def format_table(rows: list[dict[str, str]], columns: list[str]) -> str:
    """Format a list of row dicts as a text table.

    Args:
        rows: List of dicts with keys matching `columns`.
        columns: Ordered list of column names.

    Returns:
        Formatted table string.
    """
    if not rows:
        return "(no entries)"

    # Compute column widths
    widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            val = str(row.get(col, ""))
            widths[col] = max(widths[col], len(val))

    # Header
    header = "  ".join(col.ljust(widths[col]) for col in columns)
    separator = "  ".join("-" * widths[col] for col in columns)

    lines = [header, separator]
    for row in rows:
        line = "  ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns)
        lines.append(line)

    return "\n".join(lines)


def format_list_output(
    primitive: str,
    entries: list[dict],
    *,
    json_mode: bool = False,
) -> None:
    """Print list output for a primitive.

    Args:
        primitive: Primitive name (for heading).
        entries: List of catalog entries.
        json_mode: If True, emit JSON; otherwise emit human table.
    """
    if json_mode:
        output_entries = []
        for e in entries:
            output_entries.append(
                {
                    "name": e.get("name", ""),
                    "description": e.get("description", ""),
                    "source": _entry_source(e),
                    "tags": e.get("tags", []),
                }
            )
        print_json(output_entries)
        return

    # Human table
    rows = []
    for e in entries:
        rows.append(
            {
                "Name": e.get("name", ""),
                "Description": _truncate(e.get("description", ""), 60),
                "Source": _truncate(_entry_source(e), 50),
            }
        )

    print(f"\n## {primitive.title()} ({len(entries)} entries)\n")
    print(format_table(rows, ["Name", "Description", "Source"]))
    print()


def format_search_output(
    results: list[dict],
    query: str,
    *,
    json_mode: bool = False,
) -> None:
    """Print search results.

    Args:
        results: List of search result dicts (primitive, name, description, source).
        query: The search query (for heading).
        json_mode: If True, emit JSON.
    """
    if json_mode:
        print_json(results)
        return

    if not results:
        print(f'\nNo results found for "{query}".')
        print(
            f"\nTip: Try broader keywords or run: "
            f"python3 scripts/library.py <primitive> list"
        )
        return

    print(f'\n## Search Results for "{query}" ({len(results)} found)\n')
    rows = [
        {
            "Primitive": r.get("primitive", ""),
            "Name": r.get("name", ""),
            "Description": _truncate(r.get("description", ""), 55),
            "Source": _truncate(r.get("source", ""), 40),
        }
        for r in results
    ]
    print(format_table(rows, ["Primitive", "Name", "Description", "Source"]))
    print(
        "\nRun: python3 scripts/library.py <primitive> use <name>  to install one of these."
    )
    print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry_source(entry: dict) -> str:
    """Extract a display-friendly source string from a catalog entry."""
    if entry.get("source"):
        return entry["source"]
    if isinstance(entry.get("sources"), dict):
        sources = entry["sources"]
        return sources.get("claude") or sources.get("codex") or "(multi-source)"
    if entry.get("from_marketplace") and entry.get("repo"):
        return f"{entry['from_marketplace']}/{entry.get('path', '')}"
    return "(no source)"


def _truncate(s: str, max_len: int) -> str:
    """Truncate a string to max_len characters, appending '...' if needed."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."
