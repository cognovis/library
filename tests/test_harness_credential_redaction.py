"""Regression coverage for secret-free Open-Brain OAuth MCP configuration."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit-open-brain-mcp.py"
SPEC = importlib.util.spec_from_file_location("audit_open_brain_mcp", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_configs(tmp_path: Path, codex_entry: str, claude_entry: dict) -> tuple[Path, Path]:
    codex = tmp_path / "config.toml"
    claude = tmp_path / "claude.json"
    codex.write_text(f"[mcp_servers.open-brain]\n{codex_entry}\n")
    claude.write_text(json.dumps({"mcpServers": {"open-brain": claude_entry}}))
    return codex, claude


def test_clean_oauth_configs_pass(tmp_path: Path) -> None:
    codex, claude = _write_configs(
        tmp_path,
        'url = "https://open-brain.sussdorff.org/mcp"',
        {"type": "http", "url": "https://open-brain.sussdorff.org/mcp"},
    )

    assert MODULE.audit(codex, claude) == (0, "oauth-configuration-ok")


def test_query_token_fails_without_returning_secret(tmp_path: Path) -> None:
    sentinel = "SENTINEL_SECRET_MUST_NOT_APPEAR"
    codex, claude = _write_configs(
        tmp_path,
        f'url = "https://open-brain.sussdorff.org/mcp?token={sentinel}"',
        {"type": "http", "url": "https://open-brain.sussdorff.org/mcp"},
    )

    result = MODULE.audit(codex, claude)

    assert result[0] == 1
    assert sentinel not in repr(result)


def test_static_header_fails_without_returning_secret(tmp_path: Path) -> None:
    sentinel = "SENTINEL_SECRET_MUST_NOT_APPEAR"
    codex, claude = _write_configs(
        tmp_path,
        'url = "https://open-brain.sussdorff.org/mcp"',
        {
            "type": "http",
            "url": "https://open-brain.sussdorff.org/mcp",
            "headers": {"Authorization": f"Bearer {sentinel}"},
        },
    )

    result = MODULE.audit(codex, claude)

    assert result[0] == 1
    assert sentinel not in repr(result)


def test_quiet_command_emits_nothing_for_unsafe_config(tmp_path: Path) -> None:
    sentinel = "SENTINEL_SECRET_MUST_NOT_APPEAR"
    codex, claude = _write_configs(
        tmp_path,
        f'url = "https://open-brain.sussdorff.org/mcp?token={sentinel}"',
        {"type": "http", "url": "https://open-brain.sussdorff.org/mcp"},
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--quiet",
            "--codex-config",
            str(codex),
            "--claude-config",
            str(claude),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ""
    assert sentinel not in result.stdout + result.stderr


def test_missing_registration_is_incomplete(tmp_path: Path) -> None:
    codex = tmp_path / "missing.toml"
    claude = tmp_path / "missing.json"

    assert MODULE.audit(codex, claude) == (2, "configuration-incomplete")
