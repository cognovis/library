"""Distribution-rights composition: the gate every foreign projection passes.

ADR-0011 `Distribution Rights` records four grants independently and composes
them **in a fixed order**:

1. `install_rights` is checked first and governs *both* targets. A recorded
   denial of local installation is not something an operator opt-in may
   override -- the opt-in exists to accept a redistribution risk the operator is
   entitled to accept, not to grant a permission the upstream party withheld.
2. `redistribution_rights` then adds the separate committed-tree restriction.

| `install_rights` | `redistribution_rights` | machine-local | committed |
|---|---|---|---|
| `granted` | `granted` | allowed | allowed |
| `granted` | `unknown` | opt-in, after display | blocked (default) |
| `granted` | `denied` | opt-in, after display | blocked |
| `unknown` | any | opt-in, after display | blocked |
| `denied` | any | blocked; no opt-in overrides | blocked |

`unknown` is the conservative state, not a permissive middle one. It differs
from `denied` only in that it is unfinished work an operator may knowingly
accept for a machine-local target, whereas `denied` is a decision somebody else
already made.

**Durable cache retention is governed by `install_rights`, not by
`fetch_authorization`.** A credential proving endpoint access proves the
provider will serve the bytes now; it says nothing about a right to keep an
indefinite offline copy. Treating a subscriber token as a retention grant is
exactly the conflation the rest of this model exists to prevent.

**How the block reason is chosen**, because two vocabulary entries look
interchangeable until the "Cleared by" column is read:

| Situation | Reason | Why |
|---|---|---|
| `install_rights: unknown` | `license-unknown` | Cleared by recording an evidence source, and it blocks both targets, so "choosing a machine-local target" does not clear it |
| `install_rights: denied` | `license-denied` | A recorded grant forbids this use |
| install granted, redistribution not granted | `redistribution-blocked` | Literally "fetch allowed, redistribution not", and cleared by "a rights change, or choosing a machine-local target" |

**Display before mutation is mechanical here, not a convention.** An
`OperatorOptIn` carries the digest of the exact rights statement it
acknowledges. `project` refuses an opt-in whose digest does not match the
statement this decision displays, so an opt-in collected against some other
item, some other target, or an older rights state cannot authorize this one.
The alternative -- a boolean flag -- would let a caller pass `True` without ever
rendering anything, which is the failure this criterion exists to prevent.

This module names no provider, no provider kind, and no upstream URL. It
consumes recorded grants and returns decisions; where those grants came from is
the catalog's business.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .inventory import (
    PROJECTION_TARGETS,
    RIGHTS_GRANTS,
    Rights,
)

#: The act a decision governs. The two projection targets are the schema's own
#: `projection_eligibility` keys; retention and derivation are separate acts
#: with their own rules and are therefore never folded into that field.
CACHE_RETENTION = "durable_cache_retention"
DERIVATIVE = "derivative"

ALLOWED = "allowed"
BLOCKED = "blocked"
OPT_IN_REQUIRED = "operator-opt-in-required"


class RightsRefusal(RuntimeError):
    """Base class for a refusal produced by the rights gate."""


class ProjectionRefused(RightsRefusal):
    """A projection was refused. Nothing was mutated."""

    def __init__(self, message: str, decision: "RightsDecision") -> None:
        super().__init__(message)
        self.decision = decision


class DerivativeRefused(RightsRefusal):
    """A derivative was refused, so no adapted artifact was created at all.

    The unmodified upstream artifact remains available on `available_artifact`,
    and the unresolved rights state is retained in `provenance`.
    """

    def __init__(
        self,
        message: str,
        decision: "RightsDecision",
        provenance: Mapping[str, Any],
        available_artifact: Mapping[str, bytes],
    ) -> None:
        super().__init__(message)
        self.decision = decision
        self.provenance = dict(provenance)
        self.available_artifact = available_artifact


@dataclass(frozen=True)
class RightsDecision:
    """One composed decision about one act, with the evidence that produced it."""

    act: str
    state: str
    governing_grant: str
    governing_state: str
    evidence_source: str | None
    block_reason: str | None
    rights: Rights

    def display(self) -> str:
        """The operator-facing rights statement for this act.

        Every grant is shown, not only the governing one, because an operator
        deciding whether to accept an unresolved state needs to see what else is
        unresolved. The governing grant and the consequence are named
        explicitly so the message is actionable rather than a status dump.
        """
        lines = [
            f"act: {self.act}",
            f"decision: {self.state}",
            "recorded distribution rights:",
        ]
        lines.extend(f"  {grant.describe()}" for grant in self.rights.grants())
        lines.append(
            f"governing grant: {self.governing_grant}={self.governing_state}; "
            f"evidence source: {self.evidence_source or 'none recorded'}"
        )
        if self.block_reason:
            lines.append(f"block reason: {self.block_reason}")
        lines.append(f"consequence: {_CONSEQUENCE[self.state]}")
        return "\n".join(lines)

    def display_digest(self) -> str:
        """Content digest of the displayed statement, which binds an opt-in."""
        return hashlib.sha256(self.display().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "act": self.act,
            "state": self.state,
            "governing_grant": self.governing_grant,
            "governing_state": self.governing_state,
            "evidence_source": self.evidence_source,
            "block_reason": self.block_reason,
        }


_CONSEQUENCE = {
    ALLOWED: "the content may be written to this target",
    OPT_IN_REQUIRED: (
        "the content is written only after an explicit operator opt-in that "
        "acknowledges this rights state"
    ),
    BLOCKED: "nothing is written to this target",
}


@dataclass(frozen=True)
class OperatorOptIn:
    """An operator's explicit acceptance of a displayed rights state.

    `acknowledged_display_digest` is the digest of the statement the operator
    was shown. It is what makes "displayed before mutation" checkable after the
    fact instead of a claim in a docstring.
    """

    operator: str
    acknowledged_display_digest: str
    acknowledged_at: str

    def __post_init__(self) -> None:
        for name in ("operator", "acknowledged_display_digest", "acknowledged_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"OperatorOptIn.{name} is required")


@dataclass(frozen=True)
class ProjectionOutcome:
    """What a completed projection did, in the order it did it."""

    decision: RightsDecision
    display: str
    events: tuple[str, ...]
    result: Any = None


@dataclass(frozen=True)
class Derivative:
    """A first-party derivative and the upstream provenance it must retain."""

    files: Mapping[str, bytes]
    provenance: Mapping[str, Any]


def _decision(
    act: str,
    state: str,
    rights: Rights,
    grant_name: str,
    block_reason: str | None,
) -> RightsDecision:
    grant = rights.grant(grant_name)
    return RightsDecision(
        act=act,
        state=state,
        governing_grant=grant.name,
        governing_state=grant.state,
        evidence_source=grant.evidence_source,
        block_reason=block_reason,
        rights=rights,
    )


def evaluate_projection(rights: Rights, target: str) -> RightsDecision:
    """Compose the grants into a projection decision for one target.

    Args:
        rights: The recorded grants for this item.
        target: One of the `projection_eligibility` targets.

    Returns:
        The composed decision, naming the governing grant, its state, and the
        evidence source that resolved it.

    Raises:
        ValueError: when the target is not a recorded projection target.
    """
    if target not in PROJECTION_TARGETS:
        raise ValueError(
            f"unknown projection target {target!r}; "
            f"ADR-0011 records {list(PROJECTION_TARGETS)}"
        )

    install = rights.install_rights
    if install == "denied":
        return _decision(target, BLOCKED, rights, "install_rights", "license-denied")
    if install == "unknown":
        state = BLOCKED if target == "project_committed" else OPT_IN_REQUIRED
        return _decision(target, state, rights, "install_rights", "license-unknown")

    redistribution = rights.redistribution_rights
    if redistribution == "granted":
        grant_name = "redistribution_rights" if target == "project_committed" else "install_rights"
        return _decision(target, ALLOWED, rights, grant_name, None)

    state = BLOCKED if target == "project_committed" else OPT_IN_REQUIRED
    return _decision(
        target, state, rights, "redistribution_rights", "redistribution-blocked"
    )


def projection_eligibility(rights: Rights) -> dict[str, str]:
    """The `projection_eligibility` schema field for one item's rights."""
    return {target: evaluate_projection(rights, target).state for target in PROJECTION_TARGETS}


def evaluate_cache_retention(rights: Rights) -> RightsDecision:
    """Whether authorized bytes may be *kept* across sessions.

    Retention is not a projection: no harness path is touched and nothing is
    installed. It is also not free of rights, which is why it is governed by
    `install_rights` rather than by the fetch grant that produced the bytes.
    """
    install = rights.install_rights
    if install == "denied":
        return _decision(
            CACHE_RETENTION, BLOCKED, rights, "install_rights", "license-denied"
        )
    if install == "unknown":
        return _decision(
            CACHE_RETENTION, OPT_IN_REQUIRED, rights, "install_rights", "license-unknown"
        )
    return _decision(CACHE_RETENTION, ALLOWED, rights, "install_rights", None)


def evaluate_derivative(rights: Rights) -> RightsDecision:
    """Whether a materially adapted first-party derivative may be created.

    Adaptation is itself a licensed act. There is no opt-in path: an operator
    may accept a risk they carry themselves, but creating an adaptation nobody
    granted is not a risk that stops at their machine.
    """
    state = ALLOWED if rights.derivative_rights == "granted" else BLOCKED
    reason = None if state == ALLOWED else _derivative_reason(rights.derivative_rights)
    return _decision(DERIVATIVE, state, rights, "derivative_rights", reason)


def _derivative_reason(grant_state: str) -> str:
    return "license-denied" if grant_state == "denied" else "license-unknown"


def project(
    decision: RightsDecision,
    mutate: Callable[[], Any],
    *,
    opt_in: OperatorOptIn | None = None,
) -> ProjectionOutcome:
    """Perform a projection under one composed decision, or refuse it.

    The rights statement is rendered first, unconditionally, and recorded as the
    first event. `mutate` runs last and only once the decision and the opt-in
    have both been satisfied.

    Args:
        decision: A decision from `evaluate_projection`.
        mutate: The callable that writes content. Never called on a refusal.
        opt_in: The operator's acknowledgement, required when the decision is
            `operator-opt-in-required`.

    Returns:
        The outcome, carrying the displayed statement and the ordered events.

    Raises:
        ProjectionRefused: when the decision is blocked, when a required opt-in
            is absent, or when the opt-in acknowledges a different statement.
    """
    display = decision.display()
    events = ["rights-displayed"]

    if decision.state == BLOCKED:
        raise ProjectionRefused(
            f"{decision.act} is blocked: "
            f"{decision.governing_grant}={decision.governing_state} "
            f"(evidence source: {decision.evidence_source or 'none recorded'}). "
            "No operator opt-in overrides this state.",
            decision,
        )

    if decision.state == OPT_IN_REQUIRED:
        if opt_in is None:
            raise ProjectionRefused(
                f"{decision.act} requires an explicit operator opt-in: "
                f"{decision.governing_grant}={decision.governing_state} "
                f"(evidence source: {decision.evidence_source or 'none recorded'})",
                decision,
            )
        if opt_in.acknowledged_display_digest != decision.display_digest():
            raise ProjectionRefused(
                f"{decision.act}: the operator acknowledged a different rights "
                "statement than the one this decision displays, so the opt-in "
                "does not authorize it",
                decision,
            )
        events.append("operator-opt-in-accepted")

    events.append("projection-authorized")
    result = mutate()
    events.append("content-materialized")
    return ProjectionOutcome(
        decision=decision, display=display, events=tuple(events), result=result
    )


def _provenance(
    rights: Rights, upstream_provenance: Mapping[str, Any], derivative_state: str
) -> dict[str, Any]:
    """Upstream provenance plus the rights state, retained verbatim.

    The rights state travels with the artifact because a derivative refused for
    an unresolved grant is exactly the case where somebody later asks "why is
    there no adapted copy" -- and the answer has to be in the record, not in a
    log line that scrolled away.
    """
    provenance = dict(upstream_provenance)
    provenance["rights"] = rights.to_dict()
    provenance["rights_evidence"] = {
        name: rights.grant(name).evidence_source for name in RIGHTS_GRANTS
    }
    provenance["derivative_state"] = derivative_state
    return provenance


def create_derivative(
    rights: Rights,
    upstream_artifact: Mapping[str, bytes],
    adapt: Callable[[Mapping[str, bytes]], Mapping[str, bytes]],
    *,
    upstream_provenance: Mapping[str, Any],
) -> Derivative:
    """Create a first-party derivative, or refuse and create nothing.

    Args:
        rights: The recorded grants for the upstream artifact.
        upstream_artifact: The unmodified upstream files.
        adapt: The adaptation. Never called without a recorded grant.
        upstream_provenance: Upstream identity and pin, retained on the result.

    Returns:
        The derivative and its provenance, including the rights state.

    Raises:
        DerivativeRefused: when `derivative_rights` is not `granted`. The
            refusal carries the unmodified upstream artifact and the retained
            rights state.
    """
    decision = evaluate_derivative(rights)
    if decision.state != ALLOWED:
        raise DerivativeRefused(
            "no adapted artifact is created: "
            f"derivative_rights={decision.governing_state} "
            f"(evidence source: {decision.evidence_source or 'none recorded'}). "
            "Only the unmodified upstream artifact is available.",
            decision,
            _provenance(rights, upstream_provenance, "refused"),
            upstream_artifact,
        )

    adapted = dict(adapt(upstream_artifact))
    if not adapted:
        raise ValueError("an adaptation must produce at least one file")
    return Derivative(
        files=adapted,
        provenance=_provenance(rights, upstream_provenance, "created"),
    )
