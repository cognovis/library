"""Legacy cache objects are re-materialized, never renamed (CL-m6cc, AC2 and AC4).

ADR-0011 `Re-key versus re-materialization` refuses the obvious migration. A
legacy object is keyed `<type>/<marketplace>/<name>@<commit14>` and carries no
recorded normalized digest and no transformation identity. Moving that directory
into the tuple key space would mint a digest identity it never had, and every
later integrity check would then confirm a fabrication. So the legacy object
stays exactly where it is, stays usable, and the honest identity is recomputed
by re-materializing from the provider on the next install or repair.

The second rule is the one a cleanup step erodes first: **migration grants no
deletion authority**. Not for a cache object, not for a receipt, not for a
projected file. The tests below take a full census of every byte before and
after a complete migration run and require the census to be a superset.

Covers AC2 and AC4.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.foreign_cache import (  # noqa: E402
    CacheKey,
    ObjectStore,
    normalized_content_digest,
)
from lib.providers.migration import (  # noqa: E402
    CacheMigrationOutcome,
    CacheMigrationPlan,
    LegacyCacheObject,
    MigrationRefused,
    RematerializationRequest,
    apply_cache_migration,
    census,
    migrate_lock_receipts,
    plan_cache_migration,
    scan_legacy_cache,
)

NOW = "2026-08-09T14:00:00Z"

#: The transformation identity a re-materialized object records. A legacy object
#: has none at all, which is half of why its key cannot be computed from its path.
TRANSFORMATION = "identity/1"


def _legacy_object(root: Path, marketplace: str, name: str, tag: str, body: bytes) -> Path:
    """One directory in the pre-ADR-0011 Layer-B layout."""
    path = root / "skills" / marketplace / f"{name}@{tag}"
    path.mkdir(parents=True)
    (path / "SKILL.md").write_bytes(body)
    (path / "reference.md").write_bytes(b"# reference\n")
    return path


# -- AC2: re-key is re-materialization ----------------------------------------


def test_rematerialize_not_rename(tmp_path: Path) -> None:
    """AC2. The legacy directory stays put; the new object is recomputed.

    Four things are checked, and the fourth is the one a rename would pass:
    the new object's digest must be derived from the bytes that were retrieved,
    not from anything readable off the legacy path. The test proves it by
    re-materializing content that differs from the legacy directory's content
    and requiring the new digest to describe the retrieved bytes.
    """
    legacy_root = tmp_path / "legacy"
    legacy = _legacy_object(legacy_root, "cognovis-core", "anchor", "local", b"# v1\n")
    legacy_inode = legacy.stat().st_ino
    legacy_census = census([legacy_root])

    plan = plan_cache_migration(legacy_root)
    assert isinstance(plan, CacheMigrationPlan)
    assert plan.renames == ()
    assert plan.deletions == ()
    assert len(plan.requests) == 1

    request = plan.requests[0]
    assert isinstance(request, RematerializationRequest)
    assert request.legacy_path == str(legacy)
    # A legacy object cannot state its own tuple key: it has neither a recorded
    # normalized digest nor a transformation identity.
    assert request.new_cache_key is None
    assert request.requires_provider is True
    assert request.usable_meanwhile is True

    # The provider now serves different bytes than the legacy directory holds --
    # which is precisely the situation a revisionless `@local` tag hides.
    retrieved = {"SKILL.md": b"# v2\n", "reference.md": b"# reference\n"}
    store = ObjectStore(tmp_path / "objects")

    def rematerialize(pending: RematerializationRequest) -> str:
        key = CacheKey(
            provider_identity="provider-under-test",
            upstream_id=f"skills/{pending.name}",
            upstream_revision=None,
            normalized_content_digest=normalized_content_digest(retrieved),
            library_type=pending.library_type,
            transformation_version=TRANSFORMATION,
        )
        store.materialize(key, retrieved, created_at=NOW)
        return key.digest()

    outcome = apply_cache_migration(
        plan,
        state_path=tmp_path / "legacy-migration.json",
        witness_roots=[legacy_root],
        rematerialize=rematerialize,
        observed_at=NOW,
    )
    assert isinstance(outcome, CacheMigrationOutcome)
    assert outcome.renamed == ()
    assert outcome.deleted == ()

    # 1. The legacy directory is the same directory, in the same place.
    assert legacy.is_dir()
    assert legacy.stat().st_ino == legacy_inode
    assert (legacy / "SKILL.md").read_bytes() == b"# v1\n"
    assert census([legacy_root]) == legacy_census
    assert str(legacy) in outcome.retained_legacy_paths

    # 2. A new object exists, and it was created by materialization.
    assert len(outcome.rematerialized) == 1
    new_digest = outcome.rematerialized[0]
    objects = store.objects()
    assert len(objects) == 1

    # 3. The recomputed digest describes the retrieved bytes.
    assert objects[0].key.normalized_content_digest == normalized_content_digest(retrieved)
    assert objects[0].key.digest() == new_digest
    assert objects[0].key.transformation_version == TRANSFORMATION

    # 4. And it is not the digest of the legacy directory's content, so nothing
    #    about the new identity could have been read off the old path.
    stale = normalized_content_digest(
        {"SKILL.md": b"# v1\n", "reference.md": b"# reference\n"}
    )
    assert objects[0].key.normalized_content_digest != stale


def test_a_legacy_object_stays_usable_until_it_is_rematerialized(tmp_path: Path) -> None:
    """Without a provider, the migration records intent and changes nothing.

    ADR-0011 accepts that the first post-migration operation may be slower and
    needs provider availability. What it does not accept is an interval in which
    the legacy bytes are gone and the new ones do not exist yet.
    """
    legacy_root = tmp_path / "legacy"
    legacy = _legacy_object(legacy_root, "cognovis-core", "anchor", "local", b"# v1\n")
    before = census([legacy_root])

    outcome = apply_cache_migration(
        plan_cache_migration(legacy_root),
        state_path=tmp_path / "legacy-migration.json",
        witness_roots=[legacy_root],
        rematerialize=None,
        observed_at=NOW,
    )

    assert outcome.rematerialized == ()
    assert [item.legacy_path for item in outcome.pending] == [str(legacy)]
    assert census([legacy_root]) == before
    assert (legacy / "SKILL.md").read_bytes() == b"# v1\n"

    # The intent is durable, so a later `sync` or repair knows what is owed
    # without re-deriving it from a directory layout that will disappear.
    state = json.loads((tmp_path / "legacy-migration.json").read_text(encoding="utf-8"))
    assert state["pending"][0]["legacy_path"] == str(legacy)
    assert state["pending"][0]["requires_provider"] is True


def test_scan_reads_the_legacy_layout_without_inventing_a_revision(
    tmp_path: Path,
) -> None:
    """`@local` is a tag, not a revision. Recording it as one would be the lie."""
    legacy_root = tmp_path / "legacy"
    _legacy_object(legacy_root, "cognovis-core", "anchor", "local", b"a")
    _legacy_object(legacy_root, "third-party", "beacon", "0123456789abcd", b"b")

    found = {item.name: item for item in scan_legacy_cache(legacy_root)}
    assert sorted(found) == ["anchor", "beacon"]

    anchor = found["anchor"]
    assert isinstance(anchor, LegacyCacheObject)
    assert anchor.library_type == "skill"
    assert anchor.marketplace == "cognovis-core"
    assert anchor.revision_tag == "local"
    assert anchor.is_revisionless() is True
    assert anchor.recorded_normalized_digest is None
    assert anchor.recorded_transformation_version is None

    assert found["beacon"].revision_tag == "0123456789abcd"
    assert found["beacon"].is_revisionless() is False


# -- AC4: migration grants no deletion authority -------------------------------


def test_migration_grants_no_deletion_authority(tmp_path: Path) -> None:
    """AC4. A full migration run deletes no object, no receipt, no projected file.

    "Full" is the load-bearing word. The run below covers all three populations
    at once, including a legacy cache object nothing references, an unresolvable
    receipt, and a projected file whose receipt cannot be reconstructed -- the
    three cases a cleanup step would each argue itself into.
    """
    legacy_root = tmp_path / "legacy"
    orphan = _legacy_object(legacy_root, "abandoned", "ghost", "local", b"# nobody\n")
    live = _legacy_object(legacy_root, "cognovis-core", "anchor", "local", b"# v1\n")

    projections = tmp_path / "projections"
    (projections / "skills" / "orphaned").mkdir(parents=True)
    (projections / "skills" / "orphaned" / "SKILL.md").write_bytes(b"# unreceipted\n")

    lock_entries = [
        {
            "id": "skill:anchor:global",
            "type": "skill",
            "name": "anchor",
            "scope": "global",
            "catalog_identity": "cognovis-core",
            "source": "https://example.invalid/catalog",
            "source_commit": "0" * 40,
            "resolved_version": "2026.7.1",
            "install_timestamp": "2026-07-16T05:35:00Z",
            "verified": True,
            "adopted": False,
            "prune_blocked_reason": None,
            "targets": [
                {"path": str(live / "SKILL.md"), "kind": "file", "content_sha256": "a" * 64}
            ],
        },
        {
            # Source, digest, and catalog identity are all gone. This is the
            # receipt a tidy-up deletes.
            "id": "skill:ghost:global",
            "type": "skill",
            "name": "ghost",
            "scope": "global",
            "catalog_identity": "",
            "source": "",
            "install_timestamp": "2025-01-02T00:00:00Z",
            "verified": False,
            "adopted": False,
            "prune_blocked_reason": None,
            "targets": [],
        },
    ]

    witness = [legacy_root, projections]
    before = census(witness)

    lock_outcome = migrate_lock_receipts(lock_entries)
    cache_outcome = apply_cache_migration(
        plan_cache_migration(legacy_root),
        state_path=tmp_path / "legacy-migration.json",
        witness_roots=witness,
        rematerialize=None,
        observed_at=NOW,
    )

    after = census(witness)

    # Nothing disappeared and nothing changed. A superset would be acceptable to
    # the invariant; equality is what this run should produce, and asserting the
    # stronger fact catches an "additive" write that quietly rewrites a file.
    assert after == before

    # Every receipt survives, including the unresolvable one.
    assert [item["id"] for item in lock_outcome.entries] == [
        "skill:anchor:global",
        "skill:ghost:global",
    ]
    assert lock_outcome.unresolvable == ("skill:ghost:global",)
    assert lock_outcome.deleted == ()

    # Every cache object survives, including the one nothing references.
    assert orphan.is_dir()
    assert live.is_dir()
    assert cache_outcome.deleted == ()
    assert set(cache_outcome.retained_legacy_paths) == {str(orphan), str(live)}

    # And the unreceipted projection is untouched.
    assert (projections / "skills" / "orphaned" / "SKILL.md").read_bytes() == (
        b"# unreceipted\n"
    )


def test_a_migration_that_loses_a_byte_refuses_rather_than_reports(
    tmp_path: Path,
) -> None:
    """The no-deletion rule is self-checked, not merely documented.

    A future cleanup step inside a re-materialization hook would otherwise pass
    every test above by deleting something none of them names. The census
    witness makes the run itself fail.
    """
    legacy_root = tmp_path / "legacy"
    legacy = _legacy_object(legacy_root, "cognovis-core", "anchor", "local", b"# v1\n")

    def destructive(pending: RematerializationRequest) -> str:
        (Path(pending.legacy_path) / "reference.md").unlink()
        return "0" * 64

    with pytest.raises(MigrationRefused) as excinfo:
        apply_cache_migration(
            plan_cache_migration(legacy_root),
            state_path=tmp_path / "legacy-migration.json",
            witness_roots=[legacy_root],
            rematerialize=destructive,
            observed_at=NOW,
        )
    assert "reference.md" in str(excinfo.value)
    assert legacy.is_dir()


def test_census_records_content_not_merely_presence(tmp_path: Path) -> None:
    """A census keyed on paths alone would miss content replacement."""
    root = tmp_path / "tree"
    (root / "nested").mkdir(parents=True)
    target = root / "nested" / "file.txt"
    target.write_bytes(b"one")
    first = census([root])
    target.write_bytes(b"two")
    assert census([root]) != first
    assert first[str(target)] == hashlib.sha256(b"one").hexdigest()


def test_census_records_a_symlink_by_its_literal_target(tmp_path: Path) -> None:
    """Eleven of the legacy projections are symlinks; a census must see them.

    Following the link would census the destination twice and would report a
    replaced link as unchanged whenever both destinations happen to match.
    """
    root = tmp_path / "tree"
    root.mkdir()
    (root / "real").write_bytes(b"real")
    link = root / "link"
    link.symlink_to(root / "real")
    recorded = census([root])
    assert recorded[str(link)] == f"symlink:{root / 'real'}"

    link.unlink()
    link.symlink_to(root / "elsewhere")
    assert census([root]) != recorded
