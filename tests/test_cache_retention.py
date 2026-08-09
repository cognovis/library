"""Cache retention and re-fetchability-aware garbage collection (CL-uliw).

ADR-0011 `Retention, Garbage Collection, and Explicit Purge` gives automatic
garbage collection two retention inputs, and only the first one is obvious:

1. an object referenced by any active receipt in **any** scope is ineligible;
2. re-fetchability must be **proven**, not inferred from provider health.

The second input is what makes an outage survivable. A cache that discards
unreferenced objects while its source is down discards exactly the bytes that
cannot be retrieved again, at exactly the moment they became irreplaceable.

Covers AC1, AC2, and AC3.
"""

from __future__ import annotations

import ast
import errno
import fcntl
import hashlib
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from datetime import timedelta
from typing import Iterator, Mapping, Sequence

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.cache_transaction import (  # noqa: E402
    CompletenessEvidence,
    ProjectionActivation,
    install_foreign_item,
)
from lib.providers.contract import FetchedFile, FetchedItem  # noqa: E402
from lib.providers.executable_admission import content_digest  # noqa: E402
from lib.providers.foreign_cache import (  # noqa: E402
    IDENTITY_TRANSFORMATION,
    QUARANTINE_SUFFIX,
    ObjectStore,
    TofuPinStore,
)
from lib.providers.inventory import (  # noqa: E402
    NormalizedItem,
    ProviderAvailability,
    Rights,
)
from lib.providers.offline import ResolutionEvidence  # noqa: E402
from lib.providers.receipts import (  # noqa: E402
    ReceiptStore,
    ReceiptTarget,
    reconcile_upstream_state,
    remove_named_receipt,
)
from lib.providers import retention  # noqa: E402
from lib.providers.retention import (  # noqa: E402
    REQUIRED_SCOPES,
    RETENTION_REFUSALS,
    ReceiptScope,
    ReferenceIndex,
    RefetchProof,
    RetentionError,
    ScopeUnreadable,
    collect_garbage,
    plan_garbage_collection,
)

PROVIDER = "provider-under-test"
OTHER_PROVIDER = "second-provider-under-test"
NOW = "2026-08-09T09:00:00Z"
LATER = "2026-08-09T12:00:00Z"
MIT = "upstream LICENSE (MIT), read from the fetched item on 2026-08-09"

#: How old this suite lets deletion-authorizing evidence be. Required at every
#: call site with no default (wave-2 F4): an observation and a proof that agree
#: with each other prove nothing if both were taken long before the run.
WINDOW = timedelta(hours=6)

GRANTED = Rights(
    fetch_authorization="granted",
    install_rights="granted",
    redistribution_rights="granted",
    derivative_rights="granted",
    evidence_source=MIT,
)

AVAILABLE = ProviderAvailability(state="available", observed_at=NOW)
UNAVAILABLE = ProviderAvailability(
    state="unavailable", observed_at=LATER, reason="host did not answer within 30s"
)
DEGRADED = ProviderAvailability(
    state="degraded", observed_at=LATER, reason="listing truncated by rate limiting"
)


def _item(**overrides: object) -> NormalizedItem:
    base = dict(
        provider_identity=PROVIDER,
        upstream_id="kits/anchor",
        upstream_name="anchor",
        collection_membership=("kits",),
        upstream_revision=None,
        library_type="skill",
        library_name="anchor",
        classification={"skill_class": "procedure"},
        runtime_compatibility=("claude-code",),
        rights=GRANTED,
        provider_availability=AVAILABLE,
        admission_state="installable",
        trust_state="reviewed",
        projection_eligibility={"project_committed": "allowed", "machine_local": "allowed"},
    )
    base.update(overrides)
    return NormalizedItem(**base)


class _Projector:
    """A harness projection that writes files and can take them away again."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def plan(self, files: Mapping[str, bytes]) -> Sequence[str]:
        return tuple(str(self.root / path) for path in sorted(files))

    @property
    def activation(self) -> ProjectionActivation:
        return ProjectionActivation(plan=self.plan, apply=self)

    def deactivate(self, targets: Sequence[ReceiptTarget]) -> Sequence[str]:
        removed = []
        for target in targets:
            path = Path(target.path)
            if path.is_file():
                path.unlink()
                removed.append(target.path)
        return tuple(removed)

    def __call__(self, files: Mapping[str, bytes]) -> Sequence[ReceiptTarget]:
        targets = []
        for path, content in sorted(files.items()):
            destination = self.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            targets.append(
                ReceiptTarget(
                    path=str(destination),
                    kind="file",
                    content_sha256=content_digest({path: content}),
                )
            )
        return tuple(targets)


class _Cache:
    """One object store, two receipt scopes, and the projector behind them."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.objects = ObjectStore(tmp_path / "cache")
        self.pins = TofuPinStore(tmp_path / "pins.json")
        self.project = ReceiptStore(tmp_path / "project" / "receipts.json")
        self.global_ = ReceiptStore(tmp_path / "global" / "receipts.json")
        self.project.path.parent.mkdir(parents=True, exist_ok=True)
        self.global_.path.parent.mkdir(parents=True, exist_ok=True)
        self.projector = _Projector(tmp_path / "harness")

    def index(self) -> ReferenceIndex:
        return ReferenceIndex(
            [
                ReceiptScope(name="project", store=self.project),
                ReceiptScope(name="global", store=self.global_),
            ]
        )

    def install(
        self,
        *,
        scope: str = "project",
        upstream_id: str = "kits/anchor",
        name: str = "anchor",
        revision: str | None = None,
        body: bytes = b"---\nname: anchor\n---\nanchor body\n",
        provider: str = PROVIDER,
        completeness: CompletenessEvidence | None = None,
    ):
        files = {"SKILL.md": body}
        store = self.project if scope == "project" else self.global_
        return install_foreign_item(
            _item(
                provider_identity=provider,
                upstream_id=upstream_id,
                upstream_name=name,
                library_name=name,
                upstream_revision=revision,
            ),
            retrieve=lambda: FetchedItem(
                upstream_id=upstream_id,
                revision=revision,
                files=tuple(
                    FetchedFile(path=path, content=content) for path, content in files.items()
                ),
                primary_path="SKILL.md",
            ),
            object_store=self.objects,
            pin_store=self.pins,
            receipt_store=store,
            transformation=IDENTITY_TRANSFORMATION,
            target="project_committed",
            activate=self.projector.activation,
            completeness=completeness or CompletenessEvidence.from_manifest(sorted(files)),
            observed_at=NOW,
        )

    def unreference(self, outcome, *, scope: str = "project") -> None:
        """Retire the receipt without deleting the bytes, as the ADR requires."""
        store = self.project if scope == "project" else self.global_
        remove_named_receipt(
            store,
            outcome.receipt.id,
            operator="operator@example.test",
            intent="the project no longer installs this item",
            observation=_observation(
                provider=outcome.receipt.provider_identity,
                identities=(outcome.receipt.qualified_identity(),),
            ),
            removed_at=LATER,
            deactivate=self.projector.deactivate,
        )


def _observation(
    *,
    provider: str = PROVIDER,
    availability: ProviderAvailability = AVAILABLE,
    identities: Sequence[str] = (),
    complete: bool = True,
    reduced_by_authorization: bool = False,
) -> ResolutionEvidence:
    return ResolutionEvidence(
        provider_identity=provider,
        availability=availability,
        listed_identities=frozenset(identities),
        complete=complete,
        reduced_by_authorization=reduced_by_authorization,
    )


def _proof(outcome, *, digest: str | None = None) -> RefetchProof:
    return RefetchProof(
        provider_identity=outcome.receipt.provider_identity,
        qualified_identity=outcome.receipt.qualified_identity(),
        observed_digest=digest or outcome.receipt.normalized_content_digest,
        observed_at=LATER,
    )


def _fingerprint(root: Path) -> dict[str, str]:
    """Every file under a tree, with its content hash. Nothing may change."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _decision(plan, digest: str):
    matches = [decision for decision in plan.decisions if decision.key_digest == digest]
    assert matches, f"no retention decision for {digest}"
    return matches[0]


# -- AC1: active receipts protect their objects, across every scope -----------


def test_referenced_object_is_protected(tmp_path: Path) -> None:
    """An active receipt in any scope makes its object ineligible (AC1)."""
    cache = _Cache(tmp_path)
    project = cache.install(scope="project", upstream_id="kits/anchor", name="anchor")
    globally = cache.install(
        scope="global",
        upstream_id="kits/beacon",
        name="beacon",
        body=b"---\nname: beacon\n---\nbeacon body\n",
    )

    identities = (
        project.receipt.qualified_identity(),
        globally.receipt.qualified_identity(),
    )
    observation = _observation(identities=identities)
    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: observation},
        refetch_proofs=(_proof(project), _proof(globally)),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )

    assert not plan.collectable
    for outcome, scope in ((project, "project"), (globally, "global")):
        decision = _decision(plan, outcome.cache_object.key.digest())
        assert not decision.collectable
        assert decision.reason == "referenced-by-active-receipt"
        assert [reference.scope for reference in decision.references] == [scope]
        assert decision.references[0].receipt_id == outcome.receipt.id

    before = _fingerprint(cache.objects.base)
    result = collect_garbage(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: observation},
        refetch_proofs=(_proof(project), _proof(globally)),
        observed_at=LATER,
        evidence_max_age=WINDOW,
        pin_store=cache.pins,
    )
    assert result.deleted == ()
    assert _fingerprint(cache.objects.base) == before
    assert cache.objects.verify(globally.cache_object.key).verified


def test_reference_index_requires_every_declared_scope(tmp_path: Path) -> None:
    """A project-only reference check would collect a globally referenced object."""
    cache = _Cache(tmp_path)
    assert set(REQUIRED_SCOPES) == {"project", "global"}

    with pytest.raises(ScopeUnreadable) as missing:
        ReferenceIndex([ReceiptScope(name="project", store=cache.project)])
    assert "global" in str(missing.value)

    with pytest.raises(ScopeUnreadable):
        ReferenceIndex(
            [
                ReceiptScope(name="project", store=cache.project),
                ReceiptScope(name="project", store=cache.global_),
            ]
        )


def test_unreadable_scope_never_reads_as_unreferenced(tmp_path: Path) -> None:
    """A scope that cannot be read is a refusal, never an empty answer."""
    cache = _Cache(tmp_path)
    globally = cache.install(scope="global", upstream_id="kits/beacon", name="beacon")

    # A corrupt scope file is not "no references".
    cache.global_.path.write_text("{ not json", encoding="utf-8")
    index = cache.index()
    with pytest.raises(ScopeUnreadable) as corrupt:
        index.references(globally.cache_object.key.digest())
    assert "global" in str(corrupt.value)

    # A scope whose declared location does not exist at all is also a refusal:
    # an unmounted or not-yet-created global state directory must not answer
    # "nothing references this".
    absent = ReceiptStore(tmp_path / "nowhere" / "receipts.json")
    with pytest.raises(ScopeUnreadable):
        ReferenceIndex(
            [
                ReceiptScope(name="project", store=cache.project),
                ReceiptScope(name="global", store=absent),
            ]
        )


# -- AC2: fail closed whenever exact re-fetchability is not proven ------------


def test_gc_fails_closed_when_unavailable(tmp_path: Path) -> None:
    """An unreachable provider retains every unreferenced object (AC2)."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    digest = outcome.cache_object.key.digest()

    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            PROVIDER: _observation(
                availability=UNAVAILABLE,
                identities=(outcome.receipt.qualified_identity(),),
            )
        },
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, digest)
    assert decision.references == ()
    assert not decision.collectable
    assert decision.reason == "provider-unavailable"
    assert decision.reason in RETENTION_REFUSALS
    assert "unavailable" in decision.detail

    # A degraded provider is refused for the same reason: partial health is not
    # proof that these bytes can be retrieved again.
    degraded = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            PROVIDER: _observation(
                availability=DEGRADED,
                identities=(outcome.receipt.qualified_identity(),),
            )
        },
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    assert _decision(degraded, digest).reason == "provider-unavailable"
    assert not degraded.collectable

    before = _fingerprint(cache.objects.base)
    result = collect_garbage(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            PROVIDER: _observation(
                availability=UNAVAILABLE,
                identities=(outcome.receipt.qualified_identity(),),
            )
        },
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
        pin_store=cache.pins,
    )
    assert result.deleted == ()
    assert _fingerprint(cache.objects.base) == before
    assert cache.objects.verify(outcome.cache_object.key).verified


def test_gc_fails_closed_when_revoked(tmp_path: Path) -> None:
    """Access revoked is its own named condition, not "provider is fine" (AC2)."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)

    observation = _observation(
        identities=(outcome.receipt.qualified_identity(),),
        reduced_by_authorization=True,
    )
    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: observation},
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, outcome.cache_object.key.digest())
    assert not decision.collectable
    assert decision.reason == "access-revoked"
    assert "authorization" in decision.detail

    result = collect_garbage(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: observation},
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
        pin_store=cache.pins,
    )
    assert result.deleted == ()
    assert cache.objects.verify(outcome.cache_object.key).verified


def test_gc_fails_closed_when_upstream_vanished(tmp_path: Path) -> None:
    """A vanished upstream is exactly when the local cache is most valuable (AC2)."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    identity = outcome.receipt.qualified_identity()

    # The upstream item disappears while the receipt is still active, so the
    # durable `upstream-vanished` state is recorded, and only then is the
    # receipt explicitly removed. The bytes stay, and they are now the last copy.
    reconcile_upstream_state(
        cache.project, _observation(identities=()), observed_at=LATER
    )
    cache.unreference(outcome)

    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: _observation(identities=())},
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, outcome.cache_object.key.digest())
    assert not decision.collectable
    assert decision.reason == "upstream-vanished"
    assert identity in decision.detail

    result = collect_garbage(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: _observation(identities=())},
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
        pin_store=cache.pins,
    )
    assert result.deleted == ()
    assert cache.objects.verify(outcome.cache_object.key).verified


def test_gc_fails_closed_for_revisionless_without_refetch_proof(tmp_path: Path) -> None:
    """Provider health is not re-fetchability for a pin-only source (AC2).

    The provider is available, complete, authorized, and still lists the item.
    Nothing about that says the bytes it now serves are the pinned bytes.
    """
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    identity = outcome.receipt.qualified_identity()

    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: _observation(identities=(identity,))},
        refetch_proofs=(),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, outcome.cache_object.key.digest())
    assert not decision.collectable
    assert decision.reason == "re-fetchability-not-proven"
    assert "digest-verified" in decision.detail

    # A proof for a different identity is not this object's proof.
    other = cache.install(
        scope="global",
        upstream_id="kits/beacon",
        name="beacon",
        body=b"---\nname: beacon\n---\nbeacon body\n",
    )
    borrowed = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: _observation(identities=(identity, other.receipt.qualified_identity()))},
        refetch_proofs=(_proof(other),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    assert _decision(borrowed, outcome.cache_object.key.digest()).reason == (
        "re-fetchability-not-proven"
    )


def test_gc_refuses_revisionless_digest_drift(tmp_path: Path) -> None:
    """Available, listed, and serving different bytes is drift, not garbage (AC2).

    Deleting here would destroy the last copy of the pinned content, and a later
    reinstall would record a fresh first-use pin -- turning detectable drift into
    undetectable silent substitution.
    """
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    identity = outcome.receipt.qualified_identity()
    served = content_digest({"SKILL.md": b"---\nname: anchor\n---\nreplaced body\n"})

    observation = _observation(identities=(identity,))
    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: observation},
        refetch_proofs=(_proof(outcome, digest=served),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, outcome.cache_object.key.digest())
    assert not decision.collectable
    assert decision.reason == "refetch-digest-drift"
    assert outcome.receipt.normalized_content_digest in decision.detail
    assert served in decision.detail

    result = collect_garbage(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: observation},
        refetch_proofs=(_proof(outcome, digest=served),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
        pin_store=cache.pins,
    )
    assert result.deleted == ()
    assert cache.objects.verify(outcome.cache_object.key).verified


def test_gc_requires_an_observation_for_the_objects_own_provider(tmp_path: Path) -> None:
    """One source's observation says nothing about another source's objects."""
    cache = _Cache(tmp_path)
    outcome = cache.install(provider=PROVIDER)
    cache.unreference(outcome)

    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            OTHER_PROVIDER: _observation(
                provider=OTHER_PROVIDER, identities=(outcome.receipt.qualified_identity(),)
            )
        },
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, outcome.cache_object.key.digest())
    assert not decision.collectable
    assert decision.reason == "provider-not-observed"


def test_gc_fails_closed_on_an_incomplete_inventory(tmp_path: Path) -> None:
    """A truncated listing cannot prove an item still exists upstream."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)

    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            PROVIDER: _observation(
                identities=(outcome.receipt.qualified_identity(),), complete=False
            )
        },
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, outcome.cache_object.key.digest())
    assert not decision.collectable
    assert decision.reason == "inventory-incomplete"


def test_gc_fails_closed_when_completeness_rests_on_the_adapters_word(
    tmp_path: Path,
) -> None:
    """An install with no independent completeness proof needs a verified re-fetch."""
    cache = _Cache(tmp_path)
    outcome = cache.install(
        revision="v1.0.0",
        completeness=CompletenessEvidence.adapter_declared(
            "the adapter's contract states the item is complete"
        ),
    )
    assert outcome.receipt.completeness_evidence == "adapter-declaration"
    cache.unreference(outcome)

    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            PROVIDER: _observation(identities=(outcome.receipt.qualified_identity(),))
        },
        refetch_proofs=(),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, outcome.cache_object.key.digest())
    assert not decision.collectable
    assert decision.reason == "re-fetchability-not-proven"
    assert "adapter-declaration" in decision.detail


def test_gc_collects_only_when_every_precondition_is_proven(tmp_path: Path) -> None:
    """The collectable case exists, and it deletes exactly one object."""
    cache = _Cache(tmp_path)
    keeper = cache.install(scope="global", upstream_id="kits/beacon", name="beacon")
    goner = cache.install(
        scope="project",
        upstream_id="kits/anchor",
        name="anchor",
        revision="v1.0.0",
        body=b"---\nname: anchor\n---\nanchor body\n",
    )
    cache.unreference(goner)
    identities = (
        keeper.receipt.qualified_identity(),
        goner.receipt.qualified_identity(),
    )

    result = collect_garbage(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: _observation(identities=identities)},
        refetch_proofs=(_proof(keeper), _proof(goner)),
        observed_at=LATER,
        evidence_max_age=WINDOW,
        pin_store=cache.pins,
    )
    assert [decision.key_digest for decision in result.deleted] == [
        goner.cache_object.key.digest()
    ]
    assert not goner.cache_object.path.exists()
    assert cache.objects.verify(keeper.cache_object.key).verified
    # Deletion leaves nothing half-removed and no staging residue behind.
    assert cache.objects.temporary_entries() == ()
    assert [obj.key.digest() for obj in cache.objects.objects()] == [
        keeper.cache_object.key.digest()
    ]


def test_gc_never_collects_quarantined_evidence(tmp_path: Path) -> None:
    """Objects a repair set aside are retained evidence, not garbage."""
    cache = _Cache(tmp_path)
    outcome = cache.install(revision="v1.0.0")
    cache.unreference(outcome)
    quarantine = outcome.cache_object.path.with_name(
        f"{outcome.cache_object.path.name}{QUARANTINE_SUFFIX}deadbeef"
    )
    shutil.copytree(outcome.cache_object.path, quarantine)
    assert quarantine in cache.objects.quarantined()

    result = collect_garbage(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            PROVIDER: _observation(identities=(outcome.receipt.qualified_identity(),))
        },
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
        pin_store=cache.pins,
    )
    assert [decision.key_digest for decision in result.deleted] == [
        outcome.cache_object.key.digest()
    ]
    assert quarantine.is_dir()
    assert quarantine in cache.objects.quarantined()
    assert not any(
        decision.path == quarantine for decision in result.plan.decisions
    )


def test_gc_rechecks_references_under_the_install_lock(tmp_path: Path) -> None:
    """A reference written after the plan still protects the object."""
    cache = _Cache(tmp_path)
    goner = cache.install(revision="v1.0.0")
    cache.unreference(goner)
    identity = goner.receipt.qualified_identity()

    real_lock = cache.pins.identity_lock
    raced: list[str] = []

    @contextmanager
    def racing_lock(qualified_identity: str) -> Iterator[None]:
        with real_lock(qualified_identity):
            if not raced:
                raced.append(qualified_identity)
                # A concurrent install in another scope adopts the same object
                # between the decision and the deletion.
                cache.global_.put(goner.receipt)
            yield

    cache.pins.identity_lock = racing_lock  # type: ignore[method-assign]
    result = collect_garbage(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: _observation(identities=(identity,))},
        refetch_proofs=(_proof(goner),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
        pin_store=cache.pins,
    )
    assert result.deleted == ()
    assert [decision.reason for decision in result.raced] == [
        "referenced-by-active-receipt"
    ]
    assert cache.objects.verify(goner.cache_object.key).verified


# -- AC3: automatic collection never escalates into purge ---------------------


def test_gc_never_invokes_purge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Under every provider condition, garbage collection never purges (AC3)."""
    calls: list[str] = []

    def _forbidden(name: str):
        def _call(*args: object, **kwargs: object):
            calls.append(name)
            raise AssertionError(f"garbage collection reached {name}")

        return _call

    monkeypatch.setattr(retention, "purge_object", _forbidden("purge_object"))
    monkeypatch.setattr(retention, "plan_purge", _forbidden("plan_purge"))

    cache = _Cache(tmp_path)
    referenced = cache.install(scope="global", upstream_id="kits/beacon", name="beacon")
    unreferenced = cache.install(revision="v1.0.0")
    cache.unreference(unreferenced)
    identities = (
        referenced.receipt.qualified_identity(),
        unreferenced.receipt.qualified_identity(),
    )
    drifted = content_digest({"SKILL.md": b"different bytes"})

    conditions = (
        _observation(identities=identities),
        _observation(availability=UNAVAILABLE, identities=identities),
        _observation(availability=DEGRADED, identities=identities),
        _observation(identities=identities, reduced_by_authorization=True),
        _observation(identities=identities, complete=False),
        _observation(identities=()),
    )
    for observation in conditions:
        for proofs in ((), (_proof(unreferenced),), (_proof(unreferenced, digest=drifted),)):
            plan = plan_garbage_collection(
                object_store=cache.objects,
                references=cache.index(),
                observations={PROVIDER: observation},
                refetch_proofs=proofs,
                observed_at=LATER,
                evidence_max_age=WINDOW,
            )
            assert plan.decisions
            collect_garbage(
                object_store=cache.objects,
                references=cache.index(),
                observations={PROVIDER: observation},
                refetch_proofs=proofs,
                observed_at=LATER,
                evidence_max_age=WINDOW,
                pin_store=cache.pins,
            )
    assert calls == []


def test_no_static_call_path_from_collection_to_purge() -> None:
    """The absence of a purge call is structural, not a property of one run (AC3).

    A runtime sentinel proves the paths that were exercised. This proves there is
    no path at all: every function reachable from the collection entry points is
    walked, and none of them names a purge entry point.
    """
    module_path = REPO_ROOT / "scripts" / "lib" / "providers" / "retention.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    purge_entry_points = {"purge_object", "plan_purge", "_delete_quarantine"}

    reached: set[str] = set()
    pending = ["collect_garbage", "plan_garbage_collection"]
    named: list[str] = []
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        reached.add(current)
        node = functions.get(current)
        if node is None:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            target = call.func
            name = (
                target.id
                if isinstance(target, ast.Name)
                else target.attr
                if isinstance(target, ast.Attribute)
                else None
            )
            if name is None:
                continue
            if name in purge_entry_points:
                named.append(f"{current} -> {name}")
            pending.append(name)

    assert named == []
    assert "collect_garbage" in reached and "plan_garbage_collection" in reached


# -- wave-1 adversarial review regressions (gpt-5.6-sol) ----------------------
#
# Each test below reproduces one demonstrated defect from the wave-1 review and
# is kept as a regression. They are written as executable tests rather than as
# repair notes because the mandated co-reviewer was unavailable for this bead,
# so every reviewer proof-of-concept is re-executed against the delivered
# candidate on every run.


def test_scope_labels_cannot_alias_one_store_as_two_scopes(tmp_path: Path) -> None:
    """Wave-1 F2: one store under both required labels hid the real global lock.

    The required-scope check passed, the actual global store was never read, and
    an object a live global receipt referenced was collected.
    """
    cache = _Cache(tmp_path)
    cache.install(scope="global", upstream_id="kits/beacon", name="beacon")

    with pytest.raises(ScopeUnreadable) as aliased:
        ReferenceIndex(
            [
                ReceiptScope(name="project", store=cache.project),
                ReceiptScope(name="global", store=cache.project),
            ]
        )
    assert "one store cannot answer for two scopes" in str(aliased.value)

    # Two distinct ReceiptStore objects over the same file are the same alias.
    with pytest.raises(ScopeUnreadable):
        ReferenceIndex(
            [
                ReceiptScope(name="project", store=cache.project),
                ReceiptScope(name="global", store=ReceiptStore(cache.project.path)),
            ]
        )


@pytest.mark.parametrize("stale_last", [True, False])
def test_conflicting_refetch_proofs_fail_closed(tmp_path: Path, stale_last: bool) -> None:
    """Wave-1 F3: the last proof in the sequence used to win.

    A stale proof that matched the pin overrode a current one that showed drift,
    so argument order decided whether irreplaceable bytes were deleted.
    """
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    identity = outcome.receipt.qualified_identity()
    served = content_digest({"SKILL.md": b"---\nname: anchor\n---\nreplaced body\n"})

    matching = _proof(outcome)
    drifting = RefetchProof(
        provider_identity=PROVIDER,
        qualified_identity=identity,
        observed_digest=served,
        observed_at=LATER,
    )
    proofs = (drifting, matching) if stale_last else (matching, drifting)

    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: _observation(identities=(identity,))},
        refetch_proofs=proofs,
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, outcome.cache_object.key.digest())
    assert decision.reason == "refetch-digest-drift"
    assert not decision.collectable

    result = collect_garbage(
        object_store=cache.objects,
        references=cache.index(),
        observations={PROVIDER: _observation(identities=(identity,))},
        refetch_proofs=proofs,
        observed_at=LATER,
        evidence_max_age=WINDOW,
        pin_store=cache.pins,
    )
    assert result.deleted == ()
    assert cache.objects.verify(outcome.cache_object.key).verified


def test_a_refetch_proof_older_than_its_observation_is_stale(tmp_path: Path) -> None:
    """Wave-1 F3: a proof is about what the source serves now, so it must be current."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    identity = outcome.receipt.qualified_identity()

    ancient = RefetchProof(
        provider_identity=PROVIDER,
        qualified_identity=identity,
        observed_digest=outcome.receipt.normalized_content_digest,
        observed_at="2000-01-01T00:00:00Z",
    )
    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            PROVIDER: _observation(
                availability=ProviderAvailability(state="available", observed_at=LATER),
                identities=(identity,),
            )
        },
        refetch_proofs=(ancient,),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, outcome.cache_object.key.digest())
    assert decision.reason == "refetch-proof-stale"
    assert "2000-01-01T00:00:00Z" in decision.detail

    # A proof whose time cannot be ordered is not a proof at all.
    with pytest.raises(ValueError, match="ISO-8601"):
        RefetchProof(
            provider_identity=PROVIDER,
            qualified_identity=identity,
            observed_digest=outcome.receipt.normalized_content_digest,
            observed_at="recently",
        )


def test_simultaneous_degraded_conditions_are_all_named(tmp_path: Path) -> None:
    """Wave-1 F6: an if/elif chain reported one of three facts that all held."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)

    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            PROVIDER: _observation(
                availability=UNAVAILABLE,
                identities=(outcome.receipt.qualified_identity(),),
                complete=False,
                reduced_by_authorization=True,
            )
        },
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, outcome.cache_object.key.digest())
    assert set(decision.conditions) >= {
        "provider-unavailable",
        "access-revoked",
        "inventory-incomplete",
    }
    # Precedence still picks one primary reason, and it is the first in the
    # declared order rather than the first branch that happened to run.
    assert decision.reason == "provider-unavailable"
    assert list(decision.conditions) == [
        reason for reason in RETENTION_REFUSALS if reason in set(decision.conditions)
    ]


@pytest.mark.parametrize("mode", ["raises", "silently-ineffective"])
def test_a_failed_removal_is_never_reported_as_a_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Wave-1 F5: `ignore_errors=True` turned a failed removal into a success.

    Both shapes are covered: a removal that raises, and the shape the swallowed
    error actually produced -- a removal that reports nothing and removes
    nothing, which the caller then recorded as a deletion.
    """
    cache = _Cache(tmp_path)
    outcome = cache.install(revision="v1.0.0")
    cache.unreference(outcome)

    def _refuse(*args: object, **kwargs: object) -> None:
        if mode == "raises":
            raise OSError("the filesystem refused to remove the staged tree")

    monkeypatch.setattr(retention.shutil, "rmtree", _refuse)
    with pytest.raises(RetentionError) as failed:
        collect_garbage(
            object_store=cache.objects,
            references=cache.index(),
            observations={
                PROVIDER: _observation(identities=(outcome.receipt.qualified_identity(),))
            },
            refetch_proofs=(_proof(outcome),),
            observed_at=LATER,
            evidence_max_age=WINDOW,
            pin_store=cache.pins,
        )
    assert "not deleted" in str(failed.value) or "still present" in str(failed.value)

    # The bytes are still on disk, staged and reclaimable rather than lost.
    monkeypatch.undo()
    assert cache.objects.temporary_entries() != ()


# -- wave-2 adversarial review regressions (gpt-5.6-sol) ----------------------


def test_a_corrupt_receipt_scope_is_never_read_as_empty(tmp_path: Path) -> None:
    """Wave-2 F3: `receipts: null` parsed as "this scope holds nothing".

    The index trusted the store to raise on a damaged file, and the store's own
    parser turned a falsey value into an empty active set. Absence of receipts is
    deletion authority, so the two must never be the same answer.
    """
    cache = _Cache(tmp_path)
    outcome = cache.install(scope="global", revision="v1.0.0")
    digest = outcome.cache_object.key.digest()
    assert cache.index().references(digest)

    for broken in ("null", "false", '""', '"[]"', "0"):
        cache.global_.path.write_text(
            '{"schema": "cognovis.foreign-receipt-store.v1", "receipts": '
            + broken
            + "}",
            encoding="utf-8",
        )
        index = cache.index()
        with pytest.raises(ScopeUnreadable):
            index.references(digest)
        with pytest.raises(ScopeUnreadable):
            collect_garbage(
                object_store=cache.objects,
                references=cache.index(),
                observations={
                    PROVIDER: _observation(
                        identities=(outcome.receipt.qualified_identity(),)
                    )
                },
                refetch_proofs=(_proof(outcome),),
                observed_at=LATER,
                evidence_max_age=WINDOW,
                pin_store=cache.pins,
            )
        assert cache.objects.verify(outcome.cache_object.key).verified

    # A damaged `retired` list is the same fact: it carries the completeness and
    # upstream-state evidence an unreferenced object is judged on.
    cache.global_.path.write_text(
        '{"schema": "cognovis.foreign-receipt-store.v1", "receipts": [], '
        '"retired": null}',
        encoding="utf-8",
    )
    with pytest.raises(ScopeUnreadable):
        cache.index().receipts_for_digest(digest)


def test_evidence_older_than_the_run_window_fails_closed(tmp_path: Path) -> None:
    """Wave-2 F4: an observation and a proof that agree can both be decades old."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    identity = outcome.receipt.qualified_identity()
    ancient = "2000-01-01T00:00:00Z"

    plan = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            PROVIDER: _observation(
                availability=ProviderAvailability(state="available", observed_at=ancient),
                identities=(identity,),
            )
        },
        refetch_proofs=(
            RefetchProof(
                provider_identity=PROVIDER,
                qualified_identity=identity,
                observed_digest=outcome.receipt.normalized_content_digest,
                observed_at=ancient,
            ),
        ),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    decision = _decision(plan, outcome.cache_object.key.digest())
    assert not decision.collectable
    assert decision.reason == "provider-observation-stale"
    assert set(decision.conditions) >= {"provider-observation-stale", "refetch-proof-stale"}

    # Evidence from after the run is equally unusable.
    future = plan_garbage_collection(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            PROVIDER: _observation(
                availability=ProviderAvailability(
                    state="available", observed_at="2099-01-01T00:00:00Z"
                ),
                identities=(identity,),
            )
        },
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
    )
    assert _decision(future, outcome.cache_object.key.digest()).reason == (
        "provider-observation-stale"
    )

    # The window is a required decision, not a defaulted one.
    with pytest.raises(TypeError, match="evidence_max_age"):
        plan_garbage_collection(  # type: ignore[call-arg]
            object_store=cache.objects,
            references=cache.index(),
            observations={PROVIDER: _observation(identities=(identity,))},
            observed_at=LATER,
        )
    with pytest.raises(ValueError, match="positive timedelta"):
        plan_garbage_collection(
            object_store=cache.objects,
            references=cache.index(),
            observations={PROVIDER: _observation(identities=(identity,))},
            observed_at=LATER,
            evidence_max_age=timedelta(0),
        )
    with pytest.raises(ValueError, match="ISO-8601"):
        plan_garbage_collection(
            object_store=cache.objects,
            references=cache.index(),
            observations={PROVIDER: _observation(identities=(identity,))},
            observed_at="now",
            evidence_max_age=WINDOW,
        )


def test_collection_holds_every_receipt_scope_lock_while_it_deletes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave-2 F2: a receipt committed after the final read still lost its object.

    The install identity lock excludes an install transaction and nothing else.
    A bare `ReceiptStore.put` is guarded only by the receipt file's own lock, so
    the proof and the deletion have to hold that lock too. `flock` is per open
    file description, so a second non-blocking attempt from this same process
    fails exactly when the lock is held.
    """
    cache = _Cache(tmp_path)
    outcome = cache.install(revision="v1.0.0")
    cache.unreference(outcome)

    def _scope_lock_is_held(store: ReceiptStore) -> bool:
        handle = os.open(
            str(store.path.with_name(f"{store.path.name}.lock")),
            os.O_CREAT | os.O_RDWR,
            0o600,
        )
        try:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                return exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK)
            fcntl.flock(handle, fcntl.LOCK_UN)
            return False
        finally:
            os.close(handle)

    observed: list[tuple[bool, bool]] = []
    real_discard = retention._discard_object

    def _watching_discard(object_store, cache_object):
        observed.append(
            (_scope_lock_is_held(cache.project), _scope_lock_is_held(cache.global_))
        )
        return real_discard(object_store, cache_object)

    monkeypatch.setattr(retention, "_discard_object", _watching_discard)
    result = collect_garbage(
        object_store=cache.objects,
        references=cache.index(),
        observations={
            PROVIDER: _observation(identities=(outcome.receipt.qualified_identity(),))
        },
        refetch_proofs=(_proof(outcome),),
        observed_at=LATER,
        evidence_max_age=WINDOW,
        pin_store=cache.pins,
    )
    assert len(result.deleted) == 1
    assert observed == [(True, True)]
