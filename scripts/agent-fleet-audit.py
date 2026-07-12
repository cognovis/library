#!/usr/bin/env python3
"""Audit installed Claude and Codex agent fleet roots.

The audit intentionally fails closed: a configured root that is missing or
contains zero active agent files is an error, because a zero-agent scan can mask
obsolete layout assumptions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HarnessScan:
    name: str
    root: Path
    pattern: str


@dataclass(frozen=True)
class HarnessResult:
    name: str
    root: Path
    pattern: str
    files: list[Path]
    error: str | None = None

    @property
    def inspected_count(self) -> int:
        return len(self.files)

    def to_json(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "pattern": f"**/{self.pattern}",
            "inspected_count": self.inspected_count,
            "files": [str(path.relative_to(self.root)) for path in self.files],
            "error": self.error,
        }


def _env_path(primary: str, fallback: str, default: str) -> Path:
    return Path(os.environ.get(primary) or os.environ.get(fallback) or default).expanduser()


def _scan_harness(scan: HarnessScan) -> HarnessResult:
    if not scan.root.exists():
        return HarnessResult(
            name=scan.name,
            root=scan.root,
            pattern=scan.pattern,
            files=[],
            error=f"{scan.name} agents root does not exist: {scan.root}",
        )
    if not scan.root.is_dir():
        return HarnessResult(
            name=scan.name,
            root=scan.root,
            pattern=scan.pattern,
            files=[],
            error=f"{scan.name} agents root is not a directory: {scan.root}",
        )
    files = sorted(path for path in scan.root.rglob(scan.pattern) if path.is_file())
    if not files:
        return HarnessResult(
            name=scan.name,
            root=scan.root,
            pattern=scan.pattern,
            files=[],
            error=f"{scan.name} inspected zero agents at {scan.root}",
        )
    return HarnessResult(
        name=scan.name,
        root=scan.root,
        pattern=scan.pattern,
        files=files,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit active Claude .md and Codex .toml agent files.",
    )
    parser.add_argument(
        "--claude-root",
        type=Path,
        default=_env_path(
            "AGENT_FLEET_AUDIT_CLAUDE_ROOT",
            "CLAUDE_AGENTS_DIR",
            "~/.claude/agents",
        ),
        help=(
            "Claude agents root to scan. Defaults to AGENT_FLEET_AUDIT_CLAUDE_ROOT, "
            "CLAUDE_AGENTS_DIR, or ~/.claude/agents."
        ),
    )
    parser.add_argument(
        "--codex-root",
        type=Path,
        default=_env_path(
            "AGENT_FLEET_AUDIT_CODEX_ROOT",
            "CODEX_AGENTS_DIR",
            "~/.codex/agents",
        ),
        help=(
            "Codex agents root to scan. Defaults to AGENT_FLEET_AUDIT_CODEX_ROOT, "
            "CODEX_AGENTS_DIR, or ~/.codex/agents."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable counts.",
    )
    return parser


def _render_json(results: list[HarnessResult]) -> str:
    payload = {
        "ok": all(result.error is None for result in results),
        "harnesses": {result.name: result.to_json() for result in results},
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _render_text(results: list[HarnessResult]) -> str:
    return "\n".join(f"{result.name}: {result.inspected_count}" for result in results)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    scans = [
        HarnessScan("claude", args.claude_root.expanduser(), "*.md"),
        HarnessScan("codex", args.codex_root.expanduser(), "*.toml"),
    ]
    results = [_scan_harness(scan) for scan in scans]
    if args.json:
        print(_render_json(results))
    else:
        print(_render_text(results))

    errors = [result.error for result in results if result.error]
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
