"""Operator-explicit purge by object digest (CL-uliw).

ADR-0011 `Operator-explicit purge` is the only path that deletes an unreferenced
cache object under degraded conditions. It requires an object digest -- not a
name, not a glob, not a provider -- proves across every scope that no active
receipt references it, records an explicit acknowledgement that the loss is
permanent and the bytes may not be re-fetchable, and is never invoked by
automatic reconciliation or garbage collection.

"Purge is a human act with a digest in their hand" is the sentence these tests
hold in place.

Covers AC4, AC5, AC6, and AC7.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
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
    remove_named_receipt,
)
from lib.providers.retention import (  # noqa: E402
    PURGE_ACKNOWLEDGEMENT,
    PURGE_REFUSALS,
    PurgeAcknowledgement,
    PurgeLedger,
    PurgeRefused,
    ReceiptScope,
    ReferenceIndex,
    RetentionError,
    ScopeUnreadable,
    plan_purge,
    purge_object,
)
from lib.providers import retention  # noqa: E402

PROVIDER = "provider-under-test"
NOW = "2026-08-09T09:00:00Z"
LATER = "2026-08-09T12:00:00Z"
OPERATOR = "operator@example.test"
MIT = "upstream LICENSE (MIT), read from the fetched item on 2026-08-09"

GRANTED = Rights(
    fetch_authorization="granted",
    install_rights="granted",
    redistribution_rights="granted",
    derivative_rights="granted",
    evidence_source=MIT,
)
AVAILABLE = ProviderAvailability(state="available", observed_at=NOW)
UNAVAILABLE = ProviderAvailability(
    state="unavailable", observed_at=LATER, reason="the source host is gone"
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
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.objects = ObjectStore(tmp_path / "cache")
        self.pins = TofuPinStore(tmp_path / "pins.json")
        self.project = ReceiptStore(tmp_path / "project" / "receipts.json")
        self.global_ = ReceiptStore(tmp_path / "global" / "receipts.json")
        self.project.path.parent.mkdir(parents=True, exist_ok=True)
        self.global_.path.parent.mkdir(parents=True, exist_ok=True)
        self.projector = _Projector(tmp_path / "harness")
        self.ledger = PurgeLedger(tmp_path / "purge-ledger.json")

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
        body: bytes = b"---\nname: anchor\n---\nanchor body\n",
    ):
        files = {"SKILL.md": body, "reference.md": b"# reference\n"}
        store = self.project if scope == "project" else self.global_
        return install_foreign_item(
            _item(upstream_id=upstream_id, upstream_name=name, library_name=name),
            retrieve=lambda: FetchedItem(
                upstream_id=upstream_id,
                revision=None,
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
            completeness=CompletenessEvidence.from_manifest(sorted(files)),
            observed_at=NOW,
        )

    def unreference(self, outcome, *, scope: str = "project") -> None:
        store = self.project if scope == "project" else self.global_
        remove_named_receipt(
            store,
            outcome.receipt.id,
            operator=OPERATOR,
            intent="the item is gone upstream and the project no longer installs it",
            observation=ResolutionEvidence(
                provider_identity=outcome.receipt.provider_identity,
                availability=UNAVAILABLE,
            ),
            removed_at=LATER,
            deactivate=self.projector.deactivate,
        )


def _acknowledgement(digest: str, **overrides: object) -> PurgeAcknowledgement:
    base = dict(
        operator=OPERATOR,
        digest=digest,
        reason="the source is permanently gone and the disk is needed",
        acknowledged_at=LATER,
        acknowledgement=PURGE_ACKNOWLEDGEMENT,
    )
    base.update(overrides)
    return PurgeAcknowledgement(**base)  # type: ignore[arg-type]


def _fingerprint(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# -- AC4: a purge is addressed by object digest, and by nothing else ----------


def test_purge_requires_digest(tmp_path: Path) -> None:
    """A name, a glob, or a provider identifier is rejected (AC4)."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    digest = outcome.cache_object.key.digest()

    not_digests = (
        "anchor",
        "skill/anchor",
        "skill/*",
        "*",
        PROVIDER,
        f"{PROVIDER}#kits/anchor",
        outcome.receipt.id,
        "0" * 40,
        f"sha256:{'a' * 64}",
        digest.upper(),
        digest[:32],
        f"{digest} ",
        "",
    )
    for candidate in not_digests:
        with pytest.raises(PurgeRefused) as refused:
            plan_purge(
                object_store=cache.objects, references=cache.index(), digest=candidate
            )
        assert refused.value.reason == "not-an-object-digest"
        assert refused.value.reason in PURGE_REFUSALS

        # The same refusal guards the acknowledgement, so an operator cannot
        # even record an intent to purge something that is not an object.
        with pytest.raises(PurgeRefused) as acknowledged:
            _acknowledgement(candidate)
        assert acknowledged.value.reason == "not-an-object-digest"

    # A well-formed digest that addresses nothing is a distinct refusal, never a
    # fuzzy match onto a neighbouring object.
    with pytest.raises(PurgeRefused) as missing:
        plan_purge(object_store=cache.objects, references=cache.index(), digest="b" * 64)
    assert missing.value.reason == "no-such-object"

    plan = plan_purge(
        object_store=cache.objects, references=cache.index(), digest=digest
    )
    assert plan.deletable
    assert plan.digest == digest


def test_purge_is_never_reached_by_automatic_reconciliation(tmp_path: Path) -> None:
    """Purge refuses any origin other than an operator naming the digest."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)

    with pytest.raises(PurgeRefused) as refused:
        purge_object(
            object_store=cache.objects,
            references=cache.index(),
            pin_store=cache.pins,
            ledger=cache.ledger,
            acknowledgement=_acknowledgement(outcome.cache_object.key.digest()),
            origin="automatic-garbage-collection",
        )
    assert refused.value.reason == "not-operator-explicit"
    assert cache.objects.verify(outcome.cache_object.key).verified
    assert cache.ledger.entries() == ()


# -- AC5: no active receipt in any scope may reference the digest -------------


def test_purge_refuses_referenced_digest(tmp_path: Path) -> None:
    """A live reference stops the purge, whichever scope holds it (AC5)."""
    cache = _Cache(tmp_path)
    outcome = cache.install(scope="global")
    digest = outcome.cache_object.key.digest()

    plan = plan_purge(object_store=cache.objects, references=cache.index(), digest=digest)
    assert not plan.deletable
    assert plan.blocked_reason == "referenced-by-active-receipt"
    assert [reference.scope for reference in plan.references] == ["global"]
    assert plan.references[0].receipt_id == outcome.receipt.id

    with pytest.raises(PurgeRefused) as refused:
        purge_object(
            object_store=cache.objects,
            references=cache.index(),
            pin_store=cache.pins,
            ledger=cache.ledger,
            acknowledgement=_acknowledgement(digest),
        )
    assert refused.value.reason == "referenced-by-active-receipt"
    assert "global" in str(refused.value)
    assert cache.objects.verify(outcome.cache_object.key).verified
    assert cache.ledger.entries() == ()


def test_purge_rechecks_references_under_the_install_lock(tmp_path: Path) -> None:
    """A reference that appears after the plan still stops the deletion (AC5)."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    digest = outcome.cache_object.key.digest()

    real_lock = cache.pins.identity_lock
    raced: list[str] = []

    @contextmanager
    def racing_lock(qualified_identity: str) -> Iterator[None]:
        with real_lock(qualified_identity):
            if not raced:
                raced.append(qualified_identity)
                cache.global_.put(outcome.receipt)
            yield

    cache.pins.identity_lock = racing_lock  # type: ignore[method-assign]
    with pytest.raises(PurgeRefused) as refused:
        purge_object(
            object_store=cache.objects,
            references=cache.index(),
            pin_store=cache.pins,
            ledger=cache.ledger,
            acknowledgement=_acknowledgement(digest),
        )
    assert refused.value.reason == "referenced-by-active-receipt"
    assert cache.objects.verify(outcome.cache_object.key).verified


def test_purge_refuses_when_a_scope_cannot_be_read(tmp_path: Path) -> None:
    """An unreadable scope is never the same answer as an unreferenced object."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    cache.global_.path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ScopeUnreadable):
        purge_object(
            object_store=cache.objects,
            references=cache.index(),
            pin_store=cache.pins,
            ledger=cache.ledger,
            acknowledgement=_acknowledgement(outcome.cache_object.key.digest()),
        )
    assert cache.objects.verify(outcome.cache_object.key).verified


# -- AC6: the loss is acknowledged, explicitly and durably --------------------


def test_purge_requires_acknowledgement(tmp_path: Path) -> None:
    """Without the explicit acknowledgement of permanent loss, nothing is deleted (AC6)."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    digest = outcome.cache_object.key.digest()

    # There is no purge entry point that does not take an acknowledgement. The
    # diagnostic is matched, because "any TypeError" would also be satisfied by
    # an unrelated signature change (wave-1 A3).
    with pytest.raises(TypeError, match="acknowledgement"):
        purge_object(  # type: ignore[call-arg]
            object_store=cache.objects,
            references=cache.index(),
            pin_store=cache.pins,
            ledger=cache.ledger,
        )

    for wrong in ("", "yes", "ok", PURGE_ACKNOWLEDGEMENT.upper(), "permanent"):
        with pytest.raises(PurgeRefused) as refused:
            _acknowledgement(digest, acknowledgement=wrong)
        assert refused.value.reason == "acknowledgement-missing"
        assert "re-fetchable" in str(refused.value)

    # The acknowledgement names a person and a reason; neither is optional.
    for field, value in (("operator", ""), ("reason", ""), ("acknowledged_at", "")):
        with pytest.raises(PurgeRefused) as incomplete:
            _acknowledgement(digest, **{field: value})
        assert incomplete.value.reason == "acknowledgement-incomplete"

    assert cache.objects.verify(outcome.cache_object.key).verified
    assert cache.ledger.entries() == ()

    outcome_of_purge = purge_object(
        object_store=cache.objects,
        references=cache.index(),
        pin_store=cache.pins,
        ledger=cache.ledger,
        acknowledgement=_acknowledgement(digest),
    )
    assert not outcome.cache_object.path.exists()

    # The acknowledgement is durable: the record of who destroyed what, and on
    # what stated understanding, outlives the process that did it.
    entries = PurgeLedger(cache.ledger.path).entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["digest"] == digest
    assert entry["operator"] == OPERATOR
    assert entry["acknowledgement"] == PURGE_ACKNOWLEDGEMENT
    assert entry["reason"].startswith("the source is permanently gone")
    assert entry["status"] == "purged"
    assert entry["id"] == outcome_of_purge.ledger_entry_id
    assert sorted(entry["member_paths"]) == ["SKILL.md", "reference.md"]


def test_purge_deletes_under_degraded_conditions(tmp_path: Path) -> None:
    """A dead provider does not block the operator; it just never triggers them."""
    cache = _Cache(tmp_path)
    goner = cache.install()
    keeper = cache.install(
        scope="global",
        upstream_id="kits/beacon",
        name="beacon",
        body=b"---\nname: beacon\n---\nbeacon body\n",
    )
    cache.unreference(goner)
    digest = goner.cache_object.key.digest()

    result = purge_object(
        object_store=cache.objects,
        references=cache.index(),
        pin_store=cache.pins,
        ledger=cache.ledger,
        acknowledgement=_acknowledgement(digest),
    )
    assert result.plan.digest == digest
    assert not goner.cache_object.path.exists()
    assert sorted(result.deleted_paths) == sorted(result.plan.member_paths)
    assert cache.objects.temporary_entries() == ()
    assert [obj.key.digest() for obj in cache.objects.objects()] == [
        keeper.cache_object.key.digest()
    ]
    assert cache.objects.verify(keeper.cache_object.key).verified

    # Purging the bytes twice is a refusal, not a silent success.
    with pytest.raises(PurgeRefused) as again:
        purge_object(
            object_store=cache.objects,
            references=cache.index(),
            pin_store=cache.pins,
            ledger=cache.ledger,
            acknowledgement=_acknowledgement(digest),
        )
    assert again.value.reason == "no-such-object"


# -- AC7: the dry run reports exactly what would go, and changes nothing ------


def test_purge_dry_run_is_inert(tmp_path: Path) -> None:
    """The plan reports exactly what would be deleted and mutates nothing (AC7)."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    digest = outcome.cache_object.key.digest()

    before = _fingerprint(tmp_path)
    plan = plan_purge(object_store=cache.objects, references=cache.index(), digest=digest)

    content_root = outcome.cache_object.content_path
    on_disk = sorted(
        str(path.relative_to(content_root))
        for path in content_root.rglob("*")
        if path.is_file()
    )
    assert sorted(plan.member_paths) == on_disk
    assert plan.object_path == outcome.cache_object.path
    assert plan.byte_count == sum(
        path.stat().st_size for path in content_root.rglob("*") if path.is_file()
    )
    assert plan.deletable and plan.blocked_reason is None
    assert plan.references == ()

    assert _fingerprint(tmp_path) == before
    assert not cache.ledger.path.exists()
    assert cache.ledger.entries() == ()
    assert cache.objects.verify(outcome.cache_object.key).verified

    # A blocked plan is equally inert.
    cache.global_.put(outcome.receipt)
    before_blocked = _fingerprint(cache.objects.base)
    blocked = plan_purge(
        object_store=cache.objects, references=cache.index(), digest=digest
    )
    assert not blocked.deletable
    assert blocked.member_paths == plan.member_paths
    assert _fingerprint(cache.objects.base) == before_blocked
    assert cache.objects.verify(outcome.cache_object.key).verified


def test_purge_leaves_quarantined_evidence_unless_it_is_named(tmp_path: Path) -> None:
    """Set-aside evidence is only destroyed when the operator asks for it too."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    digest = outcome.cache_object.key.digest()
    quarantine = outcome.cache_object.path.with_name(
        f"{outcome.cache_object.path.name}{QUARANTINE_SUFFIX}deadbeef"
    )
    shutil.copytree(outcome.cache_object.path, quarantine)

    plan = plan_purge(object_store=cache.objects, references=cache.index(), digest=digest)
    assert plan.quarantine_paths == (quarantine,)
    assert not plan.includes_quarantine

    purge_object(
        object_store=cache.objects,
        references=cache.index(),
        pin_store=cache.pins,
        ledger=cache.ledger,
        acknowledgement=_acknowledgement(digest),
    )
    assert not outcome.cache_object.path.exists()
    assert quarantine.is_dir()

    second = purge_object(
        object_store=cache.objects,
        references=cache.index(),
        pin_store=cache.pins,
        ledger=cache.ledger,
        acknowledgement=_acknowledgement(digest),
        include_quarantined=True,
    )
    assert second.plan.includes_quarantine
    assert not quarantine.exists()
    assert cache.objects.quarantined() == ()
    assert [entry["status"] for entry in cache.ledger.entries()] == ["purged", "purged"]


# -- wave-1 adversarial review regressions (gpt-5.6-sol) ----------------------


def test_purge_never_reaches_a_lookalike_directory_inside_another_object(
    tmp_path: Path,
) -> None:
    """Wave-1 F1: quarantine discovery searched the whole object tree.

    A legitimate member directory of a *different*, actively referenced object
    was named like a quarantine of the purged digest, and purging removed it.
    """
    cache = _Cache(tmp_path)
    victim = cache.install()
    cache.unreference(victim)
    digest = victim.cache_object.key.digest()

    # A second item legitimately ships a directory whose name looks exactly like
    # a quarantine of the victim's digest.
    member = f"docs/{digest}{QUARANTINE_SUFFIX}legitimate/note.md"
    files = {"SKILL.md": b"---\nname: keeper\n---\nkeeper body\n", member: b"# note\n"}
    keeper = install_foreign_item(
        _item(upstream_id="kits/keeper", upstream_name="keeper", library_name="keeper"),
        retrieve=lambda: FetchedItem(
            upstream_id="kits/keeper",
            revision=None,
            files=tuple(
                FetchedFile(path=path, content=content) for path, content in files.items()
            ),
            primary_path="SKILL.md",
        ),
        object_store=cache.objects,
        pin_store=cache.pins,
        receipt_store=cache.global_,
        transformation=IDENTITY_TRANSFORMATION,
        target="project_committed",
        activate=cache.projector.activation,
        completeness=CompletenessEvidence.from_manifest(sorted(files)),
        observed_at=NOW,
    )
    assert cache.objects.verify(keeper.cache_object.key).verified

    plan = plan_purge(
        object_store=cache.objects,
        references=cache.index(),
        digest=digest,
        include_quarantined=True,
    )
    assert plan.quarantine_paths == ()
    assert not plan.includes_quarantine

    purge_object(
        object_store=cache.objects,
        references=cache.index(),
        pin_store=cache.pins,
        ledger=cache.ledger,
        acknowledgement=_acknowledgement(digest),
        include_quarantined=True,
    )
    assert not victim.cache_object.path.exists()
    assert (keeper.cache_object.content_path / member).is_file()
    assert cache.objects.verify(keeper.cache_object.key).verified


def test_quarantine_only_purge_uses_the_install_identity_lock(tmp_path: Path) -> None:
    """Wave-1 F4: a synthetic `purge#<digest>` lock serialized against nothing."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    digest = outcome.cache_object.key.digest()
    identity = outcome.receipt.qualified_identity()
    quarantine = outcome.cache_object.path.with_name(
        f"{outcome.cache_object.path.name}{QUARANTINE_SUFFIX}deadbeef"
    )
    shutil.copytree(outcome.cache_object.path, quarantine)

    purge_object(
        object_store=cache.objects,
        references=cache.index(),
        pin_store=cache.pins,
        ledger=cache.ledger,
        acknowledgement=_acknowledgement(digest),
    )
    assert not outcome.cache_object.path.exists()

    # Only the quarantined bytes remain. The plan still recovers the real
    # identity from the quarantined tree's own descriptor.
    plan = plan_purge(
        object_store=cache.objects,
        references=cache.index(),
        digest=digest,
        include_quarantined=True,
    )
    assert plan.identity == identity
    assert plan.key is not None

    real_lock = cache.pins.identity_lock
    taken: list[str] = []

    @contextmanager
    def racing_lock(qualified_identity: str) -> Iterator[None]:
        with real_lock(qualified_identity):
            taken.append(qualified_identity)
            if len(taken) == 1:
                cache.global_.put(outcome.receipt)
            yield

    cache.pins.identity_lock = racing_lock  # type: ignore[method-assign]
    with pytest.raises(PurgeRefused) as refused:
        purge_object(
            object_store=cache.objects,
            references=cache.index(),
            pin_store=cache.pins,
            ledger=cache.ledger,
            acknowledgement=_acknowledgement(digest),
            include_quarantined=True,
        )
    assert refused.value.reason == "referenced-by-active-receipt"
    assert taken == [identity]
    assert quarantine.is_dir()


def test_purge_refuses_a_quarantine_it_cannot_identify(tmp_path: Path) -> None:
    """Bytes that cannot be serialized against an install are retained."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    digest = outcome.cache_object.key.digest()
    quarantine = outcome.cache_object.path.with_name(
        f"{outcome.cache_object.path.name}{QUARANTINE_SUFFIX}deadbeef"
    )
    shutil.copytree(outcome.cache_object.path, quarantine)
    (quarantine / "object.json").unlink()

    purge_object(
        object_store=cache.objects,
        references=cache.index(),
        pin_store=cache.pins,
        ledger=cache.ledger,
        acknowledgement=_acknowledgement(digest),
    )
    with pytest.raises(PurgeRefused) as refused:
        purge_object(
            object_store=cache.objects,
            references=cache.index(),
            pin_store=cache.pins,
            ledger=cache.ledger,
            acknowledgement=_acknowledgement(digest),
            include_quarantined=True,
        )
    assert refused.value.reason == "unidentifiable-subject"
    assert refused.value.reason in PURGE_REFUSALS
    assert quarantine.is_dir()


@pytest.mark.parametrize("mode", ["raises", "silently-ineffective"])
def test_a_failed_purge_removal_never_records_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Wave-1 F5: the ledger recorded `purged` while every byte was still there."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    digest = outcome.cache_object.key.digest()

    def _refuse(*args: object, **kwargs: object) -> None:
        if mode == "raises":
            raise OSError("the filesystem refused to remove the staged tree")

    monkeypatch.setattr(retention.shutil, "rmtree", _refuse)
    with pytest.raises(RetentionError):
        purge_object(
            object_store=cache.objects,
            references=cache.index(),
            pin_store=cache.pins,
            ledger=cache.ledger,
            acknowledgement=_acknowledgement(digest),
        )
    monkeypatch.undo()

    entries = PurgeLedger(cache.ledger.path).entries()
    assert [entry["status"] for entry in entries] == ["planned"]
    assert entries[0]["completed_at"] is None
    assert entries[0]["deleted_paths"] == []
    # The bytes survived as a reclaimable staging entry rather than vanishing.
    assert cache.objects.temporary_entries() != ()


def test_a_quarantine_only_plan_reports_the_members_it_would_delete(
    tmp_path: Path,
) -> None:
    """Wave-1 A1: the dry run announced zero members while deleting a full tree."""
    cache = _Cache(tmp_path)
    outcome = cache.install()
    cache.unreference(outcome)
    digest = outcome.cache_object.key.digest()
    quarantine = outcome.cache_object.path.with_name(
        f"{outcome.cache_object.path.name}{QUARANTINE_SUFFIX}deadbeef"
    )
    shutil.copytree(outcome.cache_object.path, quarantine)

    plan = plan_purge(
        object_store=cache.objects,
        references=cache.index(),
        digest=digest,
        include_quarantined=True,
    )
    quarantine_files = sorted(
        f"{quarantine.name}/{path.relative_to(quarantine)}"
        for path in quarantine.rglob("*")
        if path.is_file()
    )
    assert sorted(plan.quarantine_member_paths) == quarantine_files
    assert plan.quarantine_byte_count == sum(
        path.stat().st_size for path in quarantine.rglob("*") if path.is_file()
    )
    assert plan.total_byte_count == plan.byte_count + plan.quarantine_byte_count

    # Without the operator naming them, the quarantined bytes are not counted as
    # something this purge would delete.
    unnamed = plan_purge(
        object_store=cache.objects, references=cache.index(), digest=digest
    )
    assert unnamed.quarantine_member_paths == plan.quarantine_member_paths
    assert unnamed.total_byte_count == unnamed.byte_count


def test_a_malformed_purge_ledger_is_never_read_as_an_empty_one(tmp_path: Path) -> None:
    """Wave-1 A2: `entries or []` turned a damaged record of destroyed bytes into none."""
    ledger = PurgeLedger(tmp_path / "purge-ledger.json")
    for broken in ("null", "false", '""', '"[]"', "{}"):
        ledger.path.write_text(
            '{"schema": "cognovis.cache-purge-ledger.v1", "entries": ' + broken + "}",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="never read as an empty one"):
            ledger.entries()

    ledger.path.write_text(
        '{"schema": "cognovis.cache-purge-ledger.v1", "entries": ["not-a-record"]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        ledger.entries()

    ledger.path.write_text(
        '{"schema": "cognovis.cache-purge-ledger.v1", "entries": []}', encoding="utf-8"
    )
    assert ledger.entries() == ()
