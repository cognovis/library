"""Admission evaluation: what was not installed, and exactly why.

ADR-0011 models `admission_state`, `executable_admission`, `cache_state`, and
`projection_eligibility` as **orthogonal** states. The load-bearing case is an
item that is lawfully fetched, verified, and durable on this machine while its
committed projection stays forbidden. Any model that treats "cached" as
"installable" cannot express it, so nothing here collapses the axes.

Admission is a separate pass over normalized inventory rather than a step inside
normalization, and that is a design decision rather than a packaging one:
**discovery never implies permission.** Normalization answers "what exists at
this provider"; this module answers "what may this scope do with it", which
depends on scope policy the provider knows nothing about — target runtimes,
required trust, configured credentials, and the operator's own admission
decisions. Evaluating during discovery would make an item's recorded state a
function of whoever happened to enumerate it first.

Evaluation is pure: it returns decisions and a new inventory, and never mutates
the discovered items.

**How `admission_state` is derived.** One rule, applied after every reason is
collected:

| State | Condition |
|---|---|
| `installable` | No block reason, and at least one projection target is `allowed` |
| `blocked` | At least one block reason |
| `discoverable` | Neither — nothing is wrong and nothing is yet permitted |

`blocked` is deliberately not reserved for hopeless cases. It is a first-class,
queryable state meaning "you did not get this, here is why", and an operator
must be able to ask that question without re-running discovery. An item whose
`install_rights` are unresolved is blocked *and* carries a machine-local
opt-in path in `projection_eligibility` — those are two different facts about
two different axes, and the ADR keeps them in two different fields for exactly
this case.

**Two vocabulary readings recorded rather than assumed**, because the closed
list admits no additions without an ADR:

- A `refused` executable admission records `untrusted-source`, not
  `executable-admission-pending`. The pending entry is cleared by "the
  Executable Admission gate"; a refusal has already been through that gate, and
  what it needs is the explicit review that clears `untrusted-source`. Calling a
  refusal "pending" would also make a decided state read as an undone one.
- `runtime_compatibility: unknown` blocks nothing by itself — the ADR schema
  table says so explicitly — so `incompatible-runtime` is recorded only when a
  declared, known compatibility set excludes every declared target runtime.

This module names no provider, no provider kind, and no upstream URL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .executable_admission import (
    ExecutableAdmissionLedger,
    executable_admission_for_item,
)
from .inventory import (
    BLOCK_REASONS,
    BlockReason,
    NormalizedInventory,
    NormalizedItem,
    PROJECTION_TARGETS,
    TRUST_STATES,
)
from .rights import evaluate_projection, projection_eligibility

#: Trust ordering. `unreviewed` is the floor, so a scope that requires nothing
#: blocks nothing on trust.
_TRUST_RANK = {state: rank for rank, state in enumerate(("unreviewed", "reviewed", "first-party"))}

#: Reasons produced by the rights composition. Every other reason is a
#: non-rights block and floors projection eligibility on every target, because
#: admission is a precondition of installability.
_RIGHTS_REASONS = frozenset({"license-unknown", "license-denied", "redistribution-blocked"})

#: A compatibility value that excludes nothing (ADR-0011 schema table).
_UNKNOWN_RUNTIME = "unknown"


@dataclass(frozen=True)
class AdmissionContext:
    """The scope policy an admission decision is made against.

    Every field is empty or permissive by default, so an unconfigured scope
    blocks only on rights and on executable admission — the two things the
    provider's own record already decides. A scope that declares a policy gets
    it enforced; a scope that declares none is not given a synthetic one.
    """

    target_runtimes: tuple[str, ...] = ()
    required_trust: str = "unreviewed"
    required_auth_references: tuple[str, ...] = ()
    satisfied_auth_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.required_trust not in TRUST_STATES:
            raise ValueError(
                f"required_trust must be one of {list(TRUST_STATES)}, "
                f"got {self.required_trust!r}"
            )
        for name in (
            "target_runtimes",
            "required_auth_references",
            "satisfied_auth_references",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def unsatisfied_auth(self) -> tuple[str, ...]:
        satisfied = set(self.satisfied_auth_references)
        return tuple(
            reference
            for reference in self.required_auth_references
            if reference not in satisfied
        )


@dataclass(frozen=True)
class AdmissionDecision:
    """One item's evaluated admission, with every reason and its evidence."""

    qualified_identity: str
    admission_state: str
    block_reasons: tuple[BlockReason, ...]
    executable_admission: str
    projection_eligibility: Mapping[str, str]

    def reason_values(self) -> tuple[str, ...]:
        return tuple(reason.reason for reason in self.block_reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "qualified_identity": self.qualified_identity,
            "admission_state": self.admission_state,
            "block_reasons": [reason.to_dict() for reason in self.block_reasons],
            "executable_admission": self.executable_admission,
            "projection_eligibility": dict(self.projection_eligibility),
        }


@dataclass(frozen=True)
class AdmissionReport:
    """The evaluated inventory plus every decision, queryable by identity."""

    inventory: NormalizedInventory
    decisions: Mapping[str, AdmissionDecision] = field(default_factory=dict)

    def blocked_identities(self) -> tuple[str, ...]:
        return tuple(
            identity
            for identity, decision in self.decisions.items()
            if decision.admission_state == "blocked"
        )

    def reasons_for(self, identity: str) -> tuple[BlockReason, ...]:
        """Why this item was not installed, without re-running discovery."""
        return self.decisions[identity].block_reasons


def _rights_reasons(item: NormalizedItem) -> list[BlockReason]:
    """The reasons produced by composing this item's grants.

    Only the governing grant produces a reason. Reporting a redistribution
    problem underneath an installation denial would suggest that resolving the
    redistribution question changes anything, and it does not.
    """
    reasons: list[BlockReason] = []
    seen: set[str] = set()
    for target in PROJECTION_TARGETS:
        decision = evaluate_projection(
            item.rights, target, subject=item.qualified_identity()
        )
        if decision.block_reason is None or decision.block_reason in seen:
            continue
        seen.add(decision.block_reason)
        reasons.append(
            BlockReason(
                reason=decision.block_reason,
                evidence=(
                    f"{decision.governing_grant} resolves to "
                    f"{decision.governing_state} for this item"
                ),
                source=(
                    decision.evidence_source
                    or "no evidence source is recorded for this grant"
                ),
                detail=f"{target}: {decision.state}",
            )
        )
    return reasons


def _runtime_reason(item: NormalizedItem, context: AdmissionContext) -> BlockReason | None:
    if not context.target_runtimes:
        return None
    declared = set(item.runtime_compatibility)
    if _UNKNOWN_RUNTIME in declared:
        return None
    if declared & set(context.target_runtimes):
        return None
    return BlockReason(
        reason="incompatible-runtime",
        evidence=(
            f"declared runtime compatibility {sorted(declared)} excludes every "
            f"target runtime {sorted(context.target_runtimes)}"
        ),
        source="the item's declared runtime_compatibility and this scope's targets",
    )


def _trust_reason(
    item: NormalizedItem, context: AdmissionContext, executable_admission: str
) -> BlockReason | None:
    if executable_admission == "refused":
        return BlockReason(
            reason="untrusted-source",
            evidence=(
                "executable admission was refused for the reviewed content digest; "
                "re-admission is a new decision on new evidence"
            ),
            source="the scope operator's executable-admission ledger",
        )
    if _TRUST_RANK[item.trust_state] < _TRUST_RANK[context.required_trust]:
        return BlockReason(
            reason="untrusted-source",
            evidence=(
                f"trust_state={item.trust_state}, and this scope requires "
                f"{context.required_trust}"
            ),
            source="the item's recorded trust_state and this scope's policy",
        )
    return None


def evaluate_item(
    item: NormalizedItem,
    context: AdmissionContext,
    *,
    ledger: ExecutableAdmissionLedger | None = None,
    contents: Mapping[str, Mapping[str, bytes]] | None = None,
) -> AdmissionDecision:
    """Evaluate one normalized item against one scope policy.

    Args:
        item: A normalized item, as discovered.
        context: The scope policy this admission is judged against.
        ledger: The operator's executable-admission decisions. An absent ledger
            is an empty one, never a permissive one.
        contents: Qualified identity to the item's complete content, from which
            the admission-binding digest is computed.

    Returns:
        The decision. The item itself is never modified.

    An executable item's own `executable_admission` field is **not** consulted.
    Review demonstrated the reason: a normalized item carrying
    `executable_admission="admitted"` -- a value any producer of an item can
    write -- evaluated to `installable` with no reviewer, no digest, and no
    permission surface behind it. Authority for an executable decision lives in
    the operator's ledger, so the absence of a ledger entry for the current
    content is `pending`, which is what the field would have had to prove.
    """
    executable_admission = executable_admission_for_item(
        item, ledger or ExecutableAdmissionLedger(), contents or {}
    )

    reasons: list[BlockReason] = list(_rights_reasons(item))

    for reference in context.unsatisfied_auth():
        reasons.append(
            BlockReason(
                reason="authentication-required",
                evidence=(
                    f"credential reference {reference!r} is required by this provider "
                    "and is not configured for this scope"
                ),
                source="the provider's declared auth_requirements and this scope's configuration",
            )
        )

    runtime_reason = _runtime_reason(item, context)
    if runtime_reason is not None:
        reasons.append(runtime_reason)

    if executable_admission == "pending":
        reasons.append(
            BlockReason(
                reason="executable-admission-pending",
                evidence=(
                    f"{item.library_type} is executable and no admission decision is "
                    "recorded for its current content digest"
                ),
                source="the scope operator's executable-admission ledger",
            )
        )

    trust_reason = _trust_reason(item, context, executable_admission)
    if trust_reason is not None:
        reasons.append(trust_reason)

    if item.provider_availability.state == "unavailable":
        detail = item.provider_availability.reason or "no reason recorded"
        reasons.append(
            BlockReason(
                reason="content-unavailable",
                evidence=(
                    f"provider availability was {item.provider_availability.state} at "
                    f"{item.provider_availability.observed_at}: {detail}"
                ),
                source="the provider availability observation recorded on this item",
            )
        )

    ordered = tuple(sorted(reasons, key=lambda entry: BLOCK_REASONS.index(entry.reason)))

    eligibility = projection_eligibility(item.rights, subject=item.qualified_identity())
    if any(reason.reason not in _RIGHTS_REASONS for reason in ordered):
        eligibility = {target: "blocked" for target in PROJECTION_TARGETS}

    if ordered:
        admission_state = "blocked"
    elif any(state == "allowed" for state in eligibility.values()):
        admission_state = "installable"
    else:
        admission_state = "discoverable"

    return AdmissionDecision(
        qualified_identity=item.qualified_identity(),
        admission_state=admission_state,
        block_reasons=ordered,
        executable_admission=executable_admission,
        projection_eligibility=eligibility,
    )


def apply_decision(item: NormalizedItem, decision: AdmissionDecision) -> NormalizedItem:
    """A copy of one item carrying its evaluated admission fields."""
    payload = item.to_dict()
    payload["admission_state"] = decision.admission_state
    payload["block_reasons"] = [reason.to_dict() for reason in decision.block_reasons]
    payload["executable_admission"] = decision.executable_admission
    payload["projection_eligibility"] = dict(decision.projection_eligibility)
    return NormalizedItem.from_dict(payload)


def evaluate_inventory(
    inventory: Sequence[NormalizedItem] | NormalizedInventory,
    context: AdmissionContext,
    *,
    ledger: ExecutableAdmissionLedger | None = None,
    contents: Mapping[str, Mapping[str, bytes]] | None = None,
) -> AdmissionReport:
    """Evaluate a whole normalized inventory against one scope policy."""
    decisions: dict[str, AdmissionDecision] = {}
    evaluated: list[NormalizedItem] = []
    for item in inventory:
        decision = evaluate_item(item, context, ledger=ledger, contents=contents)
        decisions[decision.qualified_identity] = decision
        evaluated.append(apply_decision(item, decision))
    return AdmissionReport(inventory=NormalizedInventory(evaluated), decisions=decisions)
