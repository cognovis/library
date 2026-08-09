"""Disposition of already-materialized third-party projections (CL-m6cc, AC5-AC8).

ADR-0011 `Legacy Projection Disposition` inventoried 23 skill directories and 4
workflow specs that are materialized on the operator's machine with **no
lockfile receipt at all**. With zero receipts there is no recorded provenance,
so the survey could only match names -- and a Library-shaped bridge without a
Library receipt is not Library-owned. This slice therefore re-derives provenance
by **content digest**, and treats a name as decoration.

Three rules follow, and this file is where they become executable:

1. A projection resolving to `unknown` or `denied` redistribution is
   **non-compliant** and cannot be re-materialized by any later sync or repair.
   Unattributed provenance resolves to `unknown`, so an unattributed projection
   is non-compliant until its digest resolves. That is the correction routed
   from the `CL-2p73` review: the ADR concluded "nothing is currently
   non-compliant" one paragraph after establishing that name matching cannot
   establish provenance.
2. Every non-compliant projection has an explicit remediation path, and neither
   path executes on its own.
3. The unreceipted first-party workflow projections are re-materialized so a
   receipt exists, without changing ADR-0006 executor authority.

Covers AC5, AC6, AC7, and AC8.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.cache_transaction import (  # noqa: E402
    CompletenessEvidence,
    install_foreign_item,
    reinstall_from_cache,
)
from lib.providers.contract import FetchedFile, FetchedItem  # noqa: E402
from lib.providers.foreign_cache import (  # noqa: E402
    ObjectStore,
    TofuPinStore,
    normalized_content_digest,
)
from lib.providers.inventory import (  # noqa: E402
    NormalizedItem,
    ProviderAvailability,
    Rights,
)
from lib.providers.legacy_projections import (  # noqa: E402
    PENDING_DIGEST_ATTRIBUTION,
    REMEDIATION_PATHS,
    DeclaredProvenance,
    LegacyProjection,
    NonComplianceRegister,
    ProjectionClassification,
    ProvenanceAttribution,
    ReceiptBackfillRequest,
    RematerializationBlocked,
    RemediationRefused,
    apply_receipt_backfill,
    apply_remediation,
    attribute_by_digest,
    classify_inventory,
    classify_projection,
    guard_rematerialization,
    inventory_document,
    plan_receipt_backfill,
    plan_remediation,
    receipt_index_for,
    scan_projections,
)
from lib.providers.receipts import ReceiptStore  # noqa: E402
from lib.providers.wiring import (  # noqa: E402
    ForeignState,
    filesystem_activation,
    install_marketplace_item,
    repair_projection,
)

NOW = "2026-08-09T15:00:00Z"
PROVIDER = "provider-under-test"
MIT = "upstream LICENSE (MIT) fetched from the provider on 2026-08-09"
SUBSCRIBER = "subscriber-token-scoped endpoint; no redistribution grant located"

GRANTED = Rights(
    fetch_authorization="granted",
    install_rights="granted",
    redistribution_rights="granted",
    derivative_rights="granted",
    evidence_source=MIT,
)
UNRESOLVED = Rights(
    fetch_authorization="granted",
    install_rights="unknown",
    redistribution_rights="unknown",
    derivative_rights="unknown",
    evidence_source=SUBSCRIBER,
)
AVAILABLE = ProviderAvailability(state="available", observed_at=NOW)


def _projection(root: Path, name: str, body: bytes) -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_bytes(body)
    return path


def _item(**overrides: object) -> NormalizedItem:
    base = dict(
        provider_identity=PROVIDER,
        upstream_id="skills/anchor",
        upstream_name="anchor",
        collection_membership=("skills",),
        upstream_revision=None,
        library_type="skill",
        library_name="anchor",
        classification={"skill_class": "procedure"},
        runtime_compatibility=("claude-code",),
        rights=GRANTED,
        provider_availability=AVAILABLE,
        admission_state="installable",
        trust_state="reviewed",
        projection_eligibility={"project_committed": "allowed", "machine_local": "allowed"},
    )
    base.update(overrides)
    return NormalizedItem(**base)


class _Provider:
    """Just enough source to drive one install."""

    def __init__(self, files: Mapping[str, bytes]) -> None:
        self.files = dict(files)

    def identity(self) -> str:
        return PROVIDER

    def fetch(self, upstream_id: str, revision: str | None) -> FetchedItem:
        return FetchedItem(
            upstream_id=upstream_id,
            revision=revision,
            files=tuple(
                FetchedFile(path=path, content=content)
                for path, content in sorted(self.files.items())
            ),
            primary_path=sorted(self.files)[0],
        )

    def capabilities(self) -> frozenset[str]:
        return frozenset()


def _state(tmp_path: Path) -> ForeignState:
    return ForeignState.for_locks(
        cache_root=tmp_path / "cache",
        project_lock=tmp_path / "project" / ".library.lock",
        global_lock=tmp_path / "global" / "global.lock",
    )


# -- AC5: inventory with rights and receipt status -----------------------------


def test_projections_are_inventoried_with_rights_and_receipt_status(
    tmp_path: Path,
) -> None:
    """AC5. Every projection carries its digest, its rights, and its receipt state.

    The inventory is derived, never asserted: `scan_projections` reads bytes and
    computes digests, and the classification is a function of that digest plus a
    provider's recorded rights. Nothing in this path takes a name as input.
    """
    root = tmp_path / "skills"
    known = _projection(root, "anchor", b"# anchor\n")
    unknown_origin = _projection(root, "ask-matt", b"# hand copied\n")

    projections = scan_projections([root])
    assert [item.name for item in projections] == ["anchor", "ask-matt"]
    for item in projections:
        assert isinstance(item, LegacyProjection)
        assert item.content_digest.startswith("sha256:")

    known_digest = normalized_content_digest({"SKILL.md": b"# anchor\n"})
    digest_index = {known_digest: (PROVIDER, "skills/anchor")}
    classifications = classify_inventory(
        projections,
        digest_index=digest_index,
        rights_for={PROVIDER: GRANTED}.get,
        receipt_index={},
    )
    by_name = {item.projection.name: item for item in classifications}

    attributed = by_name["anchor"]
    assert isinstance(attributed, ProjectionClassification)
    assert attributed.attribution.state == "attributed"
    assert attributed.attribution.provider_identity == PROVIDER
    assert attributed.redistribution_state == "granted"
    assert attributed.redistribution_evidence == MIT
    assert attributed.receipt_status == "unreceipted"
    assert attributed.compliance == "compliant"
    assert attributed.remediation == ()

    unattributed = by_name["ask-matt"]
    assert unattributed.attribution.state == "unattributed"
    assert unattributed.attribution.provider_identity is None
    assert unattributed.redistribution_state == "unknown"
    assert unattributed.pending_reason == PENDING_DIGEST_ATTRIBUTION
    assert unattributed.compliance == "non-compliant"
    assert unattributed.remediation == REMEDIATION_PATHS


def test_a_name_never_attributes_a_projection(tmp_path: Path) -> None:
    """The routed correction, as a test.

    `ask-matt` is one of the 23 names the ADR survey matched against upstream.
    Sharing that name with an upstream item attributes nothing; only a digest
    does. The classification is therefore identical for a name-matching
    projection whose bytes are unknown and for one with no upstream name at all.
    """
    root = tmp_path / "skills"
    _projection(root, "ask-matt", b"# not the upstream bytes\n")
    _projection(root, "entirely-local-name", b"# not the upstream bytes\n")

    upstream_digest = normalized_content_digest({"SKILL.md": b"# the real upstream\n"})
    classifications = classify_inventory(
        scan_projections([root]),
        digest_index={upstream_digest: (PROVIDER, "skills/ask-matt")},
        rights_for={PROVIDER: GRANTED}.get,
        receipt_index={},
    )
    states = {item.projection.name: item.attribution.state for item in classifications}
    assert states == {"ask-matt": "unattributed", "entirely-local-name": "unattributed"}

    # And attribution takes no name argument at all, so there is no parameter a
    # future caller could pass a name through.
    attribution = attribute_by_digest(
        scan_projections([root])[0], digest_index={upstream_digest: (PROVIDER, "x")}
    )
    assert isinstance(attribution, ProvenanceAttribution)
    assert attribution.state == "unattributed"
    assert attribution.evidence_source


def test_receipt_status_is_read_from_the_receipt_store(tmp_path: Path) -> None:
    """A receipt is proof; a Library-shaped directory is not.

    `receipt_index_for` builds the path index from real receipt targets, so a
    projection is `receipted` only when a receipt claims its exact path.
    """
    root = tmp_path / "skills"
    projected = _projection(root, "anchor", b"# anchor\n")

    state = _state(tmp_path)
    provider = _Provider({"SKILL.md": b"# anchor\n"})
    install_foreign_item(
        _item(),
        retrieve=lambda: provider.fetch("skills/anchor", None),
        object_store=state.object_store(),
        pin_store=state.pin_store(),
        receipt_store=state.receipt_store("global"),
        target="machine_local",
        activate=filesystem_activation(root / "anchor"),
        observed_at=NOW,
        completeness=CompletenessEvidence.from_manifest(["SKILL.md"]),
    )

    index = receipt_index_for([state.receipt_store("global")])
    classifications = classify_inventory(
        scan_projections([root]),
        digest_index={},
        rights_for={}.get,
        receipt_index=index,
    )
    anchor = next(item for item in classifications if item.projection.name == "anchor")
    assert anchor.receipt_status == "receipted"
    assert str(projected / "SKILL.md") in index


def test_denied_redistribution_is_non_compliant_with_its_own_reason(
    tmp_path: Path,
) -> None:
    """Attributed but denied is non-compliant, and not for a pending-digest reason.

    Conflating "we have not looked" with "someone said no" would make the
    remediation conversation dishonest in both directions.
    """
    root = tmp_path / "skills"
    _projection(root, "restricted", b"# restricted\n")
    digest = normalized_content_digest({"SKILL.md": b"# restricted\n"})
    denied = Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="denied",
        derivative_rights="denied",
        evidence_source="upstream LICENSE forbids redistribution, read 2026-08-09",
    )
    classification = classify_projection(
        scan_projections([root])[0],
        attribution=attribute_by_digest(
            scan_projections([root])[0], digest_index={digest: (PROVIDER, "x/restricted")}
        ),
        rights_for={PROVIDER: denied}.get,
        receipt_status="unreceipted",
    )
    assert classification.redistribution_state == "denied"
    assert classification.compliance == "non-compliant"
    assert classification.pending_reason is None
    assert classification.remediation == REMEDIATION_PATHS


def test_the_committed_inventory_report_is_derived_from_this_module(
    tmp_path: Path,
) -> None:
    """AC5's evidence document is generated, not hand-written.

    A hand-maintained inventory drifts from the machine it describes, and the
    ADR's own survey is the worked example of what that costs.
    """
    root = tmp_path / "skills"
    _projection(root, "anchor", b"# anchor\n")
    document = inventory_document(
        classify_inventory(
            scan_projections([root]),
            digest_index={},
            rights_for={}.get,
            receipt_index={},
        ),
        observed_at=NOW,
    )
    assert document["schema"] == "cognovis.legacy-projection-inventory.v1"
    assert document["observed_at"] == NOW
    assert document["counts"]["non_compliant"] == 1
    entry = document["entries"][0]
    assert entry["name"] == "anchor"
    assert entry["redistribution_state"] == "unknown"
    assert entry["pending_reason"] == PENDING_DIGEST_ATTRIBUTION
    assert entry["receipt_status"] == "unreceipted"
    assert sorted(entry["remediation"]) == sorted(REMEDIATION_PATHS)


# -- AC6: non-compliant projections cannot be re-materialized -------------------


def test_non_compliant_blocks_rematerialization(tmp_path: Path) -> None:
    """AC6. Neither sync nor repair may re-materialize a non-compliant projection.

    Both production paths are exercised, because they are different call sites
    with different arguments and only one of them is the obvious one. The block
    is enforced at the projection *plan* phase, so a refusal happens before any
    byte is written -- and the test proves that by asserting the target file
    never appears.
    """
    root = tmp_path / "skills"
    _projection(root, "anchor", b"# already here, provenance unknown\n")

    register = NonComplianceRegister(tmp_path / "non-compliant.json")
    classification = classify_projection(
        scan_projections([root])[0],
        attribution=attribute_by_digest(scan_projections([root])[0], digest_index={}),
        rights_for={}.get,
        receipt_status="unreceipted",
    )
    assert classification.compliance == "non-compliant"
    assert classification.blocks_rematerialization() is True
    register.record(classification, recorded_at=NOW)

    assert register.is_blocked(path=str(root / "anchor" / "SKILL.md")) is True
    assert register.is_blocked(digest=classification.projection.content_digest) is True

    state = _state(tmp_path)
    provider = _Provider({"SKILL.md": b"# replacement bytes\n"})

    # Path 1: a later `library marketplace install` / sync.
    with pytest.raises(RematerializationBlocked) as sync_refusal:
        install_marketplace_item(
            _item(),
            provider=provider,
            state=state,
            scope="global",
            target="machine_local",
            target_root=root / "anchor",
            non_compliance=register,
            observed_at=NOW,
        )
    assert "non-compliant" in str(sync_refusal.value)
    # Untouched: the refusal happened before the plan produced a write.
    assert (root / "anchor" / "SKILL.md").read_bytes() == (
        b"# already here, provenance unknown\n"
    )

    # Path 2: repair from the verified cache. Install one compliant item first so
    # a receipt and cache object exist to repair from, then register its target
    # as non-compliant and try again.
    other_root = tmp_path / "other"
    outcome = install_foreign_item(
        _item(upstream_id="skills/beacon", library_name="beacon"),
        retrieve=lambda: provider.fetch("skills/beacon", None),
        object_store=state.object_store(),
        pin_store=state.pin_store(),
        receipt_store=state.receipt_store("global"),
        target="machine_local",
        activate=filesystem_activation(other_root),
        observed_at=NOW,
        completeness=CompletenessEvidence.from_manifest(["SKILL.md"]),
    )
    repaired = other_root / "SKILL.md"
    assert repaired.is_file()
    repaired.unlink()

    blocked_repair = NonComplianceRegister(tmp_path / "repair-block.json")
    blocked_repair.record(
        classification.replace_projection(
            LegacyProjection(
                path=str(repaired),
                name="beacon",
                kind="file",
                content_digest=outcome.receipt.projected_content_digest,
                member_count=1,
            )
        ),
        recorded_at=NOW,
    )
    with pytest.raises(RematerializationBlocked):
        repair_projection(
            receipt=outcome.receipt,
            state=state,
            scope="global",
            target_root=other_root,
            availability=AVAILABLE,
            non_compliance=blocked_repair,
            observed_at=NOW,
        )
    assert not repaired.exists()


def test_a_compliant_projection_is_not_blocked(tmp_path: Path) -> None:
    """The block must discriminate, or it is an outage rather than a control."""
    root = tmp_path / "skills"
    register = NonComplianceRegister(tmp_path / "non-compliant.json")
    guard_rematerialization(register, paths=[str(root / "anything")], digest="0" * 64)

    state = _state(tmp_path)
    provider = _Provider({"SKILL.md": b"# fine\n"})
    outcome = install_marketplace_item(
        _item(),
        provider=provider,
        state=state,
        scope="global",
        target="machine_local",
        target_root=root / "anchor",
        non_compliance=register,
        observed_at=NOW,
    )
    assert (root / "anchor" / "SKILL.md").read_bytes() == b"# fine\n"
    assert outcome.receipt.verified is True


def test_the_register_refuses_a_malformed_store(tmp_path: Path) -> None:
    """A damaged register is never read as "nothing is blocked".

    That default would silently restore re-materialization for every
    non-compliant projection, which is the one failure this register exists to
    prevent.
    """
    path = tmp_path / "non-compliant.json"
    path.write_text(
        json.dumps(
            {"schema": "cognovis.legacy-projection-non-compliance.v1", "entries": None}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        NonComplianceRegister(path).blocked()


def test_the_register_refuses_a_compliant_classification(tmp_path: Path) -> None:
    """Recording a compliant projection would make the register meaningless."""
    root = tmp_path / "skills"
    _projection(root, "anchor", b"# anchor\n")
    digest = normalized_content_digest({"SKILL.md": b"# anchor\n"})
    classification = classify_projection(
        scan_projections([root])[0],
        attribution=attribute_by_digest(
            scan_projections([root])[0], digest_index={digest: (PROVIDER, "x/anchor")}
        ),
        rights_for={PROVIDER: GRANTED}.get,
        receipt_status="unreceipted",
    )
    assert classification.compliance == "compliant"
    with pytest.raises(ValueError):
        NonComplianceRegister(tmp_path / "r.json").record(classification, recorded_at=NOW)


# -- AC7: remediation is explicit, never automatic ------------------------------


def test_remediation_requires_operator(tmp_path: Path) -> None:
    """AC7. Neither remediation path runs without an operator confirmation.

    The confirmation cannot be fabricated: it is issued only from a presentation
    this module renders, so a confirmation's existence proves the statement was
    shown. That is the same shape `CL-n7ex` arrived at after review broke a
    boolean flag and then broke a digest-only token.
    """
    root = tmp_path / "skills"
    projected = _projection(root, "ask-matt", b"# hand copied\n")
    classification = classify_projection(
        scan_projections([root])[0],
        attribution=attribute_by_digest(scan_projections([root])[0], digest_index={}),
        rights_for={}.get,
        receipt_status="unreceipted",
    )
    plan = plan_remediation(classification)
    assert tuple(option.path_id for option in plan.options) == REMEDIATION_PATHS
    assert plan.subject == str(projected)
    # The statement names the subject and the rights state, so one confirmation
    # cannot silently cover a different projection.
    assert str(projected) in plan.statement
    assert "unknown" in plan.statement

    # No presenter: refused, and nothing moved.
    with pytest.raises(RemediationRefused):
        apply_remediation(plan, choice="operator-confirmed-removal", confirm=None)
    assert (projected / "SKILL.md").read_bytes() == b"# hand copied\n"

    # A hand-built confirmation carrying an invented token: refused.
    class _Forged:
        token = "0" * 32
        statement_digest = "0" * 64
        subject = str(projected)
        choice = "operator-confirmed-removal"
        operator = "someone"
        confirmed_at = NOW

    with pytest.raises(RemediationRefused):
        apply_remediation(
            plan, choice="operator-confirmed-removal", confirm=lambda _p: _Forged()
        )
    assert (projected / "SKILL.md").read_bytes() == b"# hand copied\n"

    # A confirmation for the other choice does not authorize this one.
    with pytest.raises(RemediationRefused):
        apply_remediation(
            plan,
            choice="operator-confirmed-removal",
            confirm=lambda presentation: presentation.confirm(
                operator="malte",
                choice="relocate-machine-local",
                confirmed_at=NOW,
            ),
        )
    assert (projected / "SKILL.md").read_bytes() == b"# hand copied\n"

    # The relocation path, correctly confirmed, moves rather than destroys.
    machine_local = tmp_path / "machine-local"
    shown: list[str] = []

    def confirm(presentation):
        shown.append(presentation.statement)
        return presentation.confirm(
            operator="malte", choice="relocate-machine-local", confirmed_at=NOW
        )

    result = apply_remediation(
        plan,
        choice="relocate-machine-local",
        confirm=confirm,
        relocate_root=machine_local,
    )
    assert shown and str(projected) in shown[0]
    assert result.choice == "relocate-machine-local"
    assert not projected.exists()
    relocated = machine_local / "ask-matt"
    assert (relocated / "SKILL.md").read_bytes() == b"# hand copied\n"
    assert result.destination == str(relocated)


def test_a_confirmation_is_good_exactly_once(tmp_path: Path) -> None:
    """Replaying one confirmation must not authorize a second remediation."""
    root = tmp_path / "skills"
    _projection(root, "ask-matt", b"# hand copied\n")
    classification = classify_projection(
        scan_projections([root])[0],
        attribution=attribute_by_digest(scan_projections([root])[0], digest_index={}),
        rights_for={}.get,
        receipt_status="unreceipted",
    )
    plan = plan_remediation(classification)
    captured: list[object] = []

    def confirm(presentation):
        confirmation = presentation.confirm(
            operator="malte", choice="relocate-machine-local", confirmed_at=NOW
        )
        captured.append(confirmation)
        return confirmation

    apply_remediation(
        plan,
        choice="relocate-machine-local",
        confirm=confirm,
        relocate_root=tmp_path / "first",
    )
    with pytest.raises(RemediationRefused):
        apply_remediation(
            plan,
            choice="relocate-machine-local",
            confirm=lambda _p: captured[0],
            relocate_root=tmp_path / "second",
        )
    assert not (tmp_path / "second").exists()


def test_removal_is_confirmed_per_projection_and_deletes_only_it(
    tmp_path: Path,
) -> None:
    """The destructive path exists, is reachable, and is exactly scoped.

    ADR-0011 permits operator-confirmed removal of non-compliant content. The
    invariant it must not break is the neighbouring one: a confirmation for one
    projection removes that projection and nothing beside it.
    """
    root = tmp_path / "skills"
    doomed = _projection(root, "ask-matt", b"# hand copied\n")
    neighbour = _projection(root, "keep-me", b"# unrelated\n")
    classification = classify_projection(
        scan_projections([root])[0],
        attribution=attribute_by_digest(scan_projections([root])[0], digest_index={}),
        rights_for={}.get,
        receipt_status="unreceipted",
    )
    plan = plan_remediation(classification)
    result = apply_remediation(
        plan,
        choice="operator-confirmed-removal",
        confirm=lambda presentation: presentation.confirm(
            operator="malte", choice="operator-confirmed-removal", confirmed_at=NOW
        ),
    )
    assert result.removed == (str(doomed),)
    assert not doomed.exists()
    assert (neighbour / "SKILL.md").read_bytes() == b"# unrelated\n"


def test_remediation_is_not_reachable_from_migration() -> None:
    """Migration must not be able to reach a remediation, even indirectly.

    AC7 says remediation is never automatic. The strongest form of that is a
    module boundary: the migration module does not import the module that can
    remove or relocate bytes.
    """
    source = (REPO_ROOT / "scripts" / "lib" / "providers" / "migration.py").read_text(
        encoding="utf-8"
    )
    assert "legacy_projections" not in source


# -- AC8: the unreceipted workflow projections gain receipts --------------------


def test_workflow_projections_receipted(tmp_path: Path) -> None:
    """AC8. The four workflow specs are re-materialized so a receipt exists.

    Re-materialization, not adoption: an adopted receipt would record whatever
    is on disk as authoritative, and the whole reason these four are a defect is
    that nobody can say what produced the bytes on disk. The catalog is the
    authority, and the receipt records the bytes the catalog served.
    """
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    names = ("bead-context-pack.js", "bead-review.js", "quick-fix.js", "stream-review.js")
    for name in names:
        (workflows / name).write_bytes(f"// stale {name}\n".encode())

    catalog = {
        name: {name: f"// catalog {name}\n".encode()} for name in names
    }

    requests = plan_receipt_backfill(
        scan_projections([workflows]),
        catalog_lookup=lambda projection: catalog.get(projection.name),
        provider_identity="library-first-party",
        library_type="workflow",
        rights=Rights(
            fetch_authorization="granted",
            install_rights="granted",
            redistribution_rights="granted",
            derivative_rights="granted",
            evidence_source="first-party Library catalog entry in library.yaml",
        ),
    )
    assert len(requests) == 4
    for request in requests:
        assert isinstance(request, ReceiptBackfillRequest)
        # ADR-0006 keeps executor authority. A backfill writes a receipt; it
        # does not choose or change an executor.
        assert request.preserves_executor_authority is True
        assert request.executor_authority == "adr-0006"

    state = _state(tmp_path)
    outcome = apply_receipt_backfill(
        requests,
        state=state,
        scope="global",
        target_root=workflows,
        observed_at=NOW,
    )

    store = state.receipt_store("global")
    receipts = store.all()
    assert len(receipts) == 4
    receipted = {
        Path(target.path).name
        for receipt in receipts
        for target in receipt.targets
    }
    assert receipted == set(names)

    # Every receipt is complete enough to reproduce its projection.
    for receipt in receipts:
        assert receipt.verified is True
        assert receipt.normalized_content_digest
        assert receipt.cache_key_digest
        assert receipt.rights.redistribution_rights == "granted"

    # The bytes on disk are now the catalog's, and the receipt says so.
    for name in names:
        assert (workflows / name).read_bytes() == f"// catalog {name}\n".encode()

    assert outcome.receipted == tuple(sorted(names))
    assert outcome.executor_authority_changed is False

    # And the inventory now reports them as receipted rather than as the
    # unreproducible state this AC exists to end.
    index = receipt_index_for([store])
    classifications = classify_inventory(
        scan_projections([workflows]),
        digest_index={},
        rights_for={}.get,
        receipt_index=index,
    )
    assert {item.receipt_status for item in classifications} == {"receipted"}


def test_a_workflow_projection_with_no_catalog_entry_is_not_receipted(
    tmp_path: Path,
) -> None:
    """A backfill invents nothing.

    A receipt written without a catalog source would be a receipt that cannot
    reproduce anything -- the exact defect, restated in a document that now
    claims otherwise.
    """
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "orphan.js").write_bytes(b"// nobody knows\n")

    requests = plan_receipt_backfill(
        scan_projections([workflows]),
        catalog_lookup=lambda _projection: None,
        provider_identity="library-first-party",
        library_type="workflow",
        rights=GRANTED,
    )
    assert requests == ()
    assert (workflows / "orphan.js").read_bytes() == b"// nobody knows\n"


def test_a_backfill_never_projects_before_its_receipt_is_written(
    tmp_path: Path,
) -> None:
    """The install order is the contract, and a backfill is an install.

    A failure while writing the receipt must leave no active projection whose
    bytes changed. The original file is what remains.
    """
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "quick-fix.js").write_bytes(b"// stale\n")

    requests = plan_receipt_backfill(
        scan_projections([workflows]),
        catalog_lookup=lambda projection: {projection.name: b"// catalog\n"},
        provider_identity="library-first-party",
        library_type="workflow",
        rights=GRANTED,
    )

    class _Broken(ReceiptStore):
        def put(self, receipt):  # type: ignore[override]
            raise OSError("receipt store is unwritable")

    state = _state(tmp_path)
    broken = _Broken(state.receipt_paths["global"])
    with pytest.raises(Exception):
        apply_receipt_backfill(
            requests,
            state=state,
            scope="global",
            target_root=workflows,
            observed_at=NOW,
            receipt_store=broken,
        )
    assert (workflows / "quick-fix.js").read_bytes() == b"// stale\n"


# -- receipt-declared provenance (AC5, accuracy) --------------------------------


def test_a_lock_receipt_declares_provenance_that_a_name_could_not(
    tmp_path: Path,
) -> None:
    """AC5. A projection an existing lock receipt claims is not "unknown origin".

    The ADR's survey found `0 of 23` receipts for the projections it named, and
    concluded that local evidence cannot attribute them. That is true for those
    23 and false for the rest of the same directory: the operator's real
    `global.lock` claims most of what is installed there, with a catalog
    identity and a bridge symlink pointing at its own cache object.

    Treating every projection as unattributed would therefore be inaccurate in
    the expensive direction -- it would mark the Library's own installs
    non-compliant and block them from repair, which turns a rights control into
    an outage. `receipt-declared` is a third provenance state, weaker than a
    digest match and much stronger than a name, and it is named separately so
    the two can never be read as the same evidence.
    """
    root = tmp_path / "skills"
    _projection(root, "declared", b"# first party\n")
    _projection(root, "undeclared", b"# nobody knows\n")

    declared = {
        str(root / "declared"): DeclaredProvenance(
            receipt_id="skill:declared:global",
            provider_identity="first-party-catalog",
            evidence_source=(
                "lock receipt skill:declared:global in "
                "/config/global.lock records catalog_identity first-party-catalog"
            ),
        )
    }
    first_party = Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="granted",
        derivative_rights="granted",
        evidence_source="the operator's own first-party catalog",
    )

    classifications = classify_inventory(
        scan_projections([root]),
        digest_index={},
        rights_for={"first-party-catalog": first_party}.get,
        receipt_index={str(root / "declared"): "skill:declared:global"},
        declared_provenance=declared,
    )
    by_name = {item.projection.name: item for item in classifications}

    covered = by_name["declared"]
    assert covered.attribution.state == "receipt-declared"
    assert covered.attribution.provider_identity == "first-party-catalog"
    assert covered.redistribution_state == "granted"
    assert covered.receipt_status == "receipted"
    assert covered.compliance == "compliant"
    assert covered.pending_reason is None

    orphan = by_name["undeclared"]
    assert orphan.attribution.state == "unattributed"
    assert orphan.compliance == "non-compliant"
    assert orphan.pending_reason == PENDING_DIGEST_ATTRIBUTION


def test_a_declaration_does_not_outrank_a_digest(tmp_path: Path) -> None:
    """A digest match is the stronger evidence and wins.

    A lock receipt states what the Library *believes* it installed. A digest
    states what is actually there. When both are available and they disagree
    about the provider, the bytes decide -- otherwise a receipt could keep
    vouching for content that was replaced underneath it.
    """
    root = tmp_path / "skills"
    _projection(root, "anchor", b"# anchor\n")
    digest = normalized_content_digest({"SKILL.md": b"# anchor\n"})
    classification = classify_projection(
        scan_projections([root])[0],
        attribution=attribute_by_digest(
            scan_projections([root])[0], digest_index={digest: (PROVIDER, "skills/anchor")}
        ),
        rights_for={PROVIDER: GRANTED}.get,
        receipt_status="receipted",
        declared=DeclaredProvenance(
            receipt_id="skill:anchor:global",
            provider_identity="some-other-catalog",
            evidence_source="a lock receipt that claims a different origin",
        ),
    )
    assert classification.attribution.state == "attributed"
    assert classification.attribution.provider_identity == PROVIDER


def test_a_declaration_with_no_recorded_rights_stays_unresolved(
    tmp_path: Path,
) -> None:
    """A receipt is provenance, not permission.

    A lock entry naming a catalog nobody recorded rights for resolves to
    `unknown`, because discovery is not permission and neither is having
    installed something once.
    """
    root = tmp_path / "skills"
    _projection(root, "declared", b"# from somewhere\n")
    classification = classify_projection(
        scan_projections([root])[0],
        attribution=attribute_by_digest(scan_projections([root])[0], digest_index={}),
        rights_for={}.get,
        receipt_status="receipted",
        declared=DeclaredProvenance(
            receipt_id="skill:declared:global",
            provider_identity="catalog-with-no-recorded-rights",
            evidence_source="a lock receipt naming a catalog with no rights record",
        ),
    )
    assert classification.attribution.state == "receipt-declared"
    assert classification.redistribution_state == "unknown"
    assert classification.compliance == "non-compliant"
    assert classification.pending_reason is None


def test_declared_provenance_requires_its_own_evidence() -> None:
    """A declaration without a named source is not evidence.

    `CL-n7ex` made a resolved grant refuse construction without a named
    evidence source. A provenance declaration that could be created empty would
    reintroduce exactly that hole one layer up.
    """
    with pytest.raises(ValueError):
        DeclaredProvenance(
            receipt_id="skill:x:global",
            provider_identity="a-catalog",
            evidence_source="",
        )
