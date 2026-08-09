"""Additive foreign-field migration of existing lock receipts (CL-m6cc, AC1 and AC3).

ADR-0011 `Migration` makes the receipt migration **additive**: a receipt that
predates the foreign fields stays valid and reads as `unknown` rather than
failing. That is not politeness towards old data. A migration that refused old
receipts would push an operator towards deleting them, and the receipt is the
only record that says what a materialized projection is -- so the failure mode
of a strict migration is exactly the unattributable projection this ADR exists
to end.

The second rule is the mirror image: a receipt whose source, digest, or catalog
identity cannot be reconstructed is marked `unresolvable`, **retained**, and
prune-blocked. Unknown state is never converted into deletion authority.

Covers AC1 and AC3.
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers import migration  # noqa: E402
from lib.providers.inventory import Rights  # noqa: E402
from lib.providers.migration import (  # noqa: E402
    FOREIGN_RECEIPT_FIELDS,
    MIGRATED_UPSTREAM_STATE,
    RECONSTRUCTION_FACTS,
    UNKNOWN,
    LegacyResolution,
    LockMigrationOutcome,
    MigrationRefused,
    legacy_receipt_resolution,
    migrate_foreign_receipt_fields,
    migrate_lock_receipts,
    read_foreign_fields,
)
from lib.providers.receipts import ForeignReceipt  # noqa: E402


def _legacy_entry(**overrides: object) -> dict:
    """One pre-ADR-0011 v2 receipt: complete for its own schema, and no more."""
    entry = {
        "id": "skill:anchor:global",
        "type": "skill",
        "name": "anchor",
        "scope": "global",
        "catalog_identity": "cognovis-core",
        "source": "https://example.invalid/catalog",
        "source_commit": "0123456789abcdef0123456789abcdef01234567",
        "resolved_version": "2026.7.1",
        "cache_path": "/cache/skills/cognovis-core/anchor@0123456789abcd",
        "install_timestamp": "2026-07-16T05:35:00Z",
        "verified": True,
        "adopted": False,
        "prune_blocked_reason": None,
        "targets": [
            {
                "path": "/home/operator/.claude/skills/anchor/SKILL.md",
                "kind": "file",
                "content_sha256": "a" * 64,
            }
        ],
    }
    entry.update(overrides)
    return entry


# -- AC1: additive fields, absent reads as unknown ----------------------------


def test_additive_fields_default_unknown() -> None:
    """AC1. Migration adds the foreign fields without changing anything else.

    Three properties, and the third is the one that matters: an unmigrated
    receipt must be *readable* as unknown, not merely migratable. A caller that
    has to migrate before it can read has a migration on the read path, and a
    read path that mutates is a read path that fails during an outage.
    """
    legacy = _legacy_entry()
    original = copy.deepcopy(legacy)

    # Readable before migration: every foreign field answers `unknown`, and
    # nothing raises.
    view = read_foreign_fields(legacy)
    for field in FOREIGN_RECEIPT_FIELDS:
        assert view.is_unknown(field), f"{field} should read as unknown before migration"
    assert view.rights() == Rights(
        fetch_authorization=UNKNOWN,
        install_rights=UNKNOWN,
        redistribution_rights=UNKNOWN,
        derivative_rights=UNKNOWN,
    )
    # Reading did not mutate the entry.
    assert legacy == original

    migrated = migrate_foreign_receipt_fields(legacy)

    # Additive: every pre-existing key keeps its exact value.
    for key, value in original.items():
        assert migrated[key] == value, f"migration changed the pre-existing field {key!r}"
    # And the source entry itself was not mutated in place.
    assert legacy == original

    # Every foreign field is now explicitly present.
    for field in FOREIGN_RECEIPT_FIELDS:
        assert field in migrated, f"{field} was not added"

    assert migrated["rights"] == Rights(
        fetch_authorization=UNKNOWN,
        install_rights=UNKNOWN,
        redistribution_rights=UNKNOWN,
        derivative_rights=UNKNOWN,
    ).to_dict()
    assert migrated["upstream_state"] == MIGRATED_UPSTREAM_STATE == UNKNOWN
    assert migrated["executable_admission"] == "pending"
    assert migrated["normalized_content_digest"] == UNKNOWN
    assert migrated["transformation_version"] == UNKNOWN

    # `unknown` is not a permissive middle state. Invariant 13 binds it to a
    # blocked committed projection, so a migrated receipt may not read as
    # installable into a committed tree.
    assert migrated["projection_eligibility"]["project_committed"] == "blocked"
    assert migrated["projection_eligibility"]["machine_local"] != "allowed"


def test_migration_never_overwrites_a_recorded_foreign_value() -> None:
    """A receipt that already carries a foreign field keeps it, exactly.

    Migration that overwrote a recorded value would replace evidence with
    `unknown` -- an honest-looking downgrade that erases the only proof an
    install ever had.
    """
    granted = Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="granted",
        derivative_rights="granted",
        evidence_source="upstream LICENSE (MIT) read on 2026-08-09",
    )
    entry = _legacy_entry(
        provider_identity="provider-under-test",
        normalized_content_digest="b" * 64,
        rights=granted.to_dict(),
    )
    migrated = migrate_foreign_receipt_fields(entry)
    assert migrated["provider_identity"] == "provider-under-test"
    assert migrated["normalized_content_digest"] == "b" * 64
    assert migrated["rights"] == granted.to_dict()

    # Idempotent: migrating twice is the same document.
    assert migrate_foreign_receipt_fields(migrated) == migrated


def test_a_migrated_entry_is_not_yet_a_live_receipt() -> None:
    """A migrated entry cannot masquerade as a verified foreign receipt.

    `unknown` is honest precisely because it is not a value the live receipt
    vocabulary accepts. If a migrated entry could be loaded as a `ForeignReceipt`
    it would inherit every guarantee the receipt store makes about receipts it
    actually wrote, and it has earned none of them.
    """
    migrated = migrate_foreign_receipt_fields(_legacy_entry())
    with pytest.raises(ValueError):
        ForeignReceipt.from_dict(migrated)


def test_grants_cannot_be_resolved_by_migration() -> None:
    """Migration never invents a rights grant.

    `granted` and `denied` require a named evidence source (`CL-n7ex`), and a
    migration has looked at nothing. `unknown` is the only state it may reach,
    and the module must not offer a shortcut past that.
    """
    migrated = migrate_foreign_receipt_fields(_legacy_entry())
    rights = Rights.from_dict(migrated["rights"])
    for grant in rights.grants():
        assert grant.state == UNKNOWN
        assert grant.evidence_source is None


# -- AC3: unresolvable receipts are retained and prune-blocked ----------------


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"source": ""}, "source"),
        ({"catalog_identity": ""}, "catalog-identity"),
        ({"targets": [{"path": "/x", "kind": "directory"}]}, "content-digest"),
    ],
)
def test_unresolvable_receipt_retained_and_blocked(
    overrides: dict, missing: str
) -> None:
    """AC3. A receipt that cannot be reconstructed is marked, kept, and blocked.

    Each parameter removes exactly one of the three reconstruction facts. All
    three must produce the same disposition, because the point is not which
    fact is missing -- it is that a receipt nobody can reproduce is retained
    rather than tidied away.
    """
    entry = _legacy_entry(**overrides)
    resolution = legacy_receipt_resolution(entry)

    assert isinstance(resolution, LegacyResolution)
    assert resolution.state == "unresolvable"
    assert missing in resolution.missing
    assert resolution.retained is True
    assert resolution.prune_blocked_reason
    assert "unresolvable" in resolution.prune_blocked_reason

    outcome = migrate_lock_receipts([entry])
    assert isinstance(outcome, LockMigrationOutcome)
    # Retained: the entry is still there, under its own id.
    assert [item["id"] for item in outcome.entries] == [entry["id"]]
    assert outcome.unresolvable == (entry["id"],)
    # Prune-blocked: the reason is written onto the retained entry, so a later
    # prune reads it without re-deriving this analysis.
    migrated = outcome.entries[0]
    assert migrated["prune_blocked_reason"] == resolution.prune_blocked_reason
    assert migration.prune_blocked(migrated) is True
    # And nothing was deleted.
    assert outcome.deleted == ()


def test_resolvable_receipt_is_not_prune_blocked_by_migration() -> None:
    """A reconstructible receipt keeps whatever prune state it already had.

    Blocking everything would make the block meaningless, and would also be a
    silent policy change applied by a migration.
    """
    entry = _legacy_entry()
    resolution = legacy_receipt_resolution(entry)
    assert resolution.state == "resolvable"
    assert resolution.missing == ()
    assert resolution.prune_blocked_reason is None

    outcome = migrate_lock_receipts([entry])
    assert outcome.unresolvable == ()
    assert outcome.entries[0]["prune_blocked_reason"] is None


def test_an_existing_prune_block_survives_migration() -> None:
    """A pre-existing block is never cleared, even for a resolvable receipt."""
    entry = _legacy_entry(prune_blocked_reason="drift detected 2026-07-20")
    outcome = migrate_lock_receipts([entry])
    assert outcome.entries[0]["prune_blocked_reason"] == "drift detected 2026-07-20"


def test_every_reconstruction_fact_is_named() -> None:
    """The three facts are a closed, named set, not an implicit conjunction."""
    assert RECONSTRUCTION_FACTS == ("source", "content-digest", "catalog-identity")


def test_migration_preserves_the_receipt_population_exactly() -> None:
    """Every id in is an id out. A migration that loses one has deleted it."""
    entries = [
        _legacy_entry(id="skill:anchor:global"),
        _legacy_entry(id="skill:beacon:global", source=""),
        _legacy_entry(id="agent:carrier:project", catalog_identity=""),
    ]
    outcome = migrate_lock_receipts(entries)
    assert [item["id"] for item in outcome.entries] == [item["id"] for item in entries]
    assert outcome.deleted == ()
    assert sorted(outcome.unresolvable) == ["agent:carrier:project", "skill:beacon:global"]


def test_a_duplicate_id_is_refused_rather_than_collapsed() -> None:
    """Two receipts sharing an id must not silently become one.

    Collapsing them is a deletion wearing a dictionary's clothes.
    """
    entries = [_legacy_entry(), _legacy_entry()]
    with pytest.raises(MigrationRefused):
        migrate_lock_receipts(entries)


def test_read_foreign_fields_refuses_a_malformed_entry() -> None:
    """A damaged receipt is never read as an empty one.

    `payload.get(field) or {}` is how a corrupt record becomes "no rights
    recorded", and "no rights recorded" is the state that authorizes the least
    careful behavior downstream.
    """
    with pytest.raises(ValueError):
        read_foreign_fields({"id": "x", "rights": "not-a-mapping"})
    with pytest.raises(ValueError):
        read_foreign_fields([])


def test_migration_module_references_no_deletion_primitive() -> None:
    """AC4, structurally. The migration module cannot delete: it has no verb.

    An assertion about behavior can be satisfied by a code path nobody took in
    the test. This one is about the module's vocabulary, so acquiring deletion
    authority means importing a name this test names.
    """
    source = (REPO_ROOT / "scripts" / "lib" / "providers" / "migration.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    forbidden = {
        "rmtree",
        "unlink",
        "remove",
        "rmdir",
        "removedirs",
        "replace",
        "rename",
        "move",
    }
    found = sorted(
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden
    ) + sorted(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in forbidden
    )
    assert found == [], f"migration.py reaches a deletion or rename primitive: {found}"
