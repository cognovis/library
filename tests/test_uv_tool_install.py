"""The control plane is distributable as a uv tool, not a global Library skill."""

from __future__ import annotations

import os
import subprocess
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_uv_tool_install_exposes_the_bootstrap_console_scripts_without_source_links(
    tmp_path: Path,
) -> None:
    tool_dir = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    env = os.environ.copy()
    env["UV_TOOL_DIR"] = str(tool_dir)
    env["UV_TOOL_BIN_DIR"] = str(bin_dir)

    install = subprocess.run(
        ["uv", "tool", "install", str(REPO_ROOT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    version = subprocess.run(
        [str(bin_dir / "library"), "--version"], env=env, capture_output=True,
        text=True, check=False,
    )

    assert install.returncode == 0, install.stderr
    assert version.returncode == 0, version.stderr
    assert version.stdout.startswith("library 2.0.0")
    for command in ("library", "cld", "cdx"):
        executable = bin_dir / command
        assert executable.is_file()
        assert not executable.resolve().is_relative_to(REPO_ROOT)
    assert not (tool_dir / "library" / ".agents" / "skills" / "library").exists()


def test_uv_tool_install_carries_the_catalog_for_commands_outside_a_checkout(
    tmp_path: Path,
) -> None:
    tool_dir = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    env = os.environ.copy()
    env["UV_TOOL_DIR"] = str(tool_dir)
    env["UV_TOOL_BIN_DIR"] = str(bin_dir)

    install = subprocess.run(
        ["uv", "tool", "install", str(REPO_ROOT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    listed = subprocess.run(
        [str(bin_dir / "library"), "skill", "list", "--json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert install.returncode == 0, install.stderr
    assert listed.returncode == 0, listed.stderr
    assert isinstance(json.loads(listed.stdout), list)

    initialized = subprocess.run(
        [str(bin_dir / "library"), "init", "--json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert initialized.returncode == 2
    assert json.loads(initialized.stdout) == {
        "status": "error",
        "message": "Canonical Workspace 'cognovis-base' is unavailable in the selected catalog.",
        "exit_code": 2,
    }

    workspaces = subprocess.run(
        [str(bin_dir / "library"), "workspace", "list", "--json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert workspaces.returncode == 0, workspaces.stderr
    assert json.loads(workspaces.stdout)["workspaces"]


def test_bootstrap_install_writes_only_the_enumerated_global_contract(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    installed = subprocess.run(
        ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr or installed.stdout
    assert (home / ".agents" / "AGENTS.md").is_file()
    assert (home / ".claude" / "CLAUDE.md").is_file()
    assert (home / ".agents" / "orchestrator-config.yml").is_file()
    assert (home / ".claude.json").is_file()
    assert (home / ".codex" / "config.toml").is_file()
    assert (home / ".pi" / "settings.json").is_file()
    assert "open-brain" in (home / ".codex" / "config.toml").read_text()
    assert "open-brain" in (home / ".claude.json").read_text()
    assert "open-brain" in (home / ".pi" / "settings.json").read_text()
    assert (home / ".config" / "library" / "bootstrap.json").is_file()
    assert not (home / ".agents" / "skills" / "library").exists()
    assert json.loads(installed.stdout)["status"] == "ok"


def test_bootstrap_install_adopts_existing_operator_owned_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    agents = home / ".agents" / "AGENTS.md"
    runtime = home / ".agents" / "orchestrator-config.yml"
    claude = home / ".claude" / "CLAUDE.md"
    for path, text in (
        (agents, "# Operator rules\n"),
        (runtime, "default_profile: operator\n"),
        (claude, "# Operator Claude rules\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    result = subprocess.run(
        ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert agents.read_text(encoding="utf-8") == "# Operator rules\n"
    assert runtime.read_text(encoding="utf-8") == "default_profile: operator\n"
    assert claude.read_text(encoding="utf-8") == "# Operator Claude rules\n"
    payload = json.loads(result.stdout)
    assert payload["conflicts"] == []
    assert (home / ".config" / "library" / "bootstrap.json").is_file()

    status = subprocess.run(
        ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap", "status", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert status.returncode == 0
    assert json.loads(status.stdout)["bootstrap"] == {"status": "ready", "missing": []}


def test_bootstrap_install_adopts_library_origin_mcp_registrations(tmp_path: Path) -> None:
    home = tmp_path / "home"
    claude_config = home / ".claude.json"
    codex_config = home / ".codex" / "config.toml"
    codex_config.parent.mkdir(parents=True)
    claude_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "open-brain": {
                        "type": "http",
                        "url": "https://open-brain.sussdorff.org/mcp",
                        "_origin": "library:mcp:open-brain",
                    },
                    "operator-server": {"type": "http", "url": "https://operator.example/mcp"},
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    codex_config.write_text(
        "model = \"operator-model\"\n\n"
        "[mcp_servers.open-brain]\n"
        "url = \"https://open-brain.sussdorff.org/mcp\"\n"
        "_origin = \"library:mcp:open-brain\"\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    result = subprocess.run(
        ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["conflicts"] == []
    assert (home / ".config" / "library" / "bootstrap.json").is_file()
    assert json.loads(claude_config.read_text(encoding="utf-8"))["mcpServers"]["operator-server"] == {
        "type": "http",
        "url": "https://operator.example/mcp",
    }
    assert "model = \"operator-model\"" in codex_config.read_text(encoding="utf-8")


def test_bootstrap_install_preflights_mcp_configs_before_any_mutation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    codex_config = home / ".codex" / "config.toml"
    codex_config.parent.mkdir(parents=True)
    codex_config.write_text("not valid = [toml\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    result = subprocess.run(
        ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["conflicts"] == ["openbrain_codex"]
    assert not (home / ".agents" / "AGENTS.md").exists()
    assert not (home / ".claude" / "CLAUDE.md").exists()
    assert not (home / ".agents" / "orchestrator-config.yml").exists()
    assert not (home / ".config" / "library" / "bootstrap.json").exists()


def test_bootstrap_remove_refuses_drifted_mcp_configuration(tmp_path: Path) -> None:
    home = tmp_path / "home"
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    command = ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap"]

    installed = subprocess.run(
        [*command, "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    codex_config = home / ".codex" / "config.toml"
    codex_config.write_text(
        "[mcp_servers.open-brain]\nurl = \"https://operator.example/mcp\"\n",
        encoding="utf-8",
    )
    removed = subprocess.run(
        [*command, "remove", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr
    assert removed.returncode == 2
    assert json.loads(removed.stdout)["conflicts"] == ["openbrain_codex"]
    assert (home / ".agents" / "AGENTS.md").is_file()
    assert (home / ".config" / "library" / "bootstrap.json").is_file()


def test_status_uses_the_bootstrap_manifest_to_report_mcp_drift(tmp_path: Path) -> None:
    home = tmp_path / "home"
    command_dir = tmp_path / "commands"
    command_dir.mkdir()
    for command in ("library", "cld", "cdx"):
        executable = command_dir / command
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    command = ["uv", "run", str(REPO_ROOT / "scripts" / "library.py")]

    installed = subprocess.run(
        [*command, "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    status_environment = environment | {"PATH": f"{command_dir}{os.pathsep}{environment['PATH']}"}
    ready = subprocess.run(
        [*command, "status", "--offline", "--json"],
        cwd=REPO_ROOT,
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    (home / ".pi" / "settings.json").write_text("{}\n", encoding="utf-8")
    drifted = subprocess.run(
        [*command, "status", "--offline", "--json"],
        cwd=REPO_ROOT,
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr
    assert json.loads(ready.stdout)["health"]["bootstrap"] == {
        "status": "ready",
        "missing": [],
    }
    assert json.loads(drifted.stdout)["health"]["bootstrap"] == {
        "status": "repair_available",
        "missing": ["openbrain_pi"],
    }


def test_bootstrap_status_and_repository_status_share_operator_safe_health(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    command_dir = tmp_path / "commands"
    command_dir.mkdir()
    for command_name in ("library", "cld", "cdx"):
        executable = command_dir / command_name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    status_environment = environment | {"PATH": f"{command_dir}{os.pathsep}{environment['PATH']}"}
    command = ["uv", "run", str(REPO_ROOT / "scripts" / "library.py")]

    installed = subprocess.run(
        [*command, "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    for path, content in (
        (home / ".agents" / "AGENTS.md", "# Operator rules\n"),
        (home / ".claude" / "CLAUDE.md", "# Operator Claude rules\n"),
        (home / ".agents" / "orchestrator-config.yml", "default_profile: operator\n"),
    ):
        path.write_text(content, encoding="utf-8")
    bootstrap_ready = subprocess.run(
        [*command, "bootstrap", "status", "--json"],
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    repository_ready = subprocess.run(
        [*command, "status", "--offline", "--json"],
        cwd=REPO_ROOT,
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    (home / ".pi" / "settings.json").write_text("{}\n", encoding="utf-8")
    bootstrap_drifted = subprocess.run(
        [*command, "bootstrap", "status", "--json"],
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    repository_drifted = subprocess.run(
        [*command, "status", "--offline", "--json"],
        cwd=REPO_ROOT,
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr
    assert bootstrap_ready.returncode == 0
    assert json.loads(bootstrap_ready.stdout)["bootstrap"] == {
        "status": "ready",
        "missing": [],
    }
    assert json.loads(repository_ready.stdout)["health"]["bootstrap"] == {
        "status": "ready",
        "missing": [],
    }
    assert bootstrap_drifted.returncode == 2
    assert json.loads(bootstrap_drifted.stdout)["bootstrap"] == {
        "status": "repair_available",
        "missing": ["openbrain_pi"],
    }
    assert json.loads(repository_drifted.stdout)["health"]["bootstrap"] == {
        "status": "repair_available",
        "missing": ["openbrain_pi"],
    }
