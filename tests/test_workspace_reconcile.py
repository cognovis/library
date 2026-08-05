from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.errors import LibraryError
from lib.workspace import (
    apply_direct_root_demotion,
    apply_prune_plan,
    apply_post_prune_lock,
    build_direct_root_demotion_plan,
    build_workspace_plan,
    resolve_workspace,
    resolve_workspace_closure,
    prepare_prune_plan,
    recover_workspace_journal,
    write_workspace_journal,
    workspace_root_id,
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


def test_prune_is_exact_digest_bound_and_preserves_foreign_siblings(
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
                {
                    "path": str(managed.relative_to(tmp_path)),
                    "kind": "file",
                    "content_sha256": compute_checksum(managed),
                }
            ],
            "owners_cache": [],
        }
    ]
    plan = build_workspace_plan(_catalog(), lock, tmp_path, "project")

    with pytest.raises(LibraryError, match="digest"):
        apply_prune_plan(lock, plan, tmp_path, "stale")
    assert managed.exists()

    deleted = apply_prune_plan(lock, plan, tmp_path, plan["digest"])

    assert deleted == [str(managed)]
    assert not managed.exists()
    assert sibling.read_text() == "project owned\n"
    assert lock["receipts"] == []


def test_prune_blocks_external_manager_claim_before_deleting(tmp_path: Path) -> None:
    from lib.lockfile import compute_checksum

    target = tmp_path / "managed.md"
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
            managed_paths={str(target): "chezmoi"},
        )
    assert target.exists()


def test_prune_recovery_resumes_after_post_prune_lock_commit(tmp_path: Path) -> None:
    from lib.lockfile import compute_checksum, save_lockfile

    target = tmp_path / "old.md"
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
    prepared = prepare_prune_plan(lock, plan, tmp_path, plan["digest"])
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
