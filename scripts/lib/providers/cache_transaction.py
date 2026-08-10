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

Four orderings inside steps 4 and 5 are decisions, not accidents:

- **The receipt is re-read from storage before anything is projected.** An
  in-memory object that a write never reached is exactly the state that produces
  an unreceipted projection, and it is indistinguishable from success unless
  somebody looks.
- **The receipt declares its intended targets before they exist.** Recording the
  target inventory only after activation leaves a window in which a live
  projection is described by a zero-target receipt; review injected a failure
  there and produced exactly that state. The plan is durable first, the mutation
  happens second, and the install-time proofs finalize the record third.
- **Executable admission is decided over the bytes that will be installed.** The
  transformation runs before the admission check, because a rule that rewrites
  content produces bytes no reviewer ever saw. The upstream digest stays the
  trust-on-first-use identity; the projected digest is what a decision is about.
- **A refused projection keeps its cache object and its receipt.** Caching is
  not installing: bytes that were lawfully fetched and verified stay durable and
  recorded even when no target may receive them. `cache_state: verified` beside
  a blocked committed projection is a normal state, not a contradiction.

**What completeness can and cannot be proven from.** A first retrieval's
completeness is not decidable from its own bytes: a truncated item is a valid
item of a different shape. It is therefore established one of three ways and the
way is recorded on the receipt -- against a member manifest the source supplied,
against an existing pin, or on nothing but the adapter's contract. The third is
recorded as `adapter-declaration` rather than left as an unnamed default, so
"we never checked" is a queryable fact instead of a silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .contract import FetchedItem
from .executable_admission import (
    ADMITTED,
    AdmissionAuthority,
    ExecutableAdmissionLedger,
    admission_refusal,
    is_executable_type,
)
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
from .inventory import NormalizedItem, ProviderAvailability
from .offline import (
    ResolutionEvidence,
    require_operation,
    status_freshness,
)
from .receipts import (
    COMPLETENESS_METHODS,
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
class ProjectionActivation:
    """A two-phase projection: declare the paths, then create them.

    A single "write it and tell me what you wrote" callable cannot be made
    recoverable, because the only record of what exists is produced after it
    already exists. Review injected a failure in exactly that window and found a
    live projection behind a zero-target receipt.

    `plan` answers "which paths am I about to touch" without touching them;
    `apply` performs the mutation and returns the targets with their
    install-time proofs. Both take the same projected content.

    A plan that does not bind the mutation is a plan in name only: review made
    `plan` return one path, `apply` create another, and failed the finalizing
    write. The receipt then described a path that did not exist while an
    unattributed file did. The transaction therefore checks that the applied
    targets are exactly the planned paths and records the actual ones before it
    refuses.
    """

    plan: Callable[[Mapping[str, bytes]], Sequence[str]]
    apply: Callable[[Mapping[str, bytes]], Sequence[ReceiptTarget]]

    def __post_init__(self) -> None:
        if not callable(self.plan) or not callable(self.apply):
            raise ValueError("a projection activation needs both a plan and an apply")


class ProjectionPlanViolated(TransactionAborted):
    """The activated targets are not the targets the receipt declared.

    Raised only after the receipt has been updated to describe what actually
    exists, so the divergence is recorded before it is reported. An unrecorded
    installed path is the failure; an honest record plus a loud refusal is the
    recovery.
    """

    def __init__(self, planned: Sequence[str], produced: Sequence[str]) -> None:
        super().__init__(
            "project",
            "the activation did not create the paths it declared. Declared "
            f"{sorted(planned)}; created {sorted(produced)}. The receipt now records "
            "what actually exists, and the projection is not accepted.",
        )
        self.planned = tuple(planned)
        self.produced = tuple(produced)


@dataclass(frozen=True)
class CompletenessEvidence:
    """How a retrieval's completeness was established, stated by the caller.

    There is no default. A caller has to say which of the three it has, because
    the weakest one is invisible when it is the fallback: review returned one
    file of a two-file item and the install pinned, cached, receipted, and
    projected the fragment without a word.
    """

    method: str
    expected_paths: tuple[str, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        if self.method not in COMPLETENESS_METHODS:
            raise ValueError(
                f"completeness method must be one of {list(COMPLETENESS_METHODS)}"
            )
        object.__setattr__(self, "expected_paths", tuple(self.expected_paths))
        if self.method == "member-manifest" and not self.expected_paths:
            raise ValueError("a member manifest names the item's expected members")
        if self.method == "adapter-declaration" and not self.detail.strip():
            raise ValueError(
                "an adapter declaration must state why no independent completeness "
                "evidence is available; it is the weakest claim in the vocabulary "
                "and it is not allowed to be the quiet one"
            )

    @classmethod
    def from_manifest(cls, paths: Sequence[str], detail: str = "") -> "CompletenessEvidence":
        return cls(method="member-manifest", expected_paths=tuple(paths), detail=detail)

    @classmethod
    def adapter_declared(cls, detail: str) -> "CompletenessEvidence":
        return cls(method="adapter-declaration", detail=detail)

    def check(self, fetched_paths: Sequence[str], identity: str) -> str:
        """Validate a retrieval against this evidence, or refuse it.

        Returns:
            The recorded completeness method. A pinned identity upgrades an
            adapter declaration to `pinned-digest`, because the digest
            comparison that follows is a real completeness proof.
        """
        if self.method != "member-manifest":
            return self.method
        expected = set(self.expected_paths)
        observed = set(fetched_paths)
        if expected != observed:
            missing = sorted(expected - observed)
            extra = sorted(observed - expected)
            raise IncompleteRetrieval(
                f"retrieval of {identity} does not match its member manifest: "
                f"missing {missing}, unexpected {extra}"
            )
        return self.method


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


def _admission_authority(ledger: Any) -> Any:
    """The admission authority for one install. Never the item's own claim.

    An omitted ledger used to mean "believe the item's `executable_admission`
    field", which made the *producer* of an item the authority over whether it
    may execute -- the exact substitution ADR-0011 forbids and that
    `admission.evaluate_item` already refuses. Review walked through it: an
    external `workflow` carrying `executable_admission="admitted"` installed and
    projected through this shared primitive with no ledger and no decision
    behind it.

    An omitted authority is now an **empty** one. Inert content is unaffected --
    it short-circuits before any record is consulted -- and an executable item
    resolves to `pending`, which is what "nobody decided" has to mean.
    """
    return ledger if ledger is not None else ExecutableAdmissionLedger()


def _executable_admission_state(
    item: NormalizedItem,
    ledger: ExecutableAdmissionLedger,
    installed_files: Mapping[str, bytes],
) -> str:
    """The admission state for the bytes that will actually be installed.

    `installed_files` is the **projected** content, not the upstream content.
    Review admitted an upstream digest, supplied a transformation that produced
    different executable bytes, and installed successfully: the decision and the
    mutation were about two different payloads, which is precisely the binding
    slice 2's gate exists to hold.
    """
    return ledger.state_for(
        item.qualified_identity(),
        normalized_content_digest(installed_files),
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
    activate: ProjectionActivation,
    observed_at: str,
    completeness: CompletenessEvidence,
    transformation: Transformation = IDENTITY_TRANSFORMATION,
    ledger: AdmissionAuthority | None = None,
    present: Callable[[Any], Any] | None = None,
) -> InstallOutcome:
    """Install or adopt one foreign item through the ordered transaction.

    Args:
        item: The normalized item, carrying its recorded rights and identity.
        retrieve: Produces the item's **complete** content, or raises.
        target: The projection target class this install is for.
        activate: Writes the projected bytes and returns the targets it created.
            Called at most once, only after the receipt is durable and its
            intended targets are on record.
        completeness: How this retrieval's completeness is established. Required,
            with no default, because the weakest option is exactly the one that
            disappears when it is implicit.
        transformation: The projection rule applied to upstream bytes. Its
            version is part of the cache key.
        ledger: The scope operator's executable-admission decisions. When given,
            the recorded state is recomputed from the **projected** bytes.
        present: Operator presenter for an opt-in-required projection.

    Raises:
        IncompleteRetrieval: when retrieval did not produce complete content.
        TofuDrift: when the content differs from the trust-on-first-use pin.
        TransactionAborted: when the receipt could not be made durable, or when
            an executable artifact has no admission decision for these bytes.
        ProjectionRefused: when the recorded rights do not permit this target.
    """
    if not isinstance(completeness, CompletenessEvidence):
        raise ValueError(
            "install requires stated completeness evidence; construct one with "
            "CompletenessEvidence.from_manifest(...) or .adapter_declared(...)"
        )
    if not isinstance(activate, ProjectionActivation):
        raise ValueError(
            "install requires a two-phase ProjectionActivation; a bare write "
            "callable cannot declare its targets before it creates them"
        )
    events: list[str] = []
    identity = item.qualified_identity()

    # The trust decision, the materialization, the receipt, and the activation
    # are one transaction for this identity. Serializing only the pin write left
    # a window review walked through: an install verified the old pin, a re-pin
    # moved the identity to different bytes, and the install then activated the
    # old ones under the new pin.
    with pin_store.identity_lock(identity):
        return _install_locked(
            item,
            retrieve=retrieve,
            object_store=object_store,
            pin_store=pin_store,
            receipt_store=receipt_store,
            target=target,
            activate=activate,
            observed_at=observed_at,
            completeness=completeness,
            transformation=transformation,
            ledger=ledger,
            present=present,
            events=events,
            identity=identity,
        )


def _install_locked(
    item: NormalizedItem,
    *,
    retrieve: Callable[[], FetchedItem],
    object_store: ObjectStore,
    pin_store: TofuPinStore,
    receipt_store: ReceiptStore,
    target: str,
    activate: ProjectionActivation,
    observed_at: str,
    completeness: CompletenessEvidence,
    transformation: Transformation,
    ledger: AdmissionAuthority | None,
    present: Callable[[Any], Any] | None,
    events: list[str],
    identity: str,
) -> InstallOutcome:
    """The ordered transaction, under this identity's serialization lock."""
    # 1. Retrieve complete content, and check it against the stated evidence.
    fetched = _retrieve(retrieve, item)
    upstream_files = _fetched_files(fetched)
    completeness_method = completeness.check(sorted(upstream_files), identity)
    events.append("retrieved")

    # 2. Verify against the pin, or record the first-use pin. A revisionless
    #    source is pin-only, so its pin is the only continuity it has; a pinned
    #    revision is still digest-checked, because a revision identity says which
    #    bytes were asked for and not which bytes arrived.
    digest = normalized_content_digest(upstream_files)
    pin: TofuPin | None = None
    if item.upstream_revision is None:
        existing_pin = pin_store.pin_for(identity)
        pin, first_use = pin_store.verify_or_pin(identity, digest, observed_at=observed_at)
        if existing_pin is not None and completeness_method == "adapter-declaration":
            # A digest that matched an existing pin *is* a completeness proof:
            # a truncated item cannot reproduce the pinned digest.
            completeness_method = "pinned-digest"
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
    authority = _admission_authority(ledger)
    with authority.decisions() as standing:
        admission_state = _executable_admission_state(item, standing, projected_files)
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
        projected_content_digest=cache_object.projected_content_digest,
        completeness_evidence=completeness_method,
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
    if item.upstream_revision is None:
        # Re-verify immediately before the receipt becomes durable. The identity
        # lock already serializes a competing re-pin, and this is the second
        # half of the same guarantee: what the receipt records is what the pin
        # says at the moment it is written, not what it said when we fetched.
        pin_store.verify(identity, digest)

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
        # The remedy is rendered from the CLI's own words rather than written
        # out here. Until `CL-2wqz` this refusal named the state and stopped,
        # which was accurate and a dead end: no command existed that could
        # change the answer, so the artifact was refused permanently.
        raise TransactionAborted(
            "project",
            admission_refusal(
                identity,
                normalized_content_digest(projected_files),
                item.library_type,
                admission_state,
            ),
        )

    decision = evaluate_projection(item.rights, target, subject=identity)
    created: list[ReceiptTarget] = []

    def _activate_under_the_standing_decision() -> tuple[ReceiptTarget, ...]:
        """Write only while the decision that authorized the write still stands.

        The check above reads a decision and the write happens later, and review
        walked through the gap: a `deny` for these exact bytes was recorded and
        returned success while this install was still retrieving, and the
        artifact was projected anyway on the grant read on the way in. An
        operator whose denial completed had every reason to believe it had taken
        effect.

        Re-reading is not enough on its own, because a re-read is another check
        with another gap after it. The decisions are therefore held still across
        the activation itself, which is the only window where the difference is
        observable. Inert content skips all of it: no decision governs it, so
        there is nothing to hold still.
        """
        if not is_executable_type(item.library_type):
            return tuple(activate.apply(projected_files))
        with authority.decisions() as decisions:
            state_now = _executable_admission_state(item, decisions, projected_files)
            if state_now != ADMITTED:
                raise TransactionAborted(
                    "project",
                    admission_refusal(
                        identity,
                        normalized_content_digest(projected_files),
                        item.library_type,
                        state_now,
                    ),
                )
            return tuple(activate.apply(projected_files))

    def _mutate() -> tuple[ReceiptTarget, ...]:
        # The intent is durable before the mutation. A crash after activation
        # and before finalization then leaves a receipt that already names the
        # paths it was about to create, instead of an installed target that no
        # receipt describes.
        planned = tuple(str(path) for path in activate.plan(projected_files))
        planned_receipt = receipt_store.put(
            durable.with_event(
                ReceiptEvent(
                    event="projection-planned",
                    recorded_at=observed_at,
                    detail=(
                        f"declared {len(planned)} intended target path(s) for {target} "
                        "before activating anything"
                    ),
                ),
                planned_targets=list(planned),
            )
        )
        produced = _activate_under_the_standing_decision()
        created.extend(produced)
        produced_paths = tuple(entry.path for entry in produced)
        divergent = set(produced_paths) != set(planned)
        receipt_store.put(
            planned_receipt.with_event(
                ReceiptEvent(
                    event="projection-plan-violated" if divergent else "projection-activated",
                    recorded_at=observed_at,
                    detail=(
                        (
                            "the activation created paths other than the ones it "
                            f"declared; recording {len(produced)} actual target(s) so "
                            "nothing installed is unattributable"
                        )
                        if divergent
                        else (
                            f"{len(produced)} target(s) activated for {target} after "
                            "the cache object, the receipt, and the declared target "
                            "plan were durable"
                        )
                    ),
                ),
                targets=[entry.to_dict() for entry in produced],
                planned_targets=sorted({*planned, *produced_paths}),
                verified=bool(produced) and not divergent,
            )
        )
        if divergent:
            raise ProjectionPlanViolated(planned, produced_paths)
        return produced

    outcome = project(decision, _mutate, present=present)
    events.append("projection-activated")

    receipt = receipt_store.get(durable.id) or durable
    return InstallOutcome(
        receipt=receipt,
        cache_object=cache_object,
        events=tuple(events),
        pin=pin,
        projection=outcome,
    )


def _repair_under_the_standing_decision(
    receipt: ForeignReceipt,
    ledger: AdmissionAuthority | None,
    content: Mapping[str, bytes],
    *,
    activate: ProjectionActivation,
) -> tuple[ReceiptTarget, ...]:
    """Write a repaired projection only while its admission decision stands.

    The decision is re-derived from the **verified cached content**, not read
    off the receipt: `receipt.executable_admission` records what was decided
    when the projection was installed, and the whole point of this check is that
    the answer may have changed since. As on the install path, the decisions are
    held still across the activation, so a denial recorded during the repair
    either lands before the write and refuses it or waits for a write that was
    authorized while it happened.
    """
    if not is_executable_type(receipt.library_type):
        return tuple(activate.apply(content))
    authority = _admission_authority(ledger)
    identity = receipt.qualified_identity()
    with authority.decisions() as decisions:
        state_now = decisions.state_for(
            identity,
            normalized_content_digest(content),
            library_type=receipt.library_type,
        )
        if state_now != ADMITTED:
            raise TransactionAborted(
                "project",
                admission_refusal(
                    identity,
                    normalized_content_digest(content),
                    receipt.library_type,
                    state_now,
                ),
            )
        return tuple(activate.apply(content))


def reinstall_from_cache(
    *,
    receipt: ForeignReceipt,
    object_store: ObjectStore,
    receipt_store: ReceiptStore,
    availability: ProviderAvailability | ResolutionEvidence,
    activate: ProjectionActivation,
    observed_at: str,
    ledger: AdmissionAuthority | None = None,
) -> ReinstallOutcome:
    """Repair a projection from the verified cache, with no remote claim.

    Allowed while the source is unreachable: the bytes are present, they are
    verified locally, and nothing about the source is asserted. The returned
    freshness is a separate fact from the returned integrity, and it is never
    `current` for an unreachable source.

    The object is read **once**. The snapshot that was digested is the snapshot
    that is installed, because review substituted the stored file between a
    successful `verify` and the read that produced the installed bytes.

    **Repair is an executable write, and admission governs it.** Cache integrity
    proves which bytes are present; it says nothing about whether the operator
    currently admits them. Review granted a workflow, installed it, superseded
    the grant with a refusal, deleted the projection, and repaired: the refused
    bytes were written back while the ledger still answered `refused`. Repair is
    the write path an enforcement check written for `install` quietly misses --
    it makes no remote claim and reads as recovery -- which is the same reason
    `CL-m6cc` had to add the re-materialization block here separately.

    Raises:
        TransactionAborted: when the cache object fails verification, or when the
            standing admission decision for these exact bytes is not `admitted`.
            A repair that installs unverified or unadmitted bytes is the
            substitution this whole slice exists to prevent.
    """
    require_operation("reinstall-from-cache", availability)
    if not isinstance(activate, ProjectionActivation):
        raise ValueError(
            "reinstall requires a two-phase ProjectionActivation; a repair that "
            "cannot declare its targets first is not recoverable either"
        )
    observation = availability if isinstance(availability, ResolutionEvidence) else None
    observed_availability = (
        observation.availability if observation is not None else availability
    )
    key = cache_key_for_receipt(receipt)
    content, integrity = object_store.read_verified(key)
    if not integrity.verified:
        raise TransactionAborted(
            "verify",
            f"cache object for {receipt.qualified_identity()} failed verification: "
            f"{integrity.detail}",
        )

    planned = tuple(str(path) for path in activate.plan(content))
    planned_receipt = receipt_store.put(
        receipt.with_event(
            ReceiptEvent(
                event="projection-planned",
                recorded_at=observed_at,
                detail=(
                    f"declared {len(planned)} intended target path(s) before repairing "
                    f"from cache object {key.digest()}"
                ),
            ),
            planned_targets=list(planned),
        )
    )
    targets = _repair_under_the_standing_decision(
        receipt, ledger, content, activate=activate
    )
    produced_paths = tuple(entry.path for entry in targets)
    divergent = set(produced_paths) != set(planned)
    updated = receipt_store.put(
        planned_receipt.with_event(
            ReceiptEvent(
                event="projection-plan-violated" if divergent else "reinstalled-from-cache",
                recorded_at=observed_at,
                detail=(
                    (
                        "the repair created paths other than the ones it declared; "
                        f"recording {len(targets)} actual target(s) so nothing "
                        "installed is unattributable"
                    )
                    if divergent
                    else (
                        f"reinstalled {len(targets)} target(s) from verified cache "
                        f"object {key.digest()}; no remote claim was made"
                    )
                ),
                provider_state=(
                    f"source state {observed_availability.state!r} at "
                    f"{observed_availability.observed_at}"
                ),
            ),
            targets=[entry.to_dict() for entry in targets],
            planned_targets=sorted({*planned, *produced_paths}),
            verified=bool(targets) and not divergent,
            provider_availability=observed_availability.to_dict(),
        )
    )
    if divergent:
        raise ProjectionPlanViolated(planned, produced_paths)
    availability = observed_availability
    return ReinstallOutcome(
        receipt=updated,
        integrity=integrity,
        freshness=status_freshness(
            availability, revisionless=receipt.upstream_revision is None
        ),
        targets=targets,
    )


def cache_status(
    *,
    receipt: ForeignReceipt,
    object_store: ObjectStore,
    availability: ProviderAvailability | ResolutionEvidence,
) -> StatusReport:
    """Report local integrity and remote freshness as two separate facts."""
    require_operation("status", availability)
    observed = (
        availability.availability
        if isinstance(availability, ResolutionEvidence)
        else availability
    )
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
            observed, revisionless=receipt.upstream_revision is None
        ),
        upstream_state=receipt.upstream_state,
        provider_state=(
            f"source state {observed.state!r} observed at {observed.observed_at}"
        ),
        detail=detail,
    )


__all__ = [
    "TRANSACTION_STEPS",
    "CompletenessEvidence",
    "IncompleteRetrieval",
    "InstallOutcome",
    "ProjectionActivation",
    "ProjectionPlanViolated",
    "ReinstallOutcome",
    "StatusReport",
    "TransactionAborted",
    "cache_key_for",
    "cache_key_for_receipt",
    "cache_status",
    "install_foreign_item",
    "reinstall_from_cache",
]
