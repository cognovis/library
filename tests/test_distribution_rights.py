"""Distribution rights composition and the projection gate (CL-n7ex AC1-AC3, AC7).

ADR-0011 `Distribution Rights` records four independent grants, each with its
own evidence source, and composes them into projection decisions in a fixed
order: `install_rights` first -- governing both targets -- then
`redistribution_rights`, which adds the committed-tree restriction only.

These tests hold the parts an operator can be hurt by: an unresolved grant must
never read as permission, an opt-in must never override a recorded denial, and
the rights state must be on screen before anything is written.
"""

from __future__ import annotations

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
    create_derivative,
    evaluate_cache_retention,
    evaluate_derivative,
    evaluate_projection,
    project,
    projection_eligibility,
)


def _opt_in(decision, operator: str = "malte") -> OperatorOptIn:
    """An opt-in that acknowledges exactly the statement this decision displays."""
    return OperatorOptIn(
        operator=operator,
        acknowledged_display_digest=decision.display_digest(),
        acknowledged_at="2026-08-09T09:00:00Z",
    )


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
        rights.with_grant("install_rights", "probably")


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
    assert projection_eligibility(rights) == {
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
        grant_evidence={
            "redistribution_rights": "no published redistribution grant located",
        },
    )

    decision = evaluate_projection(rights, "project_committed")

    assert decision.state == "blocked"
    assert decision.governing_grant == "redistribution_rights"
    assert decision.governing_state == redistribution
    assert decision.evidence_source == "no published redistribution grant located"
    assert decision.block_reason == "redistribution-blocked"

    # The rendered decision names both the rights state and its evidence source.
    rendered = decision.display()
    assert "redistribution_rights" in rendered
    assert redistribution in rendered
    assert "no published redistribution grant located" in rendered

    mutations: list[str] = []
    with pytest.raises(ProjectionRefused) as refusal:
        project(decision, lambda: mutations.append("wrote"))
    assert mutations == [], "a blocked committed projection materializes nothing"
    assert refusal.value.decision is decision

    # An opt-in does not unblock a committed projection either. The opt-in exists
    # for a machine-local target, which is a different act.
    with pytest.raises(ProjectionRefused):
        project(decision, lambda: mutations.append("wrote"), opt_in=_opt_in(decision))
    assert mutations == []


def test_install_rights_govern_both_targets_and_compose_first() -> None:
    """`install_rights` is checked first; a denial is not opt-in-overridable."""
    unknown_install = Rights(fetch_authorization="granted", install_rights="unknown")
    assert projection_eligibility(unknown_install) == {
        "project_committed": "blocked",
        "machine_local": "operator-opt-in-required",
    }
    committed = evaluate_projection(unknown_install, "project_committed")
    assert committed.governing_grant == "install_rights"
    assert committed.block_reason == "license-unknown"

    denied_install = Rights(
        fetch_authorization="granted",
        install_rights="denied",
        redistribution_rights="granted",
        grant_evidence={"install_rights": "upstream licence forbids local installation"},
    )
    assert projection_eligibility(denied_install) == {
        "project_committed": "blocked",
        "machine_local": "blocked",
    }

    machine_local = evaluate_projection(denied_install, "machine_local")
    assert machine_local.state == "blocked"
    assert machine_local.governing_grant == "install_rights"
    assert machine_local.block_reason == "license-denied"

    mutations: list[str] = []
    with pytest.raises(ProjectionRefused) as refusal:
        project(
            machine_local,
            lambda: mutations.append("wrote"),
            opt_in=_opt_in(machine_local),
        )
    assert mutations == [], "no opt-in overrides a recorded denial"
    assert "denied" in str(refusal.value)

    granted = Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="granted",
        derivative_rights="granted",
        evidence_source="upstream LICENSE (MIT)",
    )
    assert projection_eligibility(granted) == {
        "project_committed": "allowed",
        "machine_local": "allowed",
    }


def test_durable_cache_retention_is_governed_by_install_rights() -> None:
    """Retrieval authorization is not retention authorization (ADR-0011)."""
    fetch_only = Rights(fetch_authorization="granted", install_rights="denied")
    retention = evaluate_cache_retention(fetch_only)
    assert retention.state == "blocked"
    assert retention.governing_grant == "install_rights"

    unresolved = Rights(fetch_authorization="granted", install_rights="unknown")
    assert evaluate_cache_retention(unresolved).state == "operator-opt-in-required"

    retainable = Rights(fetch_authorization="granted", install_rights="granted")
    assert evaluate_cache_retention(retainable).state == "allowed"


# -- AC3: machine-local projection requires an opt-in, shown first -----------


def test_machine_local_requires_optin_after_display() -> None:
    """The rights state is displayed before mutation, and binds the opt-in."""
    rights = reference_rights_for(EXECUTIVE_CIRCLE_IDENTITY)
    decision = evaluate_projection(rights, "machine_local")

    assert decision.state == "operator-opt-in-required"
    assert decision.governing_grant == "install_rights"
    assert decision.governing_state == "unknown"
    assert decision.block_reason == "license-unknown"

    mutations: list[str] = []

    # 1. No opt-in at all: refused, nothing written.
    with pytest.raises(ProjectionRefused) as refusal:
        project(decision, lambda: mutations.append("wrote"))
    assert mutations == []
    assert "operator opt-in" in str(refusal.value)

    # 2. An opt-in that acknowledges a *different* rights statement is refused.
    #    This is what makes "displayed before mutation" mechanical rather than a
    #    promise: the acknowledgement is bound to the exact statement shown.
    permissive = Rights(fetch_authorization="granted", install_rights="granted")
    stale = evaluate_projection(permissive, "machine_local")
    with pytest.raises(ProjectionRefused) as mismatch:
        project(
            decision,
            lambda: mutations.append("wrote"),
            opt_in=_opt_in(stale),
        )
    assert mutations == []
    assert "acknowledged" in str(mismatch.value)

    # 3. An opt-in bound to this decision's displayed statement proceeds, and the
    #    display is recorded before the mutation, not after it.
    outcome = project(
        decision, lambda: mutations.append("wrote"), opt_in=_opt_in(decision)
    )
    assert mutations == ["wrote"]
    assert outcome.events == (
        "rights-displayed",
        "operator-opt-in-accepted",
        "projection-authorized",
        "content-materialized",
    )
    assert outcome.events.index("rights-displayed") < outcome.events.index(
        "content-materialized"
    )
    assert outcome.display == decision.display()
    assert "install_rights" in outcome.display


def test_an_allowed_projection_still_displays_the_rights_state_first() -> None:
    granted = Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="granted",
        evidence_source="upstream LICENSE (MIT)",
    )
    decision = evaluate_projection(granted, "project_committed")
    assert decision.state == "allowed"

    mutations: list[str] = []
    outcome = project(decision, lambda: mutations.append("wrote"))

    assert mutations == ["wrote"]
    assert outcome.events == (
        "rights-displayed",
        "projection-authorized",
        "content-materialized",
    )


def test_evaluate_projection_rejects_an_unknown_target() -> None:
    with pytest.raises(ValueError):
        evaluate_projection(Rights(), "somebody_elses_laptop")


# -- AC7: no derivative without a grant --------------------------------------


@pytest.mark.parametrize("derivative", ["unknown", "denied"])
def test_derivative_refused_without_grant(derivative: str) -> None:
    """Adaptation is itself a licensed act; without a grant nothing is created."""
    rights = Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="granted",
        derivative_rights=derivative,
        grant_evidence={"derivative_rights": "no published derivative-works grant"},
    )
    upstream = {"SKILL.md": b"---\nname: implement\n---\nupstream body\n"}
    adaptations: list[str] = []

    def adapt(files: dict[str, bytes]) -> dict[str, bytes]:
        adaptations.append("adapted")
        return {"SKILL.md": files["SKILL.md"] + b"\nlocal change\n"}

    decision = evaluate_derivative(rights)
    assert decision.state == "blocked"
    assert decision.governing_grant == "derivative_rights"
    assert decision.governing_state == derivative

    with pytest.raises(DerivativeRefused) as refusal:
        create_derivative(
            rights,
            upstream,
            adapt,
            upstream_provenance={
                "qualified_identity": f"{EXECUTIVE_CIRCLE_IDENTITY}#kits/anchor",
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
    assert provenance["qualified_identity"].endswith("#kits/anchor")
    assert refusal.value.available_artifact == upstream, (
        "only the unmodified upstream artifact remains available"
    )


def test_derivative_is_created_when_the_grant_is_recorded() -> None:
    rights = Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="granted",
        derivative_rights="granted",
        evidence_source="upstream LICENSE (MIT)",
    )
    upstream = {"SKILL.md": b"body\n"}

    result = create_derivative(
        rights,
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
    )
    result = create_derivative(
        rights,
        {"SKILL.md": b"body\n"},
        lambda files: {"SKILL.md": b"adapted\n"},
        upstream_provenance={"qualified_identity": "provider#item", "upstream_revision": None},
    )

    derived_rights = Rights.from_dict(result.provenance["rights"])
    assert evaluate_projection(derived_rights, "project_committed").state == "blocked"
