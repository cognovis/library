from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"


def _run(project: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(LIBRARY_PY), *args],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )


def _write_fixture(project: Path) -> tuple[Path, Path]:
    source = project / "team-core"
    for name in ("python-dev", "python-test"):
        skill = source / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n# {name}\n")
    workspaces = source / "workspaces"
    workspaces.mkdir()
    manifest = {
        "schema_version": 1,
        "name": "python-cli",
        "version": "1.0.0",
        "description": "Python CLI baseline.",
        "status": "experimental",
        "roots": [
            {"type": "skill", "name": "python-dev"},
            {"type": "skill", "name": "python-test"},
        ],
    }
    (workspaces / "python-cli.yaml").write_text(yaml.safe_dump(manifest))
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "Test"], check=True
    )
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "fixture"], check=True)

    catalog = {
        "catalog_identity": "https://github.com/example/platform",
        "default_dirs": {
            "skills": [{"default": ".agents/skills/", "global": "~/.agents/skills/"}]
        },
        "sources": {
            "catalogs": [
                {
                    "name": "team-core",
                    "source": "https://github.com/example/core",
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
                    "description": f"{name} skill.",
                    "source": str(source / "skills" / name / "SKILL.md"),
                    "metadata": {"library": {"source_catalog": "team-core"}},
                }
                for name in ("python-dev", "python-test")
            ],
            "workspaces": [
                {
                    **manifest,
                    "source": str(workspaces / "python-cli.yaml"),
                    "metadata": {
                        "library": {
                            "source_catalog": "team-core",
                            "inventory": "convention-scan",
                        }
                    },
                }
            ],
        },
    }
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    return source, workspaces / "python-cli.yaml"


def test_workspace_discovery_validation_and_dry_run_are_read_only(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _source, manifest_path = _write_fixture(project)

    listed = _run(project, home, "workspace", "list", "--json")
    shown = _run(project, home, "workspace", "show", "team-core:python-cli", "--json")
    validated = _run(
        project, home, "workspace", "validate", str(manifest_path), "--json"
    )
    planned = _run(
        project,
        home,
        "workspace",
        "use",
        "team-core:python-cli",
        "--scope",
        "project",
        "--dry-run",
        "--json",
    )

    assert (
        listed.returncode
        == shown.returncode
        == validated.returncode
        == planned.returncode
        == 0
    )
    assert (
        json.loads(listed.stdout)["workspaces"][0]["reference"]
        == "team-core:python-cli"
    )
    assert json.loads(shown.stdout)["closure"] == [
        "skill:python-dev",
        "skill:python-test",
    ]
    assert json.loads(validated.stdout)["status"] == "valid"
    assert json.loads(planned.stdout)["status"] == "dry-run"
    assert not (project / ".library.lock").exists()
    assert not (project / ".agents").exists()


def test_workspace_use_registers_one_root_and_materializes_members(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)

    used = _run(
        project,
        home,
        "workspace",
        "use",
        "team-core:python-cli",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )

    assert used.returncode == 0, used.stderr or used.stdout
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert [root["type"] for root in lock["requested_roots"]] == ["workspace"]
    assert {receipt["id"] for receipt in lock["receipts"]} == {
        "skill:python-dev",
        "skill:python-test",
    }
    assert all(
        receipt["owners_cache"] == [lock["requested_roots"][0]["id"]]
        for receipt in lock["receipts"]
    )
    assert (project / ".agents" / "skills" / "python-dev" / "SKILL.md").exists()
    assert (project / ".agents" / "skills" / "python-test" / "SKILL.md").exists()

    status = _run(
        project,
        home,
        "workspace",
        "status",
        "--all",
        "--scope",
        "project",
        "--json",
    )
    assert status.returncode == 0, status.stderr or status.stdout
    assert json.loads(status.stdout)["status"] == "converged"


def test_workspace_use_blocks_foreign_target_before_any_install(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    foreign = project / ".agents" / "skills" / "python-dev" / "SKILL.md"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("project authored\n")

    used = _run(
        project,
        home,
        "workspace",
        "use",
        "team-core:python-cli",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )

    assert used.returncode == 3
    assert json.loads(used.stdout)["status"] == "blocked"
    assert foreign.read_text() == "project authored\n"
    assert not (project / ".agents" / "skills" / "python-test").exists()
    assert not (project / ".library.lock").exists()


def test_workspace_remove_then_digest_bound_prune_deletes_only_receipt_files(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    use_args = (
        "workspace",
        "use",
        "team-core:python-cli",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )
    assert _run(project, home, *use_args).returncode == 0
    sibling = project / ".agents" / "skills" / "python-dev" / "project-note.md"
    sibling.write_text("keep\n")

    removed = _run(
        project,
        home,
        "workspace",
        "remove",
        "team-core:python-cli",
        "--scope",
        "project",
        "--json",
    )
    preview = _run(
        project,
        home,
        "workspace",
        "sync",
        "--all",
        "--scope",
        "project",
        "--prune",
        "--json",
    )

    assert removed.returncode == preview.returncode == 0
    digest = json.loads(preview.stdout)["digest"]
    applied = _run(
        project,
        home,
        "workspace",
        "sync",
        "--all",
        "--scope",
        "project",
        "--prune",
        "--apply",
        "--acknowledge-plan",
        digest,
        "--json",
    )

    assert applied.returncode == 0, applied.stderr or applied.stdout
    assert sibling.read_text() == "keep\n"
    assert not (project / ".agents" / "skills" / "python-test" / "SKILL.md").exists()
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert lock["receipts"] == []
