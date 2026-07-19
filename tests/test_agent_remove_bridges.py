"""remove_agent must delete what its own lockfile entry records, and say so honestly.

Guards clc-1fa0. Two defects observed on 2026-07-19 while removing an agent whose
source had been deleted:

1. The lockfile entry recorded a Codex bridge under `bridge_symlinks`, but the
   removal only deleted the conventionally-computed Claude target. Because the
   lockfile entry disappears with the removal, the orphan became invisible to
   `audit` and to a second `remove` while Codex still offered the agent.
2. `agent remove <name>` without `--scope` runs against project scope and printed
   `OK: Agent '<name>' removed.` even though nothing matched and nothing changed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

LIBRARY_SPEC = importlib.util.spec_from_file_location("library_py", SCRIPTS_DIR / "library.py")
LIBRARY_MODULE = importlib.util.module_from_spec(LIBRARY_SPEC)
LIBRARY_SPEC.loader.exec_module(LIBRARY_MODULE)

from lib.installers.agent import remove_agent  # noqa: E402
from lib.lockfile import find_lockfile, load_lockfile, save_lockfile  # noqa: E402


CATALOG = {
    "default_dirs": {
        "agents": [
            {"default": ".claude/agents/"},
            {"global": "~/.claude/agents/"},
        ]
    },
    "library": {"agents": [{"name": "demo-agent", "source": "unused"}]},
}


def _install_fixture(project: Path, *, with_bridge: bool = True) -> tuple[Path, Path]:
    """Create a Claude agent install plus a Codex bridge, recorded in the lockfile."""
    claude_dir = project / ".claude" / "agents"
    claude_dir.mkdir(parents=True, exist_ok=True)
    claude_target = claude_dir / "demo-agent.md"
    claude_target.write_text("---\nname: demo-agent\n---\n\nbody\n", encoding="utf-8")

    codex_dir = project / ".codex" / "agents"
    codex_dir.mkdir(parents=True, exist_ok=True)
    codex_target = codex_dir / "demo-agent.toml"
    codex_target.write_text('name = "demo-agent"\n', encoding="utf-8")

    lockfile_path = find_lockfile(project, global_scope=False)
    lock_data = load_lockfile(lockfile_path)
    lock_data.setdefault("installed", []).append(
        {
            "name": "demo-agent",
            "type": "agent",
            "marketplace": "local",
            "source": "unused",
            "install_target": str(claude_target),
            "bridge_symlinks": [f"{codex_target} -> {project / 'cache' / 'demo-agent.toml'}"]
            if with_bridge
            else [],
        }
    )
    save_lockfile(lockfile_path, lock_data)
    return claude_target, codex_target


def _codex_base(project: Path) -> Path:
    return project / ".codex" / "agents"


@pytest.fixture()
def project(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    root = tmp_path / "proj"
    root.mkdir()
    return root


# -- AC1: recorded bridges are removed --------------------------------------


def test_recorded_codex_bridge_is_removed(project: Path, monkeypatch):
    claude_target, codex_target = _install_fixture(project)
    monkeypatch.setattr(
        "lib.installers.agent._resolve_agent_base",
        lambda catalog, prim, scope, repo_root, harness: {
            "claude_code": repo_root / ".claude" / "agents",
            "codex": repo_root / ".codex" / "agents",
            "opencode": repo_root / ".opencode" / "agents",
        }[harness],
    )

    result = remove_agent(CATALOG, "demo-agent", repo_root=project, scope="project")

    assert result["status"] == "ok"
    assert not claude_target.exists()
    assert not codex_target.exists(), "lockfile-recorded Codex bridge survived the removal"
    assert str(codex_target) in result["data"]["removed_files"]


def test_no_orphan_remains_for_any_harness(project: Path, monkeypatch):
    """The whole point: after removal no harness still offers the agent."""
    _install_fixture(project)
    monkeypatch.setattr(
        "lib.installers.agent._resolve_agent_base",
        lambda catalog, prim, scope, repo_root, harness: repo_root
        / {"claude_code": ".claude", "codex": ".codex", "opencode": ".opencode"}[harness]
        / "agents",
    )

    remove_agent(CATALOG, "demo-agent", repo_root=project, scope="project")

    leftovers = [p for p in project.rglob("demo-agent.*") if "cache" not in p.parts]
    assert leftovers == [], f"orphaned agent files: {leftovers}"


# -- AC2: the dry-run plan matches the effect -------------------------------


def test_dry_run_plan_lists_every_path_the_real_removal_deletes(project: Path, monkeypatch):
    _install_fixture(project)
    monkeypatch.setattr(
        "lib.installers.agent._resolve_agent_base",
        lambda catalog, prim, scope, repo_root, harness: repo_root
        / {"claude_code": ".claude", "codex": ".codex", "opencode": ".opencode"}[harness]
        / "agents",
    )

    plan = remove_agent(CATALOG, "demo-agent", repo_root=project, scope="project", dry_run=True)
    planned = {
        op["path"] for op in plan["operations"] if op["operation"] == "delete"
    }

    result = remove_agent(CATALOG, "demo-agent", repo_root=project, scope="project")
    actually_removed = set(result["data"]["removed_files"])

    assert actually_removed <= planned, (
        "the real removal deleted paths the dry-run never showed: "
        f"{actually_removed - planned}"
    )


# -- AC3: a no-op reports honestly ------------------------------------------


def test_scope_mismatch_reports_error_instead_of_success(project: Path, monkeypatch):
    """The observed trap: a global install, removed with the default project scope."""
    monkeypatch.setattr(
        "lib.installers.agent._resolve_agent_base",
        lambda catalog, prim, scope, repo_root, harness: repo_root / ".claude" / "agents",
    )

    result = remove_agent(CATALOG, "never-installed", repo_root=project, scope="project")

    assert result["status"] == "error"
    assert "not installed in scope 'project'" in result["message"]
    assert "removed" not in result.get("message", "").replace("nothing was removed", "")


def test_successful_removal_still_reports_ok(project: Path, monkeypatch):
    _install_fixture(project, with_bridge=False)
    monkeypatch.setattr(
        "lib.installers.agent._resolve_agent_base",
        lambda catalog, prim, scope, repo_root, harness: repo_root / ".claude" / "agents",
    )

    result = remove_agent(CATALOG, "demo-agent", repo_root=project, scope="project")

    assert result["status"] == "ok"


# -- AC4: foreign or absent bridges are left alone --------------------------


def test_bridge_outside_managed_directories_is_preserved(project: Path, monkeypatch):
    _install_fixture(project, with_bridge=False)
    foreign = project / "somewhere-else" / "demo-agent.toml"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("operator owned\n", encoding="utf-8")

    lockfile_path = find_lockfile(project, global_scope=False)
    lock_data = load_lockfile(lockfile_path)
    lock_data["installed"][0]["bridge_symlinks"] = [f"{foreign} -> {project / 'cache'}"]
    save_lockfile(lockfile_path, lock_data)

    monkeypatch.setattr(
        "lib.installers.agent._resolve_agent_base",
        lambda catalog, prim, scope, repo_root, harness: repo_root
        / {"claude_code": ".claude", "codex": ".codex", "opencode": ".opencode"}[harness]
        / "agents",
    )

    result = remove_agent(CATALOG, "demo-agent", repo_root=project, scope="project")

    assert foreign.exists(), "a bridge outside managed directories must not be deleted"
    assert foreign.read_text(encoding="utf-8") == "operator owned\n"
    assert any("outside managed" in item for item in result["data"]["skipped_bridges"])


def test_already_absent_bridge_is_reported_not_fatal(project: Path, monkeypatch):
    claude_target, codex_target = _install_fixture(project)
    codex_target.unlink()
    monkeypatch.setattr(
        "lib.installers.agent._resolve_agent_base",
        lambda catalog, prim, scope, repo_root, harness: repo_root
        / {"claude_code": ".claude", "codex": ".codex", "opencode": ".opencode"}[harness]
        / "agents",
    )

    result = remove_agent(CATALOG, "demo-agent", repo_root=project, scope="project")

    assert result["status"] == "ok"
    assert any("already absent" in item for item in result["data"]["skipped_bridges"])
