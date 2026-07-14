#!/usr/bin/env python3
"""test_mcp_installer_sha.py — Tests for MCP install-time upstream SHA capture."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
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


def make_supervised_catalog() -> dict:
    return {
        "library": {
            "mcp_servers": [
                {
                    "name": "cognovis-tools",
                    "source": (
                        "https://github.com/cognovis/library-core/blob/main/"
                        "mcp-servers/cognovis-tools/pyproject.toml"
                    ),
                    "supervised_local_service": {"url": "http://127.0.0.1:8765/mcp"},
                    "install": {
                        "mcp": {
                            "claude_code": {
                                "snippet": {
                                    "type": "http",
                                    "url": "http://127.0.0.1:8765/mcp",
                                }
                            }
                        }
                    },
                }
            ]
        },
        "marketplaces": [],
    }


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


# Guards CL-0frv: deploy, runtime verification, and lockfile must share one SHA.
def test_regression_supervised_deploy_uses_one_clean_expected_revision(
    tmp_path, monkeypatch
):
    from lib.installers.mcp_installer import McpDeployCheckout, install_mcp

    _patch_harness_helpers(monkeypatch)
    deploy_path = tmp_path / "deploy"
    project_path = deploy_path / "mcp-servers" / "cognovis-tools"
    project_path.mkdir(parents=True)
    checkout = McpDeployCheckout(path=deploy_path, source_revision=REMOTE_SHA)
    monkeypatch.setattr(
        "lib.installers.mcp_installer.ensure_mcp_deploy_clone",
        Mock(return_value=checkout),
    )
    service = Mock(
        return_value={
            "action": "restart",
            "state": "healthy",
            "source_revision": REMOTE_SHA,
        }
    )
    monkeypatch.setattr("lib.installers.mcp_installer.ensure_supervised_service", service)
    remote_sha = Mock(return_value="different-remote-sha")
    monkeypatch.setattr("lib.installers.mcp_installer.get_remote_sha", remote_sha)

    result = install_mcp(
        make_supervised_catalog(),
        "cognovis-tools",
        tmp_path,
        scope="project",
        harness="claude_code",
        env_overrides={"CLAUDE_SETTINGS_FILE": str(tmp_path / "claude.json")},
    )

    assert result["status"] == "ok"
    assert _read_lockfile_source_commit(tmp_path) == REMOTE_SHA
    service.assert_called_once_with(
        make_supervised_catalog()["library"]["mcp_servers"][0],
        project_path,
        expected_revision=REMOTE_SHA,
        dry_run=False,
    )
    remote_sha.assert_not_called()


def test_supervised_deploy_rejects_dirty_checkout(tmp_path, monkeypatch):
    from lib.errors import InstallError
    from lib.installers.mcp_installer import verify_deploy_checkout

    dirty = SimpleNamespace(returncode=0, stdout=" M daemon.py\n", stderr="")
    monkeypatch.setattr("lib.installers.mcp_installer.subprocess.run", Mock(return_value=dirty))

    with pytest.raises(InstallError, match="not clean"):
        verify_deploy_checkout(tmp_path)
