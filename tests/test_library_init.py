"""Public fixed-baseline initialization coverage for ``library init``."""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY = REPO_ROOT / "scripts" / "library.py"


def _run(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["HOME"] = str(project / "isolated-home")
    return subprocess.run(
        ["uv", "run", str(LIBRARY), *arguments],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_cognovis_base_fixture(project: Path) -> None:
    source = project / "fixture-catalog"
    for name in ("fixture-skill", "fixture-helper"):
        skill = source / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n# Fixture\n")
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "fixture@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "Fixture"], check=True
    )
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "fixture"], check=True)
    catalog = {
        "catalog_identity": "https://github.com/cognovis/library",
        "default_dirs": {
            "skills": [
                {"default": ".agents/skills/"},
                {"claude_bridge": ".claude/skills/"},
            ]
        },
        "sources": {
            "catalogs": [
                {
                    "name": "library-platform",
                    "source": "https://github.com/cognovis/library",
                    "local_path": str(source),
                    "content_types": ["skills", "workspaces"],
                }
            ],
            "marketplaces": [],
        },
        "library": {
            "skills": [
                {
                    "name": name,
                    "description": "Fixture skill.",
                    "version": "1.0.0",
                    "source": str(source / "skills" / name / "SKILL.md"),
                    "metadata": {"library": {"source_catalog": "library-platform"}},
                }
                for name in ("fixture-skill", "fixture-helper")
            ],
            "workspaces": [
                {
                    "schema_version": 1,
                    "name": "cognovis-base",
                    "version": "1.0.0",
                    "description": "Controlled fixture baseline.",
                    "status": "experimental",
                    "roots": [
                        {"type": "skill", "name": "fixture-skill"},
                        {"type": "skill", "name": "fixture-helper"},
                    ],
                    "metadata": {"library": {"source_catalog": "library-platform"}},
                }
            ],
        },
    }
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))


def test_init_installs_only_the_fixed_workspace_and_reconciles_gitignore(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_cognovis_base_fixture(project)
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)

    first = _run(project, "init", "--json")
    second = _run(project, "init", "--json")

    assert first.returncode == second.returncode == 0, first.stderr or first.stdout
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert [root["name"] for root in lock["requested_roots"]] == ["cognovis-base"]
    assert (project / ".agents" / "skills" / "library" / "SKILL.md").is_file()
    gitignore = (project / ".gitignore").read_text()
    assert gitignore.count("# BEGIN Library-managed project installs") == 1
    assert "/.agents/skills/library/SKILL.md" in gitignore
    assert json.loads(second.stdout)["status"] == "applied"


def test_repeated_init_preserves_lock_and_gitignore_bytes_when_unchanged(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_cognovis_base_fixture(project)
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)

    first = _run(project, "init", "--json")
    assert first.returncode == 0, first.stderr or first.stdout
    lock_path = project / ".library.lock"
    initial_lock = lock_path.read_bytes()
    stable_lock = re.sub(
        r"install_timestamp: '[^']+'",
        "install_timestamp: '2000-01-01T00:00:00Z'",
        initial_lock.decode(),
    ).encode()
    assert stable_lock != initial_lock
    lock_path.write_bytes(stable_lock)
    stable_gitignore = (project / ".gitignore").read_bytes()

    second = _run(project, "init", "--json")

    assert second.returncode == 0, second.stderr or second.stdout
    actual_lock = lock_path.read_bytes()
    assert actual_lock == stable_lock, second.stderr + "\n" + "\n".join(
        difflib.unified_diff(
            stable_lock.decode().splitlines(),
            actual_lock.decode().splitlines(),
            fromfile="stable-lock",
            tofile="second-init-lock",
        )
    )
    assert (project / ".gitignore").read_bytes() == stable_gitignore


def test_init_has_no_workspace_selector_and_rejects_non_git_before_mutation(
    tmp_path: Path,
) -> None:
    non_git = tmp_path / "non-git"
    non_git.mkdir()
    sentinel = non_git / "sentinel"
    sentinel.write_text("unchanged")

    selector = _run(non_git, "init", "another-workspace")
    rejected = _run(non_git, "init", "--json")

    assert selector.returncode == 2
    assert rejected.returncode == 1
    assert sentinel.read_text() == "unchanged"
    assert not (non_git / ".library.lock").exists()
    assert json.loads(rejected.stdout)["message"] == "Project installs require a Git worktree top-level"
