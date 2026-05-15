#!/usr/bin/env python3
"""Tests for CL-uyp: unified installed view."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"
PYTHON = sys.executable


PROJECT_SHA = "1111111111111111111111111111111111111111"
GLOBAL_SHA = "2222222222222222222222222222222222222222"
REMOTE_SHA = "9999999999999999999999999999999999999999"


def run_library(*args: str, cwd: Path, home: Path, extra_env: dict[str, str] | None = None):
    """Run library.py with an isolated HOME."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [PYTHON, str(LIBRARY_PY), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def write_lockfile(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump({"installed": entries}))


def entry(
    name: str,
    primitive: str = "skill",
    source_commit: str = PROJECT_SHA,
    source: str = "/tmp/source/SKILL.md",
    timestamp: str = "2026-05-15T08:00:00Z",
) -> dict:
    return {
        "name": name,
        "type": primitive,
        "marketplace": "local",
        "source": source,
        "source_commit": source_commit,
        "cache_path": f"/tmp/cache/{name}/",
        "install_target": f".agents/{primitive}s/{name}/",
        "install_timestamp": timestamp,
        "checksum_sha256": "a" * 64,
        "checksum_type": "directory",
        "license": "unknown",
        "bridge_symlinks": [],
    }


def write_minimal_catalog(project: Path) -> None:
    project.joinpath("library.yaml").write_text(
        "library:\n"
        "  skills:\n"
        "    - name: installed-skill\n"
        "      source: /tmp/source/installed-skill/SKILL.md\n"
        "    - name: available-skill\n"
        "      source: /tmp/source/available-skill/SKILL.md\n"
        "  agents: []\n"
        "  prompts: []\n"
        "  scripts: []\n"
        "  standards: []\n"
        "  guardrails: []\n"
        "  mcp_servers: []\n"
        "  model_standards: []\n"
        "  golden_prompts: []\n"
    )


def test_installed_detects_precedence_conflict(tmp_path: Path):
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()

    write_lockfile(project / ".library.lock", [entry("shared", source_commit=PROJECT_SHA)])
    write_lockfile(
        home / ".config" / "library" / "global.lock",
        [entry("shared", source_commit=GLOBAL_SHA, timestamp="2026-05-14T08:00:00Z")],
    )

    result = run_library("installed", "--json", cwd=project, home=home)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    by_scope = {item["scope"]: item for item in data["entries"]}
    assert by_scope["project"]["precedence"] == "active"
    assert by_scope["global"]["precedence"] == "shadowed"
    assert data["precedence_conflicts"] == [
        {
            "name": "shared",
            "primitive": "skill",
            "active_scope": "project",
            "shadowed_scope": "global",
        }
    ]


def test_installed_human_output_has_required_columns(tmp_path: Path):
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    write_lockfile(project / ".library.lock", [entry("visible")])

    result = run_library("installed", cwd=project, home=home)
    assert result.returncode == 0, result.stderr
    for column in [
        "primitive",
        "name",
        "scope",
        "source",
        "commit",
        "installed_at",
        "upstream",
        "precedence",
    ]:
        assert column in result.stdout
    assert "visible" in result.stdout


def test_installed_diff_catalog_classifies_available_and_orphan(tmp_path: Path):
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    write_minimal_catalog(project)
    write_lockfile(
        project / ".library.lock",
        [
            entry("installed-skill"),
            entry("orphan-agent", primitive="agent", source="/tmp/source/orphan-agent.md"),
        ],
    )

    result = run_library("installed", "--diff-catalog", "--json", cwd=project, home=home)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    assert data["catalog_diff"]["available_not_installed"] == {
        "skill": ["available-skill"],
    }
    assert data["catalog_diff"]["installed_not_in_catalog"] == {
        "agent": ["orphan-agent"],
    }


def test_installed_runs_without_library_yaml_when_global_lockfile_exists(tmp_path: Path):
    cwd = tmp_path / "anywhere"
    home = tmp_path / "home"
    cwd.mkdir()
    write_lockfile(home / ".config" / "library" / "global.lock", [entry("global-only")])

    result = run_library("installed", "--json", cwd=cwd, home=home)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert [(item["scope"], item["name"]) for item in data["entries"]] == [
        ("global", "global-only")
    ]


def test_installed_empty_lockfiles_exit_zero(tmp_path: Path):
    cwd = tmp_path / "empty"
    home = tmp_path / "home"
    cwd.mkdir()

    result = run_library("installed", "--json", cwd=cwd, home=home)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "entries": [],
        "precedence_conflicts": [],
    }


def test_installed_scope_and_primitive_filters(tmp_path: Path):
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    write_lockfile(
        project / ".library.lock",
        [
            entry("project-skill"),
            entry("project-agent", primitive="agent", source="/tmp/source/project-agent.md"),
        ],
    )
    write_lockfile(home / ".config" / "library" / "global.lock", [entry("global-skill")])

    result = run_library(
        "installed",
        "--scope=project",
        "--primitive=skill",
        "--json",
        cwd=project,
        home=home,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert [(item["scope"], item["primitive"], item["name"]) for item in data["entries"]] == [
        ("project", "skill", "project-skill")
    ]


def test_sync_dry_run_refreshes_same_set_status_reports_behind(tmp_path: Path):
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    write_minimal_catalog(project)
    write_lockfile(
        project / ".library.lock",
        [
            entry(
                "agent-current",
                primitive="agent",
                source_commit=PROJECT_SHA,
                source="https://github.com/test/repo-current",
            ),
            entry(
                "agent-behind",
                primitive="agent",
                source_commit=GLOBAL_SHA,
                source="https://github.com/test/repo-behind",
            ),
            entry("agent-unknown", primitive="agent", source_commit="local"),
        ],
    )

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"ls-remote\" ]; then\n"
        "  case \"$2\" in\n"
        f"    *repo-current*) printf '{PROJECT_SHA}\\tHEAD\\n' ;;\n"
        f"    *repo-behind*) printf '{REMOTE_SHA}\\tHEAD\\n' ;;\n"
        "    *) exit 128 ;;\n"
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        "exec /usr/bin/git \"$@\"\n"
    )
    fake_git.chmod(0o755)
    env = {"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}

    status = run_library("status", "--json", cwd=project, home=home, extra_env=env)
    assert status.returncode == 2, status.stderr
    status_data = json.loads(status.stdout)
    behind_labels = {
        f"{item['primitive']}:{item['name']}"
        for item in status_data["entries"]
        if item["upstream_status"] == "behind"
    }

    sync = run_library("sync", "--dry-run", "--json", cwd=project, home=home, extra_env=env)
    assert sync.returncode == 0, sync.stderr
    sync_data = json.loads(sync.stdout)
    assert set(sync_data["refreshed"]) == behind_labels
    assert "agent:agent-unknown" in sync_data["skipped"]
