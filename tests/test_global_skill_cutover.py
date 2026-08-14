"""Transactional removal coverage for legacy global Skill projections."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import library as library_cli  # noqa: E402
from lib import global_skill_cutover  # noqa: E402


def _commit_repository(repository: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "add",
            ".",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )


def _write_approved_fleet_manifest(tmp_path: Path, repositories: list[Path]) -> Path:
    entries: list[dict[str, str]] = []
    remote_root = tmp_path / "published-remotes"
    remote_root.mkdir(exist_ok=True)
    for index, repository in enumerate(repositories):
        branch = subprocess.run(
            ["git", "-C", str(repository), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        remote = remote_root / f"{index:02d}-{repository.name}.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
        subprocess.run(
            ["git", "-C", str(repository), "remote", "add", "origin", str(remote)],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "push",
                "--quiet",
                "--set-upstream",
                "origin",
                branch,
            ],
            check=True,
        )
        entries.append(
            {
                "path": str(repository.resolve()),
                "branch": branch,
                "published_commit": commit,
                "remote": "origin",
            }
        )
    manifest = tmp_path / "approved-fleet.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bead_id": "CL-31po",
                "approval": {
                    "approved_by": "fixture-operator",
                    "approved_at": "2026-08-14T00:00:00Z",
                },
                "repositories": entries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def _write_global_lock(home: Path, target: Path, *, with_bridge: bool = False) -> Path:
    lock_path = home / ".config" / "library" / "global.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "id": "skill:legacy-skill",
        "type": "skill",
        "name": "legacy-skill",
        "scope": "global",
        "verified": True,
        "install_target": f"{target}/",
        "targets": [
            {"path": str(target), "kind": "directory"},
            {
                "path": str(target / "SKILL.md"),
                "kind": "file",
                "content_sha256": library_cli.sha256(
                    (target / "SKILL.md").read_bytes()
                ).hexdigest(),
            },
        ],
    }
    if with_bridge:
        bridge = home / ".claude" / "skills" / "legacy-skill"
        bridge.parent.mkdir(parents=True, exist_ok=True)
        bridge.symlink_to(target)
        receipt["bridge_symlinks"] = [f"{bridge} -> {target}"]
        receipt["targets"].append(
            {
                "path": str(bridge),
                "kind": "symlink",
                "link_target": str(target),
            }
        )
    retained = {
        "id": "mcp:open-brain",
        "type": "mcp",
        "name": "open-brain",
        "scope": "global",
        "verified": True,
        "targets": [],
    }
    lock = {
        "schema_version": 2,
        "migration": {"prune_ack_required": False},
        "requested_roots": [
            {
                "id": receipt["id"],
                "type": "skill",
                "name": receipt["name"],
                "scope": "global",
            }
        ],
        "receipts": [receipt, retained],
        "prerequisites": [],
        "installed": [receipt, retained],
    }
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")
    return lock_path


def _write_catalog_fixture(catalog_root: Path) -> None:
    source = catalog_root / "fixture-source"
    baseline = source / "skills" / "baseline-skill"
    baseline.mkdir(parents=True)
    (baseline / "SKILL.md").write_text(
        "---\nname: baseline-skill\n---\n\n# Baseline skill\n",
        encoding="utf-8",
    )
    helper = source / "skills" / "baseline-helper"
    helper.mkdir(parents=True)
    (helper / "SKILL.md").write_text(
        "---\nname: baseline-helper\n---\n\n# Baseline helper\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "add",
            ".",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture source",
        ],
        check=True,
    )
    skill_names = ["baseline-skill", "baseline-helper"] + [
        f"catalog-skill-{index:03d}" for index in range(2, 110)
    ]
    skills = [
        {
            "name": name,
            "description": "Fixture catalog Skill.",
            "version": "1.0.0",
            "source": str(
                (helper if name == "baseline-helper" else baseline) / "SKILL.md"
            ),
            "metadata": {"library": {"source_catalog": "fixture-catalog"}},
        }
        for name in skill_names
    ]
    catalog = {
        "default_dirs": {
            "skills": [
                {"default": ".agents/skills/"},
                {"claude_bridge": ".claude/skills/"},
            ]
        },
        "sources": {
            "catalogs": [
                {
                    "name": "fixture-catalog",
                    "source": "https://example.invalid/fixture-catalog",
                    "local_path": str(source),
                    "content_types": ["skills", "workspaces"],
                }
            ],
            "marketplaces": [],
        },
        "library": {
            "skills": skills,
            "workspaces": [
                {
                    "schema_version": 1,
                    "name": "cognovis-base",
                    "version": "1.0.0",
                    "description": "Controlled fixture baseline.",
                    "status": "stable",
                    "roots": [
                        {"type": "skill", "name": "baseline-skill"},
                        {"type": "skill", "name": "baseline-helper"},
                    ],
                    "metadata": {"library": {"source_catalog": "fixture-catalog"}},
                }
            ],
        },
    }
    (catalog_root / "library.yaml").write_text(
        yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8"
    )


def _prepare_healthy_repository(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> Path:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_catalog_fixture(catalog_root)
    monkeypatch.chdir(catalog_root)
    registry = Path.home() / ".config" / "library" / "catalog-sources.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "catalogs": [
                    {
                        "identity": "https://example.invalid/fixture-catalog",
                        "checkout": str(catalog_root / "fixture-source"),
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    repository = tmp_path / "consumer"
    (repository / ".beads").mkdir(parents=True)
    (repository / ".beads" / "config.yaml").write_text("prefix: fixture\n")
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    assert library_cli.main(["init", "--project", str(repository), "--json"]) == 0
    capsys.readouterr()
    _commit_repository(repository)
    health = library_cli._repository_health(repository)
    assert health["desired_state"]["status"] == "healthy", health["desired_state"][
        "resolution_blockers"
    ]
    return repository


def test_cutover_rejects_a_linked_task_worktree_as_noncanonical(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "canonical"
    (repository / ".beads").mkdir(parents=True)
    (repository / ".beads" / "config.yaml").write_text("prefix: fixture\n")
    (repository / ".library.lock").write_text("schema_version: 2\n")
    _commit_repository(repository)
    linked = tmp_path / "linked-task-worktree"
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "worktree",
            "add",
            "--quiet",
            "-b",
            "fixture/task-worktree",
            str(linked),
        ],
        check=True,
    )

    assert global_skill_cutover.inspect_repositories([linked]) == [
        {
            "path": str(linked.resolve()),
            "status": "blocked",
            "reason": "path is a linked Git worktree, not the canonical checkout",
        }
    ]


def test_cutover_rejects_a_detached_primary_checkout(tmp_path: Path) -> None:
    repository = tmp_path / "canonical"
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch", "main", str(repository)],
        check=True,
    )
    (repository / ".beads").mkdir(parents=True)
    (repository / ".beads" / "config.yaml").write_text("prefix: fixture\n")
    (repository / ".library.lock").write_text("schema_version: 2\n")
    _commit_repository(repository)
    subprocess.run(
        ["git", "-C", str(repository), "checkout", "--detach", "--quiet"],
        check=True,
    )

    assert global_skill_cutover.inspect_repositories([repository]) == [
        {
            "path": str(repository.resolve()),
            "status": "blocked",
            "reason": "canonical checkout is detached",
        }
    ]


def test_cutover_rejects_a_clean_branch_other_than_the_approved_branch(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "canonical"
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch", "main", str(repository)],
        check=True,
    )
    (repository / ".beads").mkdir(parents=True)
    (repository / ".beads" / "config.yaml").write_text("prefix: fixture\n")
    (repository / ".library.lock").write_text("schema_version: 2\n")
    _commit_repository(repository)
    approved_commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "switch",
            "--quiet",
            "-c",
            "feat/fixture/other-branch",
        ],
        check=True,
    )

    problem = global_skill_cutover.canonical_checkout_problem(
        repository,
        expected_branch="main",
        expected_commit=approved_commit,
    )

    assert problem == ("canonical branch is feat/fixture/other-branch; expected main")


def test_cutover_rejects_a_canonical_branch_without_the_approved_upstream(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "canonical"
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch", "main", str(repository)],
        check=True,
    )
    (repository / ".beads").mkdir(parents=True)
    (repository / ".beads" / "config.yaml").write_text("prefix: fixture\n")
    (repository / ".library.lock").write_text("schema_version: 2\n")
    _commit_repository(repository)
    _write_approved_fleet_manifest(tmp_path, [repository])
    approved_commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(repository), "branch", "--unset-upstream"],
        check=True,
    )

    problem = global_skill_cutover.canonical_checkout_problem(
        repository,
        expected_branch="main",
        expected_commit=approved_commit,
        expected_remote="origin",
    )

    assert problem == "canonical branch does not track origin/main"


def test_cutover_rejects_a_commit_absent_from_the_published_branch(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "canonical"
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch", "main", str(repository)],
        check=True,
    )
    (repository / ".beads").mkdir(parents=True)
    (repository / ".beads" / "config.yaml").write_text("prefix: fixture\n")
    (repository / ".library.lock").write_text("schema_version: 2\n")
    _commit_repository(repository)
    _write_approved_fleet_manifest(tmp_path, [repository])
    (repository / "local-only.txt").write_text("not published\n")
    _commit_repository(repository)
    approved_commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "update-ref",
            "refs/remotes/origin/main",
            approved_commit,
        ],
        check=True,
    )

    problem = global_skill_cutover.canonical_checkout_problem(
        repository,
        expected_branch="main",
        expected_commit=approved_commit,
        expected_remote="origin",
    )

    assert problem == f"published origin/main does not serve {approved_commit}"


def test_cutover_rejects_a_repository_subset_of_the_approved_fleet(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    assert library_cli.main(["bootstrap", "install", "--json"]) == 0
    capsys.readouterr()
    first = (tmp_path / "first").resolve()
    second = (tmp_path / "second").resolve()
    manifest = tmp_path / "approved-fleet.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bead_id": "CL-31po",
                "approval": {
                    "approved_by": "fixture-operator",
                    "approved_at": "2026-08-14T00:00:00Z",
                },
                "repositories": [
                    {
                        "path": str(first),
                        "branch": "main",
                        "published_commit": "1" * 40,
                        "remote": "origin",
                    },
                    {
                        "path": str(second),
                        "branch": "main",
                        "published_commit": "2" * 40,
                        "remote": "origin",
                    },
                ],
            },
            indent=2,
        )
        + "\n"
    )
    backup = tmp_path / "cutover-backup"

    result = library_cli.main(
        [
            "bootstrap",
            "cutover-skills",
            "--fleet-manifest",
            str(manifest),
            "--repository",
            str(first),
            "--backup",
            str(backup),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["stage"] == "fleet-approval"
    assert payload["missing_approved_repositories"] == [str(second)]
    assert payload["unapproved_repositories"] == []
    assert not backup.exists()


def test_cutover_rejects_an_install_target_for_a_different_skill(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    target = home / ".agents" / "skills" / "other-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Other skill\n")
    lock_path = _write_global_lock(home, target)
    lock = global_skill_cutover.load_cutover_lock(lock_path)

    assert global_skill_cutover.inspect_skill_receipts(lock, home) == [
        {
            "id": "skill:legacy-skill",
            "status": "blocked",
            "reason": f"install target does not match the Skill name: {target}",
        }
    ]


def test_cutover_rejects_a_bridge_for_a_different_skill(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    target = home / ".agents" / "skills" / "legacy-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Legacy skill\n")
    lock_path = _write_global_lock(home, target, with_bridge=True)
    correct_bridge = home / ".claude" / "skills" / "legacy-skill"
    wrong_bridge = home / ".claude" / "skills" / "other-skill"
    correct_bridge.rename(wrong_bridge)
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    receipt = lock["receipts"][0]
    receipt["bridge_symlinks"] = [f"{wrong_bridge} -> {target}"]
    symlink_target = next(
        item for item in receipt["targets"] if item["kind"] == "symlink"
    )
    symlink_target["path"] = str(wrong_bridge)

    assert global_skill_cutover.inspect_skill_receipts(lock, home) == [
        {
            "id": "skill:legacy-skill",
            "status": "blocked",
            "reason": f"bridge does not match the Skill name: {wrong_bridge}",
        }
    ]


def test_cutover_refuses_an_unhealthy_repository_before_backup_or_mutation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))

    assert library_cli.main(["bootstrap", "install", "--json"]) == 0
    capsys.readouterr()

    repository = tmp_path / "consumer"
    (repository / ".beads").mkdir(parents=True)
    (repository / ".beads" / "config.yaml").write_text("prefix: fixture\n")
    _commit_repository(repository)
    fleet_manifest = _write_approved_fleet_manifest(tmp_path, [repository])

    target = home / ".agents" / "skills" / "legacy-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Legacy skill\n")
    lock_path = _write_global_lock(home, target)
    lock_before = lock_path.read_bytes()
    backup = tmp_path / "cutover-backup"

    result = library_cli.main(
        [
            "bootstrap",
            "cutover-skills",
            "--fleet-manifest",
            str(fleet_manifest),
            "--repository",
            str(repository),
            "--backup",
            str(backup),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["status"] == "blocked"
    assert payload["stage"] == "repository-health"
    assert payload["repositories"] == [
        {
            "path": str(repository.resolve()),
            "status": "blocked",
            "reason": ".library.lock is missing",
        }
    ]
    assert target.is_dir()
    assert lock_path.read_bytes() == lock_before
    assert not backup.exists()


def test_cutover_refuses_drifted_skill_content_before_backup(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    assert library_cli.main(["bootstrap", "install", "--json"]) == 0
    capsys.readouterr()

    repository = _prepare_healthy_repository(tmp_path, monkeypatch, capsys)
    fleet_manifest = _write_approved_fleet_manifest(tmp_path, [repository])
    target = home / ".agents" / "skills" / "legacy-skill"
    target.mkdir(parents=True)
    skill_file = target / "SKILL.md"
    skill_file.write_text("# Recorded content\n")
    lock_path = _write_global_lock(home, target)
    lock_before = lock_path.read_bytes()
    skill_file.write_text("# Operator changed content\n")
    backup = tmp_path / "cutover-backup"

    result = library_cli.main(
        [
            "bootstrap",
            "cutover-skills",
            "--fleet-manifest",
            str(fleet_manifest),
            "--repository",
            str(repository),
            "--backup",
            str(backup),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["status"] == "blocked"
    assert payload["stage"] == "receipt-ownership"
    assert payload["skills"] == [
        {
            "id": "skill:legacy-skill",
            "status": "blocked",
            "reason": f"content drift at {skill_file}",
        }
    ]
    assert skill_file.read_text() == "# Operator changed content\n"
    assert lock_path.read_bytes() == lock_before
    assert not backup.exists()


def test_cutover_backs_up_and_removes_only_global_skills(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    assert library_cli.main(["bootstrap", "install", "--json"]) == 0
    capsys.readouterr()

    repository = _prepare_healthy_repository(tmp_path, monkeypatch, capsys)
    fleet_manifest = _write_approved_fleet_manifest(tmp_path, [repository])

    target = home / ".agents" / "skills" / "legacy-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Legacy skill\n")
    lock_path = _write_global_lock(home, target, with_bridge=True)
    bridge = home / ".claude" / "skills" / "legacy-skill"
    original_lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    retained_before = next(
        receipt
        for receipt in original_lock["receipts"]
        if receipt["id"] == "mcp:open-brain"
    )
    backup = tmp_path / "cutover-backup"
    result = library_cli.main(
        [
            "bootstrap",
            "cutover-skills",
            "--fleet-manifest",
            str(fleet_manifest),
            "--repository",
            str(repository),
            "--backup",
            str(backup),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0, payload
    assert payload["status"] == "ok"
    assert payload["stage"] == "complete"
    assert payload["catalog_skill_count"] == 110
    assert payload["global_skill_receipts"] == 0
    assert payload["removed_skill_receipts"] == ["skill:legacy-skill"]
    assert payload["backup"] == str(backup.resolve())
    assert not target.exists()
    assert not bridge.exists() and not bridge.is_symlink()

    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["global_lock"]["source"] == str(lock_path)
    assert len(manifest["targets"]) == 2
    assert all(
        item["source_state"] == item["backup_state"] for item in manifest["targets"]
    )

    final_lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    assert not [item for item in final_lock["receipts"] if item["type"] == "skill"]
    assert not [item for item in final_lock["installed"] if item["type"] == "skill"]
    assert not [
        item for item in final_lock["requested_roots"] if item["type"] == "skill"
    ]
    assert (
        next(
            receipt
            for receipt in final_lock["receipts"]
            if receipt["id"] == "mcp:open-brain"
        )
        == retained_before
    )
    assert library_cli._bootstrap_health(home)["status"] == "ready"


def test_cutover_refuses_unrecorded_content_inside_an_owned_skill(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    assert library_cli.main(["bootstrap", "install", "--json"]) == 0
    capsys.readouterr()
    repository = _prepare_healthy_repository(tmp_path, monkeypatch, capsys)
    fleet_manifest = _write_approved_fleet_manifest(tmp_path, [repository])

    target = home / ".agents" / "skills" / "legacy-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Legacy skill\n")
    lock_path = _write_global_lock(home, target)
    lock_before = lock_path.read_bytes()
    unmanaged = target / "operator-note.md"
    unmanaged.write_text("operator-owned\n")
    backup = tmp_path / "cutover-backup"

    result = library_cli.main(
        [
            "bootstrap",
            "cutover-skills",
            "--fleet-manifest",
            str(fleet_manifest),
            "--repository",
            str(repository),
            "--backup",
            str(backup),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["stage"] == "receipt-ownership"
    assert payload["skills"][0]["reason"] == f"unrecorded nested content at {target}"
    assert unmanaged.read_text() == "operator-owned\n"
    assert lock_path.read_bytes() == lock_before
    assert not backup.exists()


def test_cutover_rechecks_repository_health_at_the_transaction_boundary(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    assert library_cli.main(["bootstrap", "install", "--json"]) == 0
    capsys.readouterr()
    repository = _prepare_healthy_repository(tmp_path, monkeypatch, capsys)
    fleet_manifest = _write_approved_fleet_manifest(tmp_path, [repository])

    target = home / ".agents" / "skills" / "legacy-skill"
    target.mkdir(parents=True)
    skill_file = target / "SKILL.md"
    skill_file.write_text("# Legacy skill\n")
    lock_path = _write_global_lock(home, target)
    lock_before = lock_path.read_bytes()
    backup = tmp_path / "cutover-backup"
    real_execute = global_skill_cutover.execute_cutover

    def dirty_repository_before_transaction(**kwargs):
        (repository / "operator-change.txt").write_text("preserve me\n")
        return real_execute(**kwargs)

    monkeypatch.setattr(
        global_skill_cutover,
        "execute_cutover",
        dirty_repository_before_transaction,
    )

    result = library_cli.main(
        [
            "bootstrap",
            "cutover-skills",
            "--fleet-manifest",
            str(fleet_manifest),
            "--repository",
            str(repository),
            "--backup",
            str(backup),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["stage"] == "transaction"
    assert "prerequisites changed at repository-health" in payload["message"]
    assert (repository / "operator-change.txt").read_text() == "preserve me\n"
    assert skill_file.read_text() == "# Legacy skill\n"
    assert lock_path.read_bytes() == lock_before
    assert not backup.exists()


def test_cutover_rechecks_repository_health_after_backup_before_deletion(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    assert library_cli.main(["bootstrap", "install", "--json"]) == 0
    capsys.readouterr()
    repository = _prepare_healthy_repository(tmp_path, monkeypatch, capsys)
    fleet_manifest = _write_approved_fleet_manifest(tmp_path, [repository])

    target = home / ".agents" / "skills" / "legacy-skill"
    target.mkdir(parents=True)
    skill_file = target / "SKILL.md"
    skill_file.write_text("# Legacy skill\n")
    lock_path = _write_global_lock(home, target)
    lock_before = lock_path.read_bytes()
    backup = tmp_path / "cutover-backup"
    real_copy = global_skill_cutover._copy_path
    changed = False

    def change_repository_after_backup_copy(source: Path, destination: Path) -> None:
        nonlocal changed
        real_copy(source, destination)
        if not changed:
            changed = True
            (repository / "operator-change.txt").write_text("preserve me\n")

    monkeypatch.setattr(
        global_skill_cutover,
        "_copy_path",
        change_repository_after_backup_copy,
    )

    result = library_cli.main(
        [
            "bootstrap",
            "cutover-skills",
            "--fleet-manifest",
            str(fleet_manifest),
            "--repository",
            str(repository),
            "--backup",
            str(backup),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["stage"] == "transaction"
    assert "prerequisites changed at repository-health" in payload["message"]
    assert (repository / "operator-change.txt").read_text() == "preserve me\n"
    assert skill_file.read_text() == "# Legacy skill\n"
    assert lock_path.read_bytes() == lock_before
    assert (backup / "manifest.json").is_file()


def test_cutover_rejects_a_changed_fleet_manifest_after_backup(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    assert library_cli.main(["bootstrap", "install", "--json"]) == 0
    capsys.readouterr()
    repository = _prepare_healthy_repository(tmp_path, monkeypatch, capsys)
    fleet_manifest = _write_approved_fleet_manifest(tmp_path, [repository])

    target = home / ".agents" / "skills" / "legacy-skill"
    target.mkdir(parents=True)
    skill_file = target / "SKILL.md"
    skill_file.write_text("# Legacy skill\n")
    lock_path = _write_global_lock(home, target)
    lock_before = lock_path.read_bytes()
    backup = tmp_path / "cutover-backup"
    real_copy = global_skill_cutover._copy_path
    changed = False

    def change_manifest_after_backup_copy(source: Path, destination: Path) -> None:
        nonlocal changed
        real_copy(source, destination)
        if not changed:
            changed = True
            payload = json.loads(fleet_manifest.read_text(encoding="utf-8"))
            payload["approval"]["approved_at"] = "2026-08-14T00:00:01Z"
            fleet_manifest.write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(
        global_skill_cutover,
        "_copy_path",
        change_manifest_after_backup_copy,
    )

    result = library_cli.main(
        [
            "bootstrap",
            "cutover-skills",
            "--fleet-manifest",
            str(fleet_manifest),
            "--repository",
            str(repository),
            "--backup",
            str(backup),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["stage"] == "transaction"
    assert payload["message"] == (
        "Approved fleet manifest changed after cutover preflight"
    )
    assert skill_file.read_text() == "# Legacy skill\n"
    assert lock_path.read_bytes() == lock_before
    assert (backup / "manifest.json").is_file()


def test_cutover_rejects_skill_drift_after_backup_before_deletion(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    assert library_cli.main(["bootstrap", "install", "--json"]) == 0
    capsys.readouterr()
    repository = _prepare_healthy_repository(tmp_path, monkeypatch, capsys)
    fleet_manifest = _write_approved_fleet_manifest(tmp_path, [repository])

    target = home / ".agents" / "skills" / "legacy-skill"
    target.mkdir(parents=True)
    skill_file = target / "SKILL.md"
    skill_file.write_text("# Legacy skill\n")
    lock_path = _write_global_lock(home, target)
    lock_before = lock_path.read_bytes()
    backup = tmp_path / "cutover-backup"
    real_atomic_write = global_skill_cutover.atomic_write_text
    changed = False

    def change_skill_after_backup_manifest(path: Path, content: str) -> None:
        nonlocal changed
        real_atomic_write(path, content)
        if path == backup / "manifest.json" and not changed:
            changed = True
            skill_file.write_text("# Operator changed content\n")

    monkeypatch.setattr(
        global_skill_cutover,
        "atomic_write_text",
        change_skill_after_backup_manifest,
    )

    result = library_cli.main(
        [
            "bootstrap",
            "cutover-skills",
            "--fleet-manifest",
            str(fleet_manifest),
            "--repository",
            str(repository),
            "--backup",
            str(backup),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["stage"] == "transaction"
    assert "Global Skill ownership changed after backup" in payload["message"]
    assert f"content drift at {skill_file}" in payload["message"]
    assert skill_file.read_text() == "# Operator changed content\n"
    assert lock_path.read_bytes() == lock_before
    assert (backup / "manifest.json").is_file()


def test_cutover_refuses_a_backup_nested_inside_an_owned_skill(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    assert library_cli.main(["bootstrap", "install", "--json"]) == 0
    capsys.readouterr()
    repository = _prepare_healthy_repository(tmp_path, monkeypatch, capsys)
    fleet_manifest = _write_approved_fleet_manifest(tmp_path, [repository])

    target = home / ".agents" / "skills" / "legacy-skill"
    target.mkdir(parents=True)
    skill_file = target / "SKILL.md"
    skill_file.write_text("# Legacy skill\n")
    lock_path = _write_global_lock(home, target)
    lock_before = lock_path.read_bytes()
    backup = target / "cutover-backup"

    result = library_cli.main(
        [
            "bootstrap",
            "cutover-skills",
            "--fleet-manifest",
            str(fleet_manifest),
            "--repository",
            str(repository),
            "--backup",
            str(backup),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["stage"] == "transaction"
    assert "overlaps a Skill removal target" in payload["message"]
    assert skill_file.read_text() == "# Legacy skill\n"
    assert lock_path.read_bytes() == lock_before
    assert not backup.exists()


def test_cutover_restores_targets_and_lock_when_transaction_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    assert library_cli.main(["bootstrap", "install", "--json"]) == 0
    capsys.readouterr()
    repository = _prepare_healthy_repository(tmp_path, monkeypatch, capsys)
    fleet_manifest = _write_approved_fleet_manifest(tmp_path, [repository])

    target = home / ".agents" / "skills" / "legacy-skill"
    target.mkdir(parents=True)
    skill_file = target / "SKILL.md"
    skill_file.write_text("# Legacy skill\n")
    lock_path = _write_global_lock(home, target, with_bridge=True)
    lock_before = lock_path.read_bytes()
    bridge = home / ".claude" / "skills" / "legacy-skill"
    backup = tmp_path / "cutover-backup"

    real_remove = global_skill_cutover._remove_path
    calls = 0

    def fail_second_removal(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected removal failure")
        real_remove(path)

    monkeypatch.setattr(global_skill_cutover, "_remove_path", fail_second_removal)

    result = library_cli.main(
        [
            "bootstrap",
            "cutover-skills",
            "--fleet-manifest",
            str(fleet_manifest),
            "--repository",
            str(repository),
            "--backup",
            str(backup),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["stage"] == "transaction"
    assert "original state restored" in payload["message"]
    assert skill_file.read_text() == "# Legacy skill\n"
    assert bridge.is_symlink() and bridge.readlink() == target
    assert lock_path.read_bytes() == lock_before
    assert (backup / "manifest.json").is_file()
