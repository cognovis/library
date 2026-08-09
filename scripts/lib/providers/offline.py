"""The offline operation table of ADR-0011 `Offline Semantics`.

Offline operation is **additive and repair-only**. The table is data here rather
than a condition at each call site, because the failure this prevents is not one
wrong branch: it is the sixth caller, written a year later, that never learned
there was a table.

| Operation | Provider unavailable |
|---|---|
| Reinstall from verified cache | allowed |
| Integrity verification | allowed |
| Status, with freshness `unknown` | allowed |
| Explicit named removal of a named receipt | allowed |
| Upgrade | refused |
| Re-pin | refused |
| Ownership-derived prune | refused, fail closed |
| `--prune --apply` | refused, fail closed |
| Automatic garbage collection | refused, fail closed |

`verified local integrity` and `unknown remote freshness` are separate reported
facts and are never merged into one "ok". `status_freshness` therefore never
returns `current` for a source whose currency has not actually been compared,
and never returns it at all for a pin-only source.

**Reachability is not a complete resolution.** A refused operation is permitted
only against a `ResolutionEvidence` observation that is *conclusive*: the source
answered, the answer was complete, and no part of it was withheld by changed
authorization. A bare `ProviderAvailability` carries no completeness evidence at
all, so it can never satisfy a destructive verdict. Review demonstrated the
alternative: an observation whose own `degraded_reason` said "inventory is
incomplete or truncated" passed the prune gate, because the gate saw only the
transport state beside it.

**Boundary.** This module decides whether the offline table refuses an
operation. It does not implement retention, garbage collection, or purge; those
are `CL-uliw`, and garbage collection carries further fail-closed preconditions
that a verdict from here does not satisfy on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .inventory import ProviderAvailability

#: Operations the ADR permits while a source is unreachable.
ALLOWED_OFFLINE_OPERATIONS: tuple[str, ...] = (
    "reinstall-from-cache",
    "integrity-verification",
    "status",
    "explicit-named-removal",
)

#: Operations the ADR refuses while a source is unreachable.
REFUSED_OFFLINE_OPERATIONS: tuple[str, ...] = (
    "upgrade",
    "re-pin",
    "ownership-derived-prune",
    "prune-apply",
    "automatic-garbage-collection",
)

OPERATIONS: tuple[str, ...] = (*ALLOWED_OFFLINE_OPERATIONS, *REFUSED_OFFLINE_OPERATIONS)

#: The closed vocabulary of refusal reasons. A refusal names which of the ADR's
#: four rationales applies, so an operator reads why rather than only that.
REFUSAL_REASONS: tuple[str, ...] = (
    "remote-comparison-required",
    "would-substitute-pinned-content",
    "deletion-authority-requires-complete-resolution",
    "re-fetchability-not-proven",
)

_REASON_FOR: Mapping[str, str] = {
    "upgrade": "remote-comparison-required",
    "re-pin": "would-substitute-pinned-content",
    "ownership-derived-prune": "deletion-authority-requires-complete-resolution",
    "prune-apply": "deletion-authority-requires-complete-resolution",
    "automatic-garbage-collection": "re-fetchability-not-proven",
}

_RATIONALE: Mapping[str, str] = {
    "upgrade": "an upgrade requires a remote comparison that cannot be made now",
    "re-pin": (
        "re-pinning without a reachable source would substitute unverified bytes "
        "for the pinned ones"
    ),
    "ownership-derived-prune": (
        "deletion authority derives from a complete resolution, and this resolution "
        "is incomplete"
    ),
    "prune-apply": (
        "deletion authority derives from a complete resolution, and this resolution "
        "is incomplete"
    ),
    "automatic-garbage-collection": (
        "exact re-fetchability is not proven, so collecting now would discard bytes "
        "that cannot be retrieved again"
    ),
}

#: Preconditions a verdict from this module deliberately does not evaluate.
_ADDITIONAL_PRECONDITIONS: Mapping[str, tuple[str, ...]] = {
    "automatic-garbage-collection": (
        "no active receipt in any scope references the object",
        "exact re-fetchability is proven, which for a pin-only source requires a "
        "digest-verified re-fetch confirming the pinned digest is still served",
    ),
}

#: Freshness values. `current` is a claim about the source, so it is reachable
#: only from an actual comparison; `pin-only` records that no such comparison
#: exists for this source at all.
FRESHNESS_STATES: tuple[str, ...] = ("current", "unknown", "pin-only")


@dataclass(frozen=True)
class ResolutionEvidence:
    """One source-scoped observation of an inventory, with its completeness.

    `complete` and `reduced_by_authorization` are separate from availability
    because a reachable source can still answer partially -- a truncated listing
    or one narrowed by changed credentials -- and treating that answer as
    complete is how an item gets recorded as vanished when it never went
    anywhere, and how a prune acquires authority it was never granted.

    `provider_identity` is required. An observation without it cannot say
    *whose* inventory it describes, and review demonstrated the consequence: one
    source's complete listing marked another source's receipts as vanished.
    """

    provider_identity: str
    availability: ProviderAvailability
    listed_identities: frozenset[str] = field(default_factory=frozenset)
    complete: bool = False
    reduced_by_authorization: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.provider_identity, str) or not self.provider_identity.strip():
            raise ValueError("ResolutionEvidence.provider_identity is required")
        if not isinstance(self.availability, ProviderAvailability):
            raise ValueError("ResolutionEvidence.availability must be observed")
        object.__setattr__(self, "listed_identities", frozenset(self.listed_identities))

    def degraded_reason(self) -> str | None:
        """Why this observation cannot support a destructive conclusion, or None."""
        if self.availability.state != "available":
            return (
                f"source is {self.availability.state}"
                f"{': ' + self.availability.reason if self.availability.reason else ''}"
            )
        if not self.complete:
            return "inventory is incomplete or truncated"
        if self.reduced_by_authorization:
            return "inventory is reduced by changed authorization"
        return None

    @property
    def conclusive(self) -> bool:
        """True when absence from this listing actually means absence upstream."""
        return self.degraded_reason() is None

    def describe(self) -> str:
        reason = self.degraded_reason()
        state = (
            f"source {self.provider_identity!r} state {self.availability.state!r} "
            f"at {self.availability.observed_at}"
        )
        return state if reason is None else f"{state}; {reason}"


class OfflineRefusal(RuntimeError):
    """One refused operation, carrying its operation and typed reason.

    It is an exception rather than a returned flag because every refused entry
    in the table is fail-closed: a caller that ignores a returned value performs
    the deletion or the substitution anyway.
    """

    def __init__(self, operation: str, reason: str, detail: str) -> None:
        super().__init__(f"{operation} is refused [{reason}]: {detail}")
        self.operation = operation
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class OperationVerdict:
    """Whether the offline table permits one operation right now."""

    operation: str
    allowed: bool
    reason: str | None
    evidence: str
    additional_preconditions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.operation not in OPERATIONS:
            raise ValueError(
                f"unknown operation {self.operation!r}; the table records {list(OPERATIONS)}"
            )
        if self.reason is not None and self.reason not in REFUSAL_REASONS:
            raise ValueError(f"unknown refusal reason: {self.reason!r}")
        if self.allowed and self.reason is not None:
            raise ValueError("an allowed operation carries no refusal reason")
        if not self.allowed and self.reason is None:
            raise ValueError("a refused operation must name its typed reason")

    def raise_for_refusal(self) -> "OperationVerdict":
        if not self.allowed:
            raise OfflineRefusal(self.operation, str(self.reason), self.evidence)
        return self


def _availability_text(availability: ProviderAvailability) -> str:
    reason = f"; {availability.reason}" if availability.reason else ""
    return f"source state {availability.state!r} observed at {availability.observed_at}{reason}"


def _as_evidence(
    value: ProviderAvailability | ResolutionEvidence,
) -> tuple[ProviderAvailability, ResolutionEvidence | None]:
    if isinstance(value, ResolutionEvidence):
        return value.availability, value
    if isinstance(value, ProviderAvailability):
        return value, None
    raise ValueError(
        "evidence must be an observed ProviderAvailability or a source-scoped "
        "ResolutionEvidence value"
    )


def evaluate_operation(
    operation: str, evidence: ProviderAvailability | ResolutionEvidence
) -> OperationVerdict:
    """Apply the offline table to one operation.

    Only a *conclusive* observation permits a refused-row operation. Transport
    reachability alone does not: `degraded` is refused for the same reason
    `unavailable` is, and so is an `available` source whose listing was
    truncated or narrowed by changed authorization. A bare
    `ProviderAvailability` carries no completeness evidence, so it is treated as
    the absence of evidence rather than as its presence.
    """
    if operation not in OPERATIONS:
        raise ValueError(
            f"unknown operation {operation!r}; the table records {list(OPERATIONS)}"
        )
    availability, observation = _as_evidence(evidence)
    text = observation.describe() if observation is not None else _availability_text(availability)
    extra = _ADDITIONAL_PRECONDITIONS.get(operation, ())

    if operation in ALLOWED_OFFLINE_OPERATIONS:
        return OperationVerdict(operation, True, None, text, extra)

    if observation is None:
        return OperationVerdict(
            operation,
            False,
            _REASON_FOR[operation],
            f"{_RATIONALE[operation]}; no source-scoped inventory observation was "
            f"supplied, and reachability alone is not a complete resolution ({text})",
            extra,
        )
    if observation.conclusive:
        return OperationVerdict(operation, True, None, text, extra)
    return OperationVerdict(
        operation,
        False,
        _REASON_FOR[operation],
        f"{_RATIONALE[operation]} ({text})",
        extra,
    )


def require_operation(
    operation: str, evidence: ProviderAvailability | ResolutionEvidence
) -> OperationVerdict:
    """Return the verdict, or raise `OfflineRefusal` when the table refuses."""
    return evaluate_operation(operation, evidence).raise_for_refusal()


def status_freshness(
    availability: ProviderAvailability,
    *,
    revisionless: bool,
    revision_matches: bool | None = None,
) -> str:
    """Report remote freshness as a fact, separate from local integrity.

    Args:
        availability: The last observation of the source.
        revisionless: True when the source has no immutable revision identity.
            Such a source is pin-only: it cannot report currency at all, because
            the only comparison available is "the current bytes differ from your
            pin", which is drift and not a freshness signal.
        revision_matches: The outcome of an actual revision comparison. `None`
            means no comparison was made, which is `unknown` rather than
            `current` -- the default is deliberately the honest one.
    """
    if availability.state != "available":
        return "unknown"
    if revisionless:
        return "pin-only"
    if revision_matches is None:
        return "unknown"
    return "current" if revision_matches else "unknown"
