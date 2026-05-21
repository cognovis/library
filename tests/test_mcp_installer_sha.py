#!/usr/bin/env python3
"""test_mcp_installer_sha.py — Tests for MCP install-time upstream SHA capture."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


SOURCE_URL = "https://github.com/sussdorff/open-brain/blob/main/mcp.yaml"
REMOTE_SHA = "abc123def456abc123def456abc123def456abc123def456abc123def456ab12"


def make_catalog(source: str | None) -> dict:
    entry = {
        "name": "open-brain",
        "install": {
            "mcp": {
                "claude_code": {
                    "command": "open-brain",
                }
            }
        },
    }
    if source is not None:
        entry["source"] = source
    return {"mcp_servers": [entry], "marketplaces": []}


def _patch_harness_helpers(monkeypatch):
    monkeypatch.setattr("lib.installers.mcp_installer._import_install_mcp", lambda: SimpleNamespace())
    monkeypatch.setattr("lib.installers.mcp_installer._install_to_harness", lambda *args, **kwargs: 0)


def _read_lockfile_source_commit(project_root: Path) -> str:
    lockfile = yaml.safe_load((project_root / ".library.lock").read_text())
    return lockfile["installed"][0]["source_commit"]


def test_install_captures_remote_sha(tmp_path, monkeypatch):
    from lib.installers.mcp_installer import install_mcp

    _patch_harness_helpers(monkeypatch)
    remote_sha = Mock(return_value=REMOTE_SHA)
    monkeypatch.setattr("lib.installers.mcp_installer.get_remote_sha", remote_sha)

    result = install_mcp(make_catalog(SOURCE_URL), "open-brain", tmp_path, scope="project")

    assert result["status"] == "ok"
    assert _read_lockfile_source_commit(tmp_path) == REMOTE_SHA
    remote_sha.assert_called_once()


def test_install_handles_remote_sha_failure(tmp_path, monkeypatch, capsys):
    from lib.installers.mcp_installer import install_mcp

    _patch_harness_helpers(monkeypatch)
    monkeypatch.setattr("lib.installers.mcp_installer.get_remote_sha", Mock(return_value=None))

    result = install_mcp(make_catalog(SOURCE_URL), "open-brain", tmp_path, scope="project")

    captured = capsys.readouterr()
    assert result["status"] == "ok"
    assert "could not capture upstream SHA for mcp:open-brain" in captured.err
    assert _read_lockfile_source_commit(tmp_path) == "local"


def test_install_without_source_field_records_local(tmp_path, monkeypatch):
    from lib.installers.mcp_installer import install_mcp

    _patch_harness_helpers(monkeypatch)
    remote_sha = Mock(return_value=REMOTE_SHA)
    monkeypatch.setattr("lib.installers.mcp_installer.get_remote_sha", remote_sha)

    result = install_mcp(make_catalog(None), "open-brain", tmp_path, scope="project")

    assert result["status"] == "ok"
    assert _read_lockfile_source_commit(tmp_path) == "local"
    remote_sha.assert_not_called()
