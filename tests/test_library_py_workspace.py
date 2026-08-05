from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"


def _library_module():
    spec = importlib.util.spec_from_file_location("library_workspace_test", LIBRARY_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_platform_catalog_publishes_operational_python_cli_workspace() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.catalog import load_catalog
    from lib.workspace import resolve_workspace, resolve_workspace_closure

    catalog = load_catalog(REPO_ROOT)

    workspace = resolve_workspace(catalog, "cognovis-library-core:python-cli")
    closure = resolve_workspace_closure(catalog, workspace, REPO_ROOT, "project")

    assert workspace.version == "0.1.0"
    assert set(closure.artifacts) == {
        ("skill", "python-dev"),
        ("skill", "python-test"),
        ("standard", "python-cli-patterns"),
    }
    assert set(closure.prerequisites) == {
        ("standard", "english-only"),
        ("standard", "no-emoji"),
    }


def test_source_bound_lookup_normalizes_missing_metadata_to_unbound() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.catalog import lookup_entry

    catalog = {"library": {"mcp_servers": [{"name": "unbound-service"}]}}

    assert (
        lookup_entry(
            catalog,
            "mcp",
            "unbound-service",
            fuzzy=False,
            source_catalog="",
        )["name"]
        == "unbound-service"
    )


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
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\nversion: 1.0.0\n---\n# {name}\n"
        )
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
            "skills": [
                {"default": ".agents/skills/", "global": "~/.agents/skills/"},
                {
                    "claude_bridge": ".claude/skills/",
                    "global_claude_bridge": "~/.claude/skills/",
                },
                {
                    "cursor_bridge": ".cursor/skills/",
                    "global_cursor_bridge": "~/.cursor/skills/",
                },
            ]
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
                    "version": "1.0.0",
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
        "all",
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


def test_workspace_use_replaces_only_byte_exact_catalog_content(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    source, _manifest = _write_fixture(project)
    target = project / ".agents" / "skills" / "python-dev"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_bytes(
        (source / "skills" / "python-dev" / "SKILL.md").read_bytes()
    )

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
        "--replace-with-catalog-content",
        "--json",
    )

    assert used.returncode == 0, used.stderr or used.stdout
    assert str(target) in json.loads(used.stdout)["replacements"]
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert {receipt["id"] for receipt in lock["receipts"]} == {
        "skill:python-dev",
        "skill:python-test",
    }


def test_workspace_use_replace_flag_still_blocks_different_content(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    foreign = project / ".agents" / "skills" / "python-dev" / "SKILL.md"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("different\n")

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
        "--replace-with-catalog-content",
        "--json",
    )

    assert used.returncode == 3
    assert foreign.read_text() == "different\n"
    assert not (project / ".library.lock").exists()


def test_workspace_install_remains_bound_to_its_catalog_when_names_collide(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    source, _manifest = _write_fixture(project)
    foreign_source = project / "foreign-core" / "skills" / "python-dev"
    foreign_source.mkdir(parents=True)
    (foreign_source / "SKILL.md").write_text("foreign catalog content\n")
    catalog = yaml.safe_load((project / "library.yaml").read_text())
    catalog["sources"]["catalogs"].insert(
        0,
        {
            "name": "foreign-core",
            "source": "https://github.com/example/foreign",
            "local_path": str(project / "foreign-core"),
            "content_types": ["skills"],
        },
    )
    catalog["library"]["skills"].insert(
        0,
        {
            "name": "python-dev",
            "description": "Foreign duplicate.",
            "version": "0.5.0",
            "source": str(foreign_source / "SKILL.md"),
            "metadata": {"library": {"source_catalog": "foreign-core"}},
        },
    )
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))

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
    installed = project / ".agents" / "skills" / "python-dev" / "SKILL.md"
    assert (
        installed.read_bytes()
        == (source / "skills" / "python-dev" / "SKILL.md").read_bytes()
    )
    lock = yaml.safe_load((project / ".library.lock").read_text())
    receipt = next(
        item for item in lock["receipts"] if item["id"] == "skill:python-dev"
    )
    assert receipt["catalog_identity"] == "https://github.com/example/core"


def test_named_remove_preserves_workspace_reachable_receipt(tmp_path: Path) -> None:
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

    removed = _run(
        project,
        home,
        "skill",
        "remove",
        "python-dev",
        "--scope",
        "project",
        "--json",
    )

    assert removed.returncode == 0, removed.stderr or removed.stdout
    payload = json.loads(removed.stdout)
    assert payload["removed_files"] == []
    assert payload["retained_by"][0].startswith("workspace:")
    assert (project / ".agents" / "skills" / "python-dev" / "SKILL.md").exists()
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert "skill:python-dev" in {item["id"] for item in lock["receipts"]}


def test_named_remove_preserves_targetless_workspace_reachable_receipt(
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
    lock_path = project / ".library.lock"
    lock = yaml.safe_load(lock_path.read_text())
    receipt = next(
        item for item in lock["receipts"] if item["id"] == "skill:python-dev"
    )
    receipt["targets"] = []
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False))

    removed = _run(
        project,
        home,
        "skill",
        "remove",
        "python-dev",
        "--scope",
        "project",
        "--json",
    )

    assert removed.returncode == 0, removed.stderr or removed.stdout
    payload = json.loads(removed.stdout)
    assert payload["removed_files"] == []
    assert payload["retained_by"][0].startswith("workspace:")
    assert (project / ".agents" / "skills" / "python-dev" / "SKILL.md").exists()
    final_lock = yaml.safe_load(lock_path.read_text())
    assert "skill:python-dev" in {item["id"] for item in final_lock["receipts"]}


def test_unrelated_catalog_orphan_does_not_block_named_remove(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    for name in ("python-dev", "python-test"):
        installed = _run(
            project,
            home,
            "skill",
            "use",
            name,
            "--scope",
            "project",
            "--harness",
            "codex",
            "--json",
        )
        assert installed.returncode == 0, installed.stderr or installed.stdout
    catalog_path = project / "library.yaml"
    catalog = yaml.safe_load(catalog_path.read_text())
    catalog["library"]["skills"] = [
        entry for entry in catalog["library"]["skills"] if entry["name"] != "python-dev"
    ]
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False))

    removed = _run(
        project,
        home,
        "skill",
        "remove",
        "python-test",
        "--scope",
        "project",
        "--json",
    )

    assert removed.returncode == 0, removed.stderr or removed.stdout
    assert (project / ".agents" / "skills" / "python-dev" / "SKILL.md").exists()
    assert not (project / ".agents" / "skills" / "python-test").exists()
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert {root["id"] for root in lock["requested_roots"]} == {"skill:python-dev"}
    assert {receipt["id"] for receipt in lock["receipts"]} == {"skill:python-dev"}


def test_unverified_catalog_orphan_remove_retains_filesystem_content(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    installed = _run(
        project,
        home,
        "skill",
        "use",
        "python-dev",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )
    assert installed.returncode == 0, installed.stderr or installed.stdout
    lock_path = project / ".library.lock"
    current = yaml.safe_load(lock_path.read_text())
    lock_path.write_text(
        yaml.safe_dump({"installed": current["installed"]}, sort_keys=False)
    )
    catalog_path = project / "library.yaml"
    catalog = yaml.safe_load(catalog_path.read_text())
    catalog["library"]["skills"] = []
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False))

    removed = _run(
        project,
        home,
        "skill",
        "remove",
        "python-dev",
        "--scope",
        "project",
        "--json",
    )

    assert removed.returncode == 0, removed.stderr or removed.stdout
    payload = json.loads(removed.stdout)
    assert payload["data"]["removed_files"] == []
    assert payload["data"]["retained_orphan_paths"]
    assert (project / ".agents" / "skills" / "python-dev" / "SKILL.md").exists()
    final_lock = yaml.safe_load(lock_path.read_text())
    assert final_lock["requested_roots"] == []
    assert final_lock["receipts"] == []
    assert final_lock["migration"]["prune_ack_required"] is True


def test_targetless_catalog_orphan_remove_retains_filesystem_content(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    installed = _run(
        project,
        home,
        "skill",
        "use",
        "python-dev",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )
    assert installed.returncode == 0, installed.stderr or installed.stdout
    lock_path = project / ".library.lock"
    lock = yaml.safe_load(lock_path.read_text())
    receipt = next(
        item for item in lock["receipts"] if item["id"] == "skill:python-dev"
    )
    receipt["targets"] = []
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False))
    catalog_path = project / "library.yaml"
    catalog = yaml.safe_load(catalog_path.read_text())
    catalog["library"]["skills"] = []
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False))

    removed = _run(
        project,
        home,
        "skill",
        "remove",
        "python-dev",
        "--scope",
        "project",
        "--json",
    )

    assert removed.returncode == 0, removed.stderr or removed.stdout
    assert (project / ".agents" / "skills" / "python-dev" / "SKILL.md").exists()
    final_lock = yaml.safe_load(lock_path.read_text())
    assert final_lock["requested_roots"] == []
    assert final_lock["receipts"] == []


def test_named_remove_blocks_drift_without_mutating_lock_or_files(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    installed = _run(
        project,
        home,
        "skill",
        "use",
        "python-dev",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )
    assert installed.returncode == 0, installed.stderr or installed.stdout
    note = project / ".agents" / "skills" / "python-dev" / "project-note.md"
    note.write_text("keep\n")
    before = (project / ".library.lock").read_bytes()

    removed = _run(
        project,
        home,
        "skill",
        "remove",
        "python-dev",
        "--scope",
        "project",
        "--json",
    )

    assert removed.returncode != 0
    assert "unrecorded nested content" in (removed.stderr or removed.stdout)
    assert note.read_text() == "keep\n"
    assert (project / ".library.lock").read_bytes() == before


def test_preexisting_project_direct_root_survives_workspace_reconciliation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)

    direct = _run(
        project,
        home,
        "skill",
        "use",
        "python-dev",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )
    assert direct.returncode == 0, direct.stderr or direct.stdout
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
    roots = {root["id"]: root for root in lock["requested_roots"]}
    assert roots["skill:python-dev"]["scope"] == "project"
    workspace_id = next(
        root_id for root_id, root in roots.items() if root["type"] == "workspace"
    )
    receipt = next(
        item for item in lock["receipts"] if item["id"] == "skill:python-dev"
    )
    assert set(receipt["owners_cache"]) == {"skill:python-dev", workspace_id}


def test_workspace_status_survives_project_relocation(tmp_path: Path) -> None:
    catalog_project = tmp_path / "catalog-project"
    project = tmp_path / "consumer"
    relocated = tmp_path / "relocated-consumer"
    home = tmp_path / "home"
    catalog_project.mkdir()
    project.mkdir()
    home.mkdir()
    _write_fixture(catalog_project)
    shutil.copy2(catalog_project / "library.yaml", project / "library.yaml")
    subprocess.run(["git", "init", "-q", str(project)], check=True)

    used = _run(
        project,
        home,
        "workspace",
        "use",
        "team-core:python-cli",
        "--scope",
        "project",
        "--harness",
        "all",
        "--json",
    )
    assert used.returncode == 0, used.stderr or used.stdout

    project.rename(relocated)
    status = _run(
        relocated,
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
    bridge = relocated / ".claude" / "skills" / "python-dev"
    assert bridge.readlink() == Path("../../.agents/skills/python-dev")
    assert bridge.resolve() == relocated / ".agents" / "skills" / "python-dev"


def test_top_level_force_sync_preserves_workspace_requested_intent(
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
        "all",
        "--json",
    )
    assert used.returncode == 0, used.stderr or used.stdout

    synced = _run(
        project,
        home,
        "sync",
        "--force",
        "--scope",
        "project",
        "--project",
        str(project),
        "--harness",
        "all",
        "--json",
    )

    assert synced.returncode == 0, synced.stderr or synced.stdout
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert [root["type"] for root in lock["requested_roots"]] == ["workspace"]
    workspace_id = lock["requested_roots"][0]["id"]
    assert all(
        receipt["owners_cache"] == [workspace_id] for receipt in lock["receipts"]
    )


def test_verify_receipts_reinstalls_migrated_direct_roots_without_a_workspace(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    installed = _run(
        project,
        home,
        "skill",
        "use",
        "python-dev",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )
    assert installed.returncode == 0, installed.stderr or installed.stdout
    current = yaml.safe_load((project / ".library.lock").read_text())
    (project / ".library.lock").write_text(
        yaml.safe_dump({"installed": current["installed"]}, sort_keys=False)
    )

    verified = _run(
        project,
        home,
        "workspace",
        "sync",
        "--all",
        "--scope",
        "project",
        "--verify-receipts",
        "--harness",
        "codex",
        "--json",
    )

    assert verified.returncode == 0, verified.stderr or verified.stdout
    assert json.loads(verified.stdout)["verified_receipts"] == ["skill:python-dev"]
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert lock["migration"]["prune_ack_required"] is False
    assert lock["receipts"][0]["scope"] == "project"
    assert lock["receipts"][0]["verified"] is True
    assert lock["receipts"][0]["catalog_identity"] == "https://github.com/example/core"


def test_workspace_status_reports_filesystem_drift_and_catalog_updates(
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
    target = project / ".agents" / "skills" / "python-dev" / "SKILL.md"
    target.write_text("drifted\n")

    drifted = _run(
        project,
        home,
        "workspace",
        "status",
        "--all",
        "--scope",
        "project",
        "--json",
    )
    assert drifted.returncode == 3
    assert "target drift" in " ".join(json.loads(drifted.stdout)["blockers"])

    target.write_text("---\nname: python-dev\nversion: 1.0.0\n---\n# python-dev\n")
    catalog = yaml.safe_load((project / "library.yaml").read_text())
    catalog["library"]["skills"][0]["version"] = "1.1.0"
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))
    update = _run(
        project,
        home,
        "workspace",
        "status",
        "--all",
        "--scope",
        "project",
        "--json",
    )
    assert update.returncode == 2, update.stderr or update.stdout
    assert json.loads(update.stdout)["updates"] == ["skill:python-dev"]


def test_workspace_status_human_output_explains_protected_migration(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    installed = _run(
        project,
        home,
        "skill",
        "use",
        "python-dev",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )
    assert installed.returncode == 0, installed.stderr or installed.stdout
    current = yaml.safe_load((project / ".library.lock").read_text())
    (project / ".library.lock").write_text(
        yaml.safe_dump({"installed": current["installed"]}, sort_keys=False)
    )

    status = _run(
        project,
        home,
        "workspace",
        "status",
        "--all",
        "--scope",
        "project",
    )

    assert status.returncode == 3
    assert "protected:" in status.stdout
    assert "skill:python-dev" in status.stdout
    assert "workspace sync --all --scope project --verify-receipts" in status.stdout


def test_workspace_status_preflights_collision_for_missing_receipt(
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
    lock_path = project / ".library.lock"
    lock = yaml.safe_load(lock_path.read_text())
    lock["installed"] = [
        item
        for item in lock["installed"]
        if not (item.get("type") == "skill" and item.get("name") == "python-dev")
    ]
    lock["receipts"] = [
        item for item in lock["receipts"] if item.get("id") != "skill:python-dev"
    ]
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False))

    status = _run(
        project,
        home,
        "workspace",
        "status",
        "--all",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )

    assert status.returncode == 3
    payload = json.loads(status.stdout)
    assert payload["collisions"]
    assert "without a matching Library receipt" in " ".join(payload["collisions"])


def test_workspace_status_surfaces_direct_root_adoption_candidate(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    direct = _run(
        project,
        home,
        "skill",
        "use",
        "python-dev",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )
    assert direct.returncode == 0, direct.stderr or direct.stdout
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

    status = _run(
        project,
        home,
        "workspace",
        "status",
        "--all",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )

    assert status.returncode == 0, status.stderr or status.stdout
    candidates = json.loads(status.stdout)["adoption_candidates"]
    assert [item["id"] for item in candidates] == ["skill:python-dev"]


def test_verify_receipts_obeys_workspace_write_lock(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    installed = _run(
        project,
        home,
        "skill",
        "use",
        "python-dev",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )
    assert installed.returncode == 0, installed.stderr or installed.stdout
    lock_path = project / ".library.lock"
    current = yaml.safe_load(lock_path.read_text())
    lock_path.write_text(
        yaml.safe_dump({"installed": current["installed"]}, sort_keys=False)
    )
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.workspace import workspace_write_lock

    with workspace_write_lock(lock_path):
        verified = _run(
            project,
            home,
            "workspace",
            "sync",
            "--all",
            "--scope",
            "project",
            "--verify-receipts",
            "--harness",
            "codex",
            "--json",
        )

    assert verified.returncode != 0
    assert "Another Workspace mutation" in (verified.stderr or verified.stdout)


def test_workspace_use_fails_before_mutation_when_global_prerequisite_is_missing(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    catalog = yaml.safe_load((project / "library.yaml").read_text())
    catalog["library"]["skills"][1]["requires"] = ["mcp:test-service"]
    catalog["library"]["mcp_servers"] = [
        {
            "name": "test-service",
            "description": "Global test prerequisite.",
            "metadata": {"library": {"source_catalog": "team-core"}},
        }
    ]
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))

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
    assert "required globally" in " ".join(json.loads(used.stdout)["blockers"])
    assert not (project / ".library.lock").exists()
    assert not (project / ".agents").exists()


def test_workspace_use_rejects_incompatible_global_prerequisite_version(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    catalog = yaml.safe_load((project / "library.yaml").read_text())
    catalog["library"]["skills"][1]["requires"] = ["mcp:test-service"]
    catalog["library"]["mcp_servers"] = [
        {
            "name": "test-service",
            "description": "Global test prerequisite.",
            "version": "2.0.0",
            "metadata": {"library": {"source_catalog": "team-core"}},
        }
    ]
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))
    global_lock = home / ".config" / "library" / "global.lock"
    global_lock.parent.mkdir(parents=True)
    global_lock.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "requested_roots": [],
                "receipts": [
                    {
                        "id": "mcp:test-service",
                        "type": "mcp",
                        "name": "test-service",
                        "scope": "global",
                        "catalog_identity": "https://github.com/example/core",
                        "resolved_version": "1.0.0",
                        "verified": True,
                        "targets": [],
                    }
                ],
                "installed": [],
            },
            sort_keys=False,
        )
    )

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
    assert "incompatible with required version 2.0.0" in " ".join(
        json.loads(used.stdout)["blockers"]
    )
    assert not (project / ".library.lock").exists()


def test_workspace_use_rechecks_prerequisites_after_acquiring_write_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    monkeypatch.setenv("HOME", str(home))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.catalog import load_catalog

    module = _library_module()
    checks = iter(([], ["mcp:test-service changed while waiting for the lock"]))
    real_dispatch = module._dispatch_use
    monkeypatch.setattr(
        module,
        "_workspace_prerequisite_blockers",
        lambda _plan: next(checks),
    )

    def guarded_dispatch(*dispatch_args, **dispatch_kwargs):
        if dispatch_args[7]:
            return real_dispatch(*dispatch_args, **dispatch_kwargs)
        pytest.fail("member installation started after prerequisite drift")

    monkeypatch.setattr(module, "_dispatch_use", guarded_dispatch)
    args = argparse.Namespace(
        reference="team-core:python-cli",
        scope="project",
        harness="codex",
        dry_run=False,
        replace_with_catalog_content=False,
        json=True,
    )

    rc = module._workspace_use(args, project, load_catalog(project))
    output = json.loads(capsys.readouterr().out)

    assert rc == 3
    assert output["blockers"] == ["mcp:test-service changed while waiting for the lock"]
    assert not (project / ".library.lock").exists()
    assert not (project / ".agents").exists()


def test_filesystem_adoption_verifies_exact_receipt_and_definition_pin(
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
    definition_commit = json.loads(used.stdout)["definition_commit"]

    adopted = _run(
        project,
        home,
        "workspace",
        "adopt",
        "team-core:python-cli",
        "skill:python-dev",
        "--definition-commit",
        definition_commit,
        "--scope",
        "project",
        "--json",
    )

    assert adopted.returncode == 0, adopted.stderr or adopted.stdout
    lock = yaml.safe_load((project / ".library.lock").read_text())
    receipt = next(
        item for item in lock["receipts"] if item["id"] == "skill:python-dev"
    )
    assert receipt["adopted"] is True
    assert receipt["definition_commit"] == definition_commit


def test_actual_prune_preserves_receipt_owned_by_a_direct_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    direct = _run(
        project,
        home,
        "skill",
        "use",
        "python-dev",
        "--scope",
        "project",
        "--harness",
        "codex",
        "--json",
    )
    assert direct.returncode == 0, direct.stderr or direct.stdout
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
    assert removed.returncode == 0, removed.stderr or removed.stdout
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
    payload = json.loads(preview.stdout)
    assert [item["id"] for item in payload["prune_candidates"]] == ["skill:python-test"]
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
        payload["digest"],
        "--json",
    )

    assert applied.returncode == 0, applied.stderr or applied.stdout
    assert (project / ".agents" / "skills" / "python-dev" / "SKILL.md").exists()
    assert not (project / ".agents" / "skills" / "python-test").exists()


def test_addition_failure_stops_before_workspace_registration_or_prune(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    monkeypatch.setenv("HOME", str(home))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.catalog import load_catalog

    module = _library_module()
    real_dispatch = module._dispatch_use

    def flaky_dispatch(*dispatch_args, **dispatch_kwargs):
        name = dispatch_args[4]
        dry_run = dispatch_args[7]
        if name == "python-test" and not dry_run:
            print("injected addition failure")
            return 1
        return real_dispatch(*dispatch_args, **dispatch_kwargs)

    monkeypatch.setattr(module, "_dispatch_use", flaky_dispatch)
    args = argparse.Namespace(
        reference="team-core:python-cli",
        scope="project",
        harness="codex",
        dry_run=False,
        replace_with_catalog_content=False,
        json=True,
    )

    rc = module._workspace_use(args, project, load_catalog(project))
    capsys.readouterr()

    assert rc == 1
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert {root["id"] for root in lock["requested_roots"]} == {"skill:python-dev"}
    assert {receipt["id"] for receipt in lock["receipts"]} == {"skill:python-dev"}
    assert (project / ".agents" / "skills" / "python-dev" / "SKILL.md").exists()
    assert not (project / ".agents" / "skills" / "python-test").exists()


def test_final_lock_write_failure_leaves_recoverable_addition_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    _write_fixture(project)
    monkeypatch.setenv("HOME", str(home))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.catalog import load_catalog
    from lib.errors import LockfileError

    module = _library_module()

    def fail_final_save(_path: Path, _lock: dict) -> None:
        raise LockfileError("injected final lock write failure")

    monkeypatch.setattr(module, "save_lockfile", fail_final_save)
    args = argparse.Namespace(
        reference="team-core:python-cli",
        scope="project",
        harness="codex",
        dry_run=False,
        replace_with_catalog_content=False,
        json=True,
    )

    with pytest.raises(LockfileError, match="injected final lock write failure"):
        module._workspace_use(args, project, load_catalog(project))

    assert (project / ".library.lock.workspace-journal.json").exists()
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert {root["type"] for root in lock["requested_roots"]} == {"skill"}


def test_workspace_remove_then_prune_blocks_unrecorded_nested_content(
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

    assert applied.returncode != 0
    assert "unrecorded nested content" in (applied.stderr or applied.stdout)
    assert sibling.read_text() == "keep\n"
    assert (project / ".agents" / "skills" / "python-test" / "SKILL.md").exists()
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert {receipt["id"] for receipt in lock["receipts"]} == {
        "skill:python-dev",
        "skill:python-test",
    }
