"""Library Workspace resolution and ownership-aware reconciliation.

Workspace manifests are metadata-only requested roots. This module contains the
pure graph and lockfile operations; filesystem materialization remains owned by
the existing primitive installers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalog import get_catalogs, get_entries, normalize_catalog_identity
from .errors import EXIT_AMBIGUOUS, LibraryError
from .lockfile import compute_checksum, root_id
from .resolver import resolve_requires, resolve_requires_bound

WORKSPACE_SCHEMA_VERSION = 1
PROJECT_RECEIPT_LIMIT = 30
GLOBAL_ROOT_LIMIT = 5
GLOBAL_RECEIPT_LIMIT = 15
GLOBAL_STANDING_CONTEXT_LIMIT = 0.01
ARTIFACT_ROOT_TYPES = {
    "skill",
    "agent",
    "prompt",
    "script",
    "standard",
    "guardrail",
    "mcp",
    "model-standard",
    "agent-base",
    "workflow",
    "pi-extension",
    "pi-profile",
    "just-module",
    "runtime-config",
}
INTRINSICALLY_GLOBAL_TYPES = {"mcp"}
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
ROOT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


@dataclass
class ResolvedWorkspace:
    """One Workspace manifest bound to its source catalog identity."""

    entry: dict[str, Any]
    catalog_name: str
    catalog_identity: str

    @property
    def name(self) -> str:
        return str(self.entry["name"])

    @property
    def version(self) -> str:
        return str(self.entry["version"])


@dataclass(frozen=True)
class WorkspaceClosure:
    """Resolved same-scope artifact closure and non-owning prerequisites."""

    artifacts: tuple[tuple[str, str], ...]
    prerequisites: tuple[tuple[str, str], ...]
    artifact_bindings: tuple[tuple[str, str, str], ...] = ()
    prerequisite_bindings: tuple[tuple[str, str, str], ...] = ()


def workspace_policy(catalog: dict[str, Any], scope: str) -> dict[str, float | int]:
    """Return configured Workspace budgets with conservative v1 defaults."""
    configured = catalog.get("workspace_policy")
    policy = configured if isinstance(configured, dict) else {}
    selected = policy.get(scope)
    values = selected if isinstance(selected, dict) else {}
    if scope == "global":
        return {
            "max_roots": min(
                GLOBAL_ROOT_LIMIT, int(values.get("max_roots", GLOBAL_ROOT_LIMIT))
            ),
            "max_receipts": min(
                GLOBAL_RECEIPT_LIMIT,
                int(values.get("max_receipts", GLOBAL_RECEIPT_LIMIT)),
            ),
            "max_standing_context_fraction": min(
                GLOBAL_STANDING_CONTEXT_LIMIT,
                float(
                    values.get(
                        "max_standing_context_fraction",
                        GLOBAL_STANDING_CONTEXT_LIMIT,
                    )
                ),
            ),
        }
    return {
        "max_receipts": min(
            PROJECT_RECEIPT_LIMIT,
            int(values.get("max_receipts", PROJECT_RECEIPT_LIMIT)),
        )
    }


def workspace_root_id(catalog_identity: str, name: str) -> str:
    """Return a globally unambiguous Workspace requested-root identity."""
    return f"workspace:{normalize_catalog_identity(catalog_identity)}#{name}"


def validate_workspace_manifest(manifest: dict[str, Any]) -> None:
    """Validate the constitutive v1 Workspace manifest contract."""
    if not isinstance(manifest, dict):
        raise LibraryError("Workspace manifest must be a mapping")
    allowed = {
        "schema_version",
        "name",
        "version",
        "description",
        "status",
        "standing_context_fraction",
        "roots",
        "source",
        "metadata",
        "tags",
    }
    unexpected = sorted(set(manifest) - allowed)
    if unexpected:
        raise LibraryError(
            f"Workspace manifest contains unsupported fields: {', '.join(unexpected)}"
        )
    if manifest.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
        raise LibraryError(
            f"Unsupported Workspace schema_version {manifest.get('schema_version')!r}; "
            f"expected {WORKSPACE_SCHEMA_VERSION}"
        )
    name = manifest.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise LibraryError("Workspace name must use lowercase kebab-case")
    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER_PATTERN.fullmatch(version):
        raise LibraryError("Workspace version must be semantic version text")
    if (
        not isinstance(manifest.get("description"), str)
        or not str(manifest["description"]).strip()
    ):
        raise LibraryError("Workspace description must be non-empty")
    roots = manifest.get("roots")
    if not isinstance(roots, list) or not 2 <= len(roots) <= 10:
        raise LibraryError("Workspace must declare 2-10 direct roots")
    seen: set[str] = set()
    for item in roots:
        if not isinstance(item, dict):
            raise LibraryError("Every Workspace root must be a mapping")
        unsupported = sorted(set(item) - {"type", "name", "constraint"})
        if unsupported:
            raise LibraryError(
                "Workspace v1 roots reject nested or cross-catalog fields: "
                + ", ".join(unsupported)
            )
        primitive = item.get("type")
        member_name = item.get("name")
        if primitive not in ARTIFACT_ROOT_TYPES:
            raise LibraryError(
                f"Workspace v1 root type {primitive!r} is not an artifact primitive"
            )
        if not isinstance(member_name, str) or not ROOT_NAME_PATTERN.fullmatch(
            member_name
        ):
            raise LibraryError("Workspace root name has invalid characters")
        member_id = root_id(str(primitive), member_name)
        if member_id in seen:
            raise LibraryError(f"Workspace contains duplicate root {member_id}")
        seen.add(member_id)
        constraint = item.get("constraint")
        if constraint is not None:
            clauses = str(constraint).split(",")
            if not clauses or any(
                re.fullmatch(r"(?:<=|>=|==|<|>)\d+\.\d+\.\d+", clause) is None
                for clause in clauses
            ):
                raise LibraryError(
                    f"Unsupported Workspace version constraint {constraint!r}"
                )
    context_fraction = manifest.get("standing_context_fraction")
    if context_fraction is not None and (
        not isinstance(context_fraction, (int, float))
        or isinstance(context_fraction, bool)
        or not 0 <= float(context_fraction) <= 1
    ):
        raise LibraryError("standing_context_fraction must be between 0 and 1")


def _entry_catalog_name(entry: dict[str, Any]) -> str:
    metadata = entry.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    library_metadata = metadata.get("library")
    if not isinstance(library_metadata, dict):
        return ""
    return str(library_metadata.get("source_catalog") or "")


def _catalog_identities(catalog: dict[str, Any]) -> dict[str, str]:
    identities: dict[str, str] = {}
    for entry in get_catalogs(catalog):
        name = str(entry.get("name") or "")
        source = str(entry.get("source") or "")
        if name and source:
            identities[name] = normalize_catalog_identity(source)
    return identities


def resolve_workspace(catalog: dict[str, Any], reference: str) -> ResolvedWorkspace:
    """Resolve a qualified or uniquely unqualified Workspace reference."""
    catalog_name: str | None = None
    workspace_name = reference
    if ":" in reference:
        catalog_name, workspace_name = reference.split(":", 1)
    identities = _catalog_identities(catalog)
    if catalog_name is not None and catalog_name not in identities:
        raise LibraryError(f"Unknown source catalog '{catalog_name}'")

    candidates = [
        entry
        for entry in get_entries(catalog, "workspace")
        if entry.get("name") == workspace_name
        and (catalog_name is None or _entry_catalog_name(entry) == catalog_name)
    ]
    if not candidates:
        raise LibraryError(f"No Workspace named '{reference}' found", exit_code=2)
    if len(candidates) > 1:
        labels = sorted(
            f"{_entry_catalog_name(entry)}:{entry.get('name')}" for entry in candidates
        )
        raise LibraryError(
            f"Ambiguous Workspace '{reference}'; candidates: {', '.join(labels)}",
            exit_code=EXIT_AMBIGUOUS,
        )

    entry = candidates[0]
    validate_workspace_manifest(entry)
    resolved_catalog_name = _entry_catalog_name(entry)
    if not resolved_catalog_name or resolved_catalog_name not in identities:
        raise LibraryError(
            f"Workspace '{workspace_name}' has no registered source catalog"
        )
    return ResolvedWorkspace(
        entry=entry,
        catalog_name=resolved_catalog_name,
        catalog_identity=identities[resolved_catalog_name],
    )


def _assert_same_catalog_member(
    catalog: dict[str, Any], workspace: ResolvedWorkspace, primitive: str, name: str
) -> dict[str, Any]:
    entries = [
        entry for entry in get_entries(catalog, primitive) if entry.get("name") == name
    ]
    if not entries:
        raise LibraryError(f"Workspace root {primitive}:{name} does not exist")
    source_names = {_entry_catalog_name(entry) for entry in entries}
    if workspace.catalog_name not in source_names:
        raise LibraryError(
            f"Workspace root {primitive}:{name} is not published by "
            f"same catalog {workspace.catalog_name}"
        )
    return next(
        entry
        for entry in entries
        if _entry_catalog_name(entry) == workspace.catalog_name
    )


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise LibraryError(f"Artifact version {version!r} is not semantic version text")
    return tuple(int(part) for part in match.groups())


def _constraint_satisfied(version: str, constraint: str) -> bool:
    current = _version_tuple(version)
    for clause in (item.strip() for item in constraint.split(",")):
        if not clause:
            continue
        match = re.fullmatch(r"(<=|>=|==|<|>)(\d+\.\d+\.\d+)", clause)
        if not match:
            raise LibraryError(
                f"Unsupported Workspace version constraint {constraint!r}"
            )
        operator, expected_text = match.groups()
        expected = _version_tuple(expected_text)
        comparisons = {
            "<": current < expected,
            "<=": current <= expected,
            "==": current == expected,
            ">=": current >= expected,
            ">": current > expected,
        }
        if not comparisons[operator]:
            return False
    return True


def resolve_workspace_closure(
    catalog: dict[str, Any],
    workspace: ResolvedWorkspace,
    repo_root: Path,
    scope: str,
) -> WorkspaceClosure:
    """Resolve a Workspace's independent roots and dependency closure."""
    if scope not in {"project", "global"}:
        raise LibraryError("Workspace scope must be project or global")
    validate_workspace_manifest(workspace.entry)
    roots = workspace.entry["roots"]
    policy = workspace_policy(catalog, scope)
    if scope == "global" and len(roots) > int(policy["max_roots"]):
        raise LibraryError(
            f"Global lobby permits at most {policy['max_roots']} direct roots"
        )
    if scope == "global":
        fraction = workspace.entry.get("standing_context_fraction")
        if fraction is None:
            raise LibraryError(
                "Global lobby requires a known standing_context_fraction"
            )
        if float(fraction) > float(policy["max_standing_context_fraction"]):
            raise LibraryError(
                "Global lobby exceeds the configured standing-context budget"
            )

    ordered_artifacts: list[tuple[str, str]] = []
    prerequisites: list[tuple[str, str]] = []
    artifact_bindings: list[tuple[str, str, str]] = []
    prerequisite_bindings: list[tuple[str, str, str]] = []
    seen_artifacts: set[tuple[str, str]] = set()
    seen_prerequisites: set[tuple[str, str]] = set()
    for root in roots:
        primitive = str(root["type"])
        name = str(root["name"])
        member_entry = _assert_same_catalog_member(catalog, workspace, primitive, name)
        root_scope = member_entry.get("default_scope")
        if primitive in INTRINSICALLY_GLOBAL_TYPES and scope == "project":
            raise LibraryError(
                f"Workspace scope project conflicts with intrinsically global root "
                f"{primitive}:{name}"
            )
        if root_scope in {"project", "global"} and root_scope != scope:
            raise LibraryError(
                f"Workspace scope {scope} conflicts with {primitive}:{name} "
                f"default_scope {root_scope}"
            )
        constraint = root.get("constraint")
        if constraint is not None:
            version = member_entry.get("version")
            if not isinstance(version, str) or not _constraint_satisfied(
                version, str(constraint)
            ):
                raise LibraryError(
                    f"Workspace constraint {constraint!r} is unsatisfied for "
                    f"{primitive}:{name} at version {version!r}"
                )
        closure = resolve_requires_bound(
            catalog,
            primitive,
            name,
            source_catalog=workspace.catalog_name,
        )
        for member_primitive, member_name, member_source in closure:
            member = (member_primitive, member_name)
            member_catalog_entry = next(
                entry
                for entry in get_entries(catalog, member_primitive)
                if entry.get("name") == member_name
                and _entry_catalog_name(entry) == member_source
            )
            declared_scope = member_catalog_entry.get("default_scope")
            if scope == "project" and (
                member[0] in INTRINSICALLY_GLOBAL_TYPES or declared_scope == "global"
            ):
                if member not in seen_prerequisites:
                    prerequisites.append(member)
                    prerequisite_bindings.append(
                        (member_primitive, member_name, member_source)
                    )
                    seen_prerequisites.add(member)
                continue
            if declared_scope in {"project", "global"} and declared_scope != scope:
                raise LibraryError(
                    f"Workspace scope {scope} conflicts with {member[0]}:{member[1]} "
                    f"default_scope {declared_scope}"
                )
            if member not in seen_artifacts:
                ordered_artifacts.append(member)
                artifact_bindings.append((member_primitive, member_name, member_source))
                seen_artifacts.add(member)

    limit = int(policy["max_receipts"])
    if len(ordered_artifacts) > limit:
        raise LibraryError(
            f"Workspace closure has {len(ordered_artifacts)} receipts; limit is {limit}"
        )
    return WorkspaceClosure(
        tuple(ordered_artifacts),
        tuple(prerequisites),
        tuple(artifact_bindings),
        tuple(prerequisite_bindings),
    )


def make_workspace_requested_root(
    workspace: ResolvedWorkspace,
    scope: str,
    definition_commit: str,
    requested_ref: str,
) -> dict[str, Any]:
    """Create a v2 requested-root record for a Workspace definition."""
    return {
        "id": workspace_root_id(workspace.catalog_identity, workspace.name),
        "type": "workspace",
        "name": workspace.name,
        "scope": scope,
        "catalog_identity": workspace.catalog_identity,
        "catalog_name": workspace.catalog_name,
        "requested_ref": requested_ref,
        "resolved_version": workspace.version,
        "definition_commit": definition_commit,
        "roots": [
            root_id(str(item["type"]), str(item["name"]))
            for item in workspace.entry["roots"]
        ],
    }


def upsert_workspace_root(lock: dict[str, Any], root: dict[str, Any]) -> None:
    """Register or refresh one Workspace requested root."""
    roots = lock.setdefault("requested_roots", [])
    for index, existing in enumerate(roots):
        if existing.get("id") == root["id"]:
            roots[index] = root
            return
    roots.append(root)


def _resolve_requested_root(
    catalog: dict[str, Any],
    root: dict[str, Any],
    repo_root: Path,
    scope: str,
) -> tuple[
    list[tuple[str, str]],
    list[tuple[str, str]],
    dict[str, dict[str, str]],
]:
    primitive = str(root.get("type") or "")
    name = str(root.get("name") or "")
    if primitive == "workspace":
        catalog_name = str(root.get("catalog_name") or "")
        reference = str(root.get("requested_ref") or f"{catalog_name}:{name}")
        workspace = resolve_workspace(catalog, reference)
        if normalize_catalog_identity(str(root.get("catalog_identity") or "")) != (
            workspace.catalog_identity
        ):
            raise LibraryError(
                f"Workspace {reference} catalog identity changed; explicit re-registration required"
            )
        closure = resolve_workspace_closure(catalog, workspace, repo_root, scope)
        requirements = _prerequisite_requirements(
            catalog, closure.prerequisite_bindings
        )
        return list(closure.artifacts), list(closure.prerequisites), requirements
    if primitive not in ARTIFACT_ROOT_TYPES:
        raise LibraryError(f"Unsupported requested root {primitive}:{name}")
    closure = resolve_requires(catalog, primitive, name, repo_root, scope)
    artifacts: list[tuple[str, str]] = []
    prerequisites: list[tuple[str, str]] = []
    for member in closure:
        if scope == "project" and member[0] in INTRINSICALLY_GLOBAL_TYPES:
            prerequisites.append(member)
        else:
            artifacts.append(member)
    direct_bindings: list[tuple[str, str, str]] = []
    for prerequisite_primitive, prerequisite_name in prerequisites:
        candidate = next(
            (
                entry
                for entry in get_entries(catalog, prerequisite_primitive)
                if entry.get("name") == prerequisite_name
            ),
            None,
        )
        if candidate is not None:
            direct_bindings.append(
                (
                    prerequisite_primitive,
                    prerequisite_name,
                    _entry_catalog_name(candidate),
                )
            )
    return (
        artifacts,
        prerequisites,
        _prerequisite_requirements(catalog, tuple(direct_bindings)),
    )


def _prerequisite_requirements(
    catalog: dict[str, Any],
    bindings: tuple[tuple[str, str, str], ...],
) -> dict[str, dict[str, str]]:
    """Return catalog identity and version requirements for global assertions."""
    identities = _catalog_identities(catalog)
    requirements: dict[str, dict[str, str]] = {}
    for primitive, name, source_catalog in bindings:
        entry = next(
            item
            for item in get_entries(catalog, primitive)
            if item.get("name") == name and _entry_catalog_name(item) == source_catalog
        )
        requirements[root_id(primitive, name)] = {
            "catalog_identity": identities.get(source_catalog, ""),
            "resolved_version": str(entry.get("version") or ""),
        }
    return requirements


def _stable_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_workspace_plan(
    catalog: dict[str, Any],
    lock: dict[str, Any],
    repo_root: Path,
    scope: str,
) -> dict[str, Any]:
    """Recompute reachability and return an ownership-aware selected-scope plan."""
    owners: dict[str, list[str]] = {}
    prerequisite_owners: dict[str, list[str]] = {}
    prerequisite_requirements: dict[str, dict[str, str]] = {}
    blockers: list[str] = []
    for requested_root in lock.get("requested_roots", []):
        if requested_root.get("scope", scope) != scope:
            continue
        owner_id = str(requested_root.get("id") or "")
        try:
            artifacts, prerequisites, root_prerequisite_requirements = (
                _resolve_requested_root(catalog, requested_root, repo_root, scope)
            )
        except LibraryError as exc:
            blockers.append(f"{owner_id}: {exc}")
            continue
        for primitive, name in artifacts:
            owners.setdefault(root_id(primitive, name), []).append(owner_id)
        for primitive, name in prerequisites:
            prerequisite_id = root_id(primitive, name)
            prerequisite_owners.setdefault(prerequisite_id, []).append(owner_id)
            current = prerequisite_requirements.get(prerequisite_id)
            requirement = root_prerequisite_requirements.get(prerequisite_id, {})
            if current and current != requirement:
                blockers.append(
                    f"{prerequisite_id}: requested with conflicting catalog provenance"
                )
            else:
                prerequisite_requirements[prerequisite_id] = requirement

    receipt_by_id = {
        str(
            receipt.get("id")
            or root_id(str(receipt.get("type") or ""), str(receipt.get("name") or ""))
        ): receipt
        for receipt in lock.get("receipts", [])
        if receipt.get("scope", scope) == scope
    }
    desired_ids = set(owners)
    receipt_ids = set(receipt_by_id)
    policy = workspace_policy(catalog, scope)
    scope_receipt_limit = int(policy["max_receipts"])
    if len(desired_ids) > scope_receipt_limit:
        blockers.append(
            f"Selected {scope} closure has {len(desired_ids)} receipts; "
            f"limit is {scope_receipt_limit}"
        )
    if scope == "global":
        selected_roots = [
            root
            for root in lock.get("requested_roots", [])
            if root.get("scope", scope) == scope
        ]
        if len(selected_roots) > int(policy["max_roots"]):
            blockers.append(
                f"Global lobby has {len(selected_roots)} requested roots; "
                f"limit is {policy['max_roots']}"
            )
    additions = sorted(desired_ids - receipt_ids)
    updates: list[str] = []
    for receipt_id in sorted(desired_ids.intersection(receipt_ids)):
        primitive, _, name = receipt_id.partition(":")
        receipt = receipt_by_id[receipt_id]
        candidates = [
            entry
            for entry in get_entries(catalog, primitive)
            if entry.get("name") == name
            and (
                not receipt.get("catalog_identity")
                or _catalog_identities(catalog).get(_entry_catalog_name(entry))
                == normalize_catalog_identity(
                    str(receipt.get("catalog_identity") or "")
                )
            )
        ]
        catalog_version = next(
            (
                str(entry["version"])
                for entry in candidates
                if entry.get("version") is not None
            ),
            None,
        )
        if (
            catalog_version
            and str(receipt.get("resolved_version") or "") != catalog_version
        ):
            updates.append(receipt_id)
    prune_candidates: list[dict[str, Any]] = []
    for receipt_id in sorted(receipt_ids - desired_ids):
        receipt = receipt_by_id[receipt_id]
        prune_candidates.append(
            {
                "id": receipt_id,
                "verified": bool(receipt.get("verified", False)),
                "blocked_reason": receipt.get("prune_blocked_reason"),
                "targets": receipt.get("targets") or [],
                "scope": receipt.get("scope", scope),
                "install_target": receipt.get("install_target"),
            }
        )
    receipts = [
        {
            "id": receipt_id,
            "owners": sorted(set(owners.get(receipt_id, []))),
            "shared": len(set(owners.get(receipt_id, []))) > 1,
            "catalog_identity": receipt.get("catalog_identity"),
            "resolved_version": receipt.get("resolved_version"),
            "scope": receipt.get("scope", scope),
            "verified": bool(receipt.get("verified", False)),
            "prune_blocked_reason": receipt.get("prune_blocked_reason"),
            "protection": (
                receipt.get("prune_blocked_reason")
                or (None if receipt.get("verified", False) else "receipt is unverified")
            ),
        }
        for receipt_id, receipt in sorted(receipt_by_id.items())
    ]
    payload = {
        "scope": scope,
        "additions": additions,
        "updates": updates,
        "prune_candidates": prune_candidates,
        "blockers": blockers,
    }
    return {
        "scope": scope,
        "additions": additions,
        "updates": updates,
        "receipts": receipts,
        "prerequisites": [
            {
                "id": prerequisite_id,
                "requested_by": sorted(set(root_ids)),
                **prerequisite_requirements.get(prerequisite_id, {}),
            }
            for prerequisite_id, root_ids in sorted(prerequisite_owners.items())
        ],
        "prune_candidates": prune_candidates,
        "blockers": blockers,
        "digest": _stable_digest(payload),
    }


def apply_plan_ownership(
    lock: dict[str, Any],
    plan: dict[str, Any],
    *,
    prerequisite_statuses: dict[str, str] | None = None,
) -> None:
    """Refresh explanatory owner caches and prerequisite assertions from a plan."""
    owners_by_id = {
        str(item["id"]): list(item.get("owners") or [])
        for item in plan.get("receipts", [])
    }
    for receipt in lock.get("receipts", []):
        receipt_id = str(receipt.get("id") or "")
        receipt["owners_cache"] = owners_by_id.get(receipt_id, [])
    lock["prerequisites"] = [
        {
            "id": item["id"],
            "kind": "global-root",
            "scope": "global",
            "status": (prerequisite_statuses or {}).get(str(item["id"]), "unknown"),
            "requested_by": list(item.get("requested_by") or []),
        }
        for item in plan.get("prerequisites", [])
    ]


def apply_prune_plan(
    lock: dict[str, Any],
    plan: dict[str, Any],
    repo_root: Path,
    acknowledge_digest: str,
    *,
    lock_path: Path,
    managed_paths: dict[str, str] | None = None,
    allowed_roots: list[Path] | None = None,
) -> list[str]:
    """Commit a journaled prune transaction and resume exact target deletion."""
    from .lockfile import save_lockfile

    prepared = prepare_prune_plan(
        lock,
        plan,
        repo_root,
        acknowledge_digest,
        managed_paths=managed_paths,
        allowed_roots=allowed_roots,
    )
    write_workspace_journal(
        lock_path,
        {
            "operation": "prune",
            "scope": plan.get("scope"),
            "digest": plan.get("digest"),
            **prepared,
        },
    )
    apply_post_prune_lock(lock, set(prepared["candidate_ids"]))
    save_lockfile(lock_path, lock)
    return recover_workspace_journal(lock_path, repo_root)


def select_prune_candidates(
    plan: dict[str, Any], candidate_ids: set[str]
) -> dict[str, Any]:
    """Return a digest-bound plan containing only explicitly selected receipts."""
    selected = [
        candidate
        for candidate in plan.get("prune_candidates") or []
        if str(candidate.get("id") or "") in candidate_ids
    ]
    if {str(item.get("id") or "") for item in selected} != candidate_ids:
        missing = sorted(
            candidate_ids - {str(item.get("id") or "") for item in selected}
        )
        raise LibraryError(f"Selected prune candidates are not ownerless: {missing}")
    payload = {
        "scope": plan.get("scope"),
        "additions": plan.get("additions") or [],
        "updates": plan.get("updates") or [],
        "prune_candidates": selected,
        "blockers": plan.get("blockers") or [],
    }
    return {**plan, "prune_candidates": selected, "digest": _stable_digest(payload)}


def prepare_prune_plan(
    lock: dict[str, Any],
    plan: dict[str, Any],
    repo_root: Path,
    acknowledge_digest: str,
    *,
    managed_paths: dict[str, str] | None = None,
    allowed_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """Verify a prune plan completely without mutating lock or filesystem."""
    if acknowledge_digest != plan.get("digest"):
        raise LibraryError("Prune plan digest is missing or stale")
    if plan.get("blockers"):
        raise LibraryError("Prune is blocked because root resolution is incomplete")
    if lock.get("migration", {}).get("prune_ack_required"):
        raise LibraryError(
            "Prune is blocked until migrated receipts are verified with "
            "library workspace sync --verify-receipts"
        )
    managed_paths = _canonical_managed_inventory(managed_paths or {})
    selected_roots = [
        path.expanduser().absolute().resolve() for path in (allowed_roots or [])
    ]
    if not selected_roots:
        raise LibraryError("Prune blocked: no Library-managed roots are configured")
    candidates = plan.get("prune_candidates") or []
    verified_targets: list[dict[str, str]] = []
    verified_directories: set[str] = set()
    candidate_ids: set[str] = set()
    for candidate in candidates:
        candidate_id = str(candidate.get("id") or "")
        candidate_ids.add(candidate_id)
        if candidate.get("scope", plan.get("scope")) != plan.get("scope"):
            raise LibraryError(
                f"Prune blocked for {candidate_id}: receipt scope mismatch"
            )
        if not candidate.get("verified"):
            raise LibraryError(
                f"Prune blocked for {candidate_id}: receipt is unverified"
            )
        if candidate.get("blocked_reason"):
            raise LibraryError(
                f"Prune blocked for {candidate_id}: {candidate['blocked_reason']}"
            )
        targets = candidate.get("targets") or []
        if not targets:
            raise LibraryError(f"Prune blocked for {candidate_id}: no exact targets")
        resolved_targets: list[tuple[dict[str, Any], Path]] = []
        for target in targets:
            raw_path = Path(str(target.get("path") or "")).expanduser()
            path = raw_path if raw_path.is_absolute() else repo_root / raw_path
            canonical = _canonical_delete_path(path.absolute())
            if not any(canonical.is_relative_to(root) for root in selected_roots):
                raise LibraryError(
                    f"Prune blocked for {candidate_id}: {canonical} is outside "
                    "Library-managed roots"
                )
            resolved_targets.append((target, canonical))

        inventory_paths = {str(path) for _target, path in resolved_targets}
        for target, path in resolved_targets:
            kind = str(target.get("kind") or "")
            if kind not in {"file", "directory", "symlink"}:
                raise LibraryError(
                    f"Prune blocked for {candidate_id}: target inventory is not per-file"
                )
            manager = managed_paths.get(str(path))
            if manager:
                raise LibraryError(
                    f"Prune blocked for {candidate_id}: {path} is managed by {manager}"
                )
            if kind == "directory":
                if not path.is_dir() or path.is_symlink():
                    raise LibraryError(
                        f"Prune blocked for {candidate_id}: directory drift at {path}"
                    )
                for managed_path, managed_by in managed_paths.items():
                    managed_child = Path(managed_path).expanduser().absolute()
                    if _canonical_delete_path(managed_child).is_relative_to(path):
                        raise LibraryError(
                            f"Prune blocked for {candidate_id}: {managed_child} is "
                            f"managed by {managed_by}"
                        )
                actual_nested = {
                    str(_canonical_delete_path(child.absolute()))
                    for child in path.rglob("*")
                }
                recorded_nested = {
                    recorded
                    for recorded in inventory_paths
                    if Path(recorded) != path and Path(recorded).is_relative_to(path)
                }
                if actual_nested != recorded_nested:
                    raise LibraryError(
                        f"Prune blocked for {candidate_id}: unrecorded nested content at {path}"
                    )
                verified_directories.add(str(path))
                continue
            if kind == "symlink":
                if not path.is_symlink():
                    raise LibraryError(
                        f"Prune blocked for {candidate_id}: symlink drift at {path}"
                    )
                if str(path.readlink()) != str(target.get("link_target") or ""):
                    raise LibraryError(
                        f"Prune blocked for {candidate_id}: symlink target drift at {path}"
                    )
            else:
                if not path.is_file() or path.is_symlink():
                    raise LibraryError(
                        f"Prune blocked for {candidate_id}: file missing or changed at {path}"
                    )
                expected = str(target.get("content_sha256") or "")
                if not expected or compute_checksum(path) != expected:
                    raise LibraryError(
                        f"Prune blocked for {candidate_id}: content drift at {path}"
                    )
            prepared_target = {
                "candidate_id": candidate_id,
                "path": str(path),
                "kind": kind,
            }
            if kind == "symlink":
                prepared_target["link_target"] = str(target.get("link_target") or "")
            else:
                prepared_target["content_sha256"] = str(
                    target.get("content_sha256") or ""
                )
            verified_targets.append(prepared_target)

    return {
        "candidate_ids": sorted(candidate_ids),
        "targets": verified_targets,
        "directories": sorted(
            verified_directories,
            key=lambda value: len(Path(value).parts),
            reverse=True,
        ),
        "allowed_roots": [str(path) for path in selected_roots],
    }


def _canonical_delete_path(path: Path) -> Path:
    """Canonicalize a deletion target without following the final symlink."""
    return path.parent.resolve() / path.name


def _canonical_managed_inventory(managed_paths: dict[str, str]) -> dict[str, str]:
    """Normalize external-manager keys to the deletion safety boundary."""
    return {
        str(_canonical_delete_path(Path(raw).expanduser().absolute())): manager
        for raw, manager in managed_paths.items()
    }


def workspace_allowed_roots(
    catalog: dict[str, Any], repo_root: Path, scope: str
) -> list[Path]:
    """Return every configured Library-owned installation root for one scope."""
    from .paths import expand_path

    roots: set[Path] = set()
    if scope == "project":
        roots.update(
            {
                (repo_root / ".agents" / "pi" / "extensions").resolve(),
                (repo_root / ".agents" / "pi" / "profiles").resolve(),
                (repo_root / ".agents" / "just").resolve(),
            }
        )
    for entries in (catalog.get("default_dirs") or {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for key, raw_value in entry.items():
                is_global = str(key).startswith("global")
                if (scope == "global") != is_global or not isinstance(raw_value, str):
                    continue
                path = expand_path(raw_value, Path.home(), repo_root)
                roots.add(path.expanduser().absolute().resolve())
    return sorted(roots)


def verify_receipt_targets(
    receipt: dict[str, Any],
    repo_root: Path,
    *,
    managed_paths: dict[str, str] | None = None,
    allowed_roots: list[Path] | None = None,
) -> list[str]:
    """Verify one receipt's exact targets for adoption without changing them."""
    managed_paths = _canonical_managed_inventory(managed_paths or {})
    targets = receipt.get("targets") or []
    if not targets:
        raise LibraryError(f"Receipt {receipt.get('id')} has no exact targets")
    verified: list[str] = []
    resolved: list[tuple[dict[str, Any], Path]] = []
    selected_roots = [
        path.expanduser().absolute().resolve() for path in (allowed_roots or [])
    ]
    if not selected_roots:
        raise LibraryError("Adoption blocked: no Library-managed roots are configured")
    for target in targets:
        raw_path = Path(str(target.get("path") or "")).expanduser()
        path = raw_path if raw_path.is_absolute() else repo_root / raw_path
        path = _canonical_delete_path(path.absolute())
        if not any(path.is_relative_to(root) for root in selected_roots):
            raise LibraryError(
                f"Receipt target lies outside Library-managed roots: {path}"
            )
        resolved.append((target, path))
    inventory_paths = {str(path) for _target, path in resolved}
    for target, path in resolved:
        kind = str(target.get("kind") or "")
        if kind not in {"file", "directory", "symlink"}:
            raise LibraryError(
                f"Receipt {receipt.get('id')} target inventory is not per-file"
            )
        manager = managed_paths.get(str(path))
        if manager:
            raise LibraryError(f"{path} is managed by {manager}")
        if kind == "directory":
            if not path.is_dir() or path.is_symlink():
                raise LibraryError(f"Receipt target drift at {path}")
            actual_nested = {
                str(_canonical_delete_path(child.absolute()))
                for child in path.rglob("*")
            }
            recorded_nested = {
                recorded
                for recorded in inventory_paths
                if Path(recorded) != path and Path(recorded).is_relative_to(path)
            }
            if actual_nested != recorded_nested:
                raise LibraryError(f"Receipt has unrecorded nested content at {path}")
        elif kind == "symlink":
            if not path.is_symlink() or str(path.readlink()) != str(
                target.get("link_target") or ""
            ):
                raise LibraryError(f"Receipt target drift at {path}")
        else:
            expected = str(target.get("content_sha256") or "")
            if (
                not path.is_file()
                or path.is_symlink()
                or not expected
                or compute_checksum(path) != expected
            ):
                raise LibraryError(f"Receipt target drift at {path}")
        verified.append(str(path))
    return verified


def inspect_workspace_receipts(
    lock: dict[str, Any],
    plan: dict[str, Any],
    repo_root: Path,
    *,
    managed_paths: dict[str, str] | None = None,
    allowed_roots: list[Path] | None = None,
) -> list[str]:
    """Return selected desired-receipt filesystem drift diagnostics."""
    desired = {
        str(item.get("id") or "")
        for item in plan.get("receipts", [])
        if item.get("owners")
    }
    blockers: list[str] = []
    for receipt in lock.get("receipts", []):
        receipt_id = str(receipt.get("id") or "")
        if receipt_id not in desired or not receipt.get("targets"):
            continue
        try:
            verify_receipt_targets(
                receipt,
                repo_root,
                managed_paths=managed_paths,
                allowed_roots=allowed_roots,
            )
        except LibraryError as exc:
            blockers.append(f"{receipt_id}: {exc}")
    return blockers


def apply_post_prune_lock(lock: dict[str, Any], candidate_ids: set[str]) -> None:
    """Remove pruned receipts from an in-memory lock after full preflight."""
    lock["receipts"] = [
        receipt
        for receipt in lock.get("receipts", [])
        if str(receipt.get("id") or "") not in candidate_ids
    ]
    lock["installed"] = [
        entry
        for entry in lock.get("installed", [])
        if root_id(str(entry.get("type") or ""), str(entry.get("name") or ""))
        not in candidate_ids
    ]


def workspace_journal_path(lock_path: Path) -> Path:
    """Return the durable journal adjacent to one scope lockfile."""
    return lock_path.with_name(f"{lock_path.name}.workspace-journal.json")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    temporary.replace(path)


def write_workspace_journal(lock_path: Path, payload: dict[str, Any]) -> Path:
    """Persist a transaction journal before the corresponding mutation."""
    path = workspace_journal_path(lock_path)
    _write_json_atomic(path, payload)
    return path


def clear_workspace_journal(lock_path: Path) -> None:
    """Remove a completed transaction journal."""
    workspace_journal_path(lock_path).unlink(missing_ok=True)


def workspace_journal_digest(lock_path: Path) -> str | None:
    """Return a byte-exact digest, including for an unparseable journal."""
    path = workspace_journal_path(lock_path)
    if not path.exists():
        return None
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise LibraryError(f"Workspace journal is unreadable: {path}") from exc
    return hashlib.sha256(payload).hexdigest()


def discard_workspace_journal(lock_path: Path, acknowledge_digest: str) -> str:
    """Discard one journal only after an exact digest acknowledgement."""
    digest = workspace_journal_digest(lock_path)
    if digest is None:
        raise LibraryError("No Workspace journal exists in the selected scope")
    if acknowledge_digest != digest:
        raise LibraryError("Workspace journal digest is missing or stale")
    clear_workspace_journal(lock_path)
    return digest


def recover_workspace_journal(lock_path: Path, repo_root: Path) -> list[str]:
    """Resume a committed prune or discard a journal whose lock never committed."""
    path = workspace_journal_path(lock_path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise LibraryError(f"Workspace journal is unreadable: {path}") from exc
    if payload.get("operation") != "prune":
        if payload.get("operation") in {"use", "adopt", "remove"}:
            clear_workspace_journal(lock_path)
            return []
        raise LibraryError(f"Unsupported Workspace journal operation at {path}")
    from .lockfile import load_lockfile

    current_lock = load_lockfile(lock_path)
    candidate_ids = set(payload.get("candidate_ids") or [])
    remaining_receipts = {
        str(receipt.get("id") or "") for receipt in current_lock.get("receipts", [])
    }
    if candidate_ids.intersection(remaining_receipts):
        clear_workspace_journal(lock_path)
        return []

    deleted: list[str] = []
    allowed_roots = [Path(value) for value in payload.get("allowed_roots") or []]
    for item in payload.get("targets") or []:
        target = Path(str(item.get("path") or ""))
        if not target.is_absolute():
            target = (repo_root / target).absolute()
        target = _canonical_delete_path(target)
        if not allowed_roots or not any(
            target.is_relative_to(root) for root in allowed_roots
        ):
            raise LibraryError(
                f"Workspace recovery blocked: {target} is outside Library-managed roots"
            )
        if not (target.exists() or target.is_symlink()):
            continue
        if item.get("kind") == "symlink":
            if not target.is_symlink() or str(target.readlink()) != str(
                item.get("link_target") or ""
            ):
                raise LibraryError(
                    f"Workspace recovery blocked by symlink drift at {target}; "
                    "run library workspace recover with the exact journal digest"
                )
        else:
            expected = str(item.get("content_sha256") or "")
            if (
                not target.is_file()
                or not expected
                or compute_checksum(target) != expected
            ):
                raise LibraryError(
                    f"Workspace recovery blocked by content drift at {target}; "
                    "run library workspace recover with the exact journal digest"
                )
        target.unlink()
        deleted.append(str(target))
    for raw_directory in payload.get("directories") or []:
        directory = _canonical_delete_path(Path(str(raw_directory)).absolute())
        if not allowed_roots or not any(
            directory.is_relative_to(root) for root in allowed_roots
        ):
            raise LibraryError(
                f"Workspace recovery blocked: {directory} is outside Library-managed roots"
            )
        if directory.exists():
            try:
                directory.rmdir()
            except OSError as exc:
                raise LibraryError(
                    f"Workspace recovery blocked by directory drift at {directory}; "
                    "run library workspace recover with the exact journal digest"
                ) from exc
    clear_workspace_journal(lock_path)
    return deleted


@contextmanager
def workspace_write_lock(lock_path: Path):
    """Serialize one scope's Workspace mutations with a non-blocking file lock."""
    import fcntl

    guard_path = lock_path.with_name(f"{lock_path.name}.workspace-lock")
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    with guard_path.open("a+") as guard:
        try:
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LibraryError(
                f"Another Workspace mutation holds the selected-scope lock: {guard_path}"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(guard.fileno(), fcntl.LOCK_UN)


def build_direct_root_demotion_plan(
    catalog: dict[str, Any],
    lock: dict[str, Any],
    repo_root: Path,
    scope: str,
    workspace_reference: str,
    *,
    member: str | None = None,
    all_reachable: bool = False,
) -> dict[str, Any]:
    """Plan a lock-only transfer from direct roots to one Workspace root."""
    workspace = resolve_workspace(catalog, workspace_reference)
    owner_id = workspace_root_id(workspace.catalog_identity, workspace.name)
    if not any(root.get("id") == owner_id for root in lock.get("requested_roots", [])):
        raise LibraryError(f"Workspace {workspace_reference} is not registered")
    closure = resolve_workspace_closure(catalog, workspace, repo_root, scope)
    reachable = {root_id(primitive, name) for primitive, name in closure.artifacts}
    direct_ids = {
        str(root.get("id"))
        for root in lock.get("requested_roots", [])
        if root.get("type") != "workspace" and root.get("scope", scope) == scope
    }
    if all_reachable:
        demote = sorted(reachable.intersection(direct_ids))
    elif member:
        if member not in reachable:
            raise LibraryError(f"Direct root {member} is not reachable from Workspace")
        if member not in direct_ids:
            raise LibraryError(f"Direct root {member} is not registered")
        demote = [member]
    else:
        raise LibraryError("Choose one direct root or --all-reachable")
    payload = {"scope": scope, "workspace": owner_id, "demote": demote}
    return {**payload, "digest": _stable_digest(payload)}


def apply_direct_root_demotion(
    lock: dict[str, Any], plan: dict[str, Any], acknowledge_digest: str
) -> None:
    """Apply a digest-bound, lock-only direct-root demotion plan."""
    if acknowledge_digest != plan.get("digest"):
        raise LibraryError("Direct-root demotion digest is missing or stale")
    demote = set(plan.get("demote") or [])
    lock["requested_roots"] = [
        root
        for root in lock.get("requested_roots", [])
        if str(root.get("id")) not in demote
    ]


def remove_workspace_root(
    lock: dict[str, Any], catalog_identity: str, name: str
) -> bool:
    """Unregister one Workspace root without deleting receipts."""
    target_id = workspace_root_id(catalog_identity, name)
    roots = lock.get("requested_roots", [])
    lock["requested_roots"] = [root for root in roots if root.get("id") != target_id]
    return len(lock["requested_roots"]) != len(roots)
