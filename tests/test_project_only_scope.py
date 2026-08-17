"""Public CLI coverage for ADR-0012's project-only lifecycle boundary.

Library operates on the current Git repository. There is no second, selectable
scope, so ``--scope`` is not an option the CLI offers: it is absent from every
subcommand help text, and a literally passed ``--scope`` is rejected by one
typed error before catalog, repository, or lockfile resolution.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY = REPO_ROOT / "scripts" / "library.py"

SCOPE_REJECTED_ERROR = (
    "`--scope` is not a Library option: Library manages the current Git "
    "repository only. Re-run the command without `--scope`."
)


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
        ("skill", "use", "fixture", "--scope", "project"),
        ("skill", "use", "fixture", "--scope=project"),
        ("skill", "remove", "fixture", "--scope", "global"),
        ("skill", "sync", "--scope", "global"),
        ("skill", "audit", "--scope", "global"),
        ("skill", "list", "--scope", "project"),
        ("workspace", "use", "fixture", "--scope", "global"),
        ("workspace", "use", "fixture", "--scope", "project"),
        ("workspace", "status", "--all", "--scope", "global"),
        ("workspace", "sync", "--all", "--scope", "project"),
        ("workspace", "remove", "fixture", "--scope", "global"),
        ("audit", "--scope", "global"),
        ("status", "--scope", "project"),
        ("sync", "--scope", "global"),
        ("installed", "--scope=project"),
    ],
)
@pytest.mark.parametrize("json_mode", [False, True])
def test_scope_is_rejected_before_catalog_or_filesystem_mutation(
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
        assert payload["message"] == SCOPE_REJECTED_ERROR
    else:
        assert result.stderr.endswith(f"Error: {SCOPE_REJECTED_ERROR}\n")


@pytest.mark.parametrize(
    "command",
    [
        ("--help",),
        ("skill", "--help"),
        ("skill", "use", "--help"),
        ("skill", "remove", "--help"),
        ("skill", "sync", "--help"),
        ("skill", "audit", "--help"),
        ("skill", "list", "--help"),
        ("workspace", "use", "--help"),
        ("workspace", "status", "--help"),
        ("workspace", "sync", "--help"),
        ("workspace", "explain", "--help"),
        ("workspace", "recover", "--help"),
        ("workspace", "adopt", "--help"),
        ("workspace", "remove", "--help"),
        ("workspace", "list", "--help"),
        ("workspace", "show", "--help"),
        ("audit", "--help"),
        ("status", "--help"),
        ("sync", "--help"),
        ("installed", "--help"),
        ("marketplace", "install", "--help"),
        ("marketplace", "status", "--help"),
        ("marketplace", "update", "--help"),
        ("marketplace", "update-approve", "--help"),
        ("admission", "grant", "--help"),
    ],
)
def test_no_subcommand_help_offers_a_scope_flag(
    tmp_path: Path, command: tuple[str, ...]
) -> None:
    result = _run(tmp_path, *command)

    assert result.returncode == 0, result.stderr
    assert "--scope" not in result.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ("workspace", "use", "fixture"),
        ("workspace", "status", "--all"),
        ("workspace", "sync", "--all"),
        ("workspace", "explain", "skill:fixture"),
        ("workspace", "remove", "fixture"),
        ("workspace", "recover",),
    ],
)
def test_workspace_verbs_are_flagless(tmp_path: Path, arguments: tuple[str, ...]) -> None:
    """A workspace verb no longer demands a scope selection to be well-formed."""
    _init_git_repository(tmp_path)

    result = _run(tmp_path, *arguments, "--json")

    # Argparse usage errors exit 2 with an empty stdout; a well-formed command
    # reaches the engine and reports a typed JSON result instead.
    assert "the following arguments are required: --scope" not in result.stderr
    assert result.stdout, result.stderr
    json.loads(result.stdout)


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
def test_every_public_primitive_lifecycle_rejects_a_scope_flag_before_lookup(
    tmp_path: Path, primitive: str, json_mode: bool
) -> None:
    arguments = [primitive, "use", "fixture", "--scope", "global"]
    if json_mode:
        arguments.append("--json")

    result = _run(tmp_path, *arguments)

    assert result.returncode == 1
    if json_mode:
        assert json.loads(result.stdout)["message"] == SCOPE_REJECTED_ERROR
    else:
        assert SCOPE_REJECTED_ERROR in result.stderr


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
            "MCP registration lifecycle is retired. The supported OpenBrain "
            "singleton is managed by `library bootstrap install`; "
            "`library mcp remove <name>` only removes a legacy project lock record."
        )
    else:
        assert "MCP registration lifecycle is retired" in result.stderr
