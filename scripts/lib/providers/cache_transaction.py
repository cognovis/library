"""The ordered install/adoption transaction (ADR-0011 `Cache Transaction`).

Ordered, and the order is the contract:

1. **Retrieve** complete content. A partial or truncated retrieval aborts here.
2. **Verify** the normalized digest against the pin, or record the first-use pin.
3. **Materialize atomically** into the cache.
4. **Write the receipt**, including rights, admission, transformation identity,
   and the cache digest.
5. **Only then activate target projections.**

No harness projection becomes active before its cache object and receipt are
complete. The historic failure this prevents is a live projection whose bytes
cannot be reproduced once its source disappears -- which is the present state of
four materialized workflow projections carrying zero receipts.

Two orderings inside step 5 are decisions, not accidents:

- **The receipt is re-read from storage before anything is projected.** An
  in-memory object that a write never reached is exactly the state that produces
  an unreceipted projection, and it is indistinguishable from success unless
  somebody looks.
- **A refused projection keeps its cache object and its receipt.** Caching is
  not installing: bytes that were lawfully fetched and verified stay durable and
  recorded even when no target may receive them. `cache_state: verified` beside
  a blocked committed projection is a normal state, not a contradiction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .contract import FetchedItem
from .executable_admission import ExecutableAdmissionLedger
from .foreign_cache import (
    IDENTITY_TRANSFORMATION,
    CacheKey,
    CacheObject,
    IntegrityReport,
    ObjectStore,
    TofuPin,
    TofuPinStore,
    Transformation,
    normalized_content_digest,
)
from .inventory import NormalizedItem
from .offline import require_operation, status_freshness
from .receipts import (
    ForeignReceipt,
    ReceiptEvent,
    ReceiptStore,
    ReceiptTarget,
)
from .rights import ProjectionOutcome, evaluate_projection, project

#: The ordered steps. A failure names the step it stopped at, so an operator
#: reads how far the transaction got without reconstructing it from side effects.
TRANSACTION_STEPS: tuple[str, ...] = (
    "retrieve",
    "verify",
    "materialize",
    "receipt",
    "project",
)


class TransactionAborted(RuntimeError):
    """The transaction stopped at a named step, before the steps after it."""

    def __init__(self, step: str, detail: str, cause: BaseException | None = None) -> None:
        if step not in TRANSACTION_STEPS:
            raise ValueError(f"unknown transaction step: {step!r}")
        super().__init__(f"install aborted at step {step!r}: {detail}")
        self.step = step
        self.detail = detail
        self.cause = cause


class IncompleteRetrieval(TransactionAborted):
    """Retrieval did not produce complete content, so nothing else happened.

    Completeness is the adapter's obligation: `FetchedItem` is defined as an
    item's complete content, and an adapter that cannot produce it raises rather
    than returning what it managed to read. This type is where that failure
    becomes a transaction outcome instead of a half-installed item.
    """

    def __init__(self, detail: str, cause: BaseException | None = None) -> None:
        super().__init__("retrieve", detail, cause)


@dataclass(frozen=True)
class InstallOutcome:
    """What one completed install produced, in the order it produced it."""

    receipt: ForeignReceipt
    cache_object: CacheObject
    events: tuple[str, ...]
    pin: TofuPin | None = None
    projection: ProjectionOutcome | None = None


@dataclass(frozen=True)
class ReinstallOutcome:
    """One repair from the cache, with its two separate reported facts."""

    receipt: ForeignReceipt
    integrity: IntegrityReport
    freshness: str
    targets: tuple[ReceiptTarget, ...]


@dataclass(frozen=True)
class StatusReport:
    """Local integrity and remote freshness, reported separately.

    ADR-0011 is explicit that these are never merged into one "ok". A single
    aggregate value is how a verified local copy of unknown currency starts
    being presented as current.
    """

    local_integrity: str
    freshness: str
    upstream_state: str
    provider_state: str
    detail: str

    def describe(self) -> str:
        return (
            f"local integrity: {self.local_integrity}; remote freshness: "
            f"{self.freshness}; upstream: {self.upstream_state}; {self.provider_state}"
        )


def cache_key_for(item: NormalizedItem, digest: str, transformation: Transformation) -> CacheKey:
    """The ADR-0011 cache identity for one normalized item's content."""
    return CacheKey(
        provider_identity=item.provider_identity,
        upstream_id=item.upstream_id,
        upstream_revision=item.upstream_revision,
        normalized_content_digest=digest,
        library_type=item.library_type,
        transformation_version=transformation.version,
    )


def cache_key_for_receipt(receipt: ForeignReceipt) -> CacheKey:
    """Rebuild the cache identity a receipt records.

    A receipt carries the whole tuple precisely so a repair never has to consult
    the source to find its own bytes.
    """
    return CacheKey(
        provider_identity=receipt.provider_identity,
        upstream_id=receipt.upstream_id,
        upstream_revision=receipt.upstream_revision,
        normalized_content_digest=receipt.normalized_content_digest,
        library_type=receipt.library_type,
        transformation_version=receipt.transformation_version,
    )


def receipt_id_for(item: NormalizedItem, key: CacheKey) -> str:
    return f"{item.library_type}:{item.library_name}@{key.digest()[:16]}"


def _fetched_files(fetched: FetchedItem) -> dict[str, bytes]:
    return {entry.path: entry.content for entry in fetched.files}


def _retrieve(retrieve: Callable[[], FetchedItem], item: NormalizedItem) -> FetchedItem:
    try:
        fetched = retrieve()
    except Exception as exc:  # noqa: BLE001 - every transport failure is the same fact here
        raise IncompleteRetrieval(
            f"retrieval of {item.qualified_identity()} did not complete: {exc}", exc
        ) from exc
    if not isinstance(fetched, FetchedItem):
        raise IncompleteRetrieval(
            "retrieval must produce a complete FetchedItem; a mapping or a partial "
            "listing cannot state whether the item is whole"
        )
    if fetched.upstream_id != item.upstream_id:
        raise IncompleteRetrieval(
            f"retrieval returned {fetched.upstream_id!r} for {item.upstream_id!r}; "
            "content that belongs to another item is not this item's content"
        )
    if item.upstream_revision is not None and fetched.revision != item.upstream_revision:
        raise IncompleteRetrieval(
            f"retrieval returned revision {fetched.revision!r} for pinned revision "
            f"{item.upstream_revision!r}; a caller that pins a revision never "
            "silently gets a different one"
        )
    return fetched


def _executable_admission_state(
    item: NormalizedItem,
    ledger: ExecutableAdmissionLedger | None,
    files: Mapping[str, bytes],
) -> str:
    if ledger is None:
        return item.executable_admission
    return ledger.state_for(
        item.qualified_identity(),
        normalized_content_digest(files),
        library_type=item.library_type,
    )


def install_foreign_item(
    item: NormalizedItem,
    *,
    retrieve: Callable[[], FetchedItem],
    object_store: ObjectStore,
    pin_store: TofuPinStore,
    receipt_store: ReceiptStore,
    target: str,
    activate: Callable[[Mapping[str, bytes]], Sequence[ReceiptTarget]],
    observed_at: str,
    transformation: Transformation = IDENTITY_TRANSFORMATION,
    ledger: ExecutableAdmissionLedger | None = None,
    present: Callable[[Any], Any] | None = None,
) -> InstallOutcome:
    """Install or adopt one foreign item through the ordered transaction.

    Args:
        item: The normalized item, carrying its recorded rights and identity.
        retrieve: Produces the item's **complete** content, or raises.
        target: The projection target class this install is for.
        activate: Writes the projected bytes and returns the targets it created.
            Called at most once, only after the receipt is durable.
        transformation: The projection rule applied to upstream bytes. Its
            version is part of the cache key.
        ledger: The scope operator's executable-admission decisions. When given,
            the recorded state is recomputed from the retrieved bytes rather
            than trusted from the item.
        present: Operator presenter for an opt-in-required projection.

    Raises:
        IncompleteRetrieval: when retrieval did not produce complete content.
        TofuDrift: when the content differs from the trust-on-first-use pin.
        TransactionAborted: when the receipt could not be made durable, or when
            an executable artifact has no admission decision for these bytes.
        ProjectionRefused: when the recorded rights do not permit this target.
    """
    events: list[str] = []
    identity = item.qualified_identity()

    # 1. Retrieve complete content.
    fetched = _retrieve(retrieve, item)
    upstream_files = _fetched_files(fetched)
    events.append("retrieved")

    # 2. Verify against the pin, or record the first-use pin. A revisionless
    #    source is pin-only, so its pin is the only continuity it has; a pinned
    #    revision is still digest-checked, because a revision identity says which
    #    bytes were asked for and not which bytes arrived.
    digest = normalized_content_digest(upstream_files)
    pin: TofuPin | None = None
    if item.upstream_revision is None:
        pin, first_use = pin_store.verify_or_pin(identity, digest, observed_at=observed_at)
        events.append("first-use-pinned" if first_use else "content-verified")
    else:
        events.append("content-verified")

    # 3. Materialize atomically.
    key = cache_key_for(item, digest, transformation)
    projected_files = transformation.apply(upstream_files)
    try:
        cache_object = object_store.materialize(
            key, projected_files, created_at=observed_at
        )
    except Exception as exc:  # noqa: BLE001 - the step is the diagnostic
        raise TransactionAborted(
            "materialize", f"cache object for {identity} was not written: {exc}", exc
        ) from exc
    events.append("cache-object-materialized")

    # 4. Write the receipt, and prove it is durable by reading it back.
    admission_state = _executable_admission_state(item, ledger, upstream_files)
    receipt = ForeignReceipt(
        id=receipt_id_for(item, key),
        provider_identity=item.provider_identity,
        upstream_id=item.upstream_id,
        upstream_name=item.upstream_name,
        collection_membership=item.collection_membership,
        upstream_revision=item.upstream_revision,
        normalized_content_digest=digest,
        transformation_version=transformation.version,
        library_type=item.library_type,
        library_name=item.library_name,
        cache_key_digest=key.digest(),
        cache_path=str(cache_object.path),
        install_timestamp=observed_at,
        rights=item.rights,
        executable_admission=admission_state,
        projection_eligibility=item.projection_eligibility,
        provider_availability=item.provider_availability,
        upstream_state="present",
        verified=False,
        targets=(),
        history=(
            ReceiptEvent(
                event="installed",
                recorded_at=observed_at,
                detail=(
                    f"cache object {key.digest()} materialized under transformation "
                    f"{transformation.version} at {cache_object.path}"
                ),
                provider_state=(
                    f"source state {item.provider_availability.state!r} at "
                    f"{item.provider_availability.observed_at}"
                ),
            ),
        ),
    )
    try:
        receipt_store.put(receipt)
        durable = receipt_store.get(receipt.id)
    except Exception as exc:  # noqa: BLE001 - the step is the diagnostic
        raise TransactionAborted(
            "receipt", f"receipt for {identity} was not written: {exc}", exc
        ) from exc
    if durable is None:
        raise TransactionAborted(
            "receipt",
            f"receipt for {identity} did not survive the write; no projection is "
            "activated without one",
        )
    events.append("receipt-durable")

    # 5. Only then activate the projection.
    if admission_state in ("pending", "refused"):
        raise TransactionAborted(
            "project",
            f"{identity} is an executable artifact whose admission state is "
            f"{admission_state!r} for these exact bytes. The content is cached and "
            "receipted; caching is not installing, and no harness path receives it "
            "until the scope operator decides.",
        )

    decision = evaluate_projection(item.rights, target, subject=identity)
    created: list[ReceiptTarget] = []

    def _mutate() -> tuple[ReceiptTarget, ...]:
        produced = tuple(activate(projected_files))
        created.extend(produced)
        return produced

    outcome = project(decision, _mutate, present=present)
    events.append("projection-activated")

    receipt = receipt_store.put(
        durable.with_event(
            ReceiptEvent(
                event="projection-activated",
                recorded_at=observed_at,
                detail=(
                    f"{len(created)} target(s) activated for {target} after the cache "
                    "object and receipt were complete"
                ),
            ),
            targets=[entry.to_dict() for entry in created],
            verified=bool(created),
        )
    )
    return InstallOutcome(
        receipt=receipt,
        cache_object=cache_object,
        events=tuple(events),
        pin=pin,
        projection=outcome,
    )


def reinstall_from_cache(
    *,
    receipt: ForeignReceipt,
    object_store: ObjectStore,
    receipt_store: ReceiptStore,
    availability,
    activate: Callable[[Mapping[str, bytes]], Sequence[ReceiptTarget]],
    observed_at: str,
) -> ReinstallOutcome:
    """Repair a projection from the verified cache, with no remote claim.

    Allowed while the source is unreachable: the bytes are present, they are
    verified locally, and nothing about the source is asserted. The returned
    freshness is a separate fact from the returned integrity, and it is never
    `current` for an unreachable source.

    Raises:
        TransactionAborted: when the cache object fails verification. A repair
            that installs unverified bytes is the substitution this whole slice
            exists to prevent.
    """
    require_operation("reinstall-from-cache", availability)
    key = cache_key_for_receipt(receipt)
    integrity = object_store.verify(key)
    if not integrity.verified:
        raise TransactionAborted(
            "verify",
            f"cache object for {receipt.qualified_identity()} failed verification: "
            f"{integrity.detail}",
        )

    content = object_store.read_content(key)
    targets = tuple(activate(content))
    updated = receipt_store.put(
        receipt.with_event(
            ReceiptEvent(
                event="reinstalled-from-cache",
                recorded_at=observed_at,
                detail=(
                    f"reinstalled {len(targets)} target(s) from verified cache object "
                    f"{key.digest()}; no remote claim was made"
                ),
                provider_state=(
                    f"source state {availability.state!r} at {availability.observed_at}"
                ),
            ),
            targets=[entry.to_dict() for entry in targets],
            verified=bool(targets),
            provider_availability=availability.to_dict(),
        )
    )
    return ReinstallOutcome(
        receipt=updated,
        integrity=integrity,
        freshness=status_freshness(
            availability, revisionless=receipt.upstream_revision is None
        ),
        targets=targets,
    )


def cache_status(
    *, receipt: ForeignReceipt, object_store: ObjectStore, availability
) -> StatusReport:
    """Report local integrity and remote freshness as two separate facts."""
    require_operation("status", availability)
    key = cache_key_for_receipt(receipt)
    try:
        integrity = object_store.verify(key)
        local = "verified" if integrity.verified else "failed"
        detail = integrity.detail
    except KeyError:
        local = "absent"
        detail = f"no cache object for {receipt.qualified_identity()} at {key.digest()}"
    return StatusReport(
        local_integrity=local,
        freshness=status_freshness(
            availability, revisionless=receipt.upstream_revision is None
        ),
        upstream_state=receipt.upstream_state,
        provider_state=(
            f"source state {availability.state!r} observed at {availability.observed_at}"
        ),
        detail=detail,
    )


__all__ = [
    "TRANSACTION_STEPS",
    "IncompleteRetrieval",
    "InstallOutcome",
    "ReinstallOutcome",
    "StatusReport",
    "TransactionAborted",
    "cache_key_for",
    "cache_key_for_receipt",
    "cache_status",
    "install_foreign_item",
    "reinstall_from_cache",
]
