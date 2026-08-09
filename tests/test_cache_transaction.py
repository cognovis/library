"""The ordered install/adoption transaction (CL-y5z4 AC2, AC3).

ADR-0011 `Install and adoption transaction` fixes the order and makes it the
contract: retrieve complete content, verify the digest against the pin or record
a first-use pin, materialize atomically, write the receipt, and only then
activate projections.

The historic failure this prevents is a live projection whose bytes cannot be
reproduced once the provider disappears -- four such workflow projections exist
today with zero receipts. Both fault points are therefore tested with an
injected failure, not asserted from the happy path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator, Mapping, Sequence

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.cache_transaction import (  # noqa: E402
    CompletenessEvidence,
    IncompleteRetrieval,
    ProjectionActivation,
    TransactionAborted,
    install_foreign_item,
)
from lib.providers.contract import FetchedFile, FetchedItem  # noqa: E402
from lib.providers.executable_admission import (  # noqa: E402
    ExecutableAdmissionLedger,
    content_digest,
)
from lib.providers.foreign_cache import (  # noqa: E402
    IDENTITY_TRANSFORMATION,
    CacheKey,
    ObjectStore,
    TofuPinStore,
)
from lib.providers.foreign_cache import TofuDrift as TofuDriftError  # noqa: E402
from lib.providers.inventory import (  # noqa: E402
    NormalizedItem,
    ProviderAvailability,
    Rights,
)
from lib.providers.receipts import ReceiptStore, ReceiptTarget  # noqa: E402
from lib.providers.rights import ProjectionRefused  # noqa: E402

PROVIDER = "provider-under-test"
NOW = "2026-08-09T09:00:00Z"
MIT = "upstream LICENSE (MIT), read from the fetched item on 2026-08-09"

UPSTREAM = {
    "SKILL.md": b"---\nname: anchor\n---\nanchor body\n",
    "agents/openai.yaml": b"model: example\n",
}

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
        classification={"skill_class": "procedure"},
        runtime_compatibility=("claude-code",),
        rights=GRANTED,
        provider_availability=ProviderAvailability(state="available", observed_at=NOW),
        admission_state="installable",
        trust_state="reviewed",
        projection_eligibility={"project_committed": "allowed", "machine_local": "allowed"},
    )
    base.update(overrides)
    return NormalizedItem(**base)


def _fetched(files: Mapping[str, bytes] = UPSTREAM) -> FetchedItem:
    return FetchedItem(
        upstream_id="kits/anchor",
        revision=None,
        files=tuple(FetchedFile(path=path, content=content) for path, content in files.items()),
        primary_path="SKILL.md",
    )


class _Projector:
    """A projection target that records whether it was ever activated."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.activations = 0

    def plan(self, files: Mapping[str, bytes]) -> Sequence[str]:
        return tuple(str(self.root / path) for path in sorted(files))

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

    @property
    def activation(self) -> ProjectionActivation:
        return ProjectionActivation(plan=self.plan, apply=self)

    @property
    def is_active(self) -> bool:
        return any(self.root.rglob("*")) if self.root.exists() else False


ADAPTER_DECLARED = CompletenessEvidence.adapter_declared(
    "the reference adapter returns a complete FetchedItem and publishes no member "
    "manifest for this item"
)
MANIFEST = CompletenessEvidence.from_manifest(sorted(UPSTREAM))


def _stores(tmp_path: Path) -> tuple[ObjectStore, TofuPinStore, ReceiptStore]:
    return (
        ObjectStore(tmp_path / "cache"),
        TofuPinStore(tmp_path / "pins.json"),
        ReceiptStore(tmp_path / "receipts.json"),
    )


def _install(tmp_path: Path, **overrides: object):
    objects, pins, receipts = _stores(tmp_path)
    projector = _Projector(tmp_path / "harness")
    kwargs = dict(
        retrieve=_fetched,
        object_store=objects,
        pin_store=pins,
        receipt_store=receipts,
        transformation=IDENTITY_TRANSFORMATION,
        target="project_committed",
        activate=projector.activation,
        observed_at=NOW,
        completeness=MANIFEST,
    )
    kwargs.update(overrides)
    outcome = install_foreign_item(_item(), **kwargs)
    return outcome, objects, pins, receipts, projector


def test_partial_retrieval_leaves_no_object(tmp_path: Path) -> None:
    """A partial or truncated retrieval aborts before anything becomes visible (AC2)."""
    objects, pins, receipts = _stores(tmp_path)
    projector = _Projector(tmp_path / "harness")

    def truncated_transport() -> FetchedItem:
        raise ConnectionResetError("connection reset after 2 of 4 blobs")

    with pytest.raises(IncompleteRetrieval) as excinfo:
        install_foreign_item(
            _item(),
            retrieve=truncated_transport,
            object_store=objects,
            pin_store=pins,
            receipt_store=receipts,
            target="project_committed",
            activate=projector.activation,
            completeness=MANIFEST,
            observed_at=NOW,
        )
    assert excinfo.value.step == "retrieve"

    assert objects.objects() == ()
    assert objects.temporary_entries() == ()
    assert receipts.all() == ()
    assert pins.pins() == ()
    assert projector.activations == 0
    assert not projector.is_active

    # A write that dies mid-stream is the same fact one layer down: nothing
    # partial survives, and the next attempt does not have to clean up first.
    key = CacheKey(
        provider_identity=PROVIDER,
        upstream_id="kits/anchor",
        upstream_revision=None,
        normalized_content_digest=content_digest(UPSTREAM),
        library_type="skill",
        transformation_version=IDENTITY_TRANSFORMATION.version,
    )

    def truncated_stream() -> Iterator[tuple[str, bytes]]:
        yield "SKILL.md", UPSTREAM["SKILL.md"]
        raise ConnectionResetError("stream closed before the second file")

    with pytest.raises(ConnectionResetError):
        objects.materialize(key, truncated_stream(), created_at=NOW)

    assert not objects.path_for(key).exists()
    assert objects.objects() == ()
    assert objects.temporary_entries() == ()


def test_no_projection_before_receipt(tmp_path: Path) -> None:
    """A failure between materialization and receipt write activates nothing (AC3)."""

    class FailingReceiptStore(ReceiptStore):
        def put(self, receipt):  # type: ignore[override]
            raise OSError("no space left on device")

    objects, pins, _ = _stores(tmp_path)
    receipts = FailingReceiptStore(tmp_path / "receipts.json")
    projector = _Projector(tmp_path / "harness")

    with pytest.raises(TransactionAborted) as excinfo:
        install_foreign_item(
            _item(),
            retrieve=_fetched,
            object_store=objects,
            pin_store=pins,
            receipt_store=receipts,
            target="project_committed",
            activate=projector.activation,
            completeness=MANIFEST,
            observed_at=NOW,
        )
    assert excinfo.value.step == "receipt"

    assert projector.activations == 0, "no projection is activated without a receipt"
    assert not projector.is_active

    readable = ReceiptStore(tmp_path / "receipts.json")
    assert readable.all() == ()

    # The cache object is durable and is deliberately NOT rolled back: a failed
    # receipt write is not deletion authority over bytes that were retrieved and
    # verified. Slice 4 (CL-uliw) owns its retention and purge.
    assert len(objects.objects()) == 1


def test_projection_follows_a_durable_receipt(tmp_path: Path) -> None:
    """The happy path runs the ADR's five steps in the ADR's order."""
    outcome, objects, pins, receipts, projector = _install(tmp_path)

    assert outcome.events == (
        "retrieved",
        "first-use-pinned",
        "cache-object-materialized",
        "receipt-durable",
        "projection-activated",
    )
    assert outcome.events.index("receipt-durable") < outcome.events.index(
        "projection-activated"
    )
    assert projector.activations == 1
    assert (projector.root / "SKILL.md").read_bytes() == UPSTREAM["SKILL.md"]
    assert (projector.root / "agents" / "openai.yaml").exists()

    receipt = ReceiptStore(receipts.path).get(outcome.receipt.id)
    assert receipt is not None
    assert receipt.normalized_content_digest == content_digest(UPSTREAM)
    assert receipt.transformation_version == IDENTITY_TRANSFORMATION.version
    assert receipt.upstream_state == "present"
    assert receipt.cache_key_digest == outcome.cache_object.key.digest()
    assert len(receipt.targets) == 2
    assert receipt.verified

    # Every file of the item is cached, not only its marker file.
    assert objects.read_content(outcome.cache_object.key) == dict(UPSTREAM)
    assert pins.pin_for(f"{PROVIDER}#kits/anchor") is not None


def test_a_blocked_committed_projection_still_caches_and_receipts(tmp_path: Path) -> None:
    """`cache_state: verified` with a blocked committed target is a normal state."""
    unknown_redistribution = Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="unknown",
        evidence_source=MIT,
    )
    objects, pins, receipts = _stores(tmp_path)
    projector = _Projector(tmp_path / "harness")

    with pytest.raises(ProjectionRefused):
        install_foreign_item(
            _item(
                rights=unknown_redistribution,
                projection_eligibility={
                    "project_committed": "blocked",
                    "machine_local": "operator-opt-in-required",
                },
            ),
            retrieve=_fetched,
            object_store=objects,
            pin_store=pins,
            receipt_store=receipts,
            target="project_committed",
            activate=projector.activation,
            completeness=MANIFEST,
            observed_at=NOW,
        )

    assert projector.activations == 0
    # The bytes are lawfully fetched, verified, durable, and receipted. Only the
    # committed projection is refused.
    assert len(objects.objects()) == 1
    stored = ReceiptStore(receipts.path).all()
    assert len(stored) == 1
    assert stored[0].projection_eligibility["project_committed"] == "blocked"
    assert stored[0].targets == ()


def test_unadmitted_executable_content_is_cached_but_never_projected(tmp_path: Path) -> None:
    """Caching is not installing: an unreviewed executable reaches no harness path."""
    objects, pins, receipts = _stores(tmp_path)
    projector = _Projector(tmp_path / "harness")

    with pytest.raises(TransactionAborted) as excinfo:
        install_foreign_item(
            _item(
                library_type="workflow",
                library_name="anchor-flow",
                classification={},
                executable_admission="pending",
            ),
            retrieve=_fetched,
            object_store=objects,
            pin_store=pins,
            receipt_store=receipts,
            target="project_committed",
            activate=projector.activation,
            completeness=MANIFEST,
            observed_at=NOW,
            ledger=ExecutableAdmissionLedger(),
        )
    assert excinfo.value.step == "project"
    assert projector.activations == 0
    assert ReceiptStore(receipts.path).all()[0].executable_admission == "pending"


def test_a_failed_finalization_leaves_a_receipt_that_names_its_targets(
    tmp_path: Path,
) -> None:
    """An active projection is always described by a durable receipt (wave-1 F2).

    Recording the target inventory only after activation left a live projection
    behind a zero-target receipt when the finalizing write failed. The plan is
    now durable before the mutation, so the crash window records intent instead
    of hiding an installed target.
    """
    writes = {"count": 0}

    class FailAfterPlan(ReceiptStore):
        def put(self, receipt):  # type: ignore[override]
            writes["count"] += 1
            if writes["count"] == 3:  # install -> plan -> finalize
                raise OSError("no space left on device")
            return super().put(receipt)

    objects, pins, _ = _stores(tmp_path)
    receipts = FailAfterPlan(tmp_path / "receipts.json")
    projector = _Projector(tmp_path / "harness")

    with pytest.raises(OSError):
        install_foreign_item(
            _item(),
            retrieve=_fetched,
            object_store=objects,
            pin_store=pins,
            receipt_store=receipts,
            target="project_committed",
            activate=projector.activation,
            completeness=MANIFEST,
            observed_at=NOW,
        )

    assert projector.activations == 1, "the projection did happen"
    stored = ReceiptStore(tmp_path / "receipts.json").all()
    assert len(stored) == 1
    receipt = stored[0]
    assert not receipt.verified
    assert receipt.targets == ()
    # The paths that exist are exactly the paths the receipt declared it would
    # create, so nothing installed is unattributable.
    assert set(receipt.planned_targets) == {
        str(projector.root / path) for path in sorted(UPSTREAM)
    }
    assert all(Path(path).exists() for path in receipt.planned_targets)
    assert "projection-planned" in tuple(event.event for event in receipt.history)


def test_a_truncated_item_is_refused_against_its_manifest(tmp_path: Path) -> None:
    """A structurally valid fragment is not a complete item (wave-1 F3)."""
    objects, pins, receipts = _stores(tmp_path)
    projector = _Projector(tmp_path / "harness")

    with pytest.raises(IncompleteRetrieval) as excinfo:
        install_foreign_item(
            _item(),
            retrieve=lambda: _fetched({"SKILL.md": UPSTREAM["SKILL.md"]}),
            object_store=objects,
            pin_store=pins,
            receipt_store=receipts,
            target="project_committed",
            activate=projector.activation,
            completeness=MANIFEST,
            observed_at=NOW,
        )
    assert "agents/openai.yaml" in str(excinfo.value)
    assert objects.objects() == ()
    assert receipts.all() == ()
    assert pins.pins() == ()
    assert projector.activations == 0


def test_completeness_evidence_is_stated_and_recorded(tmp_path: Path) -> None:
    """The weakest completeness claim is named on the receipt, never implied."""
    with pytest.raises(TypeError):
        # No default: a caller has to say what it has.
        install_foreign_item(_item())  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="state why"):
        CompletenessEvidence.adapter_declared("   ")

    outcome, _, pins, receipts, _ = _install(tmp_path, completeness=ADAPTER_DECLARED)
    assert outcome.receipt.completeness_evidence == "adapter-declaration"

    # A second install of the same item is checked against the pin, which a
    # truncated retrieval cannot reproduce -- so the recorded evidence improves.
    second = install_foreign_item(
        _item(),
        retrieve=_fetched,
        object_store=ObjectStore(tmp_path / "cache"),
        pin_store=pins,
        receipt_store=receipts,
        target="project_committed",
        activate=_Projector(tmp_path / "harness2").activation,
        completeness=ADAPTER_DECLARED,
        observed_at=NOW,
    )
    assert second.receipt.completeness_evidence == "pinned-digest"

    with pytest.raises(TofuDriftError):
        install_foreign_item(
            _item(),
            retrieve=lambda: _fetched({"SKILL.md": UPSTREAM["SKILL.md"]}),
            object_store=ObjectStore(tmp_path / "cache"),
            pin_store=pins,
            receipt_store=receipts,
            target="project_committed",
            activate=_Projector(tmp_path / "harness3").activation,
            completeness=ADAPTER_DECLARED,
            observed_at=NOW,
        )


def test_admission_binds_the_projected_bytes(tmp_path: Path) -> None:
    """A decision is about the bytes that get installed (wave-1 F8).

    Review admitted an upstream digest, supplied a transformation producing
    different executable bytes, and installed successfully -- the reviewed
    content and the materialized content were never the same object.
    """
    from lib.providers.foreign_cache import Transformation

    rewriting = Transformation(
        version="harness-bridge/1",
        rule=lambda files: {path: content + b"# injected\n" for path, content in files.items()},
        description="append a line the reviewer never saw",
    )
    ledger = ExecutableAdmissionLedger()
    ledger.admit(
        f"{PROVIDER}#kits/anchor",
        content_digest(UPSTREAM),
        library_type="workflow",
        reviewer="malte",
        permission_surface=("read-only",),
        decided_at=NOW,
        evidence="reviewed the upstream bytes on 2026-08-09",
    )

    objects, pins, receipts = _stores(tmp_path)
    projector = _Projector(tmp_path / "harness")
    workflow = _item(library_type="workflow", library_name="anchor-flow", classification={})

    with pytest.raises(TransactionAborted) as excinfo:
        install_foreign_item(
            workflow,
            retrieve=_fetched,
            object_store=objects,
            pin_store=pins,
            receipt_store=receipts,
            target="project_committed",
            activate=projector.activation,
            completeness=MANIFEST,
            transformation=rewriting,
            observed_at=NOW,
            ledger=ledger,
        )
    assert excinfo.value.step == "project"
    assert projector.activations == 0
    stored = ReceiptStore(receipts.path).all()[0]
    assert stored.executable_admission == "pending"
    assert stored.projected_content_digest != stored.normalized_content_digest

    # Admitting the bytes that will actually be installed lets it through.
    ledger.admit(
        f"{PROVIDER}#kits/anchor",
        content_digest(rewriting.apply(UPSTREAM)),
        library_type="workflow",
        reviewer="malte",
        permission_surface=("read-only",),
        decided_at=NOW,
        evidence="reviewed the projected bytes on 2026-08-09",
    )
    outcome = install_foreign_item(
        workflow,
        retrieve=_fetched,
        object_store=objects,
        pin_store=pins,
        receipt_store=receipts,
        target="project_committed",
        activate=projector.activation,
        completeness=MANIFEST,
        transformation=rewriting,
        observed_at=NOW,
        ledger=ledger,
    )
    assert outcome.receipt.executable_admission == "admitted"
    assert projector.activations == 1


def test_drift_on_reinstall_never_overwrites_the_pinned_object(tmp_path: Path) -> None:
    """Fail-closed drift stops the transaction before any second object exists."""
    from lib.providers.foreign_cache import TofuDrift

    outcome, objects, pins, receipts, projector = _install(tmp_path)
    pinned_digest = outcome.cache_object.key.normalized_content_digest

    drifted = dict(UPSTREAM, **{"SKILL.md": b"substituted body\n"})
    with pytest.raises(TofuDrift) as excinfo:
        install_foreign_item(
            _item(),
            retrieve=lambda: _fetched(drifted),
            object_store=objects,
            pin_store=pins,
            receipt_store=receipts,
            target="project_committed",
            activate=projector.activation,
            completeness=MANIFEST,
            observed_at="2026-08-09T11:00:00Z",
        )
    assert excinfo.value.pinned_digest == pinned_digest
    assert excinfo.value.observed_digest == content_digest(drifted)
    assert len(objects.objects()) == 1, "no object is created for unpinned bytes"
    assert objects.read_content(outcome.cache_object.key)["SKILL.md"] == UPSTREAM["SKILL.md"]
    assert projector.activations == 1, "the drifted content never reached a target"
