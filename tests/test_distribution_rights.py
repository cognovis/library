"""Distribution rights composition and the projection gate (CL-n7ex AC1-AC3, AC7).

ADR-0011 `Distribution Rights` records four independent grants, each with its
own evidence source, and composes them into projection decisions in a fixed
order: `install_rights` first -- governing both targets -- then
`redistribution_rights`, which adds the committed-tree restriction only.

These tests hold the parts an operator can be hurt by: an unresolved grant must
never read as permission, an opt-in must never override a recorded denial, an
acknowledgement must not travel to another item, and the rights state must be on
screen before anything is written.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.inventory import Rights  # noqa: E402
from lib.providers.reference_rights import (  # noqa: E402
    EXECUTIVE_CIRCLE_IDENTITY,
    reference_rights_for,
)
from lib.providers.rights import (  # noqa: E402
    DerivativeRefused,
    OperatorOptIn,
    ProjectionRefused,
    RightsDecision,
    create_derivative,
    evaluate_cache_retention,
    evaluate_derivative,
    evaluate_projection,
    project,
    projection_eligibility,
)

SUBJECT = f"{EXECUTIVE_CIRCLE_IDENTITY}#kits/anchor"
OTHER_SUBJECT = f"{EXECUTIVE_CIRCLE_IDENTITY}#kits/beacon"

MIT = "upstream LICENSE (MIT), verified 2026-08-08"

FULLY_GRANTED = Rights(
    fetch_authorization="granted",
    install_rights="granted",
    redistribution_rights="granted",
    derivative_rights="granted",
    evidence_source=MIT,
)


def _presenter(shown: list | None = None, captured: list | None = None):
    """An operator who reads what the gate presents and acknowledges exactly it."""

    def present(presentation):
        if shown is not None:
            shown.append(presentation.statement)
        opt_in = presentation.acknowledge(
            operator="malte", acknowledged_at="2026-08-09T09:00:00Z"
        )
        if captured is not None:
            captured.append(opt_in)
        return opt_in

    return present


def _replaying_presenter(opt_in: OperatorOptIn):
    """An operator who hands back an acknowledgement of some earlier statement."""

    def present(presentation):
        return opt_in

    return present


# -- AC1: the four grants are independent ------------------------------------


def test_grants_are_independent() -> None:
    """Each grant resolves and is queried on its own, with its own evidence."""
    rights = Rights(
        fetch_authorization="granted",
        install_rights="unknown",
        redistribution_rights="unknown",
        derivative_rights="denied",
        grant_evidence={
            "fetch_authorization": "subscriber-token endpoint reachable 2026-08-08",
            "derivative_rights": "upstream terms forbid adaptation",
        },
        evidence_source="provider configuration",
    )

    assert rights.grant("fetch_authorization").state == "granted"
    assert rights.grant("install_rights").state == "unknown"
    assert rights.grant("redistribution_rights").state == "unknown"
    assert rights.grant("derivative_rights").state == "denied"

    # Evidence is per grant, falling back to the source recorded for the item.
    assert (
        rights.grant("fetch_authorization").evidence_source
        == "subscriber-token endpoint reachable 2026-08-08"
    )
    assert rights.grant("derivative_rights").evidence_source == (
        "upstream terms forbid adaptation"
    )
    assert rights.grant("install_rights").evidence_source == "provider configuration"

    # Changing one grant changes no other.
    stricter = rights.with_grant("install_rights", "denied", evidence="counsel review")
    assert stricter.install_rights == "denied"
    assert stricter.grant("install_rights").evidence_source == "counsel review"
    assert stricter.fetch_authorization == rights.fetch_authorization
    assert stricter.redistribution_rights == rights.redistribution_rights
    assert stricter.derivative_rights == rights.derivative_rights
    assert rights.install_rights == "unknown", "the original value is immutable"

    with pytest.raises(ValueError):
        rights.grant("publication_rights")
    with pytest.raises(ValueError):
        rights.with_grant("install_rights", "probably", evidence="e e e e e e")


def test_a_resolved_grant_requires_a_named_evidence_source() -> None:
    """ADR-0011: each grant resolves *with a named evidence source*.

    A grant nobody can point at is not a recorded grant. `unknown` is the state
    for "nobody has looked", and it is the only one reachable without evidence.
    """
    with pytest.raises(ValueError) as refusal:
        Rights(redistribution_rights="granted")
    assert "evidence source" in str(refusal.value)

    with pytest.raises(ValueError):
        Rights(install_rights="denied")

    # Nothing is required for the conservative state.
    assert Rights().install_rights == "unknown"
    assert Rights(install_rights="granted", evidence_source=MIT).install_rights == "granted"
    assert (
        Rights(install_rights="granted", grant_evidence={"install_rights": MIT})
        .grant("install_rights")
        .evidence_source
        == MIT
    )

    # Resolving a grant needs evidence of its own, and relaxing it discards the
    # evidence that justified the previous value.
    recorded = Rights(install_rights="granted", grant_evidence={"install_rights": MIT})
    with pytest.raises(ValueError):
        recorded.with_grant("install_rights", "denied")
    relaxed = recorded.with_grant("install_rights", "unknown")
    assert relaxed.grant("install_rights").evidence_source is None


def test_fetch_granted_with_redistribution_unknown_is_the_recorded_reference_state() -> None:
    """ADR-0011 `Resolved rights for the reference providers`, recorded verbatim."""
    rights = reference_rights_for(EXECUTIVE_CIRCLE_IDENTITY)

    assert rights.fetch_authorization == "granted"
    assert rights.install_rights == "unknown"
    assert rights.redistribution_rights == "unknown"
    assert rights.derivative_rights == "unknown"
    assert rights.grant("fetch_authorization").evidence_source
    assert rights.grant("redistribution_rights").evidence_source

    # The whole point of independence: a granted fetch says nothing about the rest.
    assert projection_eligibility(rights, subject=SUBJECT) == {
        "project_committed": "blocked",
        "machine_local": "operator-opt-in-required",
    }


# -- AC2: unknown or denied redistribution blocks a committed projection ------


@pytest.mark.parametrize("redistribution", ["unknown", "denied"])
def test_unknown_blocks_committed_projection(redistribution: str) -> None:
    """A committed projection is blocked by default and says exactly why."""
    rights = Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights=redistribution,
        evidence_source=MIT,
        grant_evidence={
            "redistribution_rights": "no published redistribution grant located",
        },
    )

    decision = evaluate_projection(rights, "project_committed", subject=SUBJECT)

    assert decision.state == "blocked"
    assert decision.governing_grant == "redistribution_rights"
    assert decision.governing_state == redistribution
    assert decision.evidence_source == "no published redistribution grant located"
    assert decision.block_reason == "redistribution-blocked"

    # The rendered decision names the subject, the rights state, and the source.
    rendered = decision.display()
    assert SUBJECT in rendered
    assert "redistribution_rights" in rendered
    assert redistribution in rendered
    assert "no published redistribution grant located" in rendered

    mutations: list[str] = []
    with pytest.raises(ProjectionRefused) as refusal:
        project(decision, lambda: mutations.append("wrote"))
    assert mutations == [], "a blocked committed projection materializes nothing"
    assert refusal.value.decision.state == "blocked"

    # A willing operator does not unblock a committed projection either. The
    # opt-in exists for a machine-local target, which is a different act, and a
    # blocked decision is refused before anything is even presented.
    shown: list[str] = []
    with pytest.raises(ProjectionRefused):
        project(decision, lambda: mutations.append("wrote"), present=_presenter(shown))
    assert mutations == []
    assert shown == []


def test_install_rights_govern_both_targets_and_compose_first() -> None:
    """`install_rights` is checked first; a denial is not opt-in-overridable."""
    unknown_install = Rights(fetch_authorization="granted", evidence_source=MIT)
    assert projection_eligibility(unknown_install, subject=SUBJECT) == {
        "project_committed": "blocked",
        "machine_local": "operator-opt-in-required",
    }
    committed = evaluate_projection(unknown_install, "project_committed", subject=SUBJECT)
    assert committed.governing_grant == "install_rights"
    assert committed.block_reason == "license-unknown"

    denied_install = Rights(
        fetch_authorization="granted",
        install_rights="denied",
        redistribution_rights="granted",
        evidence_source=MIT,
        grant_evidence={"install_rights": "upstream licence forbids local installation"},
    )
    assert projection_eligibility(denied_install, subject=SUBJECT) == {
        "project_committed": "blocked",
        "machine_local": "blocked",
    }

    machine_local = evaluate_projection(denied_install, "machine_local", subject=SUBJECT)
    assert machine_local.state == "blocked"
    assert machine_local.governing_grant == "install_rights"
    assert machine_local.block_reason == "license-denied"

    mutations: list[str] = []
    with pytest.raises(ProjectionRefused) as refusal:
        project(
            machine_local,
            lambda: mutations.append("wrote"),
            present=_presenter(),
        )
    assert mutations == [], "no opt-in overrides a recorded denial"
    assert "denied" in str(refusal.value)

    assert projection_eligibility(FULLY_GRANTED, subject=SUBJECT) == {
        "project_committed": "allowed",
        "machine_local": "allowed",
    }


def test_a_forged_decision_cannot_authorize_a_mutation() -> None:
    """A decision is a report, not a capability; the recorded rights decide."""
    denied = Rights(
        fetch_authorization="granted",
        install_rights="denied",
        evidence_source="upstream terms forbid installation",
    )
    forged = RightsDecision(
        subject=SUBJECT,
        act="machine_local",
        state="allowed",
        governing_grant="install_rights",
        governing_state="granted",
        evidence_source="trust me",
        block_reason=None,
        rights=denied,
    )

    mutations: list[str] = []
    with pytest.raises(ProjectionRefused) as refusal:
        project(forged, lambda: mutations.append("forbidden bytes"))

    assert mutations == []
    assert "does not match the recorded rights" in str(refusal.value)
    # The refusal reports the *recorded* decision, not the supplied one.
    assert refusal.value.decision.state == "blocked"
    assert refusal.value.decision.governing_state == "denied"


def test_durable_cache_retention_is_governed_by_install_rights() -> None:
    """Retrieval authorization is not retention authorization (ADR-0011)."""
    fetch_only = Rights(
        fetch_authorization="granted",
        install_rights="denied",
        evidence_source="upstream terms forbid retention",
    )
    retention = evaluate_cache_retention(fetch_only, subject=SUBJECT)
    assert retention.state == "blocked"
    assert retention.governing_grant == "install_rights"

    unresolved = Rights(fetch_authorization="granted", evidence_source="subscriber token")
    assert (
        evaluate_cache_retention(unresolved, subject=SUBJECT).state
        == "operator-opt-in-required"
    )

    retainable = Rights(
        fetch_authorization="granted", install_rights="granted", evidence_source=MIT
    )
    assert evaluate_cache_retention(retainable, subject=SUBJECT).state == "allowed"

    # Retention runs through the same gate, so a denial is unwritable there too.
    kept: list[str] = []
    with pytest.raises(ProjectionRefused):
        project(retention, lambda: kept.append("retained"))
    assert kept == []


# -- AC3: machine-local projection requires an opt-in, shown first -----------


def test_machine_local_requires_optin_after_display() -> None:
    """The rights state is displayed before mutation, and binds the opt-in."""
    rights = reference_rights_for(EXECUTIVE_CIRCLE_IDENTITY)
    decision = evaluate_projection(rights, "machine_local", subject=SUBJECT)

    assert decision.state == "operator-opt-in-required"
    assert decision.governing_grant == "install_rights"
    assert decision.governing_state == "unknown"
    assert decision.block_reason == "license-unknown"

    mutations: list[str] = []

    # 1. No presenter at all: refused, nothing written. An acknowledgement cannot
    #    exist without the gate having rendered the statement.
    with pytest.raises(ProjectionRefused) as refusal:
        project(decision, lambda: mutations.append("wrote"))
    assert mutations == []
    assert "operator opt-in" in str(refusal.value)

    # 2. A self-minted acknowledgement -- one built from the publicly computable
    #    digest rather than from a presentation -- authorizes nothing.
    forged = OperatorOptIn(
        operator="malte",
        acknowledged_display_digest=decision.display_digest(),
        acknowledged_at="2026-08-09T09:00:00Z",
        presentation_token="self-minted",
    )
    with pytest.raises(ProjectionRefused) as minted:
        project(
            decision,
            lambda: mutations.append("wrote"),
            present=_replaying_presenter(forged),
        )
    assert mutations == []
    assert "does not belong to the statement" in str(minted.value)

    # 3. An acknowledgement of a *different* rights statement is refused, even
    #    when it carries this presentation's token.
    permissive = Rights(
        fetch_authorization="granted", install_rights="granted", evidence_source=MIT
    )
    stale = evaluate_projection(permissive, "machine_local", subject=SUBJECT)

    def wrong_statement(presentation):
        return OperatorOptIn(
            operator="malte",
            acknowledged_display_digest=stale.display_digest(),
            acknowledged_at="2026-08-09T09:00:00Z",
            presentation_token=presentation.token,
        )

    with pytest.raises(ProjectionRefused) as mismatch:
        project(decision, lambda: mutations.append("wrote"), present=wrong_statement)
    assert mutations == []
    assert "acknowledged a different rights statement" in str(mismatch.value)

    # 4. An acknowledgement of the presented statement proceeds, and the display
    #    is recorded before the mutation, not after it.
    shown: list[str] = []
    outcome = project(
        decision, lambda: mutations.append("wrote"), present=_presenter(shown)
    )
    assert mutations == ["wrote"]
    assert shown == [decision.display()]
    assert outcome.events == (
        "rights-displayed",
        "rights-presented",
        "operator-opt-in-accepted",
        "projection-authorized",
        "content-materialized",
    )
    assert outcome.events.index("rights-presented") < outcome.events.index(
        "content-materialized"
    )
    assert outcome.display == decision.display()
    assert "install_rights" in outcome.display


def test_an_optin_does_not_travel_to_another_item() -> None:
    """Rights are recorded per provider; an acknowledgement is not.

    Every item from one provider shares one rights record, so without the
    subject in the displayed statement one opt-in would authorize the projection
    of items the operator never saw.
    """
    rights = reference_rights_for(EXECUTIVE_CIRCLE_IDENTITY)
    acknowledged = evaluate_projection(rights, "machine_local", subject=SUBJECT)
    other_item = evaluate_projection(rights, "machine_local", subject=OTHER_SUBJECT)

    assert acknowledged.display() != other_item.display()
    assert acknowledged.display_digest() != other_item.display_digest()

    mutations: list[str] = []
    captured: list[OperatorOptIn] = []
    project(acknowledged, lambda: mutations.append("first"), present=_presenter(captured=captured))
    assert mutations == ["first"]

    with pytest.raises(ProjectionRefused) as replay:
        project(
            other_item,
            lambda: mutations.append("second"),
            present=_replaying_presenter(captured[0]),
        )

    assert mutations == ["first"]
    assert "does not belong to the statement" in str(replay.value)

    # Nor does it authorize the same act a second time: a presentation is issued
    # once and its acknowledgement is good for that one act.
    with pytest.raises(ProjectionRefused):
        project(
            acknowledged,
            lambda: mutations.append("again"),
            present=_replaying_presenter(captured[0]),
        )
    assert mutations == ["first"]


def test_the_gate_can_present_the_statement_and_collect_the_acknowledgement() -> None:
    """The library renders and collects in one call, so nothing is self-reported."""
    rights = reference_rights_for(EXECUTIVE_CIRCLE_IDENTITY)
    decision = evaluate_projection(rights, "machine_local", subject=SUBJECT)
    shown: list[str] = []
    mutations: list[str] = []

    def present(presentation) -> OperatorOptIn:
        # The acknowledgement is derived from the text actually presented, which
        # is the whole point of this path.
        shown.append(presentation.statement)
        assert presentation.display_digest == hashlib.sha256(
            presentation.statement.encode("utf-8")
        ).hexdigest()
        return presentation.acknowledge(
            operator="malte", acknowledged_at="2026-08-09T09:00:00Z"
        )

    outcome = project(decision, lambda: mutations.append("wrote"), present=present)

    assert shown == [decision.display()]
    assert SUBJECT in shown[0]
    assert mutations == ["wrote"]
    assert outcome.events == (
        "rights-displayed",
        "rights-presented",
        "operator-opt-in-accepted",
        "projection-authorized",
        "content-materialized",
    )

    # A presenter that acknowledges something else is refused like any other.
    def wrong_present(presentation) -> OperatorOptIn:
        return OperatorOptIn(
            operator="malte",
            acknowledged_display_digest="0" * 64,
            acknowledged_at="2026-08-09T09:00:00Z",
            presentation_token=presentation.token,
        )

    with pytest.raises(ProjectionRefused):
        project(decision, lambda: mutations.append("again"), present=wrong_present)
    assert mutations == ["wrote"]

    # Each act gets a fresh presentation, so two acts never share a token.
    first: list[OperatorOptIn] = []
    second: list[OperatorOptIn] = []
    project(decision, lambda: None, present=_presenter(captured=first))
    project(decision, lambda: None, present=_presenter(captured=second))
    assert first[0].presentation_token != second[0].presentation_token


def test_an_allowed_projection_still_displays_the_rights_state_first() -> None:
    decision = evaluate_projection(FULLY_GRANTED, "project_committed", subject=SUBJECT)
    assert decision.state == "allowed"

    mutations: list[str] = []
    outcome = project(decision, lambda: mutations.append("wrote"))

    assert mutations == ["wrote"]
    assert outcome.events == (
        "rights-displayed",
        "projection-authorized",
        "content-materialized",
    )


def test_evaluate_projection_rejects_an_unknown_target_or_subject() -> None:
    with pytest.raises(ValueError):
        evaluate_projection(Rights(), "somebody_elses_laptop", subject=SUBJECT)
    with pytest.raises(ValueError):
        evaluate_projection(Rights(), "machine_local", subject="")


# -- AC7: no derivative without a grant --------------------------------------


@pytest.mark.parametrize("derivative", ["unknown", "denied"])
def test_derivative_refused_without_grant(derivative: str) -> None:
    """Adaptation is itself a licensed act; without a grant nothing is created."""
    rights = Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="granted",
        derivative_rights=derivative,
        evidence_source=MIT,
        grant_evidence={"derivative_rights": "no published derivative-works grant"},
    )
    upstream = {"SKILL.md": b"---\nname: implement\n---\nupstream body\n"}
    adaptations: list[str] = []

    def adapt(files: dict[str, bytes]) -> dict[str, bytes]:
        adaptations.append("adapted")
        return {"SKILL.md": files["SKILL.md"] + b"\nlocal change\n"}

    decision = evaluate_derivative(rights, subject=SUBJECT)
    assert decision.state == "blocked"
    assert decision.governing_grant == "derivative_rights"
    assert decision.governing_state == derivative

    with pytest.raises(DerivativeRefused) as refusal:
        create_derivative(
            rights,
            upstream,
            adapt,
            upstream_provenance={
                "qualified_identity": SUBJECT,
                "upstream_revision": None,
            },
        )

    assert adaptations == [], "no adapted artifact is created at all"
    assert upstream == {"SKILL.md": b"---\nname: implement\n---\nupstream body\n"}

    # The unresolved rights state is retained in provenance, not discarded.
    provenance = refusal.value.provenance
    assert provenance["rights"]["derivative_rights"] == derivative
    assert provenance["rights"]["redistribution_rights"] == "granted"
    assert provenance["rights_evidence"]["derivative_rights"] == (
        "no published derivative-works grant"
    )
    assert provenance["qualified_identity"] == SUBJECT
    assert refusal.value.available_artifact == upstream, (
        "only the unmodified upstream artifact remains available"
    )


def test_derivative_is_created_when_the_grant_is_recorded() -> None:
    upstream = {"SKILL.md": b"body\n"}

    result = create_derivative(
        FULLY_GRANTED,
        upstream,
        lambda files: {"SKILL.md": files["SKILL.md"] + b"local\n"},
        upstream_provenance={"qualified_identity": "provider#item", "upstream_revision": "abc"},
    )

    assert result.files == {"SKILL.md": b"body\nlocal\n"}
    assert result.provenance["upstream_revision"] == "abc"
    assert result.provenance["rights"]["derivative_rights"] == "granted"
    # A created derivative still passes through the ordinary projection gate.
    assert result.provenance["rights"]["redistribution_rights"] == "granted"


def test_a_derivative_of_unredistributable_content_is_still_projection_gated() -> None:
    """A derivative grant is not a redistribution grant."""
    rights = Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="unknown",
        derivative_rights="granted",
        evidence_source=MIT,
    )
    result = create_derivative(
        rights,
        {"SKILL.md": b"body\n"},
        lambda files: {"SKILL.md": b"adapted\n"},
        upstream_provenance={"qualified_identity": "provider#item", "upstream_revision": None},
    )

    derived_rights = Rights.from_dict(result.provenance["rights"])
    assert (
        evaluate_projection(
            derived_rights, "project_committed", subject="provider#item"
        ).state
        == "blocked"
    )
