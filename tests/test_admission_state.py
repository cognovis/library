"""Admission state and the closed block-reason vocabulary (CL-n7ex AC2, AC4).

ADR-0011 `Typed block reasons` fixes a closed, ordered vocabulary in which every
recorded reason carries the evidence that produced it. `blocked` is a
first-class queryable state, not an error: an operator must be able to ask "what
did I not get, and exactly why" without re-running discovery.

Admission is a **separate pass** over normalized inventory rather than a step
inside normalization, because discovery never implies permission.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.admission import (  # noqa: E402
    AdmissionContext,
    evaluate_inventory,
    evaluate_item,
)
from lib.providers.executable_admission import (  # noqa: E402
    ExecutableAdmissionLedger,
    content_digest,
)
from lib.providers.inventory import (  # noqa: E402
    BLOCK_REASONS,
    BlockReason,
    NormalizedInventory,
    NormalizedItem,
    ProviderAvailability,
    Rights,
)

PROVIDER = "provider-under-test"
MIT = "upstream LICENSE (MIT), verified 2026-08-08"

GRANTED = Rights(
    fetch_authorization="granted",
    install_rights="granted",
    redistribution_rights="granted",
    derivative_rights="granted",
    evidence_source=MIT,
)


def _item(**overrides: object) -> NormalizedItem:
    base = dict(
        provider_identity=PROVIDER,
        upstream_id="kits/anchor",
        upstream_name="anchor",
        collection_membership=("kits",),
        upstream_revision=None,
        library_type="skill",
        library_name="anchor",
        classification={"type_basis": "marker-file"},
        runtime_compatibility=("unknown",),
        rights=GRANTED,
        provider_availability=ProviderAvailability(
            state="available", observed_at="2026-08-09T09:00:00Z"
        ),
    )
    base.update(overrides)
    return NormalizedItem(**base)  # type: ignore[arg-type]


# -- AC4: the vocabulary is closed and every reason carries evidence ----------


def test_block_reason_vocabulary() -> None:
    """An unknown reason value is rejected; a reason without evidence is too."""
    assert BLOCK_REASONS == (
        "license-unknown",
        "license-denied",
        "redistribution-blocked",
        "authentication-required",
        "incompatible-runtime",
        "executable-admission-pending",
        "untrusted-source",
        "content-unavailable",
    )

    reason = BlockReason(
        reason="license-unknown",
        evidence="install_rights resolves to unknown for this item",
        source="the rights recorded for this provider in the catalog",
    )
    assert reason.reason == "license-unknown"
    assert reason.evidence
    assert reason.source

    with pytest.raises(ValueError):
        BlockReason(
            reason="looks-fishy",
            evidence="a reviewer disliked it",
            source="a reviewer's opinion, recorded",
        )
    # Evidence is two required halves: what was observed, and where from.
    for evidence, source in (
        ("", "the catalog rights record"),
        ("   ", "the catalog rights record"),
        ("e", "the catalog rights record"),
        ("unavailable", "the catalog rights record"),
        # "details unavailable" passed every length and shape check while naming
        # nothing; it is still refused, and now it also cannot omit its source.
        ("details unavailable", ""),
        ("install_rights resolves to unknown", "unknown"),
        # Text that admits it says nothing, in either half.
        ("details unavailable", "details unavailable"),
        ("details unavailable", "the catalog rights record"),
        ("install_rights resolves to unknown", "not recorded"),
        # A source that merely repeats the observation names no source at all.
        ("install_rights resolves to unknown", "install_rights resolves to unknown"),
    ):
        with pytest.raises(ValueError):
            BlockReason(reason="license-unknown", evidence=evidence, source=source)

    # The normalized item carries the same closed vocabulary.
    with pytest.raises(ValueError):
        _item(
            admission_state="blocked",
            block_reasons=(
                BlockReason(
                    reason="nope",
                    evidence="something looked wrong here",
                    source="a named source, observed 2026",
                ),
            ),
        )
    with pytest.raises(ValueError):
        _item(admission_state="blocked", block_reasons=())

    # Every reason an evaluation can emit is inside the vocabulary, and each one
    # arrives with the evidence that produced it.
    blocked = evaluate_item(
        _item(
            rights=Rights(
                fetch_authorization="granted",
                grant_evidence={
                    "fetch_authorization": "subscriber token, 2026-08-08",
                    "install_rights": "no published installation grant",
                },
            )
        ),
        AdmissionContext(),
    )
    assert blocked.admission_state == "blocked"
    assert [entry.reason for entry in blocked.block_reasons] == ["license-unknown"]
    assert all(entry.reason in BLOCK_REASONS for entry in blocked.block_reasons)
    assert "no published installation grant" in blocked.block_reasons[0].source
    assert "install_rights" in blocked.block_reasons[0].evidence
    assert "unknown" in blocked.block_reasons[0].evidence
    assert "install_rights" in blocked.block_reasons[0].describe()


def test_block_reasons_serialize_with_their_evidence() -> None:
    item = _item(
        admission_state="blocked",
        block_reasons=(
            BlockReason(
                reason="license-unknown",
                evidence="install_rights resolves to unknown for this item",
                source="no published installation grant was located",
            ),
        ),
    )
    payload = item.to_dict()
    assert payload["block_reasons"] == [
        {
            "reason": "license-unknown",
            "evidence": "install_rights resolves to unknown for this item",
            "source": "no published installation grant was located",
            "detail": None,
        }
    ]
    assert NormalizedItem.from_dict(payload) == item

    # A bare vocabulary value is not a reason: it carries no evidence.
    with pytest.raises(ValueError):
        NormalizedItem.from_dict({**payload, "block_reasons": ["license-unknown"]})
    with pytest.raises(ValueError):
        BlockReason.from_dict({"reason": "license-unknown"})
    with pytest.raises(ValueError):
        BlockReason.from_dict(
            {"reason": "license-unknown", "evidence": "install_rights is unknown here"}
        )


def test_a_fully_granted_item_is_installable_with_no_reasons() -> None:
    decision = evaluate_item(_item(), AdmissionContext())

    assert decision.admission_state == "installable"
    assert decision.block_reasons == ()
    assert decision.projection_eligibility == {
        "project_committed": "allowed",
        "machine_local": "allowed",
    }


def test_reasons_are_emitted_in_the_vocabulary_order_with_evidence() -> None:
    """Several independent deficits produce several ordered, evidenced reasons."""
    decision = evaluate_item(
        _item(
            library_type="workflow",
            runtime_compatibility=("pi",),
            trust_state="unreviewed",
            rights=Rights(
                fetch_authorization="granted",
                install_rights="denied",
                evidence_source="upstream terms forbid installation",
            ),
            provider_availability=ProviderAvailability(
                state="unavailable",
                observed_at="2026-08-09T09:00:00Z",
                reason="endpoint returned 503",
            ),
        ),
        AdmissionContext(
            target_runtimes=("claude-code",),
            required_trust="reviewed",
            required_auth_references=("provider-token",),
            satisfied_auth_references=(),
        ),
    )

    assert decision.admission_state == "blocked"
    assert [entry.reason for entry in decision.block_reasons] == [
        "license-denied",
        "authentication-required",
        "incompatible-runtime",
        "executable-admission-pending",
        "untrusted-source",
        "content-unavailable",
    ]
    assert all(entry.evidence.strip() for entry in decision.block_reasons)
    assert "endpoint returned 503" in dict(
        (entry.reason, entry.evidence) for entry in decision.block_reasons
    )["content-unavailable"]
    # A non-rights block floors projection eligibility on every target: admission
    # is a precondition of installability.
    assert decision.projection_eligibility == {
        "project_committed": "blocked",
        "machine_local": "blocked",
    }


def test_a_non_rights_block_floors_projection_eligibility() -> None:
    """Clean rights do not survive an unadmitted executable.

    Without the floor this item would advertise `allowed` on both targets while
    reporting `blocked` -- a contradiction a consumer could act on.
    """
    decision = evaluate_item(_item(library_type="workflow"), AdmissionContext())

    assert decision.executable_admission == "pending"
    assert decision.reason_values() == ("executable-admission-pending",)
    assert decision.projection_eligibility == {
        "project_committed": "blocked",
        "machine_local": "blocked",
    }


def test_an_unsubstantiated_admitted_field_is_not_authority() -> None:
    """Executable admission comes from the operator's ledger, never from the item."""
    claimed = _item(library_type="workflow", executable_admission="admitted")

    decision = evaluate_item(claimed, AdmissionContext())

    assert decision.executable_admission == "pending"
    assert decision.admission_state == "blocked"
    assert decision.reason_values() == ("executable-admission-pending",)

    # With a ledger-backed decision for the current content, it is admitted.
    content = {"WORKFLOW.md": b"steps: one\n"}
    ledger = ExecutableAdmissionLedger()
    ledger.admit(
        claimed.qualified_identity(),
        content_digest(content),
        library_type="workflow",
        reviewer="malte.sussdorff@cognovis.de",
        permission_surface=("filesystem:write",),
        decided_at="2026-08-09T09:00:00Z",
        evidence="reviewed the workflow body and its permission surface",
    )
    admitted = evaluate_item(
        claimed,
        AdmissionContext(),
        ledger=ledger,
        contents={claimed.qualified_identity(): content},
    )
    assert admitted.executable_admission == "admitted"
    assert admitted.admission_state == "installable"


def test_a_refused_executable_records_untrusted_source() -> None:
    """The closed vocabulary has no refused entry; a refusal is not pending."""
    item = _item(library_type="workflow")
    content = {"WORKFLOW.md": b"rm -rf /\n"}
    ledger = ExecutableAdmissionLedger()
    ledger.refuse(
        item.qualified_identity(),
        content_digest(content),
        library_type="workflow",
        reviewer="malte.sussdorff@cognovis.de",
        decided_at="2026-08-09T09:00:00Z",
        evidence="the workflow deletes outside its worktree",
    )

    decision = evaluate_item(
        item,
        AdmissionContext(),
        ledger=ledger,
        contents={item.qualified_identity(): content},
    )

    assert decision.executable_admission == "refused"
    assert decision.reason_values() == ("untrusted-source",)
    assert "refused" in decision.block_reasons[0].evidence
    assert "ledger" in decision.block_reasons[0].source


def test_redistribution_block_leaves_the_machine_local_path_open() -> None:
    """The four states are orthogonal: blocked here still names a usable path."""
    decision = evaluate_item(
        _item(
            rights=Rights(
                fetch_authorization="granted",
                install_rights="granted",
                evidence_source=MIT,
                grant_evidence={"redistribution_rights": "no grant located 2026-08-08"},
            )
        ),
        AdmissionContext(),
    )

    assert decision.admission_state == "blocked"
    assert [entry.reason for entry in decision.block_reasons] == ["redistribution-blocked"]
    assert "no grant located 2026-08-08" in decision.block_reasons[0].source
    assert "redistribution_rights" in decision.block_reasons[0].evidence
    assert decision.projection_eligibility == {
        "project_committed": "blocked",
        "machine_local": "operator-opt-in-required",
    }


def test_unknown_runtime_compatibility_blocks_nothing_by_itself() -> None:
    decision = evaluate_item(
        _item(runtime_compatibility=("unknown",)),
        AdmissionContext(target_runtimes=("claude-code",)),
    )
    assert decision.block_reasons == ()
    assert decision.admission_state == "installable"


def test_evaluate_inventory_applies_decisions_to_the_items() -> None:
    """The evaluated inventory carries the derived states on the items themselves."""
    inventory = NormalizedInventory(
        [
            _item(),
            _item(
                upstream_id="kits/restricted",
                upstream_name="restricted",
                library_name="restricted",
                rights=Rights(
                    fetch_authorization="granted", evidence_source="subscriber token"
                ),
            ),
        ]
    )

    report = evaluate_inventory(inventory, AdmissionContext())

    clean = report.inventory.resolve(f"{PROVIDER}#kits/anchor")
    restricted = report.inventory.resolve(f"{PROVIDER}#kits/restricted")

    assert clean.admission_state == "installable"
    assert clean.block_reasons == ()
    assert restricted.admission_state == "blocked"
    assert restricted.block_reason_values() == ("license-unknown",)
    assert restricted.projection_eligibility["machine_local"] == "operator-opt-in-required"

    # The decisions stay queryable by qualified identity without re-running discovery.
    assert report.decisions[f"{PROVIDER}#kits/restricted"].admission_state == "blocked"
    assert report.blocked_identities() == (f"{PROVIDER}#kits/restricted",)
    assert report.reasons_for(f"{PROVIDER}#kits/restricted")[0].evidence
    assert report.reasons_for(f"{PROVIDER}#kits/restricted")[0].source


def test_evaluation_does_not_mutate_the_discovered_inventory() -> None:
    """Discovery never implies permission, and evaluation never rewrites discovery."""
    item = _item(
        rights=Rights(
            fetch_authorization="granted",
            install_rights="denied",
            evidence_source="upstream terms forbid installation",
        )
    )
    inventory = NormalizedInventory([item])

    evaluate_inventory(inventory, AdmissionContext())

    assert item.admission_state == "discoverable"
    assert item.block_reasons == ()
    assert inventory.resolve(f"{PROVIDER}#kits/anchor") is item


def test_gate_modules_carry_no_provider_knowledge() -> None:
    """The rights and admission gates are core, and are scanned as core."""
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "checks"))
    from provider_neutrality import CORE_MODULES, scan_repository, scan_source  # noqa: E402

    for module in (
        "scripts/lib/providers/rights.py",
        "scripts/lib/providers/admission.py",
        "scripts/lib/providers/executable_admission.py",
    ):
        assert module in CORE_MODULES

    assert scan_repository(REPO_ROOT) == []

    # A provider name assembled from fragments is still a provider name. Without
    # constant folding this bypassed the check entirely.
    poisoned = (
        "def eligible(provider_identity):\n"
        "    return provider_identity == 'executive' + '-circle'\n"
    )
    kinds = {finding.kind for finding in scan_source("scripts/lib/providers/rights.py", poisoned)}
    assert "provider-name" in kinds

    # The same trick in f-string syntax survived the first repair.
    fstring_poisoned = (
        "def eligible(provider_identity):\n"
        "    return provider_identity == f\"{'executive'}{'-circle'}\"\n"
    )
    kinds = {
        finding.kind
        for finding in scan_source("scripts/lib/providers/rights.py", fstring_poisoned)
    }
    assert "provider-name" in kinds
