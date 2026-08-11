#!/usr/bin/env python3
"""Inventory deterministic Python MCP v1 migration signals in a repository."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Sequence


SIGNALS = (
    "FastMCP",
    "mcp.server.fastmcp",
    "streamable_http_app",
    "session_manager",
    "Mcp-Session-Id",
    "initialize",
    "ctx.elicit",
    "ping",
    "logging/setLevel",
    "notifications/roots/list_changed",
    "tasks/",
    "resources/subscribe",
    "resources/unsubscribe",
    "notifications/resources/updated",
)
SKIP_DIRECTORIES = {
    ".agents",
    ".claude",
    ".codex",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
TEXT_SUFFIXES = {".json", ".lock", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}


def _meta() -> dict[str, str]:
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "contract_version": "1",
        "producer": "audit_mcp_v1",
        "generated_at": generated_at,
        "schema": "core/contracts/execution-result.schema.json",
    }


def _iter_text_files(root: Path) -> Iterator[Path]:
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in SKIP_DIRECTORIES)
        base = Path(directory)
        for name in sorted(files):
            path = base / name
            if path.suffix.lower() in TEXT_SUFFIXES:
                yield path


def audit(root: Path) -> dict[str, Any]:
    resolved = root.resolve()
    if not resolved.is_dir():
        return {
            "status": "error",
            "summary": f"Target repository is not a directory: {resolved}",
            "data": {},
            "errors": [
                {
                    "code": "invalid-root",
                    "message": str(resolved),
                    "suggested_fix": "Pass the root directory of the target repository.",
                }
            ],
            "next_steps": [],
            "open_items": [],
            "meta": _meta(),
        }

    matches: list[dict[str, Any]] = []
    files_scanned = 0
    read_errors: list[dict[str, str]] = []
    for path in _iter_text_files(resolved):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            read_errors.append(
                {
                    "code": "read-failed",
                    "path": str(path),
                    "message": str(exc),
                    "continue_with": "Review the reported matches and inspect this file manually.",
                }
            )
            continue
        files_scanned += 1
        for line_number, line in enumerate(lines, start=1):
            for signal in SIGNALS:
                if signal in line:
                    matches.append(
                        {
                            "path": str(path.relative_to(resolved)),
                            "line": line_number,
                            "signal": signal,
                        }
                    )

    return {
        "status": "warning" if read_errors else "ok",
        "summary": f"Found {len(matches)} MCP v1 migration signal matches.",
        "data": {
            "root": str(resolved),
            "files_scanned": files_scanned,
            "matches": matches,
        },
        "errors": read_errors,
        "next_steps": [
            {
                "id": "classify-matches",
                "summary": "Classify each match and inspect MCPServer constructor calls manually.",
                "priority": "now",
                "automatable": False,
            }
        ],
        "open_items": [],
        "meta": {**_meta(), "signals": list(SIGNALS)},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
