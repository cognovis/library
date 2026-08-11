#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Inventory deterministic Python MCP v1 migration signals in a repository."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence


SIGNALS = (
    ("fastmcp", re.compile(r"\bFastMCP\b")),
    ("fastmcp-module", re.compile(r"\bmcp\.server\.fastmcp\b")),
    ("mcp-error", re.compile(r"\bMcpError\b")),
    ("shared-version", re.compile(r"\bmcp\.shared\.version\b")),
    ("streamable-http-app", re.compile(r"\bstreamable_http_app\b")),
    ("streamable-http-client", re.compile(r"\bstreamablehttp_client\b")),
    ("session-manager", re.compile(r"\bsession_manager\b")),
    ("session-header", re.compile(r"Mcp-Session-Id")),
    ("initialize-method", re.compile(r"(?<![\w])initialize(?![\w])")),
    ("elicitation", re.compile(r"\bctx\.elicit\b")),
    ("ping-method", re.compile(r"(?<![\w])ping(?![\w])")),
    ("logging-set-level", re.compile(r"logging/setLevel")),
    ("roots-list-changed", re.compile(r"notifications/roots/list_changed")),
    (
        "experimental-tasks",
        re.compile(r"(?:\bmcp(?:\.[A-Za-z_]\w*)*\.experimental\.tasks\b|io\.modelcontextprotocol/tasks)"),
    ),
    ("resource-subscribe", re.compile(r"(?:resources/subscribe|\bsubscribe_resource\b)")),
    ("resource-unsubscribe", re.compile(r"resources/unsubscribe")),
    (
        "resource-updated",
        re.compile(r"(?:notifications/resources/updated|\bsend_resource_updated\b)"),
    ),
    ("get-context", re.compile(r"\bmcp\.get_context\s*\(")),
    ("context-fastmcp", re.compile(r"\bctx\.fastmcp\b")),
    ("mcp-cli-dependency", re.compile(r"\bmcp\s*\[\s*cli\s*\]")),
    ("direct-httpx", re.compile(r"^\s*(?:from\s+httpx\b|import\s+httpx\b)")),
)
SKIP_DIRECTORIES = {
    ".agents",
    ".claude",
    ".codex",
    ".beads",
    ".eggs",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".tox",
    "__pycache__",
    "build",
    "dist",
    "env",
    "htmlcov",
    "node_modules",
    "site-packages",
    "venv",
}
TEXT_SUFFIXES = {".json", ".py", ".toml", ".txt", ".yaml", ".yml"}


def _meta() -> dict[str, str]:
    generated_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
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
            for signal, pattern in SIGNALS:
                if pattern.search(line):
                    matches.append(
                        {
                            "path": str(path.relative_to(resolved)),
                            "line": line_number,
                            "signal": signal,
                        }
                    )

    return {
        "status": "warning" if read_errors or files_scanned == 0 else "ok",
        "summary": f"Found {len(matches)} MCP v1 migration signal matches.",
        "data": {
            "root": str(resolved),
            "files_scanned": files_scanned,
            "matches": matches,
        },
        "errors": read_errors
        or (
            [
                {
                    "code": "no-files-scanned",
                    "message": f"No supported text files were found under {resolved}.",
                    "suggested_fix": "Pass the repository root and confirm its source files are present.",
                }
            ]
            if files_scanned == 0
            else []
        ),
        "next_steps": [
            {
                "id": "classify-matches",
                "summary": "Classify each match and inspect MCPServer constructor calls manually.",
                "priority": "now",
                "automatable": False,
            }
        ],
        "open_items": [],
        "meta": {**_meta(), "signals": [name for name, _ in SIGNALS]},
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
