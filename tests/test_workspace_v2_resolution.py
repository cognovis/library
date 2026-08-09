"""Cross-catalog Workspace resolution (CL-dbam AC1, AC3, AC4, AC6, AC7).

ADR-0011 `Cross-Catalog Resolution` adds a trust dimension to a graph whose
shape is unchanged, and restates four ADR-0010 properties as non-replaceable:
complete resolution before any mutation, deterministic pins on every resolved
node, scope isolation, and shared ownership recomputed from a fresh resolution.

The composition rule is the one that looks like a missing feature and is not.
Two catalogs supplying the same projection target **collide**; they do not
layer. An overlay across a trust boundary is a redirection mechanism -- it lets
a second source silently take over a name a reviewer approved for the first --
which is precisely what the pinned `catalogs:` block exists to prevent one layer
up.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.errors import LibraryError  # noqa: E402
from lib.providers.classification import EXECUTABLE_TYPES  # noqa: E402
from lib.providers.executable_admission import (  # noqa: E402
    ExecutableAdmissionLedger,
    ResolutionRefused,
    content_digest,
)
from lib.providers.inventory import (  # noqa: E402
    NormalizedItem,
    ProviderAvailability,
    Rights,
)
from lib.workspace import (  # noqa: E402
    assert_materializable,
    build_workspace_plan,
    gate_workspace_mutation,
    make_workspace_requested_root,
    resolve_workspace,
    resolve_workspace_closure,
    workspace_root_id,
)
from workspace_v2_fixtures import (  # noqa: E402
    CORE_IDENTITY,
    CORE_NAME,
    CORE_PIN,
    THIRD_IDENTITY,
    THIRD_NAME,
    UPSTREAM_IDENTITY,
    UPSTREAM_NAME,
    UPSTREAM_PIN,
    catalog_document,
    empty_lock,
    executable_v2_manifest,
    second_v2_manifest,
    v1_manifest,
    v2_manifest,
    workspace_root_record,
)

NOW = "2026-08-09T09:00:00Z"
GRANTED = Rights(
    fetch_authorization="granted",
    install_rights="granted",
    redistribution_rights="granted",
    derivative_rights="granted",
    evidence_source="upstream LICENSE, read on 2026-08-09",
)
AVAILABLE = ProviderAvailability(state="available", observed_at=NOW)


def _closure(catalog: dict[str, Any], reference: str, scope: str = "project"):
    workspace = resolve_workspace(catalog, reference)
    return resolve_workspace_closure(catalog, workspace, Path.cwd(), scope)


def _item(**overrides: Any) -> NormalizedItem:
    base: dict[str, Any] = dict(
        provider_identity=UPSTREAM_IDENTITY,
        upstream_id="workflows/deploy",
        upstream_name="deploy",
        collection_membership=(),
        upstream_revision=None,
        library_type="workflow",
        library_name="deploy",
        classification={},
        runtime_compatibility=("pi",),
        rights=GRANTED,
        provider_availability=AVAILABLE,
        admission_state="installable",
    )
    base.update(overrides)
    return NormalizedItem(**base)


class _Writer:
    """A mutation that records exactly what the gate handed it."""

    def __init__(self) -> None:
        self.calls: list[Mapping[str, Mapping[str, bytes]]] = []

    def __call__(self, contents: Mapping[str, Mapping[str, bytes]]) -> None:
        self.calls.append(contents)


# -- AC1: two catalogs, one closure, pins on every node ----------------------


def test_two_catalog_closure() -> None:
    closure = _closure(catalog_document(), f"{CORE_NAME}:engineering")

    assert set(closure.artifacts) == {
        ("standard", "common"),
        ("skill", "python-dev"),
        ("skill", "helper"),
    }
    by_member = {(node.primitive, node.name): node for node in closure.nodes}
    assert by_member[("skill", "python-dev")].catalog_identity == CORE_IDENTITY
    assert by_member[("skill", "helper")].catalog_identity == UPSTREAM_IDENTITY
    assert by_member[("standard", "common")].catalog_identity == CORE_IDENTITY

    # Every resolved node carries the pin of the catalog it came from, and the
    # pin is typed: a revisionless source pins its inventory snapshot.
    assert by_member[("skill", "python-dev")].pin.kind == CORE_PIN["kind"]
    assert by_member[("skill", "python-dev")].pin.value == CORE_PIN["value"]
    assert by_member[("skill", "helper")].pin.kind == UPSTREAM_PIN["kind"]
    assert by_member[("skill", "helper")].pin.value == UPSTREAM_PIN["value"]
    assert all(node.pin is not None for node in closure.nodes)

    # Display aliases never leave the manifest.
    assert {node.catalog_identity for node in closure.nodes} == {
        CORE_IDENTITY,
        UPSTREAM_IDENTITY,
    }
    assert "core" not in {node.catalog_identity for node in closure.nodes}


def test_alias_mapping_is_manifest_local() -> None:
    """Two manifests may spell the same alias for different identities."""
    catalog = catalog_document(workspaces=[v2_manifest(), second_v2_manifest()])

    engineering = _closure(catalog, f"{CORE_NAME}:engineering")
    reporting = _closure(catalog, f"{THIRD_NAME}:reporting")

    engineering_nodes = {(node.primitive, node.name): node for node in engineering.nodes}
    reporting_nodes = {(node.primitive, node.name): node for node in reporting.nodes}
    assert engineering_nodes[("skill", "python-dev")].catalog_identity == CORE_IDENTITY
    assert reporting_nodes[("skill", "report")].catalog_identity == THIRD_IDENTITY


def test_resolution_refuses_an_undeclared_catalog() -> None:
    """A dependency may not pull the closure into a source nobody pinned."""
    catalog = catalog_document()
    manifest = catalog["library"]["workspaces"][0]
    manifest["catalogs"] = [entry for entry in manifest["catalogs"] if entry["alias"] == "upstream"]
    manifest["roots"] = [
        {"type": "skill", "name": "helper", "catalog": "upstream"},
        {"type": "skill", "name": "python-dev", "catalog": "upstream"},
    ]

    with pytest.raises(LibraryError) as excinfo:
        _closure(catalog, f"{CORE_NAME}:engineering")

    assert CORE_IDENTITY in str(excinfo.value)


# -- AC3: complete resolution before any mutation ----------------------------


def _full_selection(closure) -> tuple[list[NormalizedItem], dict[str, dict[str, bytes]]]:
    """One normalized item and its content for every artifact the closure selected."""
    items: list[NormalizedItem] = []
    contents: dict[str, dict[str, bytes]] = {}
    for node in closure.nodes:
        if node.role != "artifact":
            continue
        item = _item(
            provider_identity=node.catalog_identity,
            upstream_id=f"{node.primitive}s/{node.name}",
            upstream_name=node.name,
            library_type=node.primitive,
            library_name=node.name,
        )
        items.append(item)
        contents[item.qualified_identity()] = {f"{node.name}.yaml": b"content"}
    return items, contents


def _admit_executables(
    items: Sequence[NormalizedItem], contents: Mapping[str, Mapping[str, bytes]]
) -> ExecutableAdmissionLedger:
    ledger = ExecutableAdmissionLedger()
    for item in items:
        if item.library_type not in EXECUTABLE_TYPES:
            continue
        ledger.admit(
            item.qualified_identity(),
            content_digest(contents[item.qualified_identity()]),
            library_type=item.library_type,
            reviewer="operator",
            permission_surface=(),
            decided_at=NOW,
            evidence="reviewed in test",
        )
    return ledger


def test_fails_before_mutation() -> None:
    catalog = catalog_document(workspaces=[executable_v2_manifest()])
    closure = _closure(catalog, f"{CORE_NAME}:deployment")
    items, contents = _full_selection(closure)
    executable = next(item for item in items if item.library_type == "workflow")
    identity = executable.qualified_identity()

    # 1. An unadmitted executable member fails the whole resolution and writes
    #    nothing. It is never silently skipped.
    writer = _Writer()
    with pytest.raises(ResolutionRefused) as refusal:
        gate_workspace_mutation(
            closure, items, ExecutableAdmissionLedger(), contents, mutate=writer
        )
    assert identity in str(refusal.value)
    assert writer.calls == []

    # 2. Leaving the unadmitted member out of the selection is not a way past
    #    the gate. A mutation covers the whole resolved closure or none of it.
    writer = _Writer()
    with pytest.raises(LibraryError, match="does not cover"):
        gate_workspace_mutation(
            closure,
            [item for item in items if item.library_type != "workflow"],
            ExecutableAdmissionLedger(),
            contents,
            mutate=writer,
        )
    assert writer.calls == []

    writer = _Writer()
    with pytest.raises(LibraryError, match="does not cover"):
        gate_workspace_mutation(
            closure, [], ExecutableAdmissionLedger(), {}, mutate=writer
        )
    assert writer.calls == []

    ledger = _admit_executables(items, contents)

    # 3. An item the resolution never selected cannot ride along with ones it
    #    did. That is the redirection this whole slice exists to refuse.
    smuggled = _item(
        upstream_id="workflows/other", upstream_name="other", library_name="other"
    )
    writer = _Writer()
    with pytest.raises(LibraryError, match="not resolved"):
        gate_workspace_mutation(
            closure,
            [*items, smuggled],
            ledger,
            {**contents, smuggled.qualified_identity(): {"w.yaml": b"steps: [rm]"}},
            mutate=writer,
        )
    assert writer.calls == []

    # 4. An item claiming a resolved member's name from a source the resolution
    #    did not select is refused for the same reason.
    redirected = _item(
        provider_identity=THIRD_IDENTITY,
        upstream_id="workflows/deploy",
        upstream_name="deploy",
        library_type="workflow",
        library_name="deploy",
    )
    writer = _Writer()
    with pytest.raises(LibraryError, match="not resolved"):
        gate_workspace_mutation(
            closure,
            [
                *(item for item in items if item.library_type != "workflow"),
                redirected,
            ],
            ledger,
            {**contents, redirected.qualified_identity(): {"w.yaml": b"steps: []"}},
            mutate=writer,
        )
    assert writer.calls == []

    # 5. A member with no content cannot be digested, so it cannot be admitted.
    writer = _Writer()
    with pytest.raises(LibraryError, match="no content"):
        gate_workspace_mutation(
            closure,
            items,
            ledger,
            {key: value for key, value in contents.items() if key != identity},
            mutate=writer,
        )
    assert writer.calls == []

    # 6. The admitted path writes once, with the exact bytes the gate digested,
    #    for the whole closure.
    writer = _Writer()
    resolved = gate_workspace_mutation(closure, items, ledger, contents, mutate=writer)
    assert {node.qualified_identity() for node in resolved} == set(contents)
    assert len(writer.calls) == 1
    handed = writer.calls[0]
    assert set(handed) == set(contents)
    assert dict(handed[identity]) == contents[identity]
    with pytest.raises(TypeError):
        handed[identity]["deploy.yaml"] = b"tampered"


def test_a_cross_catalog_closure_is_not_installable_yet() -> None:
    """Resolution ships in this slice; materialization waits for the adapters."""
    catalog = catalog_document()
    closure = _closure(catalog, f"{CORE_NAME}:engineering")

    with pytest.raises(LibraryError, match="not yet installable"):
        assert_materializable(closure)

    v1 = catalog_document(workspaces=[v1_manifest()])
    assert_materializable(_closure(v1, f"{CORE_NAME}:python-cli"))


def test_a_changed_catalog_pin_is_drift_not_a_silent_re_pin() -> None:
    catalog = catalog_document()
    workspace = resolve_workspace(catalog, f"{CORE_NAME}:engineering")
    root = make_workspace_requested_root(
        workspace, "project", "d" * 40, f"{CORE_NAME}:engineering"
    )
    assert [entry["identity"] for entry in root["catalogs"]] == sorted(
        [CORE_IDENTITY, UPSTREAM_IDENTITY]
    )

    moved = catalog_document()
    moved["library"]["workspaces"][0]["catalogs"][1]["pin"]["value"] = "e" * 64
    lock = empty_lock()
    lock["requested_roots"] = [{**root, "scope": "project"}]

    plan = build_workspace_plan(moved, lock, Path.cwd(), "project")

    blocker = next(item for item in plan["blockers"] if "pin drift" in item)
    assert UPSTREAM_PIN["value"] in blocker
    assert "e" * 64 in blocker


def test_incomplete_resolution_never_reaches_the_admission_gate() -> None:
    """A resolution failure fails first; there is nothing to gate."""
    catalog = catalog_document(workspaces=[executable_v2_manifest()])
    catalog["library"]["skills"][0]["version"] = "1.0.0"
    manifest = catalog["library"]["workspaces"][0]
    manifest["roots"][0]["constraint"] = ">=2.0.0"

    with pytest.raises(LibraryError) as excinfo:
        _closure(catalog, f"{CORE_NAME}:deployment")

    message = str(excinfo.value)
    assert "skill:python-dev" in message
    assert ">=2.0.0" in message
    assert CORE_IDENTITY in message
    assert CORE_NAME in message


# -- AC4: unordered set union, no overlay ------------------------------------


def test_collision_fails_without_overlay() -> None:
    catalog = catalog_document(collide=True)
    manifest = catalog["library"]["workspaces"][0]
    manifest["roots"] = [
        {"type": "skill", "name": "python-dev", "catalog": "core"},
        {"type": "skill", "name": "python-dev", "catalog": "upstream"},
    ]

    with pytest.raises(LibraryError) as excinfo:
        _closure(catalog, f"{CORE_NAME}:engineering")

    message = str(excinfo.value)
    assert "skill:python-dev" in message
    assert CORE_IDENTITY in message
    assert UPSTREAM_IDENTITY in message
    assert CORE_NAME in message
    assert UPSTREAM_NAME in message


def test_collision_across_two_workspaces_blocks_the_plan() -> None:
    """The collision is a property of the scope, not of one manifest."""
    reporting = second_v2_manifest()
    reporting["roots"] = [
        {"type": "skill", "name": "report", "catalog": "core"},
        {"type": "skill", "name": "python-dev", "catalog": "core"},
    ]
    catalog = catalog_document(workspaces=[v2_manifest(), reporting], collide=True)
    catalog["library"]["skills"].append(
        {
            "name": "python-dev",
            "description": "python-dev skill.",
            "version": "1.0.0",
            "source": "https://example.invalid/third/skills/python-dev/SKILL.md",
            "requires": ["standard:common"],
            "metadata": {"library": {"source_catalog": THIRD_NAME}},
        }
    )
    lock = empty_lock()
    lock["requested_roots"] = [
        workspace_root_record(
            workspace_root_id(CORE_IDENTITY, "engineering"),
            name="engineering",
            catalog_identity=CORE_IDENTITY,
            catalog_name=CORE_NAME,
            requested_ref=f"{CORE_NAME}:engineering",
            roots=["skill:python-dev", "skill:helper"],
        ),
        workspace_root_record(
            workspace_root_id(THIRD_IDENTITY, "reporting"),
            name="reporting",
            catalog_identity=THIRD_IDENTITY,
            catalog_name=THIRD_NAME,
            requested_ref=f"{THIRD_NAME}:reporting",
            roots=["skill:report", "skill:python-dev"],
        ),
    ]

    plan = build_workspace_plan(catalog, lock, Path.cwd(), "project")

    assert any("skill:python-dev" in blocker for blocker in plan["blockers"])
    assert any(THIRD_IDENTITY in blocker for blocker in plan["blockers"])


# -- AC6: scope isolation ----------------------------------------------------


def test_scope_isolation() -> None:
    catalog = catalog_document()

    # A cross-catalog root whose member is global-scoped cannot be pulled into
    # a project reconciliation.
    global_member = deepcopy(catalog)
    global_member["library"]["skills"][2]["default_scope"] = "global"
    with pytest.raises(LibraryError, match="scope project conflicts"):
        _closure(global_member, f"{CORE_NAME}:engineering")

    # An intrinsically global dependency stays a non-owning prerequisite even
    # when it is reached across the catalog boundary.
    with_mcp = deepcopy(catalog)
    with_mcp["library"]["skills"][2]["requires"] = ["standard:common", "mcp:test-service"]
    closure = _closure(with_mcp, f"{CORE_NAME}:engineering")
    assert ("mcp", "test-service") in closure.prerequisites
    assert ("mcp", "test-service") not in closure.artifacts
    prerequisite = next(
        node
        for node in closure.nodes
        if (node.primitive, node.name) == ("mcp", "test-service")
    )
    assert prerequisite.role == "prerequisite"
    assert prerequisite.catalog_identity == CORE_IDENTITY


# -- AC7: shared ownership across catalogs -----------------------------------


def _receipt(receipt_id: str, catalog_identity: str) -> dict[str, Any]:
    primitive, _, name = receipt_id.partition(":")
    return {
        "id": receipt_id,
        "type": primitive,
        "name": name,
        "scope": "project",
        "catalog_identity": catalog_identity,
        "resolved_version": "1.0.0",
        "verified": True,
        "targets": [],
    }


def _shared_ownership_lock() -> tuple[dict[str, Any], dict[str, Any]]:
    catalog = catalog_document(workspaces=[v2_manifest(), second_v2_manifest()])
    lock = empty_lock()
    lock["requested_roots"] = [
        workspace_root_record(
            workspace_root_id(CORE_IDENTITY, "engineering"),
            name="engineering",
            catalog_identity=CORE_IDENTITY,
            catalog_name=CORE_NAME,
            requested_ref=f"{CORE_NAME}:engineering",
            roots=["skill:python-dev", "skill:helper"],
        ),
        workspace_root_record(
            workspace_root_id(THIRD_IDENTITY, "reporting"),
            name="reporting",
            catalog_identity=THIRD_IDENTITY,
            catalog_name=THIRD_NAME,
            requested_ref=f"{THIRD_NAME}:reporting",
            roots=["skill:report", "skill:python-test"],
        ),
    ]
    lock["receipts"] = [
        _receipt("standard:common", CORE_IDENTITY),
        _receipt("skill:python-dev", CORE_IDENTITY),
        _receipt("skill:helper", UPSTREAM_IDENTITY),
        _receipt("skill:report", THIRD_IDENTITY),
        _receipt("skill:python-test", CORE_IDENTITY),
    ]
    return catalog, lock


def test_multi_catalog_shared_ownership() -> None:
    catalog, lock = _shared_ownership_lock()

    plan = build_workspace_plan(catalog, lock, Path.cwd(), "project")
    shared = next(item for item in plan["receipts"] if item["id"] == "standard:common")
    assert shared["shared"] is True
    assert len(shared["owners"]) == 2

    # Remove the Workspace root published by one catalog. The receipt reached
    # from the other survives; only the members that lost every owner become
    # prune candidates.
    lock["requested_roots"] = [
        root
        for root in lock["requested_roots"]
        if root["id"] != workspace_root_id(THIRD_IDENTITY, "reporting")
    ]
    after = build_workspace_plan(catalog, lock, Path.cwd(), "project")

    surviving = next(item for item in after["receipts"] if item["id"] == "standard:common")
    assert surviving["owners"] == [workspace_root_id(CORE_IDENTITY, "engineering")]
    candidate_ids = {item["id"] for item in after["prune_candidates"]}
    assert "standard:common" not in candidate_ids
    assert {"skill:report", "skill:python-test"} <= candidate_ids
