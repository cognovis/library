"""Foreign-content receipts, `upstream-vanished`, and explicit named removal.

A receipt is what makes an installed artifact reproducible. ADR-0011 records the
concrete failure this exists to end: four materialized workflow projections with
zero receipts, whose bytes cannot be reproduced once their source disappears.
Shape is not evidence -- a Library-shaped bridge without a Library receipt is
not Library-owned.

Three rules are enforced here rather than left to callers:

- **`upstream-vanished` is durable, queryable, and grants no deletion
  authority.** A vanished upstream is exactly when the local cache is most
  valuable, so the state that records the loss must not be the state that
  authorizes destroying the last copy.
- **Absence is only information from a reachable, complete inventory.** A
  truncated listing, a listing reduced by changed authorization, and an
  unreachable source all leave every receipt untouched.
- **Explicit named removal always works and never deletes bytes.** An operator
  must be able to remove something they can name during a total outage, and
  doing so must never destroy content that may not be re-fetchable.

Serialization is a JSON document beside the cache, with the field names ADR-0011
fixes for a foreign lock receipt (`docs/lockfile-format.md`, `v2 receipt fields
for foreign-sourced content`). Folding these records into the v2 lockfile
itself belongs with the Workspace manifest slice; the field names are chosen so
that fold is a move, not a translation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .state_files import atomic_write_text, exclusive_lock

from .inventory import (
    PROJECTION_TARGETS,
    ProviderAvailability,
    Rights,
    qualified_identity,
)
from .offline import OfflineRefusal, ResolutionEvidence, require_operation

#: An inventory observation is source-scoped resolution evidence. The type lives
#: in `offline` because the offline table has to read its completeness before it
#: can permit anything destructive; the name stays here because an inventory
#: observation is what a caller of this module actually holds.
InventoryObservation = ResolutionEvidence

RECEIPT_STORE_SCHEMA = "cognovis.foreign-receipt-store.v1"

#: The two durable upstream states of ADR-0011 `Degraded inventory`.
UPSTREAM_STATES: tuple[str, ...] = ("present", "upstream-vanished")

#: The closed receipt-history vocabulary. History answers "what happened to this
#: install and under what conditions", so each entry names an event, not prose.
RECEIPT_EVENTS: tuple[str, ...] = (
    "installed",
    "projection-planned",
    "projection-activated",
    "projection-plan-violated",
    "reinstalled-from-cache",
    "integrity-verified",
    "integrity-failed",
    "upstream-vanished",
    "upstream-reappeared",
    "explicit-removal",
)

TARGET_KINDS: tuple[str, ...] = ("file", "directory", "symlink")

#: How a retrieval's completeness was established. `adapter-declaration` is the
#: honest name for the weakest one: the adapter's contract says a `FetchedItem`
#: is complete and nothing independent confirmed it. It is a recorded value
#: rather than an unrecorded default, because review truncated a fetch and the
#: install pinned, cached, receipted, and projected the fragment in silence.
COMPLETENESS_METHODS: tuple[str, ...] = (
    "member-manifest",
    "pinned-digest",
    "adapter-declaration",
)


class DeletionAuthorityRefused(RuntimeError):
    """A caller asked a receipt to authorize deleting something. It cannot.

    Deletion authority derives from a complete resolution over a reachable
    source. `upstream-vanished` is the opposite of that evidence, and an
    unverified receipt never had it.
    """


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value


@dataclass(frozen=True)
class ReceiptTarget:
    """One file, directory, or link this receipt created or adopted."""

    path: str
    kind: str
    content_sha256: str | None = None
    link_target: str | None = None

    def __post_init__(self) -> None:
        _text(self.path, "ReceiptTarget.path")
        if self.kind not in TARGET_KINDS:
            raise ValueError(f"ReceiptTarget.kind must be one of {list(TARGET_KINDS)}")
        if self.kind == "file" and not (self.content_sha256 or "").strip():
            raise ValueError("a file target records its install-time digest")
        if self.kind == "symlink" and not (self.link_target or "").strip():
            raise ValueError("a symlink target records its literal link value")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "content_sha256": self.content_sha256,
            "link_target": self.link_target,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReceiptTarget":
        return cls(
            path=data["path"],
            kind=data["kind"],
            content_sha256=data.get("content_sha256"),
            link_target=data.get("link_target"),
        )


@dataclass(frozen=True)
class ReceiptEvent:
    """One entry of a receipt's history.

    `provider_state` and `operator` are separate recorded fields rather than
    prose inside `detail`, because ADR-0011 requires an explicit removal to
    record the degraded state **and** the operator's intent, and a reader has to
    be able to query either without parsing a sentence.
    """

    event: str
    recorded_at: str
    detail: str
    operator: str | None = None
    provider_state: str | None = None

    def __post_init__(self) -> None:
        if self.event not in RECEIPT_EVENTS:
            raise ValueError(
                f"unknown receipt event {self.event!r}; the vocabulary is {list(RECEIPT_EVENTS)}"
            )
        _text(self.recorded_at, "ReceiptEvent.recorded_at")
        _text(self.detail, "ReceiptEvent.detail")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "recorded_at": self.recorded_at,
            "detail": self.detail,
            "operator": self.operator,
            "provider_state": self.provider_state,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReceiptEvent":
        return cls(
            event=data["event"],
            recorded_at=data["recorded_at"],
            detail=data["detail"],
            operator=data.get("operator"),
            provider_state=data.get("provider_state"),
        )


@dataclass(frozen=True)
class ForeignReceipt:
    """The materialized state of one foreign item, complete enough to reproduce it."""

    id: str
    provider_identity: str
    upstream_id: str
    upstream_name: str
    collection_membership: tuple[str, ...]
    upstream_revision: str | None
    normalized_content_digest: str
    transformation_version: str
    library_type: str
    library_name: str
    cache_key_digest: str
    cache_path: str
    install_timestamp: str
    rights: Rights
    executable_admission: str
    projection_eligibility: Mapping[str, str]
    provider_availability: ProviderAvailability
    upstream_state: str = "present"
    verified: bool = False
    targets: tuple[ReceiptTarget, ...] = field(default_factory=tuple)
    history: tuple[ReceiptEvent, ...] = field(default_factory=tuple)
    #: The digest of the bytes actually stored and installed, after the
    #: transformation. `normalized_content_digest` stays the upstream identity
    #: and the pin subject; this is what an admission decision and a target
    #: inventory are about, and conflating the two let a projection install
    #: bytes nobody had reviewed.
    projected_content_digest: str | None = None
    #: Target paths this receipt declared **before** its projection was
    #: activated. A crash between activation and finalization therefore leaves
    #: an intent on record rather than an undescribed installed target.
    planned_targets: tuple[str, ...] = field(default_factory=tuple)
    #: How the retrieval's completeness was established: `member-manifest`,
    #: `pinned-digest`, or `adapter-declaration`. The last one is the honest
    #: name for "nothing but the adapter's word", and it is recorded so an
    #: operator can query which installs rest on it.
    completeness_evidence: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "id",
            "provider_identity",
            "upstream_id",
            "upstream_name",
            "normalized_content_digest",
            "transformation_version",
            "library_type",
            "library_name",
            "cache_key_digest",
            "cache_path",
            "install_timestamp",
            "executable_admission",
        ):
            _text(getattr(self, name), f"ForeignReceipt.{name}")
        if self.upstream_state not in UPSTREAM_STATES:
            raise ValueError(
                f"upstream_state must be one of {list(UPSTREAM_STATES)}, "
                f"got {self.upstream_state!r}"
            )
        if not isinstance(self.rights, Rights):
            raise ValueError("ForeignReceipt.rights must be a Rights value")
        if not isinstance(self.provider_availability, ProviderAvailability):
            raise ValueError(
                "ForeignReceipt.provider_availability must be an observed value"
            )
        if self.completeness_evidence is not None and (
            self.completeness_evidence not in COMPLETENESS_METHODS
        ):
            raise ValueError(
                f"completeness_evidence must be one of {list(COMPLETENESS_METHODS)}, "
                f"got {self.completeness_evidence!r}"
            )
        object.__setattr__(self, "collection_membership", tuple(self.collection_membership))
        object.__setattr__(self, "targets", tuple(self.targets))
        object.__setattr__(self, "planned_targets", tuple(self.planned_targets))
        object.__setattr__(self, "history", tuple(self.history))
        object.__setattr__(self, "projection_eligibility", dict(self.projection_eligibility))
        if sorted(self.projection_eligibility) != sorted(PROJECTION_TARGETS):
            raise ValueError(
                f"projection_eligibility must cover exactly {list(PROJECTION_TARGETS)}"
            )

    def qualified_identity(self) -> str:
        return qualified_identity(self.provider_identity, self.upstream_id)

    def with_event(self, event: ReceiptEvent, **changes: Any) -> "ForeignReceipt":
        """A copy carrying one more history entry, and optional field changes.

        History is append-only. A receipt whose history could be rewritten is a
        receipt that cannot answer "under what conditions was this removed".
        """
        payload = self.to_dict()
        payload.update({key: value for key, value in changes.items()})
        payload["history"] = [*[entry.to_dict() for entry in self.history], event.to_dict()]
        return ForeignReceipt.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider_identity": self.provider_identity,
            "upstream_id": self.upstream_id,
            "upstream_name": self.upstream_name,
            "collection_membership": list(self.collection_membership),
            "upstream_revision": self.upstream_revision,
            "normalized_content_digest": self.normalized_content_digest,
            "transformation_version": self.transformation_version,
            "library_type": self.library_type,
            "library_name": self.library_name,
            "cache_key_digest": self.cache_key_digest,
            "cache_path": self.cache_path,
            "install_timestamp": self.install_timestamp,
            "rights": self.rights.to_dict(),
            "executable_admission": self.executable_admission,
            "projection_eligibility": dict(self.projection_eligibility),
            "provider_availability": self.provider_availability.to_dict(),
            "upstream_state": self.upstream_state,
            "verified": self.verified,
            "targets": [target.to_dict() for target in self.targets],
            "history": [entry.to_dict() for entry in self.history],
            "projected_content_digest": self.projected_content_digest,
            "planned_targets": list(self.planned_targets),
            "completeness_evidence": self.completeness_evidence,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ForeignReceipt":
        payload = dict(data)
        payload["rights"] = (
            payload["rights"]
            if isinstance(payload["rights"], Rights)
            else Rights.from_dict(payload["rights"])
        )
        payload["provider_availability"] = (
            payload["provider_availability"]
            if isinstance(payload["provider_availability"], ProviderAvailability)
            else ProviderAvailability.from_dict(payload["provider_availability"])
        )
        payload["collection_membership"] = tuple(payload.get("collection_membership") or ())
        payload["planned_targets"] = tuple(payload.get("planned_targets") or ())
        payload["targets"] = tuple(
            target if isinstance(target, ReceiptTarget) else ReceiptTarget.from_dict(target)
            for target in payload.get("targets") or ()
        )
        payload["history"] = tuple(
            entry if isinstance(entry, ReceiptEvent) else ReceiptEvent.from_dict(entry)
            for entry in payload.get("history") or ()
        )
        return cls(**payload)


def deletion_authority(
    receipt: ForeignReceipt, observation: "InventoryObservation"
) -> ForeignReceipt:
    """Refuse to convert a receipt's state into permission to delete.

    Args:
        observation: Source-scoped resolution evidence for *this receipt's*
            source. It is required, and it must be conclusive: review obtained
            deletion authority from an observation whose own `degraded_reason`
            said the inventory was truncated, because only the transport state
            beside it was consulted.

    Raises:
        DeletionAuthorityRefused: for a non-conclusive observation, for an
            observation of a different source, for `upstream-vanished`, and for
            an unverified receipt. Each is a state in which the local bytes may
            be the last copy.
    """
    if not isinstance(observation, ResolutionEvidence):
        raise DeletionAuthorityRefused(
            "deletion authority requires a source-scoped inventory observation; "
            "reachability alone is not a complete resolution"
        )
    if observation.provider_identity != receipt.provider_identity:
        raise DeletionAuthorityRefused(
            f"{receipt.id} belongs to {receipt.provider_identity!r} but the "
            f"observation describes {observation.provider_identity!r}; one source's "
            "resolution says nothing about another's"
        )
    if not observation.conclusive:
        raise DeletionAuthorityRefused(
            f"{receipt.id} cannot be deleted from an incomplete resolution: "
            f"{observation.describe()}"
        )
    if receipt.qualified_identity() not in observation.listed_identities:
        # The observation itself proves the item is gone. Depending on somebody
        # having reconciled first would make safety a matter of call order:
        # review passed a conclusive listing that omitted the identity and got
        # authority to delete the last copy of a vanished item's bytes.
        raise DeletionAuthorityRefused(
            f"{receipt.id} is absent from this complete inventory of "
            f"{observation.provider_identity!r}, which makes it upstream-vanished. "
            "A vanished upstream is exactly when the local cache is most valuable, "
            "and it is never converted into deletion authority; reconcile the "
            "receipt so the state is recorded, then remove it explicitly if that "
            "is what you mean."
        )
    if receipt.upstream_state == "upstream-vanished":
        raise DeletionAuthorityRefused(
            f"{receipt.id} is upstream-vanished: the upstream item no longer exists, "
            "which is exactly when the local cache is most valuable. This state is "
            "never converted into deletion authority; only an explicit operator act "
            "removes the receipt, and it deletes no bytes."
        )
    if not receipt.verified:
        raise DeletionAuthorityRefused(
            f"{receipt.id} has no install-time verification, so nothing proves what "
            "its targets are; an unverified receipt is never pruneable"
        )
    return receipt


@dataclass(frozen=True)
class ReconciliationResult:
    """What one inventory observation changed, what it skipped, and what stopped it."""

    changed: tuple[ForeignReceipt, ...]
    unchanged: tuple[ForeignReceipt, ...]
    degraded_reason: str | None
    out_of_scope: tuple[ForeignReceipt, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RemovalOutcome:
    """One removed receipt, what it deactivated, and the bytes it left behind."""

    receipt: ForeignReceipt
    retained_cache_path: Path
    observation: "InventoryObservation"
    deactivated: tuple[str, ...] = field(default_factory=tuple)
    retained_targets: tuple[str, ...] = field(default_factory=tuple)


class ProjectionStillActive(RuntimeError):
    """A receipt with live targets was asked to retire without deactivating them.

    Retiring the receipt alone recreates the exact defect this whole slice
    exists to end: an active harness projection with no receipt, whose bytes
    nobody can attribute or reproduce. Review demonstrated it end to end.
    """


class ReceiptStore:
    """Durable foreign receipts, plus the retired ones removal archives.

    Reads and writes both go through the file. A removal has to survive the
    process that performed it, and a retired receipt has to stay readable after
    it stops being active -- otherwise the history entry recording *why* it was
    removed disappears with it, which is the one entry nobody can reconstruct.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> tuple[dict[str, ForeignReceipt], list[ForeignReceipt]]:
        if not self.path.is_file():
            return {}, []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema") != RECEIPT_STORE_SCHEMA:
            raise ValueError(f"unexpected receipt store schema: {payload.get('schema')}")
        active = {
            record["id"]: ForeignReceipt.from_dict(record)
            for record in payload.get("receipts") or []
        }
        retired = [
            ForeignReceipt.from_dict(record) for record in payload.get("retired") or []
        ]
        return active, retired

    def _save(
        self, active: Mapping[str, ForeignReceipt], retired: Sequence[ForeignReceipt]
    ) -> None:
        payload = {
            "schema": RECEIPT_STORE_SCHEMA,
            "receipts": [active[key].to_dict() for key in sorted(active)],
            "retired": [receipt.to_dict() for receipt in retired],
        }
        atomic_write_text(self.path, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def put(self, receipt: ForeignReceipt) -> ForeignReceipt:
        """Write one receipt durably, replacing any earlier record of the same id.

        The load and the save are one locked transaction. Atomic replacement
        protects a reader from half-written JSON and does nothing about two
        writers that each loaded the file before the other saved: review ran two
        successful `put` calls concurrently and the file kept one receipt, so an
        installed artifact lost the only record that described it.
        """
        if not isinstance(receipt, ForeignReceipt):
            raise TypeError("a receipt store holds validated ForeignReceipt values")
        with exclusive_lock(self.path):
            active, retired = self._load()
            active[receipt.id] = receipt
            self._save(active, retired)
        return receipt

    def get(self, receipt_id: str) -> ForeignReceipt | None:
        return self._load()[0].get(receipt_id)

    def all(self) -> tuple[ForeignReceipt, ...]:
        active, _ = self._load()
        return tuple(active[key] for key in sorted(active))

    def retired(self) -> tuple[ForeignReceipt, ...]:
        return tuple(self._load()[1])

    def with_upstream_state(self, state: str) -> tuple[ForeignReceipt, ...]:
        """Query by upstream state. `upstream-vanished` must be answerable."""
        if state not in UPSTREAM_STATES:
            raise ValueError(f"unknown upstream state: {state!r}")
        return tuple(receipt for receipt in self.all() if receipt.upstream_state == state)

    def referencing_digest(self, cache_key_digest: str) -> tuple[ForeignReceipt, ...]:
        """Every active receipt that references one cache object.

        Retention and purge are `CL-uliw`, but the question "does any active
        receipt reference this digest" is a property of the receipt store, and
        answering it anywhere else would mean reading these records from outside.
        """
        return tuple(
            receipt for receipt in self.all() if receipt.cache_key_digest == cache_key_digest
        )

    def _retire(self, receipt: ForeignReceipt) -> ForeignReceipt:
        """Move one receipt out of the active set and into the archive.

        Private, and additionally guarded: the docstring used to claim this was
        reached only through `remove_named_receipt` and nothing enforced it, so a
        direct call retired a receipt while its projection stayed installed. A
        retirement is only valid as the last step of an explicit removal, and
        the receipt's own history is the proof of that.
        """
        if not receipt.history or receipt.history[-1].event != "explicit-removal":
            raise ProjectionStillActive(
                f"{receipt.id} may only be retired as the final step of an explicit "
                "named removal, whose history entry records the operator, the intent, "
                "and the degraded state. Call remove_named_receipt."
            )
        with exclusive_lock(self.path):
            active, retired = self._load()
            active.pop(receipt.id, None)
            self._save(active, [*retired, receipt])
        return receipt


def reconcile_upstream_state(
    store: ReceiptStore, observation: InventoryObservation, *, observed_at: str
) -> ReconciliationResult:
    """Move receipts into or out of `upstream-vanished` from one observation.

    An observation is **source-scoped**: it may only change receipts whose
    `provider_identity` matches the source that was observed. Review installed
    two sources and reconciled one of them; every receipt of the other was
    marked `upstream-vanished`, because the observation carried no identity and
    the loop carried no filter. One source's complete listing says nothing at
    all about another source's items.

    A degraded observation changes nothing at all. That is not caution for its
    own sake: an incomplete listing that marks items vanished would then have
    them "reappear" on the next complete listing, and a state that flaps is a
    state nobody can act on.
    """
    reason = observation.degraded_reason()
    everything = store.all()
    receipts = tuple(
        receipt
        for receipt in everything
        if receipt.provider_identity == observation.provider_identity
    )
    out_of_scope = tuple(receipt for receipt in everything if receipt not in receipts)
    if reason is not None:
        return ReconciliationResult(
            changed=(),
            unchanged=receipts,
            degraded_reason=reason,
            out_of_scope=out_of_scope,
        )

    changed: list[ForeignReceipt] = []
    unchanged: list[ForeignReceipt] = []
    for receipt in receipts:
        listed = receipt.qualified_identity() in observation.listed_identities
        if not listed and receipt.upstream_state == "present":
            changed.append(
                store.put(
                    receipt.with_event(
                        ReceiptEvent(
                            event="upstream-vanished",
                            recorded_at=observed_at,
                            detail=(
                                "a reachable and complete inventory no longer lists "
                                f"{receipt.qualified_identity()}; the cached bytes are "
                                "retained and this state grants no deletion authority"
                            ),
                            provider_state=observation.describe(),
                        ),
                        upstream_state="upstream-vanished",
                        provider_availability=observation.availability.to_dict(),
                    )
                )
            )
        elif listed and receipt.upstream_state == "upstream-vanished":
            changed.append(
                store.put(
                    receipt.with_event(
                        ReceiptEvent(
                            event="upstream-reappeared",
                            recorded_at=observed_at,
                            detail=(
                                f"{receipt.qualified_identity()} is listed again by a "
                                "reachable and complete inventory"
                            ),
                            provider_state=observation.describe(),
                        ),
                        upstream_state="present",
                        provider_availability=observation.availability.to_dict(),
                    )
                )
            )
        else:
            unchanged.append(receipt)
    return ReconciliationResult(
        changed=tuple(changed),
        unchanged=tuple(unchanged),
        degraded_reason=None,
        out_of_scope=out_of_scope,
    )


def _claimed_targets(receipt: ForeignReceipt) -> tuple[ReceiptTarget, ...]:
    """Every path this receipt may have created, proven or merely declared.

    A planned path carries no install-time digest, because the whole point of
    recording it is that it was written down *before* anything was created. It
    is still a path this receipt is responsible for.
    """
    proven = {target.path: target for target in receipt.targets}
    claimed = dict(proven)
    for path in receipt.planned_targets:
        if path not in claimed:
            claimed[path] = ReceiptTarget(path=path, kind="directory")
    return tuple(claimed[path] for path in sorted(claimed))


def remove_named_receipt(
    store: ReceiptStore,
    receipt_id: str,
    *,
    operator: str,
    intent: str,
    observation: "InventoryObservation",
    removed_at: str,
    deactivate: Callable[[Sequence[ReceiptTarget]], Sequence[str]] | None = None,
    origin: str = "operator-explicit",
) -> RemovalOutcome:
    """Remove one named receipt, under any inventory condition, deleting no bytes.

    The order is deliberate and is the opposite of the install order: the
    receipt's recorded targets are deactivated **first**, and the receipt is
    retired only afterwards. A crash between the two leaves a receipt describing
    targets that are gone, which is recoverable; the reverse leaves an active
    projection with no receipt, which is the unattributable state this slice
    exists to end.

    Args:
        deactivate: Removes the receipt's recorded targets and returns the paths
            it actually removed. Required whenever the receipt records targets.
            It is a caller-supplied callable because *what* a harness projection
            is belongs to the harness, not to the receipt store.
        origin: How this removal was reached. Only an operator naming the receipt
            may reach it. Ownership-derived prune is refused here as well as in
            the offline table, so a reconciler cannot obtain through this door
            what fail-closed pruning denied it at the front.

    Returns:
        The retired receipt, what was deactivated, what was deliberately kept,
        and the cache path left in place.

    Raises:
        OfflineRefusal: when the removal did not originate from an operator.
        ProjectionStillActive: when the receipt records targets and no
            deactivation was supplied.
        KeyError: when no active receipt carries that id.
    """
    if origin != "operator-explicit":
        raise OfflineRefusal(
            "ownership-derived-prune",
            "deletion-authority-requires-complete-resolution",
            "explicit named removal is never triggered by ownership-derived prune; "
            f"this removal was reached from {origin!r}",
        )
    require_operation("explicit-named-removal", observation.availability)
    _text(operator, "removal operator")
    _text(intent, "removal intent")

    receipt = store.get(receipt_id)
    if receipt is None:
        raise KeyError(f"no active receipt with id {receipt_id!r}")

    # Everything this receipt may have put on disk: the proven targets and the
    # paths it declared before activating. A receipt that crashed between the
    # plan and the finalization has only the plan, and review retired exactly
    # that receipt while its files stayed installed.
    claimed = _claimed_targets(receipt)
    if claimed and deactivate is None:
        raise ProjectionStillActive(
            f"{receipt.id} claims {len(claimed)} target(s), recorded or planned. "
            "Retiring the receipt without deactivating them would leave an "
            "installed projection that no receipt describes -- exactly the "
            "unreproducible state this cache exists to end. Supply a deactivation; "
            "the cache object is retained either way."
        )

    removed = tuple(deactivate(claimed)) if claimed else ()
    surviving = tuple(
        target.path
        for target in claimed
        if target.path not in set(removed) and Path(target.path).exists()
    )
    if surviving:
        # The receipt stays active. A partially deactivated projection with no
        # record is the failure being prevented; a receipt that still describes
        # what is installed is the recovery record for it.
        raise ProjectionStillActive(
            f"{receipt.id} was not retired: {len(surviving)} claimed target(s) are "
            f"still present after deactivation ({', '.join(surviving[:5])}). The "
            "receipt remains active so the installed content stays attributable; "
            "finish or repair the deactivation and remove it again."
        )
    retained = tuple(
        target.path for target in claimed if target.path not in set(removed)
    )

    retired = receipt.with_event(
        ReceiptEvent(
            event="explicit-removal",
            recorded_at=removed_at,
            detail=(
                f"operator intent: {intent}. Deactivated {len(removed)} target(s) "
                f"before retiring the receipt; retained {len(retained)} target(s) "
                "that no longer matched their recorded install-time proof. The "
                f"underlying cache object at {receipt.cache_path} is retained; "
                "removal of a receipt never deletes bytes that may not be "
                "re-fetchable."
            ),
            operator=operator,
            provider_state=observation.describe(),
        )
    )
    store._retire(retired)
    return RemovalOutcome(
        receipt=retired,
        retained_cache_path=Path(receipt.cache_path),
        observation=observation,
        deactivated=removed,
        retained_targets=retained,
    )


__all__ = [
    "COMPLETENESS_METHODS",
    "RECEIPT_EVENTS",
    "UPSTREAM_STATES",
    "DeletionAuthorityRefused",
    "ForeignReceipt",
    "InventoryObservation",
    "ProjectionStillActive",
    "ReceiptEvent",
    "ReceiptStore",
    "ReceiptTarget",
    "ReconciliationResult",
    "RemovalOutcome",
    "deletion_authority",
    "reconcile_upstream_state",
    "remove_named_receipt",
]
