#!/usr/bin/env python3
"""Focused tests for supervised HTTP MCP install (clc-g5ky platform half)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURE_STDIO_SERVER = Path(__file__).resolve().parent / "fixtures" / "minimal_mcp_stdio_server.py"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.errors import InstallError  # noqa: E402
from lib.installers import mcp_installer  # noqa: E402
from lib.installers.mcp_installer import (  # noqa: E402
    _remove_from_harness,
    install_mcp,
    remove_mcp,
)


HTTP_URL = "http://127.0.0.1:8765/mcp"
PROJECT_SUFFIX = "mcp-servers/cognovis-tools"


def test_remove_dispatch_reports_handler_failure() -> None:
    handler = MagicMock(side_effect=SystemExit(2))
    module = MagicMock(install_claude_code=handler)

    assert _remove_from_harness(module, "cognovis-tools", "claude_code") == 2


def test_remove_dispatch_reports_manual_url_removal_as_failure() -> None:
    handler = MagicMock(return_value=1)
    module = MagicMock(install_url_only=handler)

    assert _remove_from_harness(module, "cognovis-tools", "claude_ai") == 1
    handler.assert_called_once_with(
        "cognovis-tools",
        {},
        dry_run=False,
        remove=True,
        harness="claude_ai",
    )


def test_import_failure_restores_environment_overrides(
    tmp_env: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "CLAUDE_SETTINGS_FILE"
    monkeypatch.setenv(key, "before")
    monkeypatch.setattr(
        mcp_installer,
        "ensure_mcp_deploy_clone",
        lambda **kwargs: tmp_env["deploy_path"],
    )

    def fail_import() -> object:
        raise ImportError("broken install helper")

    monkeypatch.setattr(mcp_installer, "_import_install_mcp", fail_import)

    with pytest.raises(InstallError, match="broken install helper"):
        install_mcp(
            tmp_env["catalog"],
            "cognovis-tools",
            tmp_env["tmp_path"],
            harness="claude_code",
            env_overrides={key: "temporary"},
        )

    assert os.environ[key] == "before"


def _make_supervised_catalog(project_path: Path, *, stdio_command: str = "uv") -> dict:
    project = str(project_path)
    stdio_args = [
        "run",
        "--project",
        project,
        "python",
        str(FIXTURE_STDIO_SERVER),
    ]
    if stdio_command != "uv":
        stdio_args = [str(FIXTURE_STDIO_SERVER)]

    return {
        "library": {
            "mcp_servers": [
                {
                    "name": "cognovis-tools",
                    "description": "Supervised test MCP entry",
                    "source": (
                        "https://github.com/cognovis/library-core/blob/main/"
                        f"{PROJECT_SUFFIX}/pyproject.toml"
                    ),
                    "species": "library-tool-surface",
                    "coding_strategy": "mcp",
                    "capabilities": {
                        "stateless": False,
                        "streaming": True,
                        "auth": "none",
                    },
                    "supervised_local_service": {
                        "url": HTTP_URL,
                        "health_url": "http://127.0.0.1:8765/health",
                        "install": {
                            "command": "echo",
                            "args": ["install-ok"],
                        },
                        "start": {
                            "command": "echo",
                            "args": ["start-ok"],
                        },
                        "health_check": {
                            "command": "echo",
                            "args": [
                                json.dumps(
                                    {
                                        "state": "healthy",
                                        "message": "ok",
                                        "version": "test:1",
                                    }
                                )
                            ],
                        },
                        "restart": {
                            "command": "echo",
                            "args": [
                                json.dumps(
                                    {
                                        "state": "healthy",
                                        "message": "restarted",
                                        "version": "test:2",
                                    }
                                )
                            ],
                        },
                        "stop": {
                            "command": "echo",
                            "args": ["stop-ok"],
                        },
                        "uninstall": {
                            "command": "echo",
                            "args": ["uninstall-ok"],
                        },
                        "stdio_rollback": {
                            "type": "stdio",
                            "command": stdio_command,
                            "args": stdio_args,
                        },
                        "legacy_stdio_descriptors": [
                            {
                                "type": "stdio",
                                "command": "sh",
                                "args": ["-c", "legacy-cognovis-tools"],
                            }
                        ],
                    },
                    "install": {
                        "mcp": {
                            "claude_code": {
                                "config_path": "~/.claude.json",
                                "snippet": {"type": "http", "url": HTTP_URL},
                            },
                            "codex": {
                                "config_path": "~/.codex/config.toml",
                                "snippet": {"url": HTTP_URL},
                            },
                            "antigravity": {
                                "config_path": "~/.gemini/config/mcp_config.json",
                                "snippet": {"type": "http", "url": HTTP_URL},
                            },
                            "cursor": {
                                "config_path": "~/.cursor/mcp.json",
                                "snippet": {"type": "http", "url": HTTP_URL},
                            },
                        }
                    },
                }
            ]
        },
        "default_dirs": {"skills": [{"default": ".agents/skills/"}]},
        "marketplaces": [],
        "sources": {"marketplaces": []},
    }


def _env_for_configs(tmp_path: Path) -> dict[str, str]:
    return {
        "CLAUDE_SETTINGS_FILE": str(tmp_path / "claude.json"),
        "CODEX_CONFIG_FILE": str(tmp_path / "codex.toml"),
        "GEMINI_SETTINGS_FILE": str(tmp_path / "gemini.json"),
        "CURSOR_MCP_FILE": str(tmp_path / "cursor.json"),
    }


def _seed_prior_config(path: Path, name: str, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".toml":
        path.write_text(f'[mcp_servers.{name}]\n_origin = "manual"\n')
    else:
        path.write_text(json.dumps({"mcpServers": {name: payload}}))


def _mcp_stdio_handshake(command: str, args: list[str]) -> None:
    proc = subprocess.Popen(
        [command, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    assert proc.stdin and proc.stdout

    def send(payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8"))
        proc.stdin.write(body)
        proc.stdin.flush()

    def read() -> dict:
        headers: dict[str, str] = {}
        while True:
            line = proc.stdout.readline().decode("utf-8").strip()
            if not line:
                break
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        length = int(headers["content-length"])
        body = proc.stdout.read(length)
        return json.loads(body.decode("utf-8"))

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.0.1"},
            },
        }
    )
    init_result = read()
    assert "result" in init_result

    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools_result = read()
    tool_names = {tool["name"] for tool in tools_result["result"]["tools"]}
    assert "echo" in tool_names

    send(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"value": "ping"}},
        }
    )
    call_result = read()
    assert "echo" in call_result["result"]["content"][0]["text"]
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def tmp_env(tmp_path: Path):
    deploy_path = tmp_path / "cognovis-library-core"
    project_path = deploy_path / PROJECT_SUFFIX
    project_path.mkdir(parents=True)
    (project_path / "pyproject.toml").write_text("[project]\nname='cognovis-tools'\n")
    catalog = _make_supervised_catalog(project_path)
    env = _env_for_configs(tmp_path / "configs")
    yield {
        "tmp_path": tmp_path,
        "deploy_path": deploy_path,
        "project_path": project_path,
        "catalog": catalog,
        "env": env,
    }


def test_library_yaml_declares_four_exact_http_snippets():
    library = yaml.safe_load((REPO_ROOT / "library.yaml").read_text())
    entry = next(
        item for item in library["library"]["mcp_servers"] if item["name"] == "cognovis-tools"
    )
    snippets = entry["install"]["mcp"]
    assert snippets["claude_code"]["snippet"] == {"type": "http", "url": HTTP_URL}
    assert snippets["codex"]["snippet"] == {"url": HTTP_URL}
    assert snippets["antigravity"]["snippet"] == {"type": "http", "url": HTTP_URL}
    assert snippets["cursor"]["snippet"] == {"type": "http", "url": HTTP_URL}
    assert entry["capabilities"]["stateless"] is False
    assert entry["capabilities"]["streaming"] is True
    assert entry["supervised_local_service"]["stdio_rollback"]["type"] == "stdio"


@patch("lib.installers.mcp_installer.ensure_mcp_deploy_clone")
def test_service_before_registration(mock_clone, tmp_env):
    mock_clone.return_value = tmp_env["deploy_path"]
    with patch(
        "lib.installers.mcp_supervised_service.service_status",
        side_effect=[
            {"state": "unhealthy"},
            {"state": "healthy", "version": "test:1"},
        ],
    ):
        with patch(
            "lib.installers.mcp_supervised_service.run_argv_command",
            return_value=MagicMock(returncode=0, stdout="", stderr=""),
        ) as mock_run:
            result = install_mcp(
                tmp_env["catalog"],
                "cognovis-tools",
                tmp_env["tmp_path"],
                harness="claude_code",
                env_overrides=tmp_env["env"],
            )
    assert result["status"] == "ok"
    assert mock_run.call_count >= 1
    claude = json.loads(Path(tmp_env["env"]["CLAUDE_SETTINGS_FILE"]).read_text())
    assert claude["mcpServers"]["cognovis-tools"]["url"] == HTTP_URL


@patch("lib.installers.mcp_installer.ensure_mcp_deploy_clone")
def test_service_failure_writes_no_registration(mock_clone, tmp_env):
    mock_clone.return_value = tmp_env["deploy_path"]
    claude_path = Path(tmp_env["env"]["CLAUDE_SETTINGS_FILE"])
    _seed_prior_config(
        claude_path,
        "cognovis-tools",
        {"type": "stdio", "command": "uv", "args": ["run", "legacy"]},
    )
    before = claude_path.read_text(encoding="utf-8")
    with patch(
        "lib.installers.mcp_supervised_service.service_status",
        return_value={"state": "unhealthy"},
    ):
        with patch(
            "lib.installers.mcp_supervised_service.run_argv_command",
            side_effect=[
                MagicMock(returncode=1, stdout="", stderr="install failed"),
                MagicMock(returncode=0, stdout="", stderr=""),
            ],
        ) as run_command:
                with pytest.raises(InstallError, match="install failed"):
                    install_mcp(
                        tmp_env["catalog"],
                        "cognovis-tools",
                        tmp_env["tmp_path"],
                        harness="claude_code",
                        env_overrides=tmp_env["env"],
                    )
    assert run_command.call_args_list[-1].args[0]["args"] == ["uninstall-ok"]
    assert claude_path.read_text(encoding="utf-8") == before
    claude = json.loads(claude_path.read_text())
    entry = claude["mcpServers"]["cognovis-tools"]
    assert entry.get("type") == "stdio"
    assert "url" not in entry


@patch("lib.installers.mcp_installer.ensure_mcp_deploy_clone")
def test_known_legacy_stdio_descriptors_are_adopted(mock_clone, tmp_env):
    mock_clone.return_value = tmp_env["deploy_path"]
    claude_path = Path(tmp_env["env"]["CLAUDE_SETTINGS_FILE"])
    codex_path = Path(tmp_env["env"]["CODEX_CONFIG_FILE"])
    _seed_prior_config(
        claude_path,
        "cognovis-tools",
        {"type": "stdio", "command": "sh", "args": ["-c", "legacy-cognovis-tools"]},
    )
    codex_path.parent.mkdir(parents=True, exist_ok=True)
    codex_path.write_text(
        '[mcp_servers.cognovis-tools]\ncommand = "sh"\nargs = ["-c", "legacy-cognovis-tools"]\n',
        encoding="utf-8",
    )

    with patch(
        "lib.installers.mcp_supervised_service.service_status",
        side_effect=[
            {"state": "unhealthy"},
            {"state": "healthy", "version": "test:1"},
        ],
    ):
        with patch(
            "lib.installers.mcp_supervised_service.run_argv_command",
            return_value=MagicMock(returncode=0, stdout="", stderr=""),
        ):
            result = install_mcp(
                tmp_env["catalog"],
                "cognovis-tools",
                tmp_env["tmp_path"],
                harness="all",
                env_overrides=tmp_env["env"],
            )

    assert result["status"] == "ok"
    claude = json.loads(claude_path.read_text(encoding="utf-8"))
    assert claude["mcpServers"]["cognovis-tools"]["url"] == HTTP_URL
    assert claude["mcpServers"]["cognovis-tools"]["_origin"] == (
        "library:mcp:cognovis-tools"
    )
    codex = codex_path.read_text(encoding="utf-8")
    assert f'url = "{HTTP_URL}"' in codex
    assert '_origin = "library:mcp:cognovis-tools"' in codex


@patch("lib.installers.mcp_installer.ensure_mcp_deploy_clone")
def test_config_failure_uninstalls_newly_created_service(mock_clone, tmp_env):
    mock_clone.return_value = tmp_env["deploy_path"]
    with patch(
        "lib.installers.mcp_installer.ensure_supervised_service",
        return_value={"action": "install", "state": "healthy", "version": "test:1"},
    ):
        with patch(
            "lib.installers.mcp_installer._install_to_harness",
            return_value=1,
        ):
            with patch(
                "lib.installers.mcp_installer.uninstall_supervised_service"
            ) as uninstall:
                with pytest.raises(InstallError):
                    install_mcp(
                        tmp_env["catalog"],
                        "cognovis-tools",
                        tmp_env["tmp_path"],
                        harness="claude_code",
                        env_overrides=tmp_env["env"],
                    )

    uninstall.assert_called_once_with(
        tmp_env["catalog"]["library"]["mcp_servers"][0],
        tmp_env["project_path"],
        dry_run=False,
    )


@patch("lib.installers.mcp_installer.ensure_mcp_deploy_clone")
def test_partial_harness_failure_restores_exact_snapshots(mock_clone, tmp_env):
    mock_clone.return_value = tmp_env["deploy_path"]
    claude_path = Path(tmp_env["env"]["CLAUDE_SETTINGS_FILE"])
    codex_path = Path(tmp_env["env"]["CODEX_CONFIG_FILE"])
    claude_path.parent.mkdir(parents=True, exist_ok=True)
    claude_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cognovis-tools": {
                        "type": "stdio",
                        "command": "uv",
                        "args": ["run", "legacy"],
                    },
                    "manual-server": {"type": "stdio", "command": "keep"},
                }
            }
        ),
        encoding="utf-8",
    )
    _seed_prior_config(codex_path, "manual-server", {"command": "keep"})
    claude_before = claude_path.read_text(encoding="utf-8")
    codex_before = codex_path.read_text(encoding="utf-8")

    original_install = __import__(
        "lib.installers.mcp_installer", fromlist=["_install_to_harness"]
    )._install_to_harness

    def flaky_install(mod, name, block, harness, dry_run=False):
        if harness == "codex":
            return 1
        return original_install(mod, name, block, harness, dry_run=dry_run)

    with patch(
        "lib.installers.mcp_supervised_service.run_argv_command",
        return_value=MagicMock(
            returncode=0,
            stdout='{"state":"healthy","version":"test:1"}',
            stderr="",
        ),
    ):
        with patch("lib.installers.mcp_installer._install_to_harness", side_effect=flaky_install):
            with pytest.raises(InstallError):
                install_mcp(
                    tmp_env["catalog"],
                    "cognovis-tools",
                    tmp_env["tmp_path"],
                    harness="all",
                    env_overrides=tmp_env["env"],
                )

    assert claude_path.read_text(encoding="utf-8") == claude_before
    assert codex_path.read_text(encoding="utf-8") == codex_before
    restored = json.loads(claude_path.read_text())
    assert restored["mcpServers"]["manual-server"]["command"] == "keep"
    claude_entry = restored["mcpServers"].get("cognovis-tools", {})
    assert claude_entry.get("type") == "stdio"


@patch("lib.installers.mcp_installer.ensure_mcp_deploy_clone")
def test_idempotent_reinstall_restarts_service(mock_clone, tmp_env):
    mock_clone.return_value = tmp_env["deploy_path"]
    statuses = iter(
        [
            {"state": "healthy", "version": "v1"},
            {"state": "healthy", "version": "v2"},
            {"state": "healthy", "version": "v1"},
            {"state": "healthy", "version": "v2"},
        ]
    )

    def next_status(command_block):
        return next(statuses)

    with patch(
        "lib.installers.mcp_supervised_service.service_status",
        side_effect=next_status,
    ):
        with patch(
            "lib.installers.mcp_supervised_service.run_argv_command",
            return_value=MagicMock(returncode=0, stdout="", stderr=""),
        ):
            install_mcp(
                tmp_env["catalog"],
                "cognovis-tools",
                tmp_env["tmp_path"],
                harness="all",
                env_overrides=tmp_env["env"],
            )
            install_mcp(
                tmp_env["catalog"],
                "cognovis-tools",
                tmp_env["tmp_path"],
                harness="all",
                env_overrides=tmp_env["env"],
            )


@patch("lib.installers.mcp_installer.ensure_mcp_deploy_clone")
def test_uninstall_removes_owned_registration_and_service(mock_clone, tmp_env):
    mock_clone.return_value = tmp_env["deploy_path"]
    with patch(
        "lib.installers.mcp_supervised_service.service_status",
        side_effect=[
            {"state": "unhealthy"},
            {"state": "healthy", "version": "test:1"},
        ],
    ):
        with patch(
            "lib.installers.mcp_supervised_service.run_argv_command",
            return_value=MagicMock(returncode=0, stdout="", stderr=""),
        ):
            install_mcp(
                tmp_env["catalog"],
                "cognovis-tools",
                tmp_env["tmp_path"],
                harness="all",
                env_overrides=tmp_env["env"],
            )
    with patch("lib.installers.mcp_supervised_service.run_argv_command") as mock_run:
        remove_mcp(
            tmp_env["catalog"],
            "cognovis-tools",
            tmp_env["tmp_path"],
            harness="all",
            env_overrides=tmp_env["env"],
        )
        assert mock_run.call_count >= 2
    for key in ("CLAUDE_SETTINGS_FILE", "GEMINI_SETTINGS_FILE", "CURSOR_MCP_FILE"):
        data = json.loads(Path(tmp_env["env"][key]).read_text())
        assert "cognovis-tools" not in data.get("mcpServers", {})


@patch("lib.installers.mcp_installer.ensure_mcp_deploy_clone")
def test_dry_run_reports_service_and_registration_actions(mock_clone, tmp_env):
    mock_clone.return_value = tmp_env["deploy_path"]
    with patch(
        "lib.installers.mcp_supervised_service.run_argv_command",
        return_value=MagicMock(
            returncode=0,
            stdout='{"state":"healthy","version":"test:1"}',
            stderr="",
        ),
    ):
        result = install_mcp(
            tmp_env["catalog"],
            "cognovis-tools",
            tmp_env["tmp_path"],
            dry_run=True,
            harness="all",
            env_overrides=tmp_env["env"],
        )
    ops = {op["operation"] for op in result["operations"]}
    assert "clone_mcp_source" in ops
    assert "supervised_service" in ops
    assert "install_mcp_server" in ops


@patch("lib.installers.mcp_installer.ensure_mcp_deploy_clone")
def test_four_harness_outputs_are_exact(mock_clone, tmp_env):
    mock_clone.return_value = tmp_env["deploy_path"]
    with patch(
        "lib.installers.mcp_supervised_service.service_status",
        side_effect=[
            {"state": "unhealthy"},
            {"state": "healthy", "version": "test:1"},
        ],
    ):
        with patch(
            "lib.installers.mcp_supervised_service.run_argv_command",
            return_value=MagicMock(returncode=0, stdout="", stderr=""),
        ):
            install_mcp(
                tmp_env["catalog"],
                "cognovis-tools",
                tmp_env["tmp_path"],
                harness="all",
                env_overrides=tmp_env["env"],
            )

    claude = json.loads(Path(tmp_env["env"]["CLAUDE_SETTINGS_FILE"]).read_text())
    assert claude["mcpServers"]["cognovis-tools"] == {
        "type": "http",
        "url": HTTP_URL,
        "_origin": "library:mcp:cognovis-tools",
    }

    codex = Path(tmp_env["env"]["CODEX_CONFIG_FILE"]).read_text()
    assert 'url = "http://127.0.0.1:8765/mcp"' in codex
    assert '_origin = "library:mcp:cognovis-tools"' in codex

    antigravity = json.loads(Path(tmp_env["env"]["GEMINI_SETTINGS_FILE"]).read_text())
    assert antigravity["mcpServers"]["cognovis-tools"] == {
        "type": "http",
        "url": HTTP_URL,
        "_origin": "library:mcp:cognovis-tools",
    }

    cursor = json.loads(Path(tmp_env["env"]["CURSOR_MCP_FILE"]).read_text())
    assert cursor["mcpServers"]["cognovis-tools"] == {
        "type": "http",
        "url": HTTP_URL,
        "_origin": "library:mcp:cognovis-tools",
    }


@patch("lib.installers.mcp_installer.ensure_mcp_deploy_clone")
def test_stdio_rollback_writes_descriptor_and_handshake(mock_clone, tmp_env):
    mock_clone.return_value = tmp_env["deploy_path"]
    catalog = _make_supervised_catalog(tmp_env["project_path"], stdio_command=sys.executable)
    catalog["library"]["mcp_servers"][0]["supervised_local_service"]["stdio_rollback"] = {
        "type": "stdio",
        "command": sys.executable,
        "args": [str(FIXTURE_STDIO_SERVER)],
    }
    with patch("lib.installers.mcp_installer.stop_supervised_service") as stop:
        result = install_mcp(
            catalog,
            "cognovis-tools",
            tmp_env["tmp_path"],
            harness="all",
            env_overrides=tmp_env["env"],
            rollback_stdio=True,
        )
    stop.assert_called_once_with(
        catalog["library"]["mcp_servers"][0],
        tmp_env["project_path"],
        dry_run=False,
    )
    assert result["data"]["transport"] == "stdio"
    claude = json.loads(Path(tmp_env["env"]["CLAUDE_SETTINGS_FILE"]).read_text())
    entry = claude["mcpServers"]["cognovis-tools"]
    assert entry["type"] == "stdio"
    _mcp_stdio_handshake(entry["command"], entry["args"])


@patch("lib.installers.mcp_installer.ensure_mcp_deploy_clone")
def test_stdio_rollback_config_failure_does_not_stop_service(mock_clone, tmp_env):
    mock_clone.return_value = tmp_env["deploy_path"]
    with patch(
        "lib.installers.mcp_installer._install_to_harness",
        return_value=1,
    ):
        with patch("lib.installers.mcp_installer.stop_supervised_service") as stop:
            with pytest.raises(InstallError):
                install_mcp(
                    tmp_env["catalog"],
                    "cognovis-tools",
                    tmp_env["tmp_path"],
                    harness="all",
                    env_overrides=tmp_env["env"],
                    rollback_stdio=True,
                )

    stop.assert_not_called()
