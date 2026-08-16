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

That rule answers "is any target eligible?", which is the question a listing
asks. A caller that names `requested_target` asks a different one — "is *this*
target eligible?" — and gets it answered by the same evaluator: a rights reason
governing only some other target is still reported, but no longer decides, and a
requested target at `operator-opt-in-required` resolves `installable`. That is
the weaker check by design; the projection presenter is what enforces the opt-in.
Both readings live in one function so that a listing and an install can never
become two independent judgements about the same item.

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

from .classification import DEFAULT_MATURITY, MATURITIES, is_unclassified
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
    #: Which maturities this scope promotes to `installable`. The default is the
    #: stable one alone, because an upstream collection that says "in progress"
    #: has stated its own confidence and an inventory that installs it anyway has
    #: overruled the author silently. Promoting one is an explicit act: a scope
    #: adds the maturity here, or a Workspace names the item. It is deliberately
    #: NOT a filter -- an unadmitted item stays in the inventory as
    #: `discoverable`, because hiding it would make the inventory disagree with
    #: the source it claims to describe.
    admitted_maturities: tuple[str, ...] = (DEFAULT_MATURITY,)

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
            "admitted_maturities",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        unknown = sorted(set(self.admitted_maturities) - set(MATURITIES))
        if unknown:
            raise ValueError(
                f"admitted_maturities must come from {list(MATURITIES)}, got {unknown}"
            )
        if not self.admitted_maturities:
            raise ValueError(
                "a scope that admits no maturity can install nothing; record the "
                "maturities it does admit"
            )

    def admits_maturity(self, maturity: str) -> bool:
        return maturity in self.admitted_maturities

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

    The deduplication key is `(reason, state)`, not the reason alone: one grant
    governs every target and therefore produces one reason string, but it does
    not resolve every target to the same state. `install_rights: unknown` is
    `license-unknown` on both targets while blocking the committed one and
    leaving the machine-local one at `operator-opt-in-required` -- two facts, and
    a key on the string alone kept whichever came first and silently discarded
    the opt-in path a caller could still take. `install_rights: denied` still
    produces exactly one reason, because there both targets really do resolve to
    the same state; nothing here is noisier than the facts are.
    """
    reasons: list[BlockReason] = []
    seen: set[tuple[str, str]] = set()
    for target in PROJECTION_TARGETS:
        decision = evaluate_projection(
            item.rights, target, subject=item.qualified_identity()
        )
        if decision.block_reason is None:
            continue
        key = (decision.block_reason, decision.state)
        if key in seen:
            continue
        seen.add(key)
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
    admission_pending_is_blocking: bool = True,
    requested_target: str | None = None,
) -> AdmissionDecision:
    """Evaluate one normalized item against one scope policy.

    Args:
        item: A normalized item, as discovered.
        context: The scope policy this admission is judged against.
        ledger: The operator's executable-admission decisions. An absent ledger
            is an empty one, never a permissive one.
        contents: Qualified identity to the item's complete content, from which
            the admission-binding digest is computed.
        requested_target: The projection target the caller is actually asking
            about. Omitted, this answers "is any target eligible?", which is the
            question an inventory listing asks. Named, it answers "is *this*
            target eligible?", which is the question an install asks.

    Returns:
        The decision. The item itself is never modified.

    Raises:
        ValueError: when `requested_target` is not a recorded projection target.

    An executable item's own `executable_admission` field is **not** consulted.
    Review demonstrated the reason: a normalized item carrying
    `executable_admission="admitted"` -- a value any producer of an item can
    write -- evaluated to `installable` with no reviewer, no digest, and no
    permission surface behind it. Authority for an executable decision lives in
    the operator's ledger, so the absence of a ledger entry for the current
    content is `pending`, which is what the field would have had to prove.

    **Both questions are answered here, by one evaluator.** A target-aware
    install used to be unreachable: every rights reason decided the summary,
    including one that governs only the target the operator did not ask for, so
    an item whose committed projection is blocked and whose machine-local
    projection is merely opt-in-required was `blocked` for both. Answering that
    at the CLI instead would have made the listing and the install two
    independent judgements about the same item, which is how they drift.

    A named target that is `operator-opt-in-required` resolves `installable`, and
    that is deliberately the **weaker** check: it says the operator may ask,
    not that the act is authorized. `install_marketplace_item` renders the rights
    statement through its presenter and refuses with `ProjectionRefused` without
    an acknowledgement of that exact statement, and it remains the gate that
    enforces the opt-in.
    """
    if requested_target is not None and requested_target not in PROJECTION_TARGETS:
        raise ValueError(
            f"unknown projection target {requested_target!r}; "
            f"ADR-0011 records {list(PROJECTION_TARGETS)}"
        )

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
        # Two different pending facts, worded apart. Discovery is non-executing
        # and does not fetch whole items, so it usually has no digest to check a
        # decision against -- and a reason that claims "no decision is recorded
        # for its current content digest" when no digest was ever computed sends
        # an operator looking for a ledger entry they could not have made. The
        # state is `pending` either way, because "we did not compute what this is"
        # must never be more permissive than "we computed it and nobody reviewed
        # it".
        digested = bool((contents or {}).get(item.qualified_identity()))
        evidence = (
            (
                f"{item.library_type} from this steward is admission-required and "
                "no admission decision is recorded for its current content digest"
            )
            if digested
            else (
                f"{item.library_type} from this steward is admission-required and "
                "this evaluation holds no content for it, so no decision could be "
                "checked; the decision binds to bytes"
            )
        )
        reasons.append(
            BlockReason(
                reason="executable-admission-pending",
                evidence=evidence,
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

    # `admission_pending_is_blocking=False` is for a caller whose *next* step is
    # the cache transaction, which digests the bytes it will write, consults the
    # operator's durable ledger, and refuses with the exact remedy command. Such a
    # caller wants every other axis judged here -- rights, maturity, runtime,
    # classification, availability -- without the admission axis, which it cannot
    # answer, swallowing them.
    #
    # The reason stays in `block_reasons` either way: it is a fact about the item
    # and suppressing it would hide from the caller that a decision is still
    # owed. Only its effect on the summary state is deferred, and only for a
    # caller that has somewhere better to answer it.
    deciding = (
        ordered
        if admission_pending_is_blocking
        else tuple(entry for entry in ordered if entry.reason != "executable-admission-pending")
    )

    # The same precedent, applied to the target axis. A caller that named the
    # target it is asking about is judged on that target: when the requested one
    # is not blocked by rights, a rights reason that governs only the other
    # target is reported but does not decide. When the requested target *is*
    # rights-blocked, every rights reason keeps deciding and the refusal is
    # exactly the one it was before.
    if requested_target is not None:
        requested = evaluate_projection(
            item.rights, requested_target, subject=item.qualified_identity()
        )
        if requested.state != "blocked":
            deciding = tuple(
                entry for entry in deciding if entry.reason not in _RIGHTS_REASONS
            )

    eligibility = projection_eligibility(item.rights, subject=item.qualified_identity())
    if any(reason.reason not in _RIGHTS_REASONS for reason in deciding):
        eligibility = {target: "blocked" for target in PROJECTION_TARGETS}

    maturity = str(item.classification.get("maturity") or DEFAULT_MATURITY)

    if is_unclassified(item.library_type):
        # ADR-0011 `Mixed external bundles`: a member fitting no existing type is
        # discoverable and unclassified. It is deliberately NOT `blocked` -- a
        # block reason asserts something was observed about the content, and
        # nothing was; the Library simply has no type to install it as. It is
        # equally deliberately never `installable`, because "install this, we do
        # not know what it is" is how a generic catch-all primitive gets created
        # by accident.
        eligibility = {target: "blocked" for target in PROJECTION_TARGETS}
        admission_state = "blocked" if deciding else "discoverable"
    elif deciding:
        admission_state = "blocked"
    elif not context.admits_maturity(maturity):
        # Not a block: nothing was observed about this item that forbids it, and
        # a `blocked` state carries evidence that something was. The item is
        # listed, classified, and available to an explicit decision -- it is just
        # not promoted by default.
        eligibility = {target: "blocked" for target in PROJECTION_TARGETS}
        admission_state = "discoverable"
    elif requested_target is not None:
        # The named target answers for itself. `operator-opt-in-required` counts
        # as installable here because the operator may ask for it; the presenter
        # and `ProjectionRefused` decide whether they get it.
        admission_state = (
            "discoverable" if eligibility[requested_target] == "blocked" else "installable"
        )
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
