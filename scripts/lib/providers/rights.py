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
opt-in-required act is authorized only through a `present` callback: `project`
renders the statement, issues a single-use `RightsPresentation`, hands it to the
presenter, and accepts only an acknowledgement carrying that presentation's
token and digest. An acknowledgement therefore cannot exist unless this module
rendered the statement first. Two weaker designs were tried and both were broken
by review: a boolean flag can be passed without rendering anything, and a
digest-bearing value can be self-minted from a publicly computable digest with
nothing ever shown.

The statement names the **subject** -- the qualified identity of the item --
alongside the target and every grant, so an acknowledgement of one item never
carries to another.

The subject is load-bearing and was added after review. Rights are recorded per
provider, so every item from one provider shares one rights record; without the
subject in the statement, two different items produced byte-identical displays
and one acknowledgement authorized the projection of items the operator had
never seen. A reviewer demonstrated exactly that replay.

**A decision is not authority; the recorded rights are.** `project` re-derives
the decision from `decision.rights` immediately before mutating and refuses any
decision that does not match. A caller-constructed `RightsDecision` claiming
`state="allowed"` over `install_rights="denied"` was shown to write forbidden
bytes when the boundary trusted the value it was handed.

What this module deliberately does **not** attempt: proving *who* the operator
is. An acknowledgement is bound to content, not to an identity, because
authenticating an operator is credential handling, which is out of scope for
this gate and gated on a separate human security review. `present` narrows the
gap by making the library itself render the statement and collect the response
in the same call.

This module names no provider, no provider kind, and no upstream URL. It
consumes recorded grants and returns decisions; where those grants came from is
the catalog's business.
"""

from __future__ import annotations

import hashlib
import secrets
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

    subject: str
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
        unresolved. The subject, the governing grant, and the consequence are
        named explicitly so the message is actionable rather than a status dump,
        and so the digest of this text binds the acknowledgement to this item.
        """
        lines = [
            f"subject: {self.subject}",
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
            "subject": self.subject,
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
class RightsPresentation:
    """A rendered rights statement, issued by this module and good once.

    The `token` is what an acknowledgement must carry. It cannot be guessed and
    it cannot be obtained without this module having rendered `statement`, which
    is what turns "displayed before mutation" from a convention into a fact.
    Review demonstrated the weaker design: an acknowledgement built from a
    publicly computable digest authorized a mutation with nothing ever shown.
    """

    statement: str
    display_digest: str
    token: str

    def acknowledge(self, *, operator: str, acknowledged_at: str) -> "OperatorOptIn":
        """The operator's acceptance of exactly this presented statement."""
        return OperatorOptIn(
            operator=operator,
            acknowledged_display_digest=self.display_digest,
            acknowledged_at=acknowledged_at,
            presentation_token=self.token,
        )


@dataclass(frozen=True)
class OperatorOptIn:
    """An operator's explicit acceptance of a displayed rights state.

    `acknowledged_display_digest` is the digest of the statement the operator
    was shown, and `presentation_token` proves this module is what showed it.
    Together they make "displayed before mutation" checkable after the fact
    instead of a claim in a docstring.
    """

    operator: str
    acknowledged_display_digest: str
    acknowledged_at: str
    presentation_token: str

    def __post_init__(self) -> None:
        for name in (
            "operator",
            "acknowledged_display_digest",
            "acknowledged_at",
            "presentation_token",
        ):
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


def _subject_text(subject: str) -> str:
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError(
            "a rights decision needs the qualified identity of its subject; "
            "without it an acknowledgement binds no particular item"
        )
    return subject


def _decision(
    subject: str,
    act: str,
    state: str,
    rights: Rights,
    grant_name: str,
    block_reason: str | None,
) -> RightsDecision:
    grant = rights.grant(grant_name)
    return RightsDecision(
        subject=_subject_text(subject),
        act=act,
        state=state,
        governing_grant=grant.name,
        governing_state=grant.state,
        evidence_source=grant.evidence_source,
        block_reason=block_reason,
        rights=rights,
    )


def evaluate_projection(rights: Rights, target: str, *, subject: str) -> RightsDecision:
    """Compose the grants into a projection decision for one target.

    Args:
        rights: The recorded grants for this item.
        target: One of the `projection_eligibility` targets.
        subject: The qualified identity of the item being projected. It is
            required, not optional, because it is what makes an acknowledgement
            item-specific.

    Returns:
        The composed decision, naming the governing grant, its state, and the
        evidence source that resolved it.

    Raises:
        ValueError: when the target is not a recorded projection target, or the
            subject is empty.
    """
    if target not in PROJECTION_TARGETS:
        raise ValueError(
            f"unknown projection target {target!r}; "
            f"ADR-0011 records {list(PROJECTION_TARGETS)}"
        )

    install = rights.install_rights
    if install == "denied":
        return _decision(
            subject, target, BLOCKED, rights, "install_rights", "license-denied"
        )
    if install == "unknown":
        state = BLOCKED if target == "project_committed" else OPT_IN_REQUIRED
        return _decision(
            subject, target, state, rights, "install_rights", "license-unknown"
        )

    redistribution = rights.redistribution_rights
    if redistribution == "granted":
        grant_name = "redistribution_rights" if target == "project_committed" else "install_rights"
        return _decision(subject, target, ALLOWED, rights, grant_name, None)

    state = BLOCKED if target == "project_committed" else OPT_IN_REQUIRED
    return _decision(
        subject, target, state, rights, "redistribution_rights", "redistribution-blocked"
    )


def projection_eligibility(rights: Rights, *, subject: str) -> dict[str, str]:
    """The `projection_eligibility` schema field for one item's rights."""
    return {
        target: evaluate_projection(rights, target, subject=subject).state
        for target in PROJECTION_TARGETS
    }


def evaluate_cache_retention(rights: Rights, *, subject: str) -> RightsDecision:
    """Whether authorized bytes may be *kept* across sessions.

    Retention is not a projection: no harness path is touched and nothing is
    installed. It is also not free of rights, which is why it is governed by
    `install_rights` rather than by the fetch grant that produced the bytes.
    """
    install = rights.install_rights
    if install == "denied":
        return _decision(
            subject, CACHE_RETENTION, BLOCKED, rights, "install_rights", "license-denied"
        )
    if install == "unknown":
        return _decision(
            subject,
            CACHE_RETENTION,
            OPT_IN_REQUIRED,
            rights,
            "install_rights",
            "license-unknown",
        )
    return _decision(subject, CACHE_RETENTION, ALLOWED, rights, "install_rights", None)


def evaluate_derivative(rights: Rights, *, subject: str) -> RightsDecision:
    """Whether a materially adapted first-party derivative may be created.

    Adaptation is itself a licensed act. There is no opt-in path: an operator
    may accept a risk they carry themselves, but creating an adaptation nobody
    granted is not a risk that stops at their machine.
    """
    state = ALLOWED if rights.derivative_rights == "granted" else BLOCKED
    reason = None if state == ALLOWED else _derivative_reason(rights.derivative_rights)
    return _decision(subject, DERIVATIVE, state, rights, "derivative_rights", reason)


#: How each gated act is re-derived at the mutation boundary.
_REDERIVE: Mapping[str, Callable[[Rights, str, str], RightsDecision]] = {
    CACHE_RETENTION: lambda rights, act, subject: evaluate_cache_retention(
        rights, subject=subject
    ),
    DERIVATIVE: lambda rights, act, subject: evaluate_derivative(rights, subject=subject),
}


def _present(decision: RightsDecision, statement: str) -> RightsPresentation:
    """Issue a single-use presentation of one decision's statement.

    The token is fresh per call, so an acknowledgement of one presentation never
    authorizes a later act -- not even the same act on the same item.
    """
    return RightsPresentation(
        statement=statement,
        display_digest=decision.display_digest(),
        token=secrets.token_hex(16),
    )


def rederive(decision: RightsDecision) -> RightsDecision:
    """Recompute a decision from the rights it claims to rest on.

    A `RightsDecision` is a *report*, not a capability. Anyone can construct one
    that says `allowed`, and review demonstrated a hand-built decision writing
    bytes over `install_rights="denied"`. Recomputing at the boundary makes the
    recorded rights the only authority.
    """
    rederive_act = _REDERIVE.get(decision.act)
    if rederive_act is not None:
        return rederive_act(decision.rights, decision.act, decision.subject)
    return evaluate_projection(decision.rights, decision.act, subject=decision.subject)


def _derivative_reason(grant_state: str) -> str:
    return "license-denied" if grant_state == "denied" else "license-unknown"


def project(
    decision: RightsDecision,
    mutate: Callable[[], Any],
    *,
    present: Callable[[RightsPresentation], OperatorOptIn] | None = None,
) -> ProjectionOutcome:
    """Perform one gated act under a composed decision, or refuse it.

    The act is a projection target or durable cache retention -- the two acts
    ADR-0011 puts under the same explicit opt-in. The decision is re-derived
    from its own recorded rights, the rights statement is rendered, and `mutate`
    runs last, only once decision and acknowledgement are both satisfied.

    Args:
        decision: A decision from `evaluate_projection` or
            `evaluate_cache_retention`. Its `state` is not trusted; the rights
            it carries are re-composed here.
        mutate: The callable that writes content. Never called on a refusal.
        present: Receives the rendered `RightsPresentation` and returns the
            operator's acknowledgement of it. This is the **only** way to
            authorize an opt-in-required act. A non-interactive policy flow
            supplies a presenter that records the statement and acknowledges it;
            it still cannot acknowledge something it was not given.

    Returns:
        The outcome, carrying the displayed statement and the ordered events.

    Raises:
        ProjectionRefused: when the decision does not match the recorded rights,
            when it is blocked, when no presenter is supplied for an
            opt-in-required act, or when the acknowledgement does not match the
            statement that was presented.
    """
    recorded = rederive(decision)
    if recorded != decision:
        raise ProjectionRefused(
            f"{decision.act}: the supplied decision does not match the recorded "
            f"rights. Recorded: {recorded.governing_grant}="
            f"{recorded.governing_state} -> {recorded.state}. "
            f"Supplied: {decision.governing_grant}={decision.governing_state} -> "
            f"{decision.state}.",
            recorded,
        )

    display = recorded.display()
    events = ["rights-displayed"]

    if recorded.state == BLOCKED:
        raise ProjectionRefused(
            f"{recorded.act} is blocked: "
            f"{recorded.governing_grant}={recorded.governing_state} "
            f"(evidence source: {recorded.evidence_source or 'none recorded'}). "
            "No operator opt-in overrides this state.",
            recorded,
        )

    if recorded.state == OPT_IN_REQUIRED:
        if present is None:
            raise ProjectionRefused(
                f"{recorded.act} requires an explicit operator opt-in: "
                f"{recorded.governing_grant}={recorded.governing_state} "
                f"(evidence source: {recorded.evidence_source or 'none recorded'}). "
                "Supply a presenter; an acknowledgement cannot exist without one.",
                recorded,
            )
        presentation = _present(recorded, display)
        events.append("rights-presented")
        opt_in = present(presentation)
        if not isinstance(opt_in, OperatorOptIn):
            raise ProjectionRefused(
                f"{recorded.act}: an acknowledgement must be an OperatorOptIn",
                recorded,
            )
        if opt_in.presentation_token != presentation.token:
            raise ProjectionRefused(
                f"{recorded.act}: the acknowledgement does not belong to the "
                "statement that was just presented, so it does not authorize it",
                recorded,
            )
        if opt_in.acknowledged_display_digest != recorded.display_digest():
            raise ProjectionRefused(
                f"{recorded.act}: the operator acknowledged a different rights "
                "statement than the one this decision displays, so the opt-in "
                "does not authorize it",
                recorded,
            )
        events.append("operator-opt-in-accepted")

    events.append("projection-authorized")
    result = mutate()
    events.append("content-materialized")
    return ProjectionOutcome(
        decision=recorded, display=display, events=tuple(events), result=result
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
            Its `qualified_identity` is the subject of the decision.

    Returns:
        The derivative and its provenance, including the rights state.

    Raises:
        DerivativeRefused: when `derivative_rights` is not `granted`. The
            refusal carries the unmodified upstream artifact and the retained
            rights state.
    """
    subject = str(upstream_provenance.get("qualified_identity") or "")
    decision = evaluate_derivative(rights, subject=subject)
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
