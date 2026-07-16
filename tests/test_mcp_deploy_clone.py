#!/usr/bin/env python3
"""
test_mcp_deploy_clone.py — Regression tests for MCP server deploy-clone-before-register
(CL-4av7).

Tests:
1. ensure_mcp_deploy_clone returns a clean checkout identity when launchable
2. ensure_mcp_deploy_clone raises InstallError when subdir missing pyproject.toml
3. ensure_mcp_deploy_clone in dry_run mode returns a planned checkout identity
4. ensure_mcp_deploy_clone raises InstallError when git clone fails
5. install_mcp does not write registration when clone fails (no dangling registration)
6. install_mcp writes registration after successful ensure_mcp_deploy_clone

Run with:
    uv run --with pytest --with pyyaml --with tomlkit python -m pytest tests/test_mcp_deploy_clone.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Insert scripts dir so relative imports inside lib/* work
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.errors import InstallError  # noqa: E402
from lib.installers.mcp_installer import (  # noqa: E402
    McpDeployCheckout,
    _derive_deploy_path,
    _project_path_from_deploy,
    ensure_mcp_deploy_clone,
    install_mcp,
)


REVISION = "a" * 40


@pytest.fixture(autouse=True)
def isolate_global_lockfile(tmp_path, monkeypatch):
    from lib import lockfile

    monkeypatch.setattr(lockfile, "GLOBAL_LOCKFILE", tmp_path / ".library-global.lock")


class TestEnsureMcpDeployClone:
    """Unit tests for ensure_mcp_deploy_clone helper."""

    def test_returns_deploy_path_when_subdir_has_pyproject(self, tmp_path):
        """The deploy result binds a clean checkout path to its exact revision."""
        deploy_path = tmp_path / "cognovis-library-core"
        subdir = deploy_path / "mcp-servers" / "cognovis-tools"
        subdir.mkdir(parents=True)
        (subdir / "pyproject.toml").write_text("[project]\nname = 'cognovis-tools'\n")
        # Make it look like a git repo so the pull path fires instead of clone
        (deploy_path / ".git").mkdir()

        with patch("subprocess.run") as run:
            run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=0, stdout=f"{REVISION}\n", stderr=""),
            ]
            result = ensure_mcp_deploy_clone(
                clone_url="https://github.com/cognovis/library-core.git",
                mcp_subdir="mcp-servers/cognovis-tools",
                deploy_path=deploy_path,
                dry_run=False,
            )
        assert result == McpDeployCheckout(
            path=deploy_path,
            source_revision=REVISION,
        )

    def test_update_failure_refuses_stale_existing_clone(self, tmp_path):
        deploy_path = tmp_path / "cognovis-library-core"
        subdir = deploy_path / "mcp-servers" / "cognovis-tools"
        subdir.mkdir(parents=True)
        (subdir / "pyproject.toml").write_text("[project]\nname='cognovis-tools'\n")
        (deploy_path / ".git").mkdir()

        with patch("subprocess.run") as run:
            run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="local changes would be overwritten",
                ),
            ]
            with pytest.raises(InstallError, match="potentially stale runtime"):
                ensure_mcp_deploy_clone(
                    clone_url="https://github.com/cognovis/library-core.git",
                    mcp_subdir="mcp-servers/cognovis-tools",
                    deploy_path=deploy_path,
                )

    def test_raises_install_error_when_subdir_missing_pyproject(self, tmp_path):
        """ensure_mcp_deploy_clone raises InstallError when subdir has no pyproject.toml."""
        deploy_path = tmp_path / "cognovis-library-core"
        # Simulate a clone: .git present, but the mcp subdir has no pyproject.toml
        (deploy_path / ".git").mkdir(parents=True)
        subdir = deploy_path / "mcp-servers" / "broken-tools"
        subdir.mkdir(parents=True)

        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with pytest.raises(InstallError, match="pyproject.toml"):
                ensure_mcp_deploy_clone(
                    clone_url="https://github.com/cognovis/library-core.git",
                    mcp_subdir="mcp-servers/broken-tools",
                    deploy_path=deploy_path,
                    dry_run=False,
                )

    def test_dry_run_returns_path_without_cloning(self, tmp_path):
        """Dry-run returns a planned path without inventing a revision."""
        deploy_path = tmp_path / "cognovis-library-core"
        # deploy_path does NOT exist — dry-run must not clone

        result = ensure_mcp_deploy_clone(
            clone_url="https://github.com/cognovis/library-core.git",
            mcp_subdir="mcp-servers/cognovis-tools",
            deploy_path=deploy_path,
            dry_run=True,
        )
        assert result == McpDeployCheckout(path=deploy_path, source_revision=None)
        assert not deploy_path.exists()  # no clone happened

    def test_raises_install_error_on_clone_failure(self, tmp_path):
        """ensure_mcp_deploy_clone raises InstallError when git clone fails."""
        deploy_path = tmp_path / "cognovis-library-core"

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "fatal: not found"
            mock_run.return_value = mock_result

            with pytest.raises(InstallError, match="clone"):
                ensure_mcp_deploy_clone(
                    clone_url="https://github.com/cognovis/library-core.git",
                    mcp_subdir="mcp-servers/cognovis-tools",
                    deploy_path=deploy_path,
                    dry_run=False,
                )


class TestInstallMcpDeployCloneIntegration:
    """Integration tests for install_mcp deploy-before-register behavior."""

    def _make_catalog(self, subdir: str) -> dict:
        """Build a minimal catalog with one MCP entry pointing to the given subdir."""
        return {
            "library": {
                "mcp_servers": [
                    {
                        "name": "test-mcp",
                        "description": "Test MCP server",
                        "source": f"https://github.com/test-org/test-repo/blob/main/{subdir}/pyproject.toml",
                        "install": {
                            "mcp": {
                                "claude_code": {
                                    "snippet": {
                                        "type": "stdio",
                                        "command": "sh",
                                        "args": [
                                            "-c",
                                            f"uv run --project ~/.local/share/library/test-org-test-repo/{subdir} test-mcp-server",
                                        ],
                                    }
                                }
                            }
                        },
                    }
                ]
            },
            "default_dirs": {
                "skills": [{"default": ".agents/skills/"}],
            },
            "marketplaces": [],
            "sources": {"marketplaces": []},
        }

    def test_no_dangling_registration_when_clone_fails(self, tmp_path):
        """install_mcp must NOT write registration when deploy clone fails."""
        catalog = self._make_catalog(subdir="mcp-servers/test-mcp")
        settings_file = tmp_path / "settings.json"

        with patch(
            "lib.installers.mcp_installer.ensure_mcp_deploy_clone"
        ) as mock_clone:
            mock_clone.side_effect = InstallError("git clone failed: fatal: not found")

            with pytest.raises(InstallError):
                install_mcp(
                    catalog=catalog,
                    name="test-mcp",
                    repo_root=tmp_path,
                    scope="global",
                    dry_run=False,
                    harness="claude_code",
                    env_overrides={
                        "CLAUDE_SETTINGS_FILE": str(settings_file),
                    },
                )

        # Registration must NOT have been written
        assert not settings_file.exists() or "test-mcp" not in settings_file.read_text()

    def test_registration_written_after_successful_clone(self, tmp_path):
        """install_mcp writes registration only after ensure_mcp_deploy_clone succeeds."""
        catalog = self._make_catalog(subdir="mcp-servers/test-mcp")
        settings_file = tmp_path / "settings.json"
        deploy_path = tmp_path / "test-org-test-repo"

        with patch(
            "lib.installers.mcp_installer.ensure_mcp_deploy_clone"
        ) as mock_clone:
            mock_clone.return_value = deploy_path

            result = install_mcp(
                catalog=catalog,
                name="test-mcp",
                repo_root=tmp_path,
                scope="global",
                dry_run=False,
                harness="claude_code",
                env_overrides={
                    "CLAUDE_SETTINGS_FILE": str(settings_file),
                },
            )

        # Registration MUST have been written
        assert settings_file.exists(), "settings.json was not created"
        settings = json.loads(settings_file.read_text())
        assert "test-mcp" in settings.get("mcpServers", {}), "test-mcp not in mcpServers"
        # Result must indicate success
        assert result.get("status") == "ok"  # success() helper returns status="ok"


class TestDeployPathDerivation:
    """Tests for _derive_deploy_path — ensuring only pyproject.toml sources trigger deploy-clone."""

    def test_cognovis_tools_supervised_catalog_paths_match_derived_project_path(self):
        """cognovis-tools supervised commands point at the installer-derived project path."""
        catalog = yaml.safe_load((REPO_ROOT / "library.yaml").read_text())
        entry = next(
            item
            for item in catalog["library"]["mcp_servers"]
            if item["name"] == "cognovis-tools"
        )
        _, mcp_subdir, deploy_path = _derive_deploy_path(entry, "cognovis-tools")
        project_path = _project_path_from_deploy(deploy_path, mcp_subdir)
        supervised_service = entry["supervised_local_service"]
        command_names = [
            "install",
            "start",
            "health_check",
            "restart",
            "stop",
            "uninstall",
            "stdio_rollback",
        ]

        assert project_path is not None
        expected_project_path = f"~/{project_path.relative_to(Path.home())}"
        for command_name in command_names:
            assert expected_project_path in supervised_service[command_name]["args"]
        assert expected_project_path in supervised_service["legacy_stdio_descriptors"][0][
            "args"
        ][-1]

    def test_pyproject_source_returns_clone_info(self):
        """pyproject.toml source URL derives clone_url, mcp_subdir, and deploy_path."""
        entry = {
            "source": "https://github.com/cognovis/library-core/blob/main/mcp-servers/cognovis-tools/pyproject.toml",
        }
        clone_url, mcp_subdir, deploy_path = _derive_deploy_path(entry, "cognovis-tools")

        assert clone_url == "https://github.com/cognovis/library-core.git"
        assert mcp_subdir == "mcp-servers/cognovis-tools"
        assert deploy_path is not None
        assert "cognovis-library-core" in str(deploy_path)

    def test_supervised_source_uses_dedicated_runtime_clone(self):
        entry = {
            "source": "https://github.com/cognovis/library-core/blob/main/mcp-servers/cognovis-tools/pyproject.toml",
            "supervised_local_service": {"url": "http://127.0.0.1:8765/mcp"},
        }

        _, _, deploy_path = _derive_deploy_path(entry, "cognovis-tools")

        assert deploy_path is not None
        assert deploy_path.parts[-3:] == (
            "mcp-servers",
            "cognovis-tools",
            "cognovis-library-core",
        )

    def test_mcp_yaml_source_returns_none(self):
        """mcp.yaml source URL returns (None, None, None) — no deploy clone needed."""
        entry = {
            "source": "https://github.com/sussdorff/open-brain/blob/main/mcp.yaml",
        }
        clone_url, mcp_subdir, deploy_path = _derive_deploy_path(entry, "open-brain")

        assert clone_url is None
        assert mcp_subdir is None
        assert deploy_path is None

    def test_no_source_returns_none(self):
        """Missing source field returns (None, None, None)."""
        entry = {}
        clone_url, mcp_subdir, deploy_path = _derive_deploy_path(entry, "test-mcp")

        assert clone_url is None
        assert mcp_subdir is None
        assert deploy_path is None
