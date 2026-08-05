from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.errors import LibraryError
from lib.workspace import (
    apply_direct_root_demotion,
    apply_post_prune_lock,
    apply_prune_plan,
    build_direct_root_demotion_plan,
    build_workspace_plan,
    discard_workspace_journal,
    prepare_prune_plan,
    recover_workspace_journal,
    resolve_workspace,
    resolve_workspace_closure,
    workspace_journal_digest,
    workspace_root_id,
    workspace_write_lock,
    write_workspace_journal,
)


def _catalog(*, duplicate: bool = False) -> dict:
    workspaces = [
        {
            "schema_version": 1,
            "name": "python-cli",
            "version": "1.0.0",
            "description": "Python CLI baseline.",
            "status": "experimental",
            "roots": [
                {"type": "skill", "name": "python-dev"},
                {"type": "skill", "name": "python-test"},
            ],
            "source": "https://github.com/example/core/blob/main/workspaces/python-cli.yaml",
            "metadata": {
                "library": {
                    "source_catalog": "team-core",
                    "inventory": "convention-scan",
                }
            },
        }
    ]
    catalogs = [
        {
            "name": "team-core",
            "source": "https://github.com/example/core",
            "content_types": ["skills", "standards", "workspaces"],
        }
    ]
    if duplicate:
        workspaces.append(
            {
                **workspaces[0],
                "source": "https://github.com/example/other/blob/main/workspaces/python-cli.yaml",
                "metadata": {
                    "library": {
                        "source_catalog": "other-core",
                        "inventory": "convention-scan",
                    }
                },
            }
        )
        catalogs.append(
            {
                "name": "other-core",
                "source": "https://github.com/example/other",
                "content_types": ["skills", "workspaces"],
            }
        )
    return {
        "sources": {"catalogs": catalogs, "marketplaces": []},
        "library": {
            "workspaces": workspaces,
            "skills": [
                {
                    "name": "python-dev",
                    "description": "Develop Python CLIs.",
                    "source": "https://github.com/example/core/blob/main/skills/python-dev/SKILL.md",
                    "requires": ["standard:python"],
                    "metadata": {"library": {"source_catalog": "team-core"}},
                },
                {
                    "name": "python-test",
                    "description": "Test Python CLIs.",
                    "source": "https://github.com/example/core/blob/main/skills/python-test/SKILL.md",
                    "requires": ["standard:python", "mcp:test-service"],
                    "metadata": {"library": {"source_catalog": "team-core"}},
                },
            ],
            "standards": [
                {
                    "name": "python",
                    "description": "Python standard.",
                    "source": "https://github.com/example/core/blob/main/standards/python.md",
                    "metadata": {"library": {"source_catalog": "team-core"}},
                }
            ],
            "mcp_servers": [
                {
                    "name": "test-service",
                    "description": "Test MCP.",
                    "metadata": {"library": {"source_catalog": "team-core"}},
                }
            ],
        },
    }


def _empty_lock() -> dict:
    return {
        "schema_version": 2,
        "migration": {"prune_ack_required": False},
        "requested_roots": [],
        "receipts": [],
        "prerequisites": [],
        "installed": [],
    }


def test_workspace_reference_requires_qualification_when_ambiguous() -> None:
    with pytest.raises(LibraryError, match="Ambiguous Workspace"):
        resolve_workspace(_catalog(duplicate=True), "python-cli")

    resolved = resolve_workspace(_catalog(duplicate=True), "team-core:python-cli")

    assert resolved.catalog_name == "team-core"
    assert resolved.catalog_identity == "https://github.com/example/core"


def test_project_closure_separates_global_prerequisites() -> None:
    catalog = _catalog()
    workspace = resolve_workspace(catalog, "team-core:python-cli")

    closure = resolve_workspace_closure(catalog, workspace, Path.cwd(), "project")

    assert closure.artifacts == (
        ("standard", "python"),
        ("skill", "python-dev"),
        ("skill", "python-test"),
    )
    assert closure.prerequisites == (("mcp", "test-service"),)


def test_unsatisfied_root_constraint_fails_before_reconciliation() -> None:
    catalog = _catalog()
    catalog["library"]["skills"][0]["version"] = "1.2.0"
    workspace = resolve_workspace(catalog, "team-core:python-cli")
    workspace.entry["roots"][0]["constraint"] = ">=2.0.0,<3.0.0"

    with pytest.raises(LibraryError, match="unsatisfied"):
        resolve_workspace_closure(catalog, workspace, Path.cwd(), "project")


def test_scope_mismatch_fails_before_reconciliation() -> None:
    catalog = _catalog()
    catalog["library"]["skills"][0]["default_scope"] = "global"
    workspace = resolve_workspace(catalog, "team-core:python-cli")

    with pytest.raises(LibraryError, match="scope project conflicts"):
        resolve_workspace_closure(catalog, workspace, Path.cwd(), "project")


def test_project_closure_treats_global_scoped_dependency_as_prerequisite() -> None:
    catalog = _catalog()
    catalog["library"]["standards"][0]["default_scope"] = "global"
    workspace = resolve_workspace(catalog, "team-core:python-cli")

    closure = resolve_workspace_closure(catalog, workspace, Path.cwd(), "project")

    assert closure.artifacts == (("skill", "python-dev"), ("skill", "python-test"))
    assert closure.prerequisites == (
        ("standard", "python"),
        ("mcp", "test-service"),
    )


def test_plan_recomputes_shared_ownership_from_all_roots() -> None:
    catalog = _catalog()
    workspace = resolve_workspace(catalog, "team-core:python-cli")
    workspace_id = workspace_root_id(workspace.catalog_identity, workspace.name)
    lock = _empty_lock()
    lock["requested_roots"] = [
        {
            "id": workspace_id,
            "type": "workspace",
            "name": workspace.name,
            "scope": "project",
            "catalog_identity": workspace.catalog_identity,
            "catalog_name": workspace.catalog_name,
            "requested_ref": "team-core:python-cli",
            "resolved_version": workspace.version,
            "definition_commit": "a" * 40,
            "roots": ["skill:python-dev", "skill:python-test"],
        },
        {
            "id": "skill:python-dev",
            "type": "skill",
            "name": "python-dev",
            "scope": "project",
            "catalog_identity": workspace.catalog_identity,
            "resolved_version": "legacy",
            "definition_commit": "b" * 40,
        },
    ]
    for primitive, name in (
        ("standard", "python"),
        ("skill", "python-dev"),
        ("skill", "python-test"),
    ):
        lock["receipts"].append(
            {
                "id": f"{primitive}:{name}",
                "type": primitive,
                "name": name,
                "scope": "project",
                "catalog_identity": workspace.catalog_identity,
                "resolved_version": "legacy",
                "verified": True,
                "adopted": False,
                "prune_blocked_reason": None,
                "targets": [],
                "owners_cache": [],
            }
        )

    plan = build_workspace_plan(catalog, lock, Path.cwd(), "project")

    owners = {item["id"]: item["owners"] for item in plan["receipts"]}
    assert owners["skill:python-dev"] == ["skill:python-dev", workspace_id]
    assert owners["standard:python"] == ["skill:python-dev", workspace_id]
    assert plan["prune_candidates"] == []


def test_direct_root_demotion_is_digest_bound_and_lock_only() -> None:
    catalog = _catalog()
    workspace = resolve_workspace(catalog, "team-core:python-cli")
    lock = _empty_lock()
    lock["requested_roots"] = [
        {
            "id": workspace_root_id(workspace.catalog_identity, workspace.name),
            "type": "workspace",
            "name": workspace.name,
            "scope": "project",
            "catalog_identity": workspace.catalog_identity,
            "catalog_name": workspace.catalog_name,
            "requested_ref": "team-core:python-cli",
            "resolved_version": workspace.version,
            "definition_commit": "a" * 40,
            "roots": ["skill:python-dev", "skill:python-test"],
        },
        {
            "id": "skill:python-dev",
            "type": "skill",
            "name": "python-dev",
            "scope": "project",
            "catalog_identity": workspace.catalog_identity,
            "resolved_version": "legacy",
            "definition_commit": "b" * 40,
        },
    ]

    plan = build_direct_root_demotion_plan(
        catalog,
        lock,
        Path.cwd(),
        "project",
        "team-core:python-cli",
        member="skill:python-dev",
    )
    before = list(lock["requested_roots"])

    with pytest.raises(LibraryError, match="digest"):
        apply_direct_root_demotion(lock, plan, "stale")
    assert lock["requested_roots"] == before

    apply_direct_root_demotion(lock, plan, plan["digest"])
    assert [root["id"] for root in lock["requested_roots"]] == [
        workspace_root_id(workspace.catalog_identity, workspace.name)
    ]


def test_global_lobby_rejects_too_many_direct_roots() -> None:
    catalog = _catalog()
    workspace = resolve_workspace(catalog, "team-core:python-cli")
    for index in range(3):
        catalog["library"]["skills"].append(
            {
                "name": f"extra-{index}",
                "description": "Extra root.",
                "source": f"https://github.com/example/core/blob/main/skills/extra-{index}/SKILL.md",
                "metadata": {"library": {"source_catalog": "team-core"}},
            }
        )
    workspace.entry["roots"] = [
        {"type": "skill", "name": "python-dev"},
        {"type": "skill", "name": "python-test"},
        {"type": "standard", "name": "python"},
        {"type": "skill", "name": "extra-0"},
        {"type": "skill", "name": "extra-1"},
        {"type": "skill", "name": "extra-2"},
    ]

    with pytest.raises(LibraryError, match="at most 5 direct roots"):
        resolve_workspace_closure(catalog, workspace, Path.cwd(), "global")


def test_workspace_policy_can_lower_but_not_raise_safety_budgets() -> None:
    catalog = _catalog()
    catalog["workspace_policy"] = {
        "project": {"max_receipts": 1},
        "global": {
            "max_roots": 99,
            "max_receipts": 99,
            "max_standing_context_fraction": 1,
        },
    }
    workspace = resolve_workspace(catalog, "team-core:python-cli")

    with pytest.raises(LibraryError, match="limit is 1"):
        resolve_workspace_closure(catalog, workspace, Path.cwd(), "project")

    workspace.entry["standing_context_fraction"] = 0.02
    with pytest.raises(LibraryError, match="standing-context budget"):
        resolve_workspace_closure(catalog, workspace, Path.cwd(), "global")


def test_workspace_write_lock_rejects_concurrent_mutation(tmp_path: Path) -> None:
    lock_path = tmp_path / ".library.lock"

    with (
        workspace_write_lock(lock_path),
        pytest.raises(LibraryError, match="Another Workspace mutation"),
        workspace_write_lock(lock_path),
    ):
        pytest.fail("second lock acquisition must not succeed")


def test_prune_is_exact_digest_bound_and_blocks_foreign_siblings(
    tmp_path: Path,
) -> None:
    from lib.lockfile import compute_checksum

    managed = tmp_path / ".agents" / "skills" / "old" / "SKILL.md"
    sibling = managed.parent / "project-note.md"
    managed.parent.mkdir(parents=True)
    managed.write_text("managed\n")
    sibling.write_text("project owned\n")
    lock = _empty_lock()
    lock["receipts"] = [
        {
            "id": "skill:old",
            "type": "skill",
            "name": "old",
            "scope": "project",
            "catalog_identity": "https://github.com/example/core",
            "resolved_version": "1.0.0",
            "verified": True,
            "adopted": False,
            "prune_blocked_reason": None,
            "targets": [
                {"path": str(managed.parent), "kind": "directory"},
                {
                    "path": str(managed.relative_to(tmp_path)),
                    "kind": "file",
                    "content_sha256": compute_checksum(managed),
                },
            ],
            "owners_cache": [],
        }
    ]
    plan = build_workspace_plan(_catalog(), lock, tmp_path, "project")

    with pytest.raises(LibraryError, match="digest"):
        apply_prune_plan(
            lock,
            plan,
            tmp_path,
            "stale",
            lock_path=tmp_path / ".library.lock",
        )
    assert managed.exists()

    with pytest.raises(LibraryError, match="unrecorded nested content"):
        apply_prune_plan(
            lock,
            plan,
            tmp_path,
            plan["digest"],
            lock_path=tmp_path / ".library.lock",
            allowed_roots=[tmp_path / ".agents" / "skills"],
        )

    assert managed.exists()
    assert sibling.read_text() == "project owned\n"
    assert lock["receipts"]


def test_prune_removes_an_exact_empty_library_container(tmp_path: Path) -> None:
    from lib.lockfile import compute_checksum

    container = tmp_path / ".agents" / "skills" / "old"
    managed = container / "SKILL.md"
    container.mkdir(parents=True)
    managed.write_text("managed\n")
    lock = _empty_lock()
    lock["receipts"] = [
        {
            "id": "skill:old",
            "type": "skill",
            "name": "old",
            "scope": "project",
            "catalog_identity": "https://github.com/example/core",
            "resolved_version": "1.0.0",
            "verified": True,
            "adopted": False,
            "prune_blocked_reason": None,
            "targets": [
                {"path": str(container), "kind": "directory"},
                {
                    "path": str(managed),
                    "kind": "file",
                    "content_sha256": compute_checksum(managed),
                },
            ],
            "owners_cache": [],
        }
    ]
    plan = build_workspace_plan(_catalog(), lock, tmp_path, "project")

    deleted = apply_prune_plan(
        lock,
        plan,
        tmp_path,
        plan["digest"],
        lock_path=tmp_path / ".library.lock",
        allowed_roots=[tmp_path / ".agents" / "skills"],
    )

    assert deleted == [str(managed)]
    assert not container.exists()
    assert lock["receipts"] == []


def test_prune_blocks_external_manager_claim_before_deleting(tmp_path: Path) -> None:
    from lib.lockfile import compute_checksum

    target = tmp_path / ".agents" / "standards" / "managed.md"
    target.parent.mkdir(parents=True)
    target.write_text("managed\n")
    lock = _empty_lock()
    lock["receipts"] = [
        {
            "id": "standard:managed",
            "type": "standard",
            "name": "managed",
            "scope": "global",
            "catalog_identity": "https://github.com/example/core",
            "resolved_version": "1.0.0",
            "verified": True,
            "adopted": False,
            "prune_blocked_reason": None,
            "targets": [
                {
                    "path": str(target),
                    "kind": "file",
                    "content_sha256": compute_checksum(target),
                }
            ],
            "owners_cache": [],
        }
    ]
    plan = build_workspace_plan(_catalog(), lock, tmp_path, "global")

    with pytest.raises(LibraryError, match="managed by chezmoi"):
        apply_prune_plan(
            lock,
            plan,
            tmp_path,
            plan["digest"],
            lock_path=tmp_path / ".library.lock",
            managed_paths={str(target): "chezmoi"},
            allowed_roots=[target.parent],
        )
    assert target.exists()


def test_prune_blocks_manager_claim_through_symlinked_parent(tmp_path: Path) -> None:
    from lib.lockfile import compute_checksum

    real_root = tmp_path / "real-standards"
    real_root.mkdir()
    alias_root = tmp_path / "standards"
    alias_root.symlink_to(real_root, target_is_directory=True)
    target = alias_root / "managed.md"
    target.write_text("managed\n")
    lock = _empty_lock()
    lock["receipts"] = [
        {
            "id": "standard:managed",
            "type": "standard",
            "name": "managed",
            "scope": "global",
            "catalog_identity": "https://github.com/example/core",
            "resolved_version": "1.0.0",
            "verified": True,
            "adopted": False,
            "prune_blocked_reason": None,
            "targets": [
                {
                    "path": str(target),
                    "kind": "file",
                    "content_sha256": compute_checksum(target),
                }
            ],
            "owners_cache": [],
        }
    ]
    plan = build_workspace_plan(_catalog(), lock, tmp_path, "global")

    with pytest.raises(LibraryError, match="managed by chezmoi"):
        prepare_prune_plan(
            lock,
            plan,
            tmp_path,
            plan["digest"],
            managed_paths={str(target): "chezmoi"},
            allowed_roots=[alias_root],
        )

    assert target.read_text() == "managed\n"


def test_prune_blocks_symlink_target_drift(tmp_path: Path) -> None:
    root = tmp_path / ".agents" / "skills"
    root.mkdir(parents=True)
    first = root / "first"
    second = root / "second"
    first.mkdir()
    second.mkdir()
    link = root / "bridge"
    link.symlink_to(first)
    lock = _empty_lock()
    lock["receipts"] = [
        {
            "id": "skill:bridge",
            "type": "skill",
            "name": "bridge",
            "scope": "project",
            "catalog_identity": "https://github.com/example/core",
            "resolved_version": "1.0.0",
            "verified": True,
            "adopted": False,
            "prune_blocked_reason": None,
            "targets": [
                {
                    "path": str(link),
                    "kind": "symlink",
                    "link_target": str(first),
                }
            ],
            "owners_cache": [],
        }
    ]
    plan = build_workspace_plan(_catalog(), lock, tmp_path, "project")
    link.unlink()
    link.symlink_to(second)

    with pytest.raises(LibraryError, match="symlink target drift"):
        apply_prune_plan(
            lock,
            plan,
            tmp_path,
            plan["digest"],
            lock_path=tmp_path / ".library.lock",
            allowed_roots=[root],
        )

    assert link.readlink() == second


def test_prune_recovery_resumes_after_post_prune_lock_commit(tmp_path: Path) -> None:
    from lib.lockfile import compute_checksum, save_lockfile

    target = tmp_path / ".agents" / "standards" / "old.md"
    target.parent.mkdir(parents=True)
    target.write_text("old\n")
    lock_path = tmp_path / ".library.lock"
    lock = _empty_lock()
    lock["receipts"] = [
        {
            "id": "standard:old",
            "type": "standard",
            "name": "old",
            "scope": "project",
            "catalog_identity": "https://github.com/example/core",
            "resolved_version": "1.0.0",
            "verified": True,
            "adopted": False,
            "prune_blocked_reason": None,
            "targets": [
                {
                    "path": str(target),
                    "kind": "file",
                    "content_sha256": compute_checksum(target),
                }
            ],
            "owners_cache": [],
        }
    ]
    plan = build_workspace_plan(_catalog(), lock, tmp_path, "project")
    prepared = prepare_prune_plan(
        lock,
        plan,
        tmp_path,
        plan["digest"],
        allowed_roots=[target.parent],
    )
    write_workspace_journal(
        lock_path,
        {"operation": "prune", **prepared, "digest": plan["digest"]},
    )
    apply_post_prune_lock(lock, set(prepared["candidate_ids"]))
    save_lockfile(lock_path, lock)

    deleted = recover_workspace_journal(lock_path, tmp_path)

    assert deleted == [str(target)]
    assert not target.exists()
    assert not lock_path.with_name(".library.lock.workspace-journal.json").exists()


def test_recovery_discard_requires_exact_journal_digest_and_deletes_nothing(
    tmp_path: Path,
) -> None:
    target = tmp_path / ".agents" / "standards" / "drifted.md"
    target.parent.mkdir(parents=True)
    target.write_text("changed\n")
    lock_path = tmp_path / ".library.lock"
    write_workspace_journal(
        lock_path,
        {
            "operation": "prune",
            "candidate_ids": ["standard:drifted"],
            "targets": [
                {
                    "path": str(target),
                    "kind": "file",
                    "content_sha256": "0" * 64,
                }
            ],
            "directories": [],
            "allowed_roots": [str(target.parent)],
        },
    )
    digest = workspace_journal_digest(lock_path)
    assert digest is not None

    with pytest.raises(LibraryError, match="digest"):
        discard_workspace_journal(lock_path, "stale")
    discarded = discard_workspace_journal(lock_path, digest)

    assert discarded == digest
    assert target.read_text() == "changed\n"
    assert workspace_journal_digest(lock_path) is None


def test_unparseable_journal_can_be_digest_acknowledged_and_discarded(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / ".library.lock"
    journal = lock_path.with_name(".library.lock.workspace-journal.json")
    journal.write_text("{not-json")

    digest = workspace_journal_digest(lock_path)

    assert digest
    assert discard_workspace_journal(lock_path, digest) == digest
    assert not journal.exists()
