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
    IncompleteRetrieval,
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
    def is_active(self) -> bool:
        return any(self.root.rglob("*")) if self.root.exists() else False


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
        activate=projector,
        observed_at=NOW,
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
            activate=projector,
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
            activate=projector,
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
            activate=projector,
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
            activate=projector,
            observed_at=NOW,
            ledger=ExecutableAdmissionLedger(),
        )
    assert excinfo.value.step == "project"
    assert projector.activations == 0
    assert ReceiptStore(receipts.path).all()[0].executable_admission == "pending"


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
            activate=projector,
            observed_at="2026-08-09T11:00:00Z",
        )
    assert excinfo.value.pinned_digest == pinned_digest
    assert excinfo.value.observed_digest == content_digest(drifted)
    assert len(objects.objects()) == 1, "no object is created for unpinned bytes"
    assert objects.read_content(outcome.cache_object.key)["SKILL.md"] == UPSTREAM["SKILL.md"]
    assert projector.activations == 1, "the drifted content never reached a target"
