#!/usr/bin/env python3
"""Audit Open-Brain MCP registrations without emitting configuration values."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit


EXPECTED_URL = "https://open-brain.sussdorff.org/mcp"
SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "bearer_token",
    "bearer_token_env_var",
    "headers",
    "token",
    "url_token",
}


def _has_sensitive_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in SENSITIVE_KEYS or _has_sensitive_value(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_sensitive_value(item) for item in value)
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    if "bearer " in lowered:
        return True
    try:
        return any(key.lower() in SENSITIVE_KEYS for key, _ in parse_qsl(urlsplit(value).query))
    except ValueError:
        return "token=" in lowered


def _is_compliant(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and entry.get("url") == EXPECTED_URL
        and not _has_sensitive_value(entry)
    )


def audit(codex_config: Path, claude_config: Path) -> tuple[int, str]:
    """Return an exit code and secret-free status label."""
    try:
        codex = tomllib.loads(codex_config.read_text()) if codex_config.is_file() else {}
        claude = json.loads(claude_config.read_text()) if claude_config.is_file() else {}
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return 2, "configuration-unreadable"

    codex_entry = codex.get("mcp_servers", {}).get("open-brain")
    claude_entry = claude.get("mcpServers", {}).get("open-brain")
    if codex_entry is None or claude_entry is None:
        return 2, "configuration-incomplete"
    if not _is_compliant(codex_entry) or not _is_compliant(claude_entry):
        return 1, "legacy-or-unsafe-configuration"
    return 0, "oauth-configuration-ok"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Open-Brain MCP OAuth registrations without printing values."
    )
    parser.add_argument(
        "--codex-config",
        type=Path,
        default=Path.home() / ".codex" / "config.toml",
    )
    parser.add_argument(
        "--claude-config",
        type=Path,
        default=Path.home() / ".claude.json",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    code, status = audit(args.codex_config, args.claude_config)
    if not args.quiet:
        print(status)
    return code


if __name__ == "__main__":
    sys.exit(main())
