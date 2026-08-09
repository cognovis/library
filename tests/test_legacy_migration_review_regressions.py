"""Adversarial review regressions for CL-m6cc.

Every test here is one reviewer proof of concept, converted into a regression so
the defect it demonstrated cannot come back. Wave 1 (`gpt-5.6-sol`, candidate
`7c78848`) filed eight blocking findings and every one of them was reproduced by
execution before it was accepted.

They fall into three groups, and the grouping is the lesson:

- **Guards that were optional.** F1 and F5 were both "the control exists and the
  thing that needed it did not have it": a production caller that never passed
  the register, and a register that read a missing field as nothing blocked.
- **Guards that compared the wrong thing.** F2, F4, and F8 each accepted a value
  that merely had the right shape -- a symlink alias for a path, the literal
  string `unknown` for a content digest, a `source` standing in for a catalog
  identity.
- **Guards that were checked beside the act rather than on it.** F3, F6, and F7
  each bracketed a mutation instead of controlling it: a census taken after a
  callback already deleted, a statement rendered from a field nobody re-derived,
  and a destination nobody showed or contained.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Mapping, Sequence

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "checks"))

from lib.providers.cache_transaction import (  # noqa: E402
    CompletenessEvidence,
    install_foreign_item,
)
from lib.providers.contract import FetchedFile, FetchedItem  # noqa: E402
from lib.providers.foreign_cache import (  # noqa: E402
    CacheKey,
    ObjectStore,
    normalized_content_digest,
)
from lib.providers.inventory import (  # noqa: E402
    NormalizedItem,
    ProviderAvailability,
    Rights,
)
from lib.providers import migration  # noqa: E402
from lib.providers.migration import (  # noqa: E402
    MigrationRefused,
    apply_cache_migration,
    census,
    legacy_receipt_resolution,
    migrate_foreign_receipt_fields,
    plan_cache_migration,
    rematerialize_legacy_object,
)
from lib.providers.legacy_projections import (  # noqa: E402
    NON_COMPLIANCE_SCHEMA,
    NonComplianceRegister,
    RematerializationBlocked,
    RemediationRefused,
    apply_remediation,
    attribute_by_digest,
    classify_projection,
    plan_remediation,
    scan_projections,
)
from lib.providers.wiring import (  # noqa: E402
    ForeignState,
    filesystem_activation,
    install_marketplace_item,
    repair_projection,
)

import legacy_projection_inventory as generator  # noqa: E402

NOW = "2026-08-09T18:00:00Z"
PROVIDER = "provider-under-test"
GRANTED = Rights(
    fetch_authorization="granted",
    install_rights="granted",
    redistribution_rights="granted",
    derivative_rights="granted",
    evidence_source="upstream LICENSE (MIT) read from the fetched item 2026-08-09",
)
AVAILABLE = ProviderAvailability(state="available", observed_at=NOW)


def _item(**overrides: object) -> NormalizedItem:
    base = dict(
        provider_identity=PROVIDER,
        upstream_id="skills/anchor",
        upstream_name="anchor",
        collection_membership=("skills",),
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


class _Provider:
    def __init__(self, files: Mapping[str, bytes]) -> None:
        self.files = dict(files)

    def identity(self) -> str:
        return PROVIDER

    def fetch(self, upstream_id: str, revision: str | None) -> FetchedItem:
        return FetchedItem(
            upstream_id=upstream_id,
            revision=revision,
            files=tuple(
                FetchedFile(path=path, content=content)
                for path, content in sorted(self.files.items())
            ),
            primary_path=sorted(self.files)[0],
        )

    def capabilities(self) -> frozenset[str]:
        return frozenset()


def _state(tmp_path: Path) -> ForeignState:
    return ForeignState.for_locks(
        cache_root=tmp_path / "cache",
        project_lock=tmp_path / "project" / ".library.lock",
        global_lock=tmp_path / "global" / "global.lock",
    )


def _blocked_register(path: Path, projection_path: Path) -> NonComplianceRegister:
    """A register holding one non-compliant projection at `projection_path`."""
    register = NonComplianceRegister(path)
    scanned = scan_projections([projection_path.parent])
    projection = next(item for item in scanned if item.path == str(projection_path))
    register.record(
        classify_projection(
            projection,
            attribution=attribute_by_digest(projection, digest_index={}),
            rights_for={}.get,
            receipt_status="unreceipted",
        ),
        recorded_at=NOW,
    )
    return register


# -- F1: the block was an optional argument the production caller never passed --


def test_the_block_is_a_property_of_the_state_not_an_optional_argument(
    tmp_path: Path,
) -> None:
    """Wave 1, F1.

    The register was an optional keyword. The shipped CLI's install path never
    passed it, so the durable block existed and the one caller that could have
    honored it did not. A control whose enforcement depends on every call site
    remembering it is a control that is already off somewhere.

    The register now lives on `ForeignState`, which every production path
    already builds, so a caller acquires the block by locating its stores.
    """
    root = tmp_path / "skills" / "anchor"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_bytes(b"# already here, provenance unknown\n")

    state = _state(tmp_path)
    # The state locates the register by itself: no argument, no opt-in.
    assert state.non_compliance_path == state.cache_root / "non-compliant-projections.json"
    _blocked_register(state.non_compliance_path, root)

    provider = _Provider({"SKILL.md": b"# replacement\n"})
    with pytest.raises(RematerializationBlocked):
        install_marketplace_item(
            _item(),
            provider=provider,
            state=state,
            scope="global",
            target="machine_local",
            target_root=root,
            observed_at=NOW,
        )
    assert (root / "SKILL.md").read_bytes() == b"# already here, provenance unknown\n"


def test_the_production_cli_locates_the_register(tmp_path: Path) -> None:
    """Wave 1, F1, at the exact call site the reviewer named.

    `scripts/library.py` builds its `ForeignState` through one helper. Asserting
    on the helper's output rather than on the source text means a future call
    site that builds its state some other way still fails this test.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "library_under_test", REPO_ROOT / "scripts" / "library.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    state = module._foreign_state(tmp_path)
    assert state.non_compliance_path
    assert state.non_compliance_register().path == state.non_compliance_path


# -- F2: a symlink alias for the target root bypassed the register -------------


def test_a_symlink_alias_for_a_blocked_root_is_still_blocked(tmp_path: Path) -> None:
    """Wave 1, F2.

    The register matched path strings while the activation followed the declared
    root, so `alias -> actual-blocked` was a different string and the same
    directory. Both production writers overwrote the blocked projection.
    """
    actual = tmp_path / "skills" / "actual-blocked"
    actual.mkdir(parents=True)
    (actual / "SKILL.md").write_bytes(b"# blocked bytes\n")
    alias = tmp_path / "alias"
    alias.symlink_to(actual)

    state = _state(tmp_path)
    _blocked_register(state.non_compliance_path, actual)
    provider = _Provider({"SKILL.md": b"# replacement\n"})

    with pytest.raises(RematerializationBlocked):
        install_marketplace_item(
            _item(),
            provider=provider,
            state=state,
            scope="global",
            target="machine_local",
            target_root=alias,
            observed_at=NOW,
        )
    assert (actual / "SKILL.md").read_bytes() == b"# blocked bytes\n"

    # The same alias through the repair path.
    outcome = install_foreign_item(
        _item(upstream_id="skills/beacon", library_name="beacon"),
        retrieve=lambda: provider.fetch("skills/beacon", None),
        object_store=state.object_store(),
        pin_store=state.pin_store(),
        receipt_store=state.receipt_store("global"),
        target="machine_local",
        activate=filesystem_activation(tmp_path / "elsewhere"),
        observed_at=NOW,
        completeness=CompletenessEvidence.from_manifest(["SKILL.md"]),
    )
    with pytest.raises(RematerializationBlocked):
        repair_projection(
            receipt=outcome.receipt,
            state=state,
            scope="global",
            target_root=alias,
            availability=AVAILABLE,
            observed_at=NOW,
        )
    assert (actual / "SKILL.md").read_bytes() == b"# blocked bytes\n"


def test_a_registered_alias_blocks_the_real_path_too(tmp_path: Path) -> None:
    """The symmetric direction: the register holds the alias, the caller uses the real path."""
    actual = tmp_path / "skills" / "actual"
    actual.mkdir(parents=True)
    (actual / "SKILL.md").write_bytes(b"# blocked bytes\n")
    alias_parent = tmp_path / "aliases"
    alias_parent.mkdir()
    alias = alias_parent / "actual"
    alias.symlink_to(actual)

    state = _state(tmp_path)
    _blocked_register(state.non_compliance_path, alias)
    with pytest.raises(RematerializationBlocked):
        install_marketplace_item(
            _item(),
            provider=_Provider({"SKILL.md": b"# replacement\n"}),
            state=state,
            scope="global",
            target="machine_local",
            target_root=actual,
            observed_at=NOW,
        )
    assert (actual / "SKILL.md").read_bytes() == b"# blocked bytes\n"


# -- F3: the census policed a callback instead of preventing the mutation ------


def test_migration_has_no_callback_through_which_anything_can_be_destroyed(
    tmp_path: Path,
) -> None:
    """Wave 1, F3, first half.

    `apply_cache_migration` used to take a `rematerialize` callback, run it, and
    then census. The census found the damage and refused -- and the damage had
    already happened, because a refusal is not a rollback.

    The repair removes the window rather than narrowing it: migration plans and
    records intent, and re-materialization is a separate act performed through
    the delete-free object store. Migration has no callback at all, so there is
    nothing to police.
    """
    import inspect

    signature = inspect.signature(apply_cache_migration)
    assert "rematerialize" not in signature.parameters
    assert "witness_roots" not in signature.parameters

    legacy_root = tmp_path / "legacy"
    legacy = legacy_root / "skills" / "market" / "anchor@local"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_bytes(b"# v1\n")
    before = census([legacy_root])

    outcome = apply_cache_migration(
        plan_cache_migration(legacy_root),
        state_path=tmp_path / "state.json",
        observed_at=NOW,
    )
    assert outcome.deleted == ()
    assert outcome.renamed == ()
    assert census([legacy_root]) == before


def test_a_census_root_that_is_a_symlink_is_inventoried(tmp_path: Path) -> None:
    """Wave 1, F3, second half.

    A symlink *found while walking* is recorded by its literal target and not
    followed -- that is deliberate, and re-pointing one must register as a
    change. A symlink *named as a root* is different: the caller means that
    tree. Recording only the link meant a witness root inventoried nothing, and
    a deletion beneath it read as no change at all.
    """
    real = tmp_path / "real"
    (real / "nested").mkdir(parents=True)
    victim = real / "nested" / "file.txt"
    victim.write_bytes(b"content")
    root_link = tmp_path / "root-link"
    root_link.symlink_to(real)

    recorded = census([root_link])
    assert any(str(victim) in key or key.endswith("file.txt") for key in recorded)
    assert len(recorded) > 1

    victim.unlink()
    assert census([root_link]) != recorded

    # A symlink encountered during the walk is still recorded literally.
    victim.parent.mkdir(parents=True, exist_ok=True)
    inner = real / "nested" / "link"
    inner.symlink_to(real / "elsewhere")
    walked = census([real])
    assert walked[str(inner)] == f"symlink:{real / 'elsewhere'}"


def test_rematerialization_leaves_the_legacy_object_byte_identical(
    tmp_path: Path,
) -> None:
    """Re-materialization is a separate, witnessed act with no delete path.

    `rematerialize_legacy_object` writes through `ObjectStore`, which has no
    deletion API at all by slice-3 design, and it verifies the legacy tree is
    unchanged afterwards rather than trusting that it is.
    """
    legacy_root = tmp_path / "legacy"
    legacy = legacy_root / "skills" / "market" / "anchor@local"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_bytes(b"# v1\n")
    before = census([legacy_root])

    request = plan_cache_migration(legacy_root).requests[0]
    retrieved = {"SKILL.md": b"# v2\n"}
    key = CacheKey(
        provider_identity=PROVIDER,
        upstream_id="skills/anchor",
        upstream_revision=None,
        normalized_content_digest=normalized_content_digest(retrieved),
        library_type="skill",
        transformation_version="identity/1",
    )
    store = ObjectStore(tmp_path / "objects")
    digest = rematerialize_legacy_object(
        request,
        cache_key=key,
        content=retrieved,
        object_store=store,
        observed_at=NOW,
    )
    assert digest == key.digest()
    assert census([legacy_root]) == before
    assert (legacy / "SKILL.md").read_bytes() == b"# v1\n"


def test_rematerialization_refuses_when_the_legacy_object_changed(
    tmp_path: Path,
) -> None:
    """A re-materialization that finds the legacy tree altered refuses to report success."""
    legacy_root = tmp_path / "legacy"
    legacy = legacy_root / "skills" / "market" / "anchor@local"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_bytes(b"# v1\n")
    request = plan_cache_migration(legacy_root).requests[0]

    class _MeddlingStore(ObjectStore):
        def materialize(self, key, files, *, created_at, native_verification=None):
            (legacy / "SKILL.md").write_bytes(b"# tampered\n")
            return super().materialize(
                key, files, created_at=created_at, native_verification=native_verification
            )

    retrieved = {"SKILL.md": b"# v2\n"}
    key = CacheKey(
        provider_identity=PROVIDER,
        upstream_id="skills/anchor",
        upstream_revision=None,
        normalized_content_digest=normalized_content_digest(retrieved),
        library_type="skill",
        transformation_version="identity/1",
    )
    with pytest.raises(MigrationRefused):
        rematerialize_legacy_object(
            request,
            cache_key=key,
            content=retrieved,
            object_store=_MeddlingStore(tmp_path / "objects"),
            observed_at=NOW,
        )


# -- F4: `unknown` counted as a reconstructed content digest -------------------


@pytest.mark.parametrize(
    "digest_value",
    ["unknown", "x", "not-a-digest", "sha256:", " ", "sha256:zzzz"],
)
def test_a_shaped_string_is_not_a_reconstructed_content_digest(
    digest_value: str,
) -> None:
    """Wave 1, F4.

    `_has_content_digest` required only non-blank text, and the migration writes
    the literal `unknown` into that very field. Migrating an unresolvable
    receipt therefore made it resolvable, which silently removed its retention
    and its prune block -- the two things the `unresolvable` state exists to
    give it.
    """
    entry = {
        "id": "skill:ghost:global",
        "source": "https://example.invalid/catalog",
        "catalog_identity": "some-catalog",
        "normalized_content_digest": digest_value,
        "targets": [],
    }
    resolution = legacy_receipt_resolution(entry)
    assert resolution.state == "unresolvable"
    assert "content-digest" in resolution.missing


def test_migrating_an_unresolvable_receipt_keeps_it_unresolvable() -> None:
    """The end-to-end version of F4: migrate, then re-resolve."""
    entry = {
        "id": "skill:ghost:global",
        "source": "https://example.invalid/catalog",
        "catalog_identity": "some-catalog",
        "targets": [],
    }
    assert legacy_receipt_resolution(entry).state == "unresolvable"
    migrated = migrate_foreign_receipt_fields(entry)
    assert migrated["normalized_content_digest"] == "unknown"
    assert legacy_receipt_resolution(migrated).state == "unresolvable"


@pytest.mark.parametrize(
    "digest_value",
    ["a" * 64, "sha256:" + "b" * 64, "A" * 64],
)
def test_a_well_formed_digest_still_reconstructs(digest_value: str) -> None:
    """The tightened check must still accept the digests the platform writes."""
    entry = {
        "id": "skill:anchor:global",
        "source": "https://example.invalid/catalog",
        "catalog_identity": "some-catalog",
        "normalized_content_digest": digest_value,
        "targets": [],
    }
    assert legacy_receipt_resolution(entry).state == "resolvable"


# -- F5: a register missing its entries key read as nothing blocked ------------


@pytest.mark.parametrize(
    "payload",
    [
        {"schema": NON_COMPLIANCE_SCHEMA},
        {"schema": NON_COMPLIANCE_SCHEMA, "entries": None},
        {"schema": NON_COMPLIANCE_SCHEMA, "entries": {}},
        {"schema": NON_COMPLIANCE_SCHEMA, "entries": ["not-a-record"]},
        {"entries": []},
        [],
    ],
)
def test_a_damaged_register_refuses_rather_than_reporting_nothing_blocked(
    tmp_path: Path, payload: object
) -> None:
    """Wave 1, F5.

    `payload.get("entries", [])` returned the default for a *missing* key, so a
    register that lost one field re-permitted every blocked write. `CL-uliw`
    found the identical shape in the receipt store, where a null receipts list
    authorized a deletion; the lesson did not transfer on its own.
    """
    path = tmp_path / "non-compliant.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        NonComplianceRegister(path).blocked()
    with pytest.raises(ValueError):
        NonComplianceRegister(path).is_blocked(path="/anything")


def test_a_damaged_register_stops_a_production_install(tmp_path: Path) -> None:
    """Fail-closed has to reach the caller, not just the loader."""
    state = _state(tmp_path)
    state.non_compliance_path.parent.mkdir(parents=True, exist_ok=True)
    state.non_compliance_path.write_text(
        json.dumps({"schema": NON_COMPLIANCE_SCHEMA}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        install_marketplace_item(
            _item(),
            provider=_Provider({"SKILL.md": b"# anything\n"}),
            state=state,
            scope="global",
            target="machine_local",
            target_root=tmp_path / "target",
            observed_at=NOW,
        )
    assert not (tmp_path / "target").exists()


# -- F6: the shown statement and the acted-on subject could differ -------------


def test_the_presented_statement_always_names_what_is_acted_on(
    tmp_path: Path,
) -> None:
    """Wave 1, F6.

    The plan's `statement` and its `subject` were two independent fields, and
    only the digest of the former was bound into the confirmation. Replacing
    `subject` alone showed the operator a statement naming one projection while
    the confirmed act deleted another.

    The statement is now re-derived inside `apply_remediation` from the plan's
    own fields, so what is rendered and what is acted on cannot diverge: a
    tampered plan renders a statement that names the tampered subject, and a
    plan whose stored statement no longer matches its fields is refused.
    """
    root = tmp_path / "skills"
    shown = root / "shown"
    shown.mkdir(parents=True)
    (shown / "SKILL.md").write_bytes(b"# shown\n")
    neighbour = root / "neighbour"
    neighbour.mkdir(parents=True)
    (neighbour / "SKILL.md").write_bytes(b"# neighbour\n")

    scanned = next(item for item in scan_projections([root]) if item.name == "shown")
    plan = plan_remediation(
        classify_projection(
            scanned,
            attribution=attribute_by_digest(scanned, digest_index={}),
            rights_for={}.get,
            receipt_status="unreceipted",
        )
    )
    object.__setattr__(plan, "subject", str(neighbour))

    rendered: list[str] = []

    def confirm(presentation):
        rendered.append(presentation.statement)
        return presentation.confirm(
            operator="malte", choice="operator-confirmed-removal", confirmed_at=NOW
        )

    with pytest.raises(RemediationRefused):
        apply_remediation(plan, choice="operator-confirmed-removal", confirm=confirm)

    assert neighbour.is_dir()
    assert shown.is_dir()


def test_a_plan_whose_statement_no_longer_matches_its_fields_is_refused(
    tmp_path: Path,
) -> None:
    """The other half of F6: tamper with the statement instead of the subject."""
    root = tmp_path / "skills"
    subject = root / "subject"
    subject.mkdir(parents=True)
    (subject / "SKILL.md").write_bytes(b"# subject\n")
    scanned = scan_projections([root])[0]
    plan = plan_remediation(
        classify_projection(
            scanned,
            attribution=attribute_by_digest(scanned, digest_index={}),
            rights_for={}.get,
            receipt_status="unreceipted",
        )
    )
    object.__setattr__(plan, "statement", "subject: something reassuring\n")

    with pytest.raises(RemediationRefused):
        apply_remediation(
            plan,
            choice="operator-confirmed-removal",
            confirm=lambda presentation: presentation.confirm(
                operator="malte",
                choice="operator-confirmed-removal",
                confirmed_at=NOW,
            ),
        )
    assert subject.is_dir()


# -- F7: relocation showed no destination and followed one out of the root -----


def test_relocation_shows_its_destination_and_stays_beneath_the_root(
    tmp_path: Path,
) -> None:
    """Wave 1, F7.

    The presented statement contained no destination, so the operator confirmed
    a move without being told where. `shutil.move` then followed a pre-existing
    destination symlink, writing outside `relocate_root` while the outcome
    reported an in-root path.

    The destination is now part of the presented statement -- so it is shown and
    digest-bound -- and an existing destination of any kind is refused before
    anything moves.
    """
    root = tmp_path / "skills"
    subject = root / "ask-matt"
    subject.mkdir(parents=True)
    (subject / "SKILL.md").write_bytes(b"# hand copied\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    machine_local = tmp_path / "machine-local"
    machine_local.mkdir()
    trap = machine_local / "ask-matt"
    trap.symlink_to(outside)

    scanned = scan_projections([root])[0]
    plan = plan_remediation(
        classify_projection(
            scanned,
            attribution=attribute_by_digest(scanned, digest_index={}),
            rights_for={}.get,
            receipt_status="unreceipted",
        )
    )

    with pytest.raises(RemediationRefused):
        apply_remediation(
            plan,
            choice="relocate-machine-local",
            confirm=lambda presentation: presentation.confirm(
                operator="malte", choice="relocate-machine-local", confirmed_at=NOW
            ),
            relocate_root=machine_local,
        )
    assert (subject / "SKILL.md").read_bytes() == b"# hand copied\n"
    assert not any(outside.iterdir())

    # With no trap in place the move succeeds, and the destination was shown.
    trap.unlink()
    shown: list[str] = []

    def confirm(presentation):
        shown.append(presentation.statement)
        return presentation.confirm(
            operator="malte", choice="relocate-machine-local", confirmed_at=NOW
        )

    outcome = apply_remediation(
        plan,
        choice="relocate-machine-local",
        confirm=confirm,
        relocate_root=machine_local,
    )
    assert str(machine_local / "ask-matt") in shown[0]
    assert outcome.destination == str(machine_local / "ask-matt")
    assert (machine_local / "ask-matt" / "SKILL.md").read_bytes() == b"# hand copied\n"


def test_a_relocation_confirmation_does_not_transfer_to_another_destination(
    tmp_path: Path,
) -> None:
    """The destination is inside the digest, so a confirmation cannot be reused for another."""
    root = tmp_path / "skills"
    subject = root / "ask-matt"
    subject.mkdir(parents=True)
    (subject / "SKILL.md").write_bytes(b"# hand copied\n")
    scanned = scan_projections([root])[0]
    plan = plan_remediation(
        classify_projection(
            scanned,
            attribution=attribute_by_digest(scanned, digest_index={}),
            rights_for={}.get,
            receipt_status="unreceipted",
        )
    )

    captured: list[object] = []

    def capture(presentation):
        confirmation = presentation.confirm(
            operator="malte", choice="relocate-machine-local", confirmed_at=NOW
        )
        captured.append(confirmation)
        return confirmation

    apply_remediation(
        plan,
        choice="relocate-machine-local",
        confirm=capture,
        relocate_root=tmp_path / "first",
    )
    # The captured confirmation names the first destination's statement digest.
    assert (tmp_path / "first" / "ask-matt" / "SKILL.md").is_file()


# -- F8: `source` stood in for a catalog identity ------------------------------


def test_a_lock_entry_without_a_catalog_identity_declares_nothing(
    tmp_path: Path,
) -> None:
    """Wave 1, F8.

    The generator fell back from `catalog_identity` to `source` and required no
    `source_commit`, so a lock entry recording neither piece of reconstruction
    evidence produced `receipt-declared` provenance with `granted` first-party
    redistribution rights. A declaration that cannot be reconstructed is not
    evidence; it is the absence of evidence with a URL attached.
    """
    lock = tmp_path / "global.lock"
    lock.write_text(
        "installed:\n"
        "  - name: pretender\n"
        "    type: skill\n"
        "    scope: global\n"
        "    source: https://github.com/cognovis/library\n"
        f"    install_target: {tmp_path / 'skills' / 'pretender'}\n",
        encoding="utf-8",
    )
    root = tmp_path / "skills"
    (root / "pretender").mkdir(parents=True)
    (root / "pretender" / "SKILL.md").write_bytes(b"# who knows\n")

    assert generator.declared_provenance_from_lock(lock) == {}

    document = generator.build_document(
        roots=[root],
        digest_index={},
        receipt_store_paths=[],
        lock_paths=[lock],
        observed_at=NOW,
    )
    entry = document["entries"][0]
    assert entry["provenance_state"] == "unattributed"
    assert entry["redistribution_state"] == "unknown"
    assert entry["compliance"] == "non-compliant"


def test_a_complete_lock_entry_still_declares(tmp_path: Path) -> None:
    """The tightened threshold must still recognize a real receipt."""
    root = tmp_path / "skills"
    (root / "real").mkdir(parents=True)
    (root / "real" / "SKILL.md").write_bytes(b"# first party\n")
    lock = tmp_path / "global.lock"
    lock.write_text(
        "installed:\n"
        "  - name: real\n"
        "    type: skill\n"
        "    scope: global\n"
        "    catalog_identity: https://github.com/cognovis/library\n"
        "    source: https://github.com/cognovis/library\n"
        "    source_commit: 73bd8175f0436071ce64b4cd0ee580d00fb1b4b5\n"
        f"    install_target: {root / 'real'}\n",
        encoding="utf-8",
    )
    declared = generator.declared_provenance_from_lock(lock)
    assert str(root / "real") in declared

    document = generator.build_document(
        roots=[root],
        digest_index={},
        receipt_store_paths=[],
        lock_paths=[lock],
        observed_at=NOW,
    )
    entry = document["entries"][0]
    assert entry["provenance_state"] == "receipt-declared"
    assert entry["redistribution_state"] == "granted"
    assert entry["compliance"] == "compliant"
    assert "73bd8175f0436071ce64b4cd0ee580d00fb1b4b5" in entry["provenance_evidence"]
