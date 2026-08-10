"""Offline semantics, `upstream-vanished`, and explicit named removal (CL-y5z4).

ADR-0011 `Offline Semantics` makes offline operation **additive and
repair-only**: reinstall, integrity verification, and status are allowed from a
verified pinned cache; upgrade, re-pin, ownership-derived prune, and
`--prune --apply` are refused. `verified local integrity` and `unknown remote
freshness` are separate reported facts and are never merged into one "ok".

Covers AC4, AC5, AC7, AC8.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Mapping, Sequence

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.cache_transaction import (  # noqa: E402
    CompletenessEvidence,
    ProjectionActivation,
    cache_status,
    install_foreign_item,
    reinstall_from_cache,
)
from lib.providers.contract import FetchedFile, FetchedItem  # noqa: E402
from lib.providers.executable_admission import content_digest  # noqa: E402
from lib.providers.foreign_cache import (  # noqa: E402
    IDENTITY_TRANSFORMATION,
    ObjectStore,
    TofuPinStore,
)
from lib.providers.inventory import (  # noqa: E402
    NormalizedItem,
    ProviderAvailability,
    Rights,
)
from lib.providers.offline import (  # noqa: E402
    ALLOWED_OFFLINE_OPERATIONS,
    REFUSAL_REASONS,
    REFUSED_OFFLINE_OPERATIONS,
    OfflineRefusal,
    evaluate_operation,
    require_operation,
    status_freshness,
)
from lib.providers.receipts import (  # noqa: E402
    DeletionAuthorityRefused,
    InventoryObservation,
    ProjectionStillActive,
    ReceiptStore,
    ReceiptTarget,
    deletion_authority,
    reconcile_upstream_state,
    remove_named_receipt,
)

from foreign_admission_support import admitting  # noqa: E402

PROVIDER = "provider-under-test"
NOW = "2026-08-09T09:00:00Z"
LATER = "2026-08-09T12:00:00Z"
MIT = "upstream LICENSE (MIT), read from the fetched item on 2026-08-09"
IDENTITY = f"{PROVIDER}#kits/anchor"

UPSTREAM = {"SKILL.md": b"---\nname: anchor\n---\nanchor body\n"}

GRANTED = Rights(
    fetch_authorization="granted",
    install_rights="granted",
    redistribution_rights="granted",
    derivative_rights="granted",
    evidence_source=MIT,
)

AVAILABLE = ProviderAvailability(state="available", observed_at=NOW)
UNAVAILABLE = ProviderAvailability(
    state="unavailable", observed_at=LATER, reason="host did not answer within 30s"
)
DEGRADED = ProviderAvailability(
    state="degraded", observed_at=LATER, reason="listing truncated by rate limiting"
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


class _Projector:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.activations = 0

    def plan(self, files: Mapping[str, bytes]) -> Sequence[str]:
        return tuple(str(self.root / path) for path in sorted(files))

    @property
    def activation(self) -> ProjectionActivation:
        return ProjectionActivation(plan=self.plan, apply=self)

    def deactivate(self, targets: Sequence[ReceiptTarget]) -> Sequence[str]:
        removed = []
        for target in targets:
            path = Path(target.path)
            if path.is_file():
                path.unlink()
                removed.append(target.path)
        return tuple(removed)

    def __call__(self, files: Mapping[str, bytes]) -> Sequence[ReceiptTarget]:
        self.activations += 1
        targets = []
        for path, content in sorted(files.items()):
            destination = self.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            targets.append(
                ReceiptTarget(
                    path=str(destination),
                    kind="file",
                    content_sha256=content_digest({path: content}),
                )
            )
        return tuple(targets)


def _installed(tmp_path: Path):
    objects = ObjectStore(tmp_path / "cache")
    pins = TofuPinStore(tmp_path / "pins.json")
    receipts = ReceiptStore(tmp_path / "receipts.json")
    projector = _Projector(tmp_path / "harness")
    item = _item()
    outcome = install_foreign_item(
        item,
        # `CL-lt51`: a foreign steward's Skill is admission-required. This suite
        # is about offline semantics, so it records the decision for exactly the
        # bytes it installs; repair then re-derives it from the cached content.
        ledger=admitting(item.qualified_identity(), UPSTREAM),
        retrieve=lambda: FetchedItem(
            upstream_id="kits/anchor",
            revision=None,
            files=tuple(
                FetchedFile(path=path, content=content) for path, content in UPSTREAM.items()
            ),
            primary_path="SKILL.md",
        ),
        object_store=objects,
        pin_store=pins,
        receipt_store=receipts,
        transformation=IDENTITY_TRANSFORMATION,
        target="project_committed",
        activate=projector.activation,
        completeness=CompletenessEvidence.from_manifest(sorted(UPSTREAM)),
        observed_at=NOW,
    )
    return outcome, objects, pins, receipts, projector


def test_offline_reinstall_and_verify(tmp_path: Path) -> None:
    """Offline repair works, and freshness is `unknown` -- never `current` (AC4)."""
    outcome, objects, _, receipts, projector = _installed(tmp_path)

    # The operator's harness path is lost; the provider is unreachable.
    for path in sorted(projector.root.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    assert not (projector.root / "SKILL.md").exists()

    integrity = objects.verify(outcome.cache_object.key)
    assert integrity.verified

    result = reinstall_from_cache(
        receipt=outcome.receipt,
        object_store=objects,
        receipt_store=receipts,
        availability=UNAVAILABLE,
        activate=projector.activation,
        observed_at=LATER,
        # Repair is a write of model-instructing content and `CL-lt51` governs it
        # by the same standing decision the install needed. The decision is
        # re-derived from the verified cached bytes, not read off the receipt.
        ledger=admitting(outcome.receipt.qualified_identity(), UPSTREAM),
    )
    assert (projector.root / "SKILL.md").read_bytes() == UPSTREAM["SKILL.md"]
    assert result.integrity.verified
    assert result.freshness == "unknown"

    status = cache_status(
        receipt=ReceiptStore(receipts.path).get(outcome.receipt.id),
        object_store=objects,
        availability=UNAVAILABLE,
    )
    assert status.local_integrity == "verified"
    assert status.freshness == "unknown"
    assert status.freshness != "current"
    # Two separate reported facts, never merged into one "ok".
    assert "verified" in status.describe() and "unknown" in status.describe()

    history = tuple(
        event.event for event in ReceiptStore(receipts.path).get(outcome.receipt.id).history
    )
    assert "reinstalled-from-cache" in history

    # An available provider still never reports a revisionless pin as `current`.
    assert status_freshness(AVAILABLE, revisionless=True) == "pin-only"
    assert status_freshness(UNAVAILABLE, revisionless=False) == "unknown"


@pytest.mark.parametrize(
    "operation",
    ["upgrade", "re-pin", "ownership-derived-prune", "prune-apply"],
)
def test_offline_refusals(operation: str, tmp_path: Path) -> None:
    """Upgrade, re-pin, prune, and `--prune --apply` are refused, typed (AC5)."""
    verdict = evaluate_operation(operation, UNAVAILABLE)
    assert not verdict.allowed
    assert verdict.reason in REFUSAL_REASONS
    assert operation in REFUSED_OFFLINE_OPERATIONS

    with pytest.raises(OfflineRefusal) as excinfo:
        require_operation(operation, UNAVAILABLE)
    refusal = excinfo.value
    assert refusal.operation == operation
    assert refusal.reason == verdict.reason
    assert refusal.reason in str(refusal)

    # Degraded is not "available enough": deletion authority and remote
    # comparison both require a complete resolution.
    assert not evaluate_operation(operation, DEGRADED).allowed

    # An explicit operator re-pin is refused at the pin store too, so the
    # refusal does not depend on any caller consulting the table first.
    if operation == "re-pin":
        _, _, pins, _, _ = _installed(tmp_path)
        drifted = content_digest({"SKILL.md": b"substituted\n"})
        with pytest.raises(OfflineRefusal):
            pins.repin(
                IDENTITY,
                drifted,
                operator="malte",
                acknowledged_drift=(pins.pin_for(IDENTITY).normalized_content_digest, drifted),
                decided_at=LATER,
                availability=UNAVAILABLE,
            )
        assert pins.pin_for(IDENTITY).normalized_content_digest != drifted


def test_offline_allows_repair_operations() -> None:
    """The additive half of the table is allowed, not merely untested (AC4)."""
    for operation in ALLOWED_OFFLINE_OPERATIONS:
        verdict = evaluate_operation(operation, UNAVAILABLE)
        assert verdict.allowed, operation
        assert verdict.reason is None
    assert set(ALLOWED_OFFLINE_OPERATIONS) & set(REFUSED_OFFLINE_OPERATIONS) == set()
    assert "automatic-garbage-collection" in REFUSED_OFFLINE_OPERATIONS


def test_upstream_vanished_state(tmp_path: Path) -> None:
    """A reachable, complete provider that stopped listing an item (AC7)."""
    outcome, objects, _, receipts, _ = _installed(tmp_path)

    # A degraded observation changes nothing: absence is not information yet.
    degraded = InventoryObservation(
        provider_identity=PROVIDER,
        availability=DEGRADED, listed_identities=frozenset(), complete=False
    )
    unchanged = reconcile_upstream_state(receipts, degraded, observed_at=LATER)
    assert unchanged.changed == ()
    assert unchanged.degraded_reason is not None
    assert ReceiptStore(receipts.path).get(outcome.receipt.id).upstream_state == "present"

    complete = InventoryObservation(
        provider_identity=PROVIDER,
        availability=AVAILABLE, listed_identities=frozenset({f"{PROVIDER}#kits/other"}), complete=True
    )
    result = reconcile_upstream_state(receipts, complete, observed_at=LATER)
    assert [receipt.id for receipt in result.changed] == [outcome.receipt.id]

    # Durable and queryable after reload.
    reloaded = ReceiptStore(receipts.path)
    vanished = reloaded.get(outcome.receipt.id)
    assert vanished.upstream_state == "upstream-vanished"
    assert reloaded.with_upstream_state("upstream-vanished") == (vanished,)
    assert "upstream-vanished" in tuple(event.event for event in vanished.history)

    # It grants no deletion authority, and the cached bytes stay put.
    back_in_scope = InventoryObservation(
        provider_identity=PROVIDER,
        availability=AVAILABLE,
        listed_identities=frozenset({f"{PROVIDER}#kits/other"}),
        complete=True,
    )
    with pytest.raises(DeletionAuthorityRefused) as excinfo:
        deletion_authority(vanished, back_in_scope)
    assert "upstream-vanished" in str(excinfo.value)
    assert objects.verify(outcome.cache_object.key).verified

    # It remains until the upstream identity reappears.
    back = InventoryObservation(
        provider_identity=PROVIDER,
        availability=AVAILABLE, listed_identities=frozenset({IDENTITY}), complete=True
    )
    reconcile_upstream_state(reloaded, back, observed_at="2026-08-09T13:00:00Z")
    restored = ReceiptStore(receipts.path).get(outcome.receipt.id)
    assert restored.upstream_state == "present"
    assert "upstream-reappeared" in tuple(event.event for event in restored.history)


@pytest.mark.parametrize(
    "observation",
    [
        InventoryObservation(provider_identity=PROVIDER, availability=UNAVAILABLE, listed_identities=frozenset(), complete=False),
        InventoryObservation(provider_identity=PROVIDER, availability=DEGRADED, listed_identities=frozenset(), complete=False),
        InventoryObservation(
            provider_identity=PROVIDER,
            availability=AVAILABLE, listed_identities=frozenset(), complete=False
        ),
        InventoryObservation(
            provider_identity=PROVIDER,
            availability=AVAILABLE,
            listed_identities=frozenset(),
            complete=True,
            reduced_by_authorization=True,
        ),
        InventoryObservation(provider_identity=PROVIDER, availability=AVAILABLE, listed_identities=frozenset(), complete=True),
    ],
    ids=["unavailable", "degraded", "incomplete", "authorization-reduced", "vanished"],
)
def test_named_removal_under_degraded_inventory(
    observation: InventoryObservation, tmp_path: Path
) -> None:
    """Named removal always works, records why, and destroys no bytes (AC8)."""
    outcome, objects, _, receipts, projector = _installed(tmp_path)

    removal = remove_named_receipt(
        receipts,
        outcome.receipt.id,
        operator="malte",
        intent="retiring the anchor kit from this machine",
        observation=observation,
        removed_at=LATER,
        deactivate=projector.deactivate,
    )

    assert ReceiptStore(receipts.path).get(outcome.receipt.id) is None
    assert removal.retained_cache_path == outcome.cache_object.path
    assert objects.verify(outcome.cache_object.key).verified, "bytes are never deleted"

    retired = ReceiptStore(receipts.path).retired()
    assert [receipt.id for receipt in retired] == [outcome.receipt.id]
    final = retired[0].history[-1]
    assert final.event == "explicit-removal"
    assert final.operator == "malte"
    assert "retiring the anchor kit" in final.detail
    assert observation.availability.state in final.provider_state


def test_named_removal_deactivates_the_projection_it_retires(tmp_path: Path) -> None:
    """Retiring a receipt never leaves its projection installed (wave-1 F1).

    Removing the receipt alone recreated the exact unreceipted active projection
    this cache exists to end: the files stayed on disk and nothing described
    them any more.
    """
    outcome, objects, _, receipts, projector = _installed(tmp_path)
    observation = InventoryObservation(
        provider_identity=PROVIDER, availability=UNAVAILABLE, complete=False
    )
    installed = projector.root / "SKILL.md"
    assert installed.is_file()

    # Without a deactivation, the removal refuses rather than orphaning it.
    with pytest.raises(ProjectionStillActive):
        remove_named_receipt(
            receipts,
            outcome.receipt.id,
            operator="malte",
            intent="retire the anchor kit",
            observation=observation,
            removed_at=LATER,
        )
    assert installed.is_file()
    assert ReceiptStore(receipts.path).get(outcome.receipt.id) is not None

    removal = remove_named_receipt(
        receipts,
        outcome.receipt.id,
        operator="malte",
        intent="retire the anchor kit",
        observation=observation,
        removed_at=LATER,
        deactivate=projector.deactivate,
    )
    assert not installed.exists()
    assert removal.deactivated == (str(installed),)
    assert ReceiptStore(receipts.path).get(outcome.receipt.id) is None
    assert objects.verify(outcome.cache_object.key).verified, "bytes are never deleted"


def test_reconciliation_is_source_scoped(tmp_path: Path) -> None:
    """One source's listing says nothing about another source's items (wave-1 F9)."""
    outcome, _, pins, receipts, _ = _installed(tmp_path)
    other = outcome.receipt.to_dict()
    other["id"] = "skill:other@0000000000000000"
    other["provider_identity"] = "other-source"
    other["upstream_id"] = "kits/other"
    receipts.put(type(outcome.receipt).from_dict(other))

    complete = InventoryObservation(
        provider_identity=PROVIDER,
        availability=AVAILABLE,
        listed_identities=frozenset({f"{PROVIDER}#kits/anchor"}),
        complete=True,
    )
    result = reconcile_upstream_state(receipts, complete, observed_at=LATER)
    assert result.changed == ()
    assert [receipt.id for receipt in result.out_of_scope] == [other["id"]]

    reloaded = ReceiptStore(receipts.path)
    assert reloaded.get(other["id"]).upstream_state == "present"
    assert reloaded.with_upstream_state("upstream-vanished") == ()


def test_an_incomplete_inventory_never_authorizes_deletion(tmp_path: Path) -> None:
    """Reachability is not a complete resolution (wave-1 F10)."""
    outcome, _, _, receipts, _ = _installed(tmp_path)
    verified = ReceiptStore(receipts.path).get(outcome.receipt.id)
    assert verified.verified

    truncated = InventoryObservation(
        provider_identity=PROVIDER,
        availability=AVAILABLE,
        listed_identities=frozenset({IDENTITY}),
        complete=False,
    )
    assert truncated.degraded_reason() == "inventory is incomplete or truncated"
    for operation in ("ownership-derived-prune", "prune-apply", "upgrade", "re-pin"):
        assert not evaluate_operation(operation, truncated).allowed, operation
    with pytest.raises(DeletionAuthorityRefused, match="incomplete resolution"):
        deletion_authority(verified, truncated)

    # Transport reachability with no observation at all is the absence of
    # evidence, not its presence.
    assert not evaluate_operation("ownership-derived-prune", AVAILABLE).allowed
    with pytest.raises(DeletionAuthorityRefused, match="source-scoped"):
        deletion_authority(verified, AVAILABLE)

    # Another source's complete resolution is not this receipt's.
    foreign = InventoryObservation(
        provider_identity="other-source",
        availability=AVAILABLE,
        listed_identities=frozenset({IDENTITY}),
        complete=True,
    )
    with pytest.raises(DeletionAuthorityRefused, match="says nothing about another"):
        deletion_authority(verified, foreign)

    # A complete listing that omits the item proves it vanished, which never
    # grants deletion authority -- and safety must not depend on the caller
    # having reconciled first (wave-2 F5).
    omitting = InventoryObservation(
        provider_identity=PROVIDER,
        availability=AVAILABLE,
        listed_identities=frozenset({f"{PROVIDER}#kits/other"}),
        complete=True,
    )
    with pytest.raises(DeletionAuthorityRefused, match="upstream-vanished"):
        deletion_authority(verified, omitting)

    conclusive = InventoryObservation(
        provider_identity=PROVIDER,
        availability=AVAILABLE,
        listed_identities=frozenset({IDENTITY}),
        complete=True,
    )
    assert evaluate_operation("ownership-derived-prune", conclusive).allowed
    assert deletion_authority(verified, conclusive) is verified


def test_removal_recovers_a_planned_only_receipt(tmp_path: Path) -> None:
    """A crash-window receipt still owns its files (wave-2 F2).

    Review crashed an install after activation and before finalization, then
    removed the resulting receipt: it recorded no targets, so deactivation was
    skipped entirely and the projection stayed installed with nothing describing
    it.
    """
    outcome, _, _, receipts, projector = _installed(tmp_path)
    installed = projector.root / "SKILL.md"
    assert installed.is_file()

    # Reduce the receipt to the state a crash between plan and finalize leaves.
    crashed = outcome.receipt.to_dict()
    crashed["targets"] = []
    crashed["verified"] = False
    crashed["planned_targets"] = [str(installed)]
    receipts.put(type(outcome.receipt).from_dict(crashed))

    observation = InventoryObservation(
        provider_identity=PROVIDER, availability=UNAVAILABLE, complete=False
    )
    with pytest.raises(ProjectionStillActive):
        remove_named_receipt(
            receipts,
            outcome.receipt.id,
            operator="malte",
            intent="retire the anchor kit",
            observation=observation,
            removed_at=LATER,
        )
    assert installed.is_file()

    removal = remove_named_receipt(
        receipts,
        outcome.receipt.id,
        operator="malte",
        intent="retire the anchor kit",
        observation=observation,
        removed_at=LATER,
        deactivate=projector.deactivate,
    )
    assert removal.deactivated == (str(installed),)
    assert not installed.exists()
    assert ReceiptStore(receipts.path).get(outcome.receipt.id) is None


def test_a_partial_deactivation_keeps_the_receipt_active(tmp_path: Path) -> None:
    """A projection that survives deactivation keeps its recovery record (wave-2 F2)."""
    outcome, _, _, receipts, projector = _installed(tmp_path)
    installed = projector.root / "SKILL.md"
    observation = InventoryObservation(
        provider_identity=PROVIDER, availability=UNAVAILABLE, complete=False
    )

    with pytest.raises(ProjectionStillActive, match="still present after deactivation"):
        remove_named_receipt(
            receipts,
            outcome.receipt.id,
            operator="malte",
            intent="retire the anchor kit",
            observation=observation,
            removed_at=LATER,
            deactivate=lambda targets: (),
        )

    assert installed.is_file()
    assert ReceiptStore(receipts.path).get(outcome.receipt.id) is not None
    assert ReceiptStore(receipts.path).retired() == ()


def test_retirement_cannot_bypass_the_removal_gates(tmp_path: Path) -> None:
    """The archive is reachable only through an explicit removal (wave-2 F3).

    The store's retire path used to be public and unguarded, so a direct call
    archived a receipt while its projection stayed on disk.
    """
    outcome, _, _, receipts, projector = _installed(tmp_path)
    assert not hasattr(receipts, "retire")

    with pytest.raises(ProjectionStillActive, match="final step of an explicit"):
        receipts._retire(outcome.receipt)
    assert ReceiptStore(receipts.path).get(outcome.receipt.id) is not None
    assert (projector.root / "SKILL.md").is_file()


def test_named_removal_is_never_reached_by_ownership_derived_prune(tmp_path: Path) -> None:
    """The one path that may remove a receipt is not the prune path (AC8)."""
    outcome, _, _, receipts, _ = _installed(tmp_path)
    observation = InventoryObservation(
        provider_identity=PROVIDER,
        availability=UNAVAILABLE, listed_identities=frozenset(), complete=False
    )

    with pytest.raises(OfflineRefusal) as excinfo:
        remove_named_receipt(
            receipts,
            outcome.receipt.id,
            operator="reconciler",
            intent="prune unreferenced receipts",
            observation=observation,
            removed_at=LATER,
            origin="ownership-derived-prune",
        )
    assert excinfo.value.operation == "ownership-derived-prune"
    assert ReceiptStore(receipts.path).get(outcome.receipt.id) is not None
