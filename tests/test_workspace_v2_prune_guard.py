"""The foreign-catalog prune guard (CL-dbam AC5, AC8).

ADR-0011 restates ADR-0010's guard with the distinction cross-catalog
composition forces. A catalog is *registered in the resolved Workspace closure*
when it is either the catalog this scope reconciles against or one of its
configured first-party source catalogs (ADR-0010's shipped provenance
comparison), or when its canonical identity appears in the pinned `catalogs:`
block of a Workspace in the selected scope's freshly resolved root set
(ADR-0011's addition). Everything else is a foreign owner and is never pruned
by this scope -- including a provider that is merely configured, because
reaching one requires a reviewed, pinned declaration.

The clause that matters is the default. `unknown`, missing, and undeterminable
registration are all **foreign** -- not "probably ours". That default is not
theoretical: `mira/.library.lock` carries the literal value
`catalog_identity: unknown` today, and reading it as registered would authorize
this scope to delete content it never installed.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.errors import LibraryError  # noqa: E402
from lib.providers.inventory import ProviderAvailability  # noqa: E402
from lib.providers.offline import ResolutionEvidence  # noqa: E402
from lib.workspace import (  # noqa: E402
    CatalogObservations,
    build_workspace_plan,
    prepare_prune_plan,
    workspace_root_id,
)
from workspace_v2_fixtures import (  # noqa: E402
    CORE_IDENTITY,
    CORE_NAME,
    FOREIGN_IDENTITY,
    UPSTREAM_IDENTITY,
    catalog_document,
    empty_lock,
    v2_manifest,
    workspace_root_record,
)

#: Freshness is measured against the real clock, so the suite's timestamps are
#: relative to it. Wave-2 review paired evidence from 2020 with a run time from
#: 2020 and a one-hour window: every check agreed with itself while the evidence
#: was six years old.
def _at(offset: timedelta = timedelta(0)) -> str:
    return (datetime.now(timezone.utc) + offset).isoformat().replace("+00:00", "Z")


NOW = _at()
STALE = _at(-timedelta(days=8))
AHEAD = _at(timedelta(hours=3))
WINDOW = timedelta(hours=6)
AVAILABLE = ProviderAvailability(state="available", observed_at=NOW)
UNAVAILABLE = ProviderAvailability(
    state="unavailable", observed_at=NOW, reason="source did not answer"
)

#: What a complete inventory of the fixture catalogs actually lists. An empty
#: listing is not a complete one, so a suite that always passed `frozenset()`
#: would be asserting deletion authority nobody has.
LISTINGS: dict[str, frozenset[str]] = {
    CORE_IDENTITY: frozenset(
        {
            f"{CORE_IDENTITY}#skills/python-dev",
            f"{CORE_IDENTITY}#skills/legacy-unknown",
            f"{CORE_IDENTITY}#skills/no-identity",
            f"{CORE_IDENTITY}#skills/blank-identity",
        }
    ),
    UPSTREAM_IDENTITY: frozenset(
        {
            f"{UPSTREAM_IDENTITY}#skills/helper",
            f"{UPSTREAM_IDENTITY}#skills/retired",
        }
    ),
}


def _conclusive(identity: str) -> ResolutionEvidence:
    return ResolutionEvidence(
        provider_identity=identity,
        availability=AVAILABLE,
        complete=True,
        listed_identities=LISTINGS.get(identity, frozenset({f"{identity}#anchor"})),
    )


def _observed(observations: dict[str, ResolutionEvidence]) -> CatalogObservations:
    return CatalogObservations(observations=observations, max_age=WINDOW)


def _observations(*identities: str) -> CatalogObservations:
    return _observed({identity: _conclusive(identity) for identity in identities})


def _receipt(
    receipt_id: str, catalog_identity: Any, *, upstream: str | None = "listed"
) -> dict[str, Any]:
    """One lock receipt.

    `upstream` selects the recorded upstream identity: `"listed"` records one the
    fixture inventory lists, `None` records none at all (which is undeterminable
    and therefore never prunable under a cross-catalog closure), and any other
    value records one the inventory does not list.
    """
    primitive, _, name = receipt_id.partition(":")
    receipt: dict[str, Any] = {
        "id": receipt_id,
        "type": primitive,
        "name": name,
        "scope": "project",
        "resolved_version": "1.0.0",
        "source_commit": "f" * 40,
        "verified": True,
        "targets": [{"path": "content.md", "kind": "file", "content_sha256": "0" * 64}],
    }
    if catalog_identity is not None:
        receipt["catalog_identity"] = catalog_identity
    if upstream is not None and isinstance(catalog_identity, str):
        receipt["provider_identity"] = catalog_identity
        receipt["upstream_id"] = (
            f"{primitive}s/{name}" if upstream == "listed" else upstream
        )
    return receipt


def _scope(*, receipts: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """One registered cross-catalog Workspace plus the receipts under test."""
    catalog = catalog_document(workspaces=[v2_manifest()])
    lock = empty_lock()
    lock["requested_roots"] = [
        workspace_root_record(
            workspace_root_id(CORE_IDENTITY, "engineering"),
            name="engineering",
            catalog_identity=CORE_IDENTITY,
            catalog_name=CORE_NAME,
            requested_ref=f"{CORE_NAME}:engineering",
            roots=["skill:python-dev", "skill:helper"],
        )
    ]
    lock["receipts"] = receipts
    return catalog, lock


def _plan(catalog: dict[str, Any], lock: dict[str, Any], observations: Any) -> dict[str, Any]:
    return build_workspace_plan(
        catalog,
        lock,
        Path.cwd(),
        "project",
        catalog_observations=observations,
        pin_verifier=lambda entry: entry.pin.value,
    )


def _candidate(plan: dict[str, Any], receipt_id: str) -> dict[str, Any]:
    return next(item for item in plan["prune_candidates"] if item["id"] == receipt_id)


ALL_OBSERVED = _observations(CORE_IDENTITY, UPSTREAM_IDENTITY)


# -- AC5 ---------------------------------------------------------------------


def test_registered_vs_foreign_owner() -> None:
    catalog, lock = _scope(
        receipts=[
            _receipt("skill:python-dev", CORE_IDENTITY),
            _receipt("skill:helper", UPSTREAM_IDENTITY),
            _receipt("skill:retired", UPSTREAM_IDENTITY),
            _receipt("skill:someone-elses", FOREIGN_IDENTITY),
        ]
    )

    plan = _plan(catalog, lock, ALL_OBSERVED)

    identities = set(plan["catalog_closure"]["identities"])
    assert {CORE_IDENTITY, UPSTREAM_IDENTITY} <= identities
    assert FOREIGN_IDENTITY not in identities
    assert plan["catalog_closure"]["complete"] is True

    registered = _candidate(plan, "skill:retired")
    assert registered["catalog_registration"] == "registered"
    assert registered["blocked_reason"] is None

    foreign = _candidate(plan, "skill:someone-elses")
    assert foreign["catalog_registration"] == "foreign"
    assert FOREIGN_IDENTITY in str(foreign["blocked_reason"])


def test_foreign_owner_is_refused_by_prune_preflight(tmp_path: Path) -> None:
    catalog, lock = _scope(
        receipts=[_receipt("skill:someone-elses", FOREIGN_IDENTITY)]
    )
    plan = _plan(catalog, lock, ALL_OBSERVED)

    with pytest.raises(LibraryError, match="foreign"):
        prepare_prune_plan(
            lock, plan, tmp_path, plan["digest"], allowed_roots=[tmp_path]
        )


def test_undeterminable_is_foreign() -> None:
    catalog, lock = _scope(
        receipts=[
            _receipt("skill:legacy-unknown", "unknown"),
            _receipt("skill:no-identity", None),
            _receipt("skill:blank-identity", "   "),
            _receipt("skill:retired", UPSTREAM_IDENTITY),
        ]
    )

    plan = _plan(catalog, lock, ALL_OBSERVED)

    for receipt_id in ("skill:legacy-unknown", "skill:no-identity", "skill:blank-identity"):
        candidate = _candidate(plan, receipt_id)
        assert candidate["catalog_registration"] == "foreign", receipt_id
        assert candidate["blocked_reason"], receipt_id
    assert _candidate(plan, "skill:retired")["catalog_registration"] == "registered"


def test_unresolvable_closure_makes_every_owner_foreign() -> None:
    """When registration cannot be determined, nothing in the scope is prunable.

    The undeterminable case is an unresolvable *catalog*, not an unresolvable
    member: a registered Workspace whose manifest can no longer be read tells
    this scope nothing about which catalogs it declares.
    """
    catalog, lock = _scope(receipts=[_receipt("skill:retired", UPSTREAM_IDENTITY)])
    lock["requested_roots"].append(
        workspace_root_record(
            workspace_root_id(CORE_IDENTITY, "vanished"),
            name="vanished",
            catalog_identity=CORE_IDENTITY,
            catalog_name=CORE_NAME,
            requested_ref=f"{CORE_NAME}:vanished",
            roots=["skill:python-dev"],
        )
    )

    plan = _plan(catalog, lock, ALL_OBSERVED)

    assert plan["catalog_closure"]["complete"] is False
    candidate = _candidate(plan, "skill:retired")
    assert candidate["catalog_registration"] == "foreign"
    assert "undeterminable" in str(candidate["blocked_reason"])


def test_an_unresolvable_member_does_not_suspend_the_scope() -> None:
    """One stale direct root must not make everything else unprunable."""
    catalog, lock = _scope(receipts=[_receipt("skill:retired", UPSTREAM_IDENTITY)])
    lock["requested_roots"].append(
        {
            "id": "skill:missing",
            "type": "skill",
            "name": "missing",
            "scope": "project",
            "catalog_identity": CORE_IDENTITY,
            "resolved_version": "1.0.0",
            "definition_commit": "e" * 40,
        }
    )

    plan = _plan(catalog, lock, ALL_OBSERVED)

    assert plan["blockers"], "the stale root is still reported"
    assert plan["catalog_closure"]["complete"] is True
    assert _candidate(plan, "skill:retired")["catalog_registration"] == "registered"


# -- AC8 ---------------------------------------------------------------------


def test_prune_fails_closed_offline() -> None:
    catalog, lock = _scope(receipts=[_receipt("skill:retired", UPSTREAM_IDENTITY)])

    # No observation at all: reachability was never established, which is not
    # the same as established reachability.
    unobserved = _plan(catalog, lock, None)
    assert _candidate(unobserved, "skill:retired")["blocked_reason"]
    assert unobserved["catalog_closure"]["complete"] is False

    # One of the two catalogs in the closure is unreachable: the whole scope's
    # prune fails closed, not only that catalog's receipts.
    partial = _plan(
        catalog,
        lock,
        _observed(
            {
                CORE_IDENTITY: _conclusive(CORE_IDENTITY),
                UPSTREAM_IDENTITY: ResolutionEvidence(
                    provider_identity=UPSTREAM_IDENTITY,
                    availability=UNAVAILABLE,
                    complete=False,
                ),
            }
        ),
    )
    assert _candidate(partial, "skill:retired")["blocked_reason"]

    # A reachable source that answered incompletely is refused for the same
    # reason a silent one is: absence from a truncated listing proves nothing.
    truncated = _plan(
        catalog,
        lock,
        _observed(
            {
                CORE_IDENTITY: _conclusive(CORE_IDENTITY),
                UPSTREAM_IDENTITY: ResolutionEvidence(
                    provider_identity=UPSTREAM_IDENTITY,
                    availability=AVAILABLE,
                    complete=False,
                ),
            }
        ),
    )
    assert _candidate(truncated, "skill:retired")["blocked_reason"]

    # A "complete" answer that lists nothing is not a complete inventory of a
    # source that supplies this scope's roots.
    empty = _plan(
        catalog,
        lock,
        _observed(
            {
                CORE_IDENTITY: _conclusive(CORE_IDENTITY),
                UPSTREAM_IDENTITY: ResolutionEvidence(
                    provider_identity=UPSTREAM_IDENTITY,
                    availability=AVAILABLE,
                    complete=True,
                ),
            }
        ),
    )
    assert "empty inventory" in str(
        _candidate(empty, "skill:retired")["blocked_reason"]
    )

    # An observation older than the evidence window says nothing about now, and
    # the comparison is against the real clock, not a time the caller supplied.
    stale = _plan(
        catalog,
        lock,
        _observed(
            {
                CORE_IDENTITY: _conclusive(CORE_IDENTITY),
                UPSTREAM_IDENTITY: ResolutionEvidence(
                    provider_identity=UPSTREAM_IDENTITY,
                    availability=ProviderAvailability(
                        state="available", observed_at=STALE
                    ),
                    complete=True,
                    listed_identities=LISTINGS[UPSTREAM_IDENTITY],
                ),
            }
        ),
    )
    assert "evidence window" in str(_candidate(stale, "skill:retired")["blocked_reason"])

    # Evidence that has not happened yet establishes nothing either.
    ahead = _plan(
        catalog,
        lock,
        _observed(
            {
                CORE_IDENTITY: _conclusive(CORE_IDENTITY),
                UPSTREAM_IDENTITY: ResolutionEvidence(
                    provider_identity=UPSTREAM_IDENTITY,
                    availability=ProviderAvailability(
                        state="available", observed_at=AHEAD
                    ),
                    complete=True,
                    listed_identities=LISTINGS[UPSTREAM_IDENTITY],
                ),
            }
        ),
    )
    assert "future" in str(_candidate(ahead, "skill:retired")["blocked_reason"])

    # An observation of a different source cannot answer for this one.
    misattributed = _plan(
        catalog,
        lock,
        _observed(
            {
                CORE_IDENTITY: _conclusive(CORE_IDENTITY),
                UPSTREAM_IDENTITY: _conclusive(CORE_IDENTITY),
            }
        ),
    )
    assert _candidate(misattributed, "skill:retired")["blocked_reason"]

    # Every catalog in the closure observed conclusively: the guard permits it.
    observed = _plan(catalog, lock, ALL_OBSERVED)
    assert _candidate(observed, "skill:retired")["blocked_reason"] is None


def test_observations_require_an_evidence_window() -> None:
    """Evidence with no window is evidence about no particular moment."""
    with pytest.raises(LibraryError, match="evidence window"):
        CatalogObservations(
            observations={CORE_IDENTITY: _conclusive(CORE_IDENTITY)},
            max_age=timedelta(0),
        )
    with pytest.raises(LibraryError, match="ResolutionEvidence"):
        CatalogObservations(
            observations={CORE_IDENTITY: AVAILABLE}, max_age=WINDOW
        )


def test_a_vanished_upstream_is_never_deletion_authority() -> None:
    """A complete listing that omits the item proves loss, not permission.

    Wave-2 F2: the earlier shape only asked this question when the receipt
    happened to record an upstream identity, and accepted any nonempty listing.
    Both holes are closed here -- a listing that does not mention the receipt,
    and a receipt with no upstream identity at all.
    """
    catalog, lock = _scope(
        receipts=[_receipt("skill:retired", UPSTREAM_IDENTITY, upstream="skills/gone")]
    )
    plan = _plan(catalog, lock, ALL_OBSERVED)
    assert "upstream-vanished" in str(
        _candidate(plan, "skill:retired")["blocked_reason"]
    )

    catalog, lock = _scope(
        receipts=[_receipt("skill:retired", UPSTREAM_IDENTITY, upstream=None)]
    )
    plan = _plan(catalog, lock, ALL_OBSERVED)
    assert "no upstream identity" in str(
        _candidate(plan, "skill:retired")["blocked_reason"]
    )


def test_prune_requires_the_decision_8_provenance_triple(tmp_path: Path) -> None:
    """Catalog identity, resolved version, and source pin must all be known."""
    for field_name in ("resolved_version", "source_commit"):
        receipt = _receipt("skill:retired", UPSTREAM_IDENTITY)
        receipt.pop(field_name)
        catalog, lock = _scope(receipts=[receipt])

        plan = _plan(catalog, lock, ALL_OBSERVED)

        candidate = _candidate(plan, "skill:retired")
        assert field_name in str(candidate["blocked_reason"]), field_name
        with pytest.raises(LibraryError, match="Decision 8 condition 2"):
            prepare_prune_plan(
                lock, plan, tmp_path, plan["digest"], allowed_roots=[tmp_path]
            )


def test_a_plan_without_a_recorded_closure_is_refused(tmp_path: Path) -> None:
    """A plan that carries no ownership evidence is not read as "all mine"."""
    catalog, lock = _scope(receipts=[_receipt("skill:retired", UPSTREAM_IDENTITY)])
    plan = _plan(catalog, lock, ALL_OBSERVED)
    plan.pop("catalog_closure")

    with pytest.raises(LibraryError, match="no resolved catalog closure"):
        prepare_prune_plan(
            lock, plan, tmp_path, plan["digest"], allowed_roots=[tmp_path]
        )


def test_v1_only_scope_needs_no_cross_catalog_observation() -> None:
    """The new requirement lands where the new capability does, and nowhere else."""
    from workspace_v2_fixtures import v1_manifest

    catalog = catalog_document(workspaces=[v1_manifest()])
    lock = empty_lock()
    lock["requested_roots"] = [
        workspace_root_record(
            workspace_root_id(CORE_IDENTITY, "python-cli"),
            name="python-cli",
            catalog_identity=CORE_IDENTITY,
            catalog_name=CORE_NAME,
            requested_ref=f"{CORE_NAME}:python-cli",
            roots=["skill:python-dev", "skill:python-test"],
        )
    ]
    lock["receipts"] = [_receipt("skill:retired", CORE_IDENTITY)]

    plan = _plan(catalog, lock, None)

    assert _candidate(plan, "skill:retired")["blocked_reason"] is None
    assert plan["catalog_closure"]["complete"] is True
