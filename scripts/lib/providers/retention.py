"""Retention, re-fetchability-aware garbage collection, and operator purge.

ADR-0011 `Retention, Garbage Collection, and Explicit Purge` gives automatic
collection **two** retention inputs, and the second one is the one that gets
lost:

1. an object referenced by any active receipt in **any** scope is ineligible;
2. re-fetchability must be **proven**, not inferred from provider health.

A cache that discards unreferenced objects while its source is degraded
discards exactly the bytes that cannot be retrieved again, at exactly the moment
they became irreplaceable. So collection here fails closed whenever any of these
holds: the source is unavailable or only partially answering, access was
revoked, the upstream item no longer exists, or the object came from a
revisionless source and no digest-verified re-fetch proves the pinned digest is
still what the source serves.

**The revisionless clause is not an edge case.** A revisionless source is
pin-only: it can be reachable, authorized, still listing the item, and serving
*different bytes* than the pin. Deleting under "the source looks healthy" would
destroy the last copy of the pinned content, and a later reinstall would record
a fresh first-use pin -- converting detectable drift into undetectable silent
substitution. The same reasoning extends one step: an install whose only
completeness evidence is `adapter-declaration` never had independent proof of
what it stored, so it is treated exactly like a revisionless one.

**Two deliberate boundary decisions**, stated because both directions are
defensible:

- *Quarantined objects are never garbage.* A repair sets a damaged object aside
  as retained evidence. Automatic collection never sees it and never removes it.
  An operator holding its digest may destroy it, but only by naming it: a purge
  removes quarantined siblings solely when `include_quarantined` is passed, so
  reclaiming space can never silently destroy the evidence of a corruption.
- *Deletion lives here, not in `ObjectStore`.* Slice 3 deliberately shipped a
  store with no delete path. Deleting bytes is a retention decision, not a
  storage operation, and keeping the only deletion behind these gates is what
  makes "the cache never deletes on its own" checkable rather than asserted.

`purge_object` is reachable from no code path in this module's collection
entry points. That is asserted structurally by the test suite, not just by the
paths one run happens to exercise.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .executable_admission import validated_digest
from .foreign_cache import QUARANTINE_SUFFIX, CacheKey, CacheObject, ObjectStore, TofuPinStore
from .inventory import parse_qualified_identity
from .offline import ResolutionEvidence, evaluate_operation
from .receipts import ForeignReceipt, ReceiptStore
from .state_files import atomic_write_text, exclusive_lock

#: A cache-object digest is the `CacheKey.digest()` value: 64 lowercase hex
#: characters and nothing else. It is deliberately a different shape from a
#: content digest, which carries an algorithm prefix.
OBJECT_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

#: The scopes a reference check must cover. ADR-0011 says "any active receipt in
#: any scope", and the failure that phrase prevents is a project-scoped
#: maintenance run collecting an object the global lock still references. The
#: set is required rather than merely supported, so a caller that supplies one
#: store gets a refusal instead of a confident wrong answer.
REQUIRED_SCOPES: tuple[str, ...] = ("project", "global")

#: Every reason automatic collection retains an object, in precedence order. A
#: refusal names the condition, because "not collected" is not an answer an
#: operator can act on.
RETENTION_REFUSALS: tuple[str, ...] = (
    "referenced-by-active-receipt",
    "provider-not-observed",
    "provider-unavailable",
    "access-revoked",
    "inventory-incomplete",
    "upstream-vanished",
    "refetch-digest-drift",
    "re-fetchability-not-proven",
)

#: The exact acknowledgement an operator records before bytes are destroyed.
#: A fixed token rather than free prose: the whole point is that the operator
#: states *this* understanding, and removing the requirement has to be a visible
#: edit rather than an extra default argument.
PURGE_ACKNOWLEDGEMENT = "permanent-loss-may-not-be-refetchable"

#: Every reason a purge refuses.
PURGE_REFUSALS: tuple[str, ...] = (
    "not-an-object-digest",
    "no-such-object",
    "acknowledgement-missing",
    "acknowledgement-incomplete",
    "referenced-by-active-receipt",
    "not-operator-explicit",
)

#: The one origin a purge accepts. Automatic reconciliation and garbage
#: collection are refused here as well as structurally, so a future caller
#: cannot obtain through this door what fail-closed collection denied it.
OPERATOR_EXPLICIT = "operator-explicit"

PURGE_LEDGER_SCHEMA = "cognovis.cache-purge-ledger.v1"

#: Completeness evidence that independently proves what was stored. Anything
#: else -- including nothing at all -- needs a digest-verified re-fetch before
#: automatic collection may delete.
PROVEN_COMPLETENESS: frozenset[str] = frozenset({"member-manifest", "pinned-digest"})


class ScopeUnreadable(RuntimeError):
    """A receipt scope could not be read, so "unreferenced" cannot be concluded.

    An unreadable scope and an empty scope are the same silence and opposite
    facts. Treating the first as the second is how a maintenance run deletes an
    object the unreadable scope was referencing.
    """


class RetentionError(RuntimeError):
    """A deletion was asked to act outside the cache it belongs to."""


class PurgeRefused(RuntimeError):
    """One refused purge, carrying its typed reason."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"purge is refused [{reason}]: {detail}")
        self.reason = reason
        self.detail = detail


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value


# -- reference checking across scopes ----------------------------------------


@dataclass(frozen=True)
class ReceiptScope:
    """One named receipt store participating in the reference check."""

    name: str
    store: ReceiptStore

    def __post_init__(self) -> None:
        _text(self.name, "ReceiptScope.name")
        if not isinstance(self.store, ReceiptStore):
            raise ValueError("a receipt scope holds a validated ReceiptStore")


@dataclass(frozen=True)
class ScopedReference:
    """One active receipt, in one scope, referencing one cache object."""

    scope: str
    receipt_id: str
    qualified_identity: str
    cache_key_digest: str

    def describe(self) -> str:
        return f"{self.scope}:{self.receipt_id} ({self.qualified_identity})"


class ReferenceIndex:
    """Answers "does any active receipt in any scope reference this object".

    Every read goes to the underlying stores. An index that cached its answer
    would be answering about the moment it was built, and the question is only
    ever asked immediately before deleting something.
    """

    def __init__(self, scopes: Sequence[ReceiptScope]) -> None:
        names = [scope.name for scope in scopes]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ScopeUnreadable(
                f"receipt scopes must be distinct; {duplicates} appears more than once, "
                "so one scope's receipts would stand in for another's"
            )
        missing = [name for name in REQUIRED_SCOPES if name not in names]
        if missing:
            raise ScopeUnreadable(
                f"the reference check must cover every scope; {missing} was not "
                f"supplied. ADR-0011 requires an active receipt in ANY scope to "
                "protect its object, and a partial check answers 'unreferenced' for "
                "objects another lock is holding."
            )
        for scope in scopes:
            location = scope.store.path.parent
            if not location.is_dir():
                raise ScopeUnreadable(
                    f"scope {scope.name!r} declares its receipts at {scope.store.path}, "
                    f"but {location} does not exist. A scope that is not where it says "
                    "it is has no answer, and 'no answer' is never 'no references'."
                )
        self._scopes: tuple[ReceiptScope, ...] = tuple(scopes)

    @property
    def scope_names(self) -> tuple[str, ...]:
        return tuple(scope.name for scope in self._scopes)

    def _read(self, scope: ReceiptScope, reader: str) -> tuple[ForeignReceipt, ...]:
        try:
            if reader == "active":
                return scope.store.all()
            if reader == "retired":
                return scope.store.retired()
            raise ValueError(f"unknown receipt reader: {reader!r}")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ScopeUnreadable(
                f"scope {scope.name!r} at {scope.store.path} could not be read: {exc}. "
                "An unreadable scope is not an empty one; nothing is collected or "
                "purged until it answers."
            ) from exc

    def references(self, cache_key_digest: str) -> tuple[ScopedReference, ...]:
        """Every active receipt, in every scope, that references this object."""
        found: list[ScopedReference] = []
        for scope in self._scopes:
            # `ReceiptStore.referencing_digest` owns this question for one store;
            # re-deriving it here would mean reading those records from outside.
            try:
                matches = scope.store.referencing_digest(cache_key_digest)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ScopeUnreadable(
                    f"scope {scope.name!r} at {scope.store.path} could not be read: "
                    f"{exc}. An unreadable scope is not an empty one."
                ) from exc
            found.extend(
                ScopedReference(
                    scope=scope.name,
                    receipt_id=receipt.id,
                    qualified_identity=receipt.qualified_identity(),
                    cache_key_digest=receipt.cache_key_digest,
                )
                for receipt in matches
            )
        return tuple(found)

    def receipts_for_digest(
        self, cache_key_digest: str
    ) -> tuple[tuple[str, ForeignReceipt], ...]:
        """Active **and retired** receipts for one object, across every scope.

        Retired receipts are the reason an unreferenced object is not an
        unknown one: they still record how the retrieval's completeness was
        established and whether the upstream item had already vanished when the
        receipt was removed.
        """
        found: list[tuple[str, ForeignReceipt]] = []
        for scope in self._scopes:
            for reader in ("active", "retired"):
                found.extend(
                    (scope.name, receipt)
                    for receipt in self._read(scope, reader)
                    if receipt.cache_key_digest == cache_key_digest
                )
        return tuple(found)


# -- proven re-fetchability ---------------------------------------------------


@dataclass(frozen=True)
class RefetchProof:
    """Proof that a source currently serves the exact digest that is pinned.

    The only evidence that makes a revisionless object collectable. It is a
    value object with a closed `method` because "we checked somehow" is not a
    proof, and a caller-supplied method string that can say anything would
    reduce this whole clause to a comment.
    """

    provider_identity: str
    qualified_identity: str
    observed_digest: str
    observed_at: str
    method: str = "digest-verified-refetch"

    def __post_init__(self) -> None:
        _text(self.provider_identity, "RefetchProof.provider_identity")
        _text(self.qualified_identity, "RefetchProof.qualified_identity")
        _text(self.observed_at, "RefetchProof.observed_at")
        validated_digest(self.observed_digest)
        if self.method != "digest-verified-refetch":
            raise ValueError(
                "the only re-fetchability proof ADR-0011 accepts is a "
                f"digest-verified re-fetch, not {self.method!r}"
            )
        provider, _ = parse_qualified_identity(self.qualified_identity)
        if provider != self.provider_identity:
            raise ValueError(
                f"proof for {self.qualified_identity!r} does not belong to "
                f"{self.provider_identity!r}; one source's re-fetch proves nothing "
                "about another's bytes"
            )


@dataclass(frozen=True)
class RetentionDecision:
    """What automatic collection decided about one object, and why."""

    key_digest: str
    qualified_identity: str
    path: Path
    collectable: bool
    reason: str | None
    conditions: tuple[str, ...]
    detail: str
    references: tuple[ScopedReference, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GarbageCollectionPlan:
    """Every object the store holds, with its retention decision."""

    observed_at: str
    decisions: tuple[RetentionDecision, ...]

    @property
    def collectable(self) -> tuple[RetentionDecision, ...]:
        return tuple(decision for decision in self.decisions if decision.collectable)

    @property
    def retained(self) -> tuple[RetentionDecision, ...]:
        return tuple(decision for decision in self.decisions if not decision.collectable)


@dataclass(frozen=True)
class GarbageCollectionResult:
    """What a collection run deleted, retained, and refused at the last moment."""

    plan: GarbageCollectionPlan
    deleted: tuple[RetentionDecision, ...]
    retained: tuple[RetentionDecision, ...]
    raced: tuple[RetentionDecision, ...] = field(default_factory=tuple)


def _proofs_by_identity(proofs: Iterable[RefetchProof]) -> dict[str, RefetchProof]:
    indexed: dict[str, RefetchProof] = {}
    for proof in proofs:
        if not isinstance(proof, RefetchProof):
            raise ValueError(
                "a re-fetchability proof must be a RefetchProof value; a bare digest "
                "cannot state which identity it was observed for"
            )
        indexed[proof.qualified_identity] = proof
    return indexed


def _completeness_evidence(known: Sequence[tuple[str, ForeignReceipt]]) -> set[str]:
    return {
        receipt.completeness_evidence or "unrecorded" for _, receipt in known
    }


def _evaluate_object(
    cache_object: CacheObject,
    *,
    references: ReferenceIndex,
    observations: Mapping[str, ResolutionEvidence],
    proofs: Mapping[str, RefetchProof],
) -> RetentionDecision:
    """Apply both retention inputs to one object and name every unmet one."""
    key = cache_object.key
    digest = key.digest()
    identity = key.qualified_identity()
    conditions: list[str] = []
    details: list[str] = []

    active = references.references(digest)
    if active:
        conditions.append("referenced-by-active-receipt")
        details.append(
            "active receipts reference this object: "
            + ", ".join(reference.describe() for reference in active)
        )

    known = references.receipts_for_digest(digest)
    observation = observations.get(key.provider_identity)
    if observation is None:
        conditions.append("provider-not-observed")
        details.append(
            f"no source-scoped observation was supplied for {key.provider_identity!r}; "
            "another source's resolution says nothing about these bytes"
        )
    else:
        # The offline table owns "may automatic garbage collection run at all
        # against this observation". Its two additional preconditions -- no
        # active receipt references the object, and exact re-fetchability is
        # proven -- are evaluated below, where the object is in hand.
        verdict = evaluate_operation("automatic-garbage-collection", observation)
        if not verdict.allowed:
            if observation.availability.state != "available":
                conditions.append("provider-unavailable")
                details.append(
                    f"the source is {observation.availability.state}: "
                    f"{observation.describe()}"
                )
            elif observation.reduced_by_authorization:
                conditions.append("access-revoked")
                details.append(
                    "the inventory is reduced by changed authorization, so access to "
                    "re-fetch these bytes is revoked or narrowed"
                )
            else:
                conditions.append("inventory-incomplete")
                details.append(
                    "the inventory is incomplete or truncated, which cannot prove the "
                    "item still exists upstream"
                )
        elif identity not in observation.listed_identities:
            conditions.append("upstream-vanished")
            details.append(
                f"a reachable and complete inventory no longer lists {identity}; a "
                "vanished upstream is exactly when the local cache is most valuable"
            )

    vanished = [receipt for _, receipt in known if receipt.upstream_state == "upstream-vanished"]
    if vanished and "upstream-vanished" not in conditions:
        conditions.append("upstream-vanished")
        details.append(
            f"a receipt records {identity} as upstream-vanished "
            f"({', '.join(sorted(receipt.id for receipt in vanished))})"
        )
    revoked = [
        receipt for _, receipt in known if receipt.rights.fetch_authorization != "granted"
    ]
    if revoked and "access-revoked" not in conditions:
        conditions.append("access-revoked")
        details.append(
            "a receipt records that authorization to fetch these bytes is no longer "
            f"granted ({', '.join(sorted(receipt.id for receipt in revoked))})"
        )

    evidence = _completeness_evidence(known)
    proven_completeness = bool(evidence & PROVEN_COMPLETENESS)
    revisionless = key.upstream_revision is None
    if revisionless or not proven_completeness:
        why = (
            "the source is revisionless, so it is pin-only and can serve different "
            "bytes while looking healthy"
            if revisionless
            else "the only completeness evidence for this object is "
            f"{sorted(evidence) or ['unrecorded']}, which is the adapter-declaration "
            "case: nothing independent ever confirmed what was stored"
        )
        proof = proofs.get(identity)
        if proof is None:
            conditions.append("re-fetchability-not-proven")
            details.append(
                f"{why}; deleting requires a digest-verified re-fetch confirming the "
                f"source still serves {key.normalized_content_digest}"
            )
        elif proof.observed_digest != key.normalized_content_digest:
            conditions.append("refetch-digest-drift")
            details.append(
                f"the re-fetch observed {proof.observed_digest} where the object pins "
                f"{key.normalized_content_digest}; this is fail-closed drift, and "
                "deleting would destroy the last copy of the pinned content"
            )

    ordered = tuple(
        reason for reason in RETENTION_REFUSALS if reason in set(conditions)
    )
    return RetentionDecision(
        key_digest=digest,
        qualified_identity=identity,
        path=cache_object.path,
        collectable=not ordered,
        reason=ordered[0] if ordered else None,
        conditions=ordered,
        detail=(
            "; ".join(details)
            if details
            else "no active receipt references this object and exact re-fetchability "
            "is proven"
        ),
        references=active,
    )


def plan_garbage_collection(
    *,
    object_store: ObjectStore,
    references: ReferenceIndex,
    observations: Mapping[str, ResolutionEvidence],
    refetch_proofs: Sequence[RefetchProof] = (),
    observed_at: str,
) -> GarbageCollectionPlan:
    """Decide, without mutating anything, what automatic collection may delete.

    Args:
        observations: One source-scoped `ResolutionEvidence` per provider
            identity. An object whose own source was not observed is retained:
            one source's listing says nothing about another's items.
        refetch_proofs: Digest-verified re-fetches, keyed by qualified identity.
            Required for every revisionless object and for every object whose
            completeness rests only on the adapter's word.

    Quarantined objects are not considered: they are retained evidence a repair
    set aside, and `ObjectStore.objects()` already excludes them.
    """
    _text(observed_at, "observed_at")
    proofs = _proofs_by_identity(refetch_proofs)
    for identity, observation in observations.items():
        if not isinstance(observation, ResolutionEvidence):
            raise ValueError(
                f"observation for {identity!r} must be source-scoped ResolutionEvidence; "
                "transport reachability alone is not a complete resolution"
            )
        if observation.provider_identity != identity:
            raise ValueError(
                f"observation filed under {identity!r} describes "
                f"{observation.provider_identity!r}; one source's resolution is never "
                "another's"
            )
    decisions = tuple(
        _evaluate_object(
            cache_object,
            references=references,
            observations=observations,
            proofs=proofs,
        )
        for cache_object in object_store.objects()
    )
    return GarbageCollectionPlan(observed_at=observed_at, decisions=decisions)


def collect_garbage(
    *,
    object_store: ObjectStore,
    references: ReferenceIndex,
    observations: Mapping[str, ResolutionEvidence],
    refetch_proofs: Sequence[RefetchProof] = (),
    observed_at: str,
    pin_store: TofuPinStore,
) -> GarbageCollectionResult:
    """Delete only what the plan proved collectable, re-proving it under the lock.

    The re-proof is not defensive padding. An install holds
    `TofuPinStore.identity_lock` across retrieval, materialization, the receipt,
    and activation, so an object can acquire its first reference at any moment
    between a plan and a deletion. Taking the same lock and evaluating the
    object again is what makes "an active receipt protects its object" true for
    receipts that did not exist when the plan was made.

    This function never purges. There is no code path from here to
    `purge_object`, under any provider condition.
    """
    plan = plan_garbage_collection(
        object_store=object_store,
        references=references,
        observations=observations,
        refetch_proofs=refetch_proofs,
        observed_at=observed_at,
    )
    proofs = _proofs_by_identity(refetch_proofs)
    deleted: list[RetentionDecision] = []
    raced: list[RetentionDecision] = []
    for decision in plan.collectable:
        with pin_store.identity_lock(decision.qualified_identity):
            cache_object = _object_for_digest(object_store, decision.key_digest)
            if cache_object is None:
                raced.append(decision)
                continue
            confirmed = _evaluate_object(
                cache_object,
                references=references,
                observations=observations,
                proofs=proofs,
            )
            if not confirmed.collectable:
                raced.append(confirmed)
                continue
            _discard_object(object_store, cache_object)
            deleted.append(confirmed)
    return GarbageCollectionResult(
        plan=plan,
        deleted=tuple(deleted),
        retained=plan.retained,
        raced=tuple(raced),
    )


# -- deletion -----------------------------------------------------------------


def _object_for_digest(object_store: ObjectStore, digest: str) -> CacheObject | None:
    for cache_object in object_store.objects():
        if cache_object.key.digest() == digest:
            return cache_object
    return None


def _member_paths(cache_object: CacheObject) -> tuple[str, ...]:
    root = cache_object.content_path
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()
        )
    )


def _byte_count(cache_object: CacheObject) -> int:
    root = cache_object.content_path
    if not root.is_dir():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _discard_tree(object_store: ObjectStore, path: Path) -> None:
    """Remove one directory tree in a way a reader never sees half of.

    The tree is renamed into the store's staging area first, so a reader either
    sees the whole object or nothing at all, and a failure part way through the
    removal leaves an abandoned staging entry that `ObjectStore.sweep_staging`
    reclaims rather than a half-deleted object that a later run reads as cached.
    """
    staging_root = object_store.staging_root
    staging_root.mkdir(parents=True, exist_ok=True)
    staged = staging_root / f"{os.getpid()}-{uuid.uuid4().hex}"
    os.rename(path, staged)
    shutil.rmtree(staged, ignore_errors=True)
    with contextlib.suppress(OSError):
        if staging_root.is_dir() and not any(staging_root.iterdir()):
            staging_root.rmdir()


def _assert_deletable(object_store: ObjectStore, path: Path) -> Path:
    """Prove a path is this store's own object before removing it."""
    resolved = Path(path).resolve()
    root = object_store.objects_root.resolve()
    if root not in resolved.parents:
        raise RetentionError(
            f"{resolved} is not inside this cache's object root {root}; deletion is "
            "refused rather than resolved"
        )
    if not resolved.is_dir():
        raise RetentionError(f"{resolved} is not a stored object directory")
    return resolved


def _discard_object(object_store: ObjectStore, cache_object: CacheObject) -> tuple[str, ...]:
    """Delete one canonical cache object and report the members it held."""
    expected = object_store.path_for(cache_object.key)
    resolved = _assert_deletable(object_store, cache_object.path)
    if resolved != expected:
        raise RetentionError(
            f"object {cache_object.key.digest()} is stored at {resolved} but its key "
            f"addresses {expected}; deletion is refused rather than reconciled"
        )
    if QUARANTINE_SUFFIX in resolved.name:
        raise RetentionError(
            f"{resolved} is quarantined evidence a repair set aside; it is never "
            "removed as part of an object deletion"
        )
    members = _member_paths(cache_object)
    _discard_tree(object_store, resolved)
    return members


def _delete_quarantine(object_store: ObjectStore, path: Path) -> Path:
    """Delete one quarantined tree an operator named explicitly."""
    resolved = _assert_deletable(object_store, path)
    if QUARANTINE_SUFFIX not in resolved.name:
        raise RetentionError(
            f"{resolved} is not a quarantined tree; only set-aside evidence is removed "
            "through this path"
        )
    _discard_tree(object_store, resolved)
    return resolved


# -- operator-explicit purge --------------------------------------------------


def _object_digest(value: object) -> str:
    """One cache-object digest, or a refusal that names what was supplied.

    ADR-0011: "requires an object digest -- not a name, not a glob, not a
    provider". The refusal names the shape because an operator who typed a name
    needs to know that a name can never address one object's bytes.
    """
    if isinstance(value, str) and OBJECT_DIGEST_RE.match(value):
        return value
    text = value if isinstance(value, str) else repr(value)
    if not isinstance(value, str) or not value.strip():
        shape = "an empty value addresses everything or nothing"
    elif any(character in value for character in "*?["):
        shape = "that is a glob, and a glob can match objects nobody inspected"
    elif "#" in value:
        shape = "that is a qualified item identity, not one object's bytes"
    elif ":" in value:
        shape = (
            "that looks like a content digest; a purge addresses the cache object, "
            "whose digest covers the whole identity tuple"
        )
    elif "/" in value:
        shape = "that is a path or a name, and a name can address many objects"
    elif re.match(r"^[0-9a-fA-F]{40}$", value):
        shape = "that is a revision identity, not a cache-object digest"
    elif OBJECT_DIGEST_RE.match(value.strip().lower()):
        shape = "a digest is 64 lowercase hex characters, with no padding or case"
    else:
        shape = "that is a name, and a name can address many objects"
    raise PurgeRefused(
        "not-an-object-digest",
        f"{text!r} is not a cache-object digest: {shape}. Purge is a human act with "
        "a digest in their hand.",
    )


@dataclass(frozen=True)
class PurgeAcknowledgement:
    """An operator's digest, reason, and stated acceptance of permanent loss.

    Digest and acknowledgement are one value on purpose. There is no purge entry
    point that takes a digest without the acknowledgement that goes with it, so
    "add a flag that skips the acknowledgement" would have to delete this type's
    only constructor rather than add a default argument.
    """

    operator: str
    digest: str
    reason: str
    acknowledged_at: str
    acknowledgement: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", _object_digest(self.digest))
        if self.acknowledgement != PURGE_ACKNOWLEDGEMENT:
            raise PurgeRefused(
                "acknowledgement-missing",
                "a purge deletes bytes permanently and they may not be re-fetchable; "
                f"record acknowledgement={PURGE_ACKNOWLEDGEMENT!r} to state that this "
                "is understood",
            )
        for label in ("operator", "reason", "acknowledged_at"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value.strip():
                raise PurgeRefused(
                    "acknowledgement-incomplete",
                    f"a purge records who destroyed what, why, and when; {label} is "
                    "missing",
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "digest": self.digest,
            "reason": self.reason,
            "acknowledged_at": self.acknowledged_at,
            "acknowledgement": self.acknowledgement,
        }


@dataclass(frozen=True)
class PurgePlan:
    """Exactly what a purge would delete, with nothing done yet."""

    digest: str
    key: CacheKey | None
    object_path: Path | None
    member_paths: tuple[str, ...]
    byte_count: int
    quarantine_paths: tuple[Path, ...]
    includes_quarantine: bool
    references: tuple[ScopedReference, ...]
    blocked_reason: str | None

    @property
    def deletable(self) -> bool:
        return self.blocked_reason is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "key": self.key.to_dict() if self.key else None,
            "object_path": str(self.object_path) if self.object_path else None,
            "member_paths": list(self.member_paths),
            "byte_count": self.byte_count,
            "quarantine_paths": [str(path) for path in self.quarantine_paths],
            "includes_quarantine": self.includes_quarantine,
            "references": [reference.describe() for reference in self.references],
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class PurgeOutcome:
    """One completed purge, and the durable record it wrote."""

    plan: PurgePlan
    deleted_paths: tuple[str, ...]
    deleted_quarantine: tuple[Path, ...]
    ledger_entry_id: str
    purged_at: str


class PurgeLedger:
    """The durable record of every purge: who, what, why, and on what statement.

    Destroying bytes is the one cache operation nothing can undo and nothing
    else records. The entry is written **before** the deletion and completed
    afterwards, so an interrupted purge leaves the intent on record rather than
    an unexplained absence.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema") != PURGE_LEDGER_SCHEMA:
            raise ValueError(f"unexpected purge ledger schema: {payload.get('schema')}")
        return list(payload.get("entries") or [])

    def _save(self, entries: Sequence[Mapping[str, Any]]) -> None:
        atomic_write_text(
            self.path,
            json.dumps(
                {"schema": PURGE_LEDGER_SCHEMA, "entries": list(entries)},
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )

    def entries(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._load())

    def record_intent(
        self, plan: PurgePlan, acknowledgement: PurgeAcknowledgement
    ) -> str:
        entry_id = f"purge-{plan.digest[:16]}-{uuid.uuid4().hex[:8]}"
        entry = {
            "id": entry_id,
            "status": "planned",
            "plan": plan.to_dict(),
            "member_paths": list(plan.member_paths),
            "byte_count": plan.byte_count,
            "completed_at": None,
            "deleted_paths": [],
            "deleted_quarantine": [],
            **acknowledgement.to_dict(),
        }
        with exclusive_lock(self.path):
            entries = self._load()
            entries.append(entry)
            self._save(entries)
        return entry_id

    def record_completion(
        self,
        entry_id: str,
        *,
        deleted_paths: Sequence[str],
        deleted_quarantine: Sequence[Path],
        completed_at: str,
    ) -> None:
        with exclusive_lock(self.path):
            entries = self._load()
            for entry in entries:
                if entry.get("id") == entry_id:
                    entry["status"] = "purged"
                    entry["completed_at"] = completed_at
                    entry["deleted_paths"] = list(deleted_paths)
                    entry["deleted_quarantine"] = [str(path) for path in deleted_quarantine]
                    break
            else:  # pragma: no cover - the intent is written under the same lock
                raise ValueError(f"no purge ledger entry with id {entry_id!r}")
            self._save(entries)


def _quarantine_paths(object_store: ObjectStore, digest: str) -> tuple[Path, ...]:
    root = object_store.objects_root
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            path
            for path in root.rglob(f"{digest}{QUARANTINE_SUFFIX}*")
            if path.is_dir()
        )
    )


def plan_purge(
    *,
    object_store: ObjectStore,
    references: ReferenceIndex,
    digest: str,
    include_quarantined: bool = False,
) -> PurgePlan:
    """Report exactly what a purge of this digest would delete, and change nothing.

    Reads only. It takes no lock, writes no ledger entry, and touches no file, so
    a dry run is inert by construction rather than by a flag that a later branch
    could forget to honor.

    Raises:
        PurgeRefused: `not-an-object-digest` when the subject is a name, a glob,
            a provider, or a content digest; `no-such-object` when a well-formed
            digest addresses nothing. A digest that addresses nothing is never
            resolved into a neighbouring object.
    """
    subject = _object_digest(digest)
    cache_object = _object_for_digest(object_store, subject)
    quarantine = _quarantine_paths(object_store, subject)
    if cache_object is None and not (include_quarantined and quarantine):
        raise PurgeRefused(
            "no-such-object",
            f"no cache object is stored under {subject}"
            + (
                f"; {len(quarantine)} quarantined tree(s) carry that digest and are "
                "removed only when they are named with include_quarantined"
                if quarantine
                else ""
            ),
        )
    active = references.references(subject)
    return PurgePlan(
        digest=subject,
        key=cache_object.key if cache_object else None,
        object_path=cache_object.path if cache_object else None,
        member_paths=_member_paths(cache_object) if cache_object else (),
        byte_count=_byte_count(cache_object) if cache_object else 0,
        quarantine_paths=quarantine,
        includes_quarantine=bool(include_quarantined and quarantine),
        references=active,
        blocked_reason="referenced-by-active-receipt" if active else None,
    )


def purge_object(
    *,
    object_store: ObjectStore,
    references: ReferenceIndex,
    pin_store: TofuPinStore,
    ledger: PurgeLedger,
    acknowledgement: PurgeAcknowledgement,
    include_quarantined: bool = False,
    origin: str = OPERATOR_EXPLICIT,
) -> PurgeOutcome:
    """Delete one cache object an operator named by digest and acknowledged.

    The only path in the Library that deletes an unreferenced cache object under
    degraded conditions, and the only one that deletes bytes an operator may not
    be able to fetch again. Degraded provider state never reaches it: automatic
    reconciliation and garbage collection are refused by `origin`, and no
    collection code path calls this function at all.

    The reference proof is taken twice: once for the plan an operator reads, and
    again under the install serialization lock immediately before the deletion,
    because an install can acquire the object's first reference in between.

    Raises:
        PurgeRefused: for a subject that is not an object digest, for a digest
            that addresses nothing, for a missing or incomplete acknowledgement,
            for an active reference in any scope, and for any origin other than
            an operator naming the digest.
        ScopeUnreadable: when any receipt scope cannot answer. Nothing is
            deleted while a scope is silent.
    """
    if not isinstance(acknowledgement, PurgeAcknowledgement):
        raise PurgeRefused(
            "acknowledgement-missing",
            "a purge requires a PurgeAcknowledgement carrying the digest, the "
            "operator, the reason, and the stated acceptance of permanent loss",
        )
    if origin != OPERATOR_EXPLICIT:
        raise PurgeRefused(
            "not-operator-explicit",
            "purge is never invoked by automatic reconciliation or garbage "
            f"collection; this call was reached from {origin!r}. Degraded provider "
            "state never triggers a purge.",
        )

    plan = plan_purge(
        object_store=object_store,
        references=references,
        digest=acknowledgement.digest,
        include_quarantined=include_quarantined,
    )
    _refuse_referenced(plan)

    identity = plan.key.qualified_identity() if plan.key else f"purge#{plan.digest}"
    with pin_store.identity_lock(identity):
        confirmed = plan_purge(
            object_store=object_store,
            references=references,
            digest=acknowledgement.digest,
            include_quarantined=include_quarantined,
        )
        _refuse_referenced(confirmed)
        entry_id = ledger.record_intent(confirmed, acknowledgement)
        deleted_members: tuple[str, ...] = ()
        if confirmed.object_path is not None:
            cache_object = _object_for_digest(object_store, confirmed.digest)
            if cache_object is None:  # pragma: no cover - held under the same lock
                raise PurgeRefused(
                    "no-such-object",
                    f"cache object {confirmed.digest} disappeared before it was purged",
                )
            deleted_members = _discard_object(object_store, cache_object)
        deleted_quarantine: list[Path] = []
        if confirmed.includes_quarantine:
            for path in confirmed.quarantine_paths:
                deleted_quarantine.append(_delete_quarantine(object_store, path))
        ledger.record_completion(
            entry_id,
            deleted_paths=deleted_members,
            deleted_quarantine=deleted_quarantine,
            completed_at=acknowledgement.acknowledged_at,
        )
    return PurgeOutcome(
        plan=confirmed,
        deleted_paths=deleted_members,
        deleted_quarantine=tuple(deleted_quarantine),
        ledger_entry_id=entry_id,
        purged_at=acknowledgement.acknowledged_at,
    )


def _refuse_referenced(plan: PurgePlan) -> PurgePlan:
    if plan.deletable:
        return plan
    raise PurgeRefused(
        str(plan.blocked_reason),
        f"cache object {plan.digest} is referenced by "
        + ", ".join(reference.describe() for reference in plan.references)
        + ". A purge proves no active receipt in any scope references the digest "
        "before deleting; remove those receipts explicitly first.",
    )


__all__ = [
    "OBJECT_DIGEST_RE",
    "OPERATOR_EXPLICIT",
    "PROVEN_COMPLETENESS",
    "PURGE_ACKNOWLEDGEMENT",
    "PURGE_LEDGER_SCHEMA",
    "PURGE_REFUSALS",
    "REQUIRED_SCOPES",
    "RETENTION_REFUSALS",
    "GarbageCollectionPlan",
    "GarbageCollectionResult",
    "PurgeAcknowledgement",
    "PurgeLedger",
    "PurgeOutcome",
    "PurgePlan",
    "PurgeRefused",
    "ReceiptScope",
    "ReferenceIndex",
    "RefetchProof",
    "RetentionDecision",
    "RetentionError",
    "ScopeUnreadable",
    "ScopedReference",
    "collect_garbage",
    "plan_garbage_collection",
    "plan_purge",
    "purge_object",
]
