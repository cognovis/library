"""Shared catalog and manifest fixtures for the Workspace schema v2 suites.

Two registered catalogs, one v2 manifest that names roots in both of them, and
the knobs each acceptance criterion needs. Kept in one place so the schema,
resolution, and prune-guard suites cannot drift apart on what "the same
manifest" means.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

CORE_NAME = "team-core"
UPSTREAM_NAME = "upstream-core"
THIRD_NAME = "third-core"

CORE_IDENTITY = "https://example.invalid/core"
UPSTREAM_IDENTITY = "https://example.invalid/upstream"
THIRD_IDENTITY = "https://example.invalid/third"

#: An owner this repository neither configures nor declares. It stands for the
#: real case ADR-0011's guard is about: content in the lock that some other
#: owner installed, which this scope must never delete.
FOREIGN_IDENTITY = "https://example.invalid/someone-else"

#: A commit pin is an immutable revision; an inventory-snapshot pin is a digest
#: over a revisionless source's normalized listing. Both shapes appear here so
#: no test accidentally proves the contract for only one of them.
CORE_PIN: dict[str, str] = {"kind": "commit", "value": "a1b2c3d4" + "0" * 32}
UPSTREAM_PIN: dict[str, str] = {"kind": "inventory-snapshot", "value": "b" * 64}
THIRD_PIN: dict[str, str] = {"kind": "commit", "value": "c" * 40}


def v1_manifest() -> dict[str, Any]:
    """The released v1 manifest, which must keep validating unchanged."""
    return {
        "schema_version": 1,
        "name": "python-cli",
        "version": "1.0.0",
        "description": "Shared Python CLI development baseline",
        "status": "experimental",
        "roots": [
            {"type": "skill", "name": "python-dev"},
            {"type": "skill", "name": "python-test"},
        ],
        "source": "workspaces/python-cli.yaml",
        "metadata": {"library": {"source_catalog": CORE_NAME}},
    }


def v2_manifest() -> dict[str, Any]:
    """One manifest naming pinned roots in two different catalogs."""
    return {
        "schema_version": 2,
        "name": "engineering",
        "version": "1.0.0",
        "description": "Engineering baseline composed across two catalogs",
        "status": "experimental",
        "catalogs": [
            {"alias": "core", "identity": CORE_IDENTITY, "pin": deepcopy(CORE_PIN)},
            {
                "alias": "upstream",
                "identity": UPSTREAM_IDENTITY,
                "pin": deepcopy(UPSTREAM_PIN),
            },
        ],
        "roots": [
            {"type": "skill", "name": "python-dev", "catalog": "core"},
            {"type": "skill", "name": "helper", "catalog": "upstream"},
        ],
        "source": "workspaces/engineering.yaml",
        "metadata": {"library": {"source_catalog": CORE_NAME}},
    }


def second_v2_manifest() -> dict[str, Any]:
    """A second Workspace using the same alias word for a different identity.

    Alias-to-identity mapping is manifest-local: this manifest's `core` alias
    points at a third catalog, and nothing about the first manifest changes.
    """
    return {
        "schema_version": 2,
        "name": "reporting",
        "version": "1.0.0",
        "description": "Reporting baseline composed across two catalogs",
        "status": "experimental",
        "catalogs": [
            {"alias": "core", "identity": THIRD_IDENTITY, "pin": deepcopy(THIRD_PIN)},
            {
                "alias": "shared",
                "identity": CORE_IDENTITY,
                "pin": deepcopy(CORE_PIN),
            },
        ],
        "roots": [
            {"type": "skill", "name": "report", "catalog": "core"},
            {"type": "skill", "name": "python-test", "catalog": "shared"},
        ],
        "source": "workspaces/reporting.yaml",
        "metadata": {"library": {"source_catalog": THIRD_NAME}},
    }


def executable_v2_manifest() -> dict[str, Any]:
    """A v2 manifest whose upstream root is an executable primitive.

    Executable admission is the one gate that must run before a Workspace writes
    anything, so the suite needs a manifest that actually reaches an executable
    member across the catalog boundary.
    """
    manifest = v2_manifest()
    manifest["name"] = "deployment"
    manifest["description"] = "Deployment baseline composed across two catalogs"
    manifest["roots"] = [
        {"type": "skill", "name": "python-dev", "catalog": "core"},
        {"type": "workflow", "name": "deploy", "catalog": "upstream"},
    ]
    manifest["source"] = "workspaces/deployment.yaml"
    return manifest


def _skill(
    name: str, source_catalog: str, requires: list[str] | None = None, **extra: Any
) -> dict[str, Any]:
    entry = {
        "name": name,
        "description": f"{name} skill.",
        "version": "1.0.0",
        "source": f"https://example.invalid/{source_catalog}/skills/{name}/SKILL.md",
        "requires": requires or [],
        "metadata": {"library": {"source_catalog": source_catalog}},
    }
    entry.update(extra)
    return entry


def catalog_document(
    *,
    workspaces: list[dict[str, Any]] | None = None,
    collide: bool = False,
) -> dict[str, Any]:
    """A registry with three catalogs and the members the v2 manifests name.

    Args:
        workspaces: Manifests to publish. Defaults to the single v2 manifest.
        collide: Publish `skill:python-dev` from the upstream catalog too, so
            two catalogs supply the same projection target.
    """
    published = workspaces if workspaces is not None else [v2_manifest()]
    skills = [
        _skill("python-dev", CORE_NAME, ["standard:common"]),
        _skill("python-test", CORE_NAME, ["standard:common", "mcp:test-service"]),
        _skill("helper", UPSTREAM_NAME, ["standard:common"]),
        _skill("report", THIRD_NAME, ["standard:common"]),
    ]
    if collide:
        skills.append(_skill("python-dev", UPSTREAM_NAME, ["standard:common"]))
    return {
        "sources": {
            "catalogs": [
                {
                    "name": CORE_NAME,
                    "source": CORE_IDENTITY,
                    "content_types": ["skills", "standards", "workspaces"],
                },
                {
                    "name": UPSTREAM_NAME,
                    "source": UPSTREAM_IDENTITY,
                    "content_types": ["skills", "workspaces"],
                },
                {
                    "name": THIRD_NAME,
                    "source": THIRD_IDENTITY,
                    "content_types": ["skills", "workspaces"],
                },
            ],
            "marketplaces": [],
        },
        "library": {
            "workspaces": deepcopy(published),
            "skills": skills,
            "standards": [
                {
                    "name": "common",
                    "description": "Common standard.",
                    "version": "1.0.0",
                    "source": "https://example.invalid/core/standards/common.md",
                    "metadata": {"library": {"source_catalog": CORE_NAME}},
                }
            ],
            "mcp_servers": [
                {
                    "name": "test-service",
                    "description": "Test MCP.",
                    "version": "1.0.0",
                    "metadata": {"library": {"source_catalog": CORE_NAME}},
                }
            ],
            "workflows": [
                {
                    "name": "deploy",
                    "description": "Deploy workflow.",
                    "version": "1.0.0",
                    "source": "https://example.invalid/upstream/workflows/deploy",
                    "requires": [],
                    "metadata": {"library": {"source_catalog": UPSTREAM_NAME}},
                }
            ],
        },
    }


def empty_lock() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "migration": {"prune_ack_required": False},
        "requested_roots": [],
        "receipts": [],
        "prerequisites": [],
        "installed": [],
    }


def workspace_root_record(
    workspace_id: str,
    *,
    name: str,
    catalog_identity: str,
    catalog_name: str,
    requested_ref: str,
    roots: list[str],
    scope: str = "project",
) -> dict[str, Any]:
    return {
        "id": workspace_id,
        "type": "workspace",
        "name": name,
        "scope": scope,
        "catalog_identity": catalog_identity,
        "catalog_name": catalog_name,
        "requested_ref": requested_ref,
        "resolved_version": "1.0.0",
        "definition_commit": "d" * 40,
        "roots": roots,
    }
