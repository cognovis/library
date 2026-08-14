"""Public CLI coverage for ADR-0012's project-only lifecycle boundary."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY = REPO_ROOT / "scripts" / "library.py"


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    return subprocess.run(
        ["uv", "run", str(LIBRARY), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _init_git_repository(path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)


@pytest.mark.parametrize(
    "arguments",
    [
        ("skill", "use", "fixture", "--scope", "global"),
        ("skill", "remove", "fixture", "--scope", "global"),
        ("skill", "sync", "--scope", "global"),
        ("skill", "audit", "--scope", "global"),
        ("workspace", "use", "fixture", "--scope", "global"),
        ("workspace", "status", "--all", "--scope", "global"),
        ("workspace", "sync", "--all", "--scope", "global"),
        ("workspace", "remove", "fixture", "--scope", "global"),
        ("audit", "--scope", "global"),
        ("status", "--scope", "global"),
        ("sync", "--scope", "global"),
    ],
)
@pytest.mark.parametrize("json_mode", [False, True])
def test_global_scope_is_rejected_before_catalog_or_filesystem_mutation(
    tmp_path: Path, arguments: tuple[str, ...], json_mode: bool
) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("unchanged", encoding="utf-8")
    command = (*arguments, "--json") if json_mode else arguments

    result = _run(tmp_path, *command)

    assert result.returncode == 1
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    if json_mode:
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["message"] == "Global Library desired state is not supported; use the current Git repository."
    else:
        assert result.stderr.endswith(
            "Error: Global Library desired state is not supported; use the current Git repository.\n"
        )


@pytest.mark.parametrize("json_mode", [False, True])
def test_init_uses_the_tool_catalog_when_a_repository_catalog_lacks_the_workspace(
    tmp_path: Path, json_mode: bool
) -> None:
    _init_git_repository(tmp_path)
    (tmp_path / "library.yaml").write_text("library: {}\n", encoding="utf-8")
    command = ("init", "--json") if json_mode else ("init",)

    result = _run(tmp_path, *command)

    assert result.returncode == 0, result.stderr or result.stdout
    assert (tmp_path / ".library.lock").exists()
    assert (tmp_path / ".gitignore").exists()
    if json_mode:
        assert json.loads(result.stdout)["status"] == "applied"
    else:
        assert "Workspace use: applied" in result.stdout


@pytest.mark.parametrize(
    "primitive",
    [
        "skill", "agent", "prompt", "script", "standard", "guardrail", "mcp",
        "model-standard", "agent-base", "workflow", "pi-extension", "pi-profile",
        "just-module", "runtime-config",
    ],
)
@pytest.mark.parametrize("json_mode", [False, True])
def test_every_public_primitive_lifecycle_rejects_global_scope_before_lookup(
    tmp_path: Path, primitive: str, json_mode: bool
) -> None:
    arguments = [primitive, "use", "fixture"]
    arguments.extend(["--scope", "global"])
    if json_mode:
        arguments.append("--json")

    result = _run(tmp_path, *arguments)

    assert result.returncode == 1
    if json_mode:
        assert json.loads(result.stdout)["message"] == (
            "Global Library desired state is not supported; use the current Git repository."
        )
    else:
        assert PROJECT_ONLY_ERROR in result.stderr


@pytest.mark.parametrize("json_mode", [False, True])
def test_mcp_lifecycle_is_retired_without_writing_global_desired_state(
    tmp_path: Path, json_mode: bool
) -> None:
    _init_git_repository(tmp_path)
    (tmp_path / "library.yaml").write_text(
        """library:
  mcp_servers:
    - name: fixture
      description: Fixture MCP server
      install:
        mcp:
          claude_code:
            snippet: {type: http, url: https://example.invalid/mcp}
marketplaces: []
guardrails: []
model_standards: []
""",
        encoding="utf-8",
    )
    arguments = ["mcp", "use", "fixture", "--dry-run"]
    if json_mode:
        arguments.append("--json")

    result = _run(tmp_path, *arguments)

    assert result.returncode == 1
    assert not (tmp_path / "home" / ".config" / "library" / "global.lock").exists()
    if json_mode:
        assert json.loads(result.stdout)["message"] == (
            "MCP registration lifecycle is retired. The supported OpenBrain singleton is "
            "managed by `library bootstrap install`; `library mcp remove <name> --scope "
            "project` only removes a legacy project lock record."
        )
    else:
        assert "MCP registration lifecycle is retired" in result.stderr


PROJECT_ONLY_ERROR = "Global Library desired state is not supported; use the current Git repository."
