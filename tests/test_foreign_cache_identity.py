"""Tuple cache identity, trust-on-first-use, and transformation identity (CL-y5z4).

ADR-0011 `Cache identity` replaces the `<type>/<marketplace>/<name>@<commit14>`
key with a tuple. The defect it fixes is **within one provider**, not across two
of them: `compute_cache_path` already separates marketplaces into path segments,
so a cross-provider test would pass before the fix and prove nothing. The three
real collisions, restated from the ADR's corrected table:

| Collision | Why the old key collides |
|---|---|
| Same provider, same name, different content | every revisionless version pins to the literal fallback tag and overwrites in place |
| Two different upstream ids normalizing to one Library name | the key carries the Library name, not the upstream id |
| Same content under two transformation rules | the key has no transformation dimension |

Covers AC1, AC6, AC9.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.cache import compute_cache_path  # noqa: E402
from lib.providers.foreign_cache import (  # noqa: E402
    IDENTITY_TRANSFORMATION,
    CacheKey,
    CacheObjectCorrupt,
    ObjectStore,
    TofuDrift,
    TofuPinStore,
    Transformation,
    normalized_content_digest,
)

PROVIDER = "provider-under-test"
NOW = "2026-08-09T09:00:00Z"
LATER = "2026-08-09T10:00:00Z"


def _key(**overrides: object) -> CacheKey:
    base = dict(
        provider_identity=PROVIDER,
        upstream_id="kits/anchor",
        upstream_revision=None,
        normalized_content_digest=normalized_content_digest({"SKILL.md": b"anchor v1"}),
        library_type="skill",
        transformation_version=IDENTITY_TRANSFORMATION.version,
    )
    base.update(overrides)
    return CacheKey(**base)


def test_revisionless_items_do_not_collide(tmp_path: Path) -> None:
    """The three within-provider collisions of the old key are separated (AC1)."""
    # (a) Same provider, same Library name, different content. The old key pins
    # every revisionless version to one fallback tag and overwrites in place,
    # destroying the only copy of the previous bytes.
    first = _key(normalized_content_digest=normalized_content_digest({"SKILL.md": b"anchor v1"}))
    second = _key(normalized_content_digest=normalized_content_digest({"SKILL.md": b"anchor v2"}))
    assert first.digest() != second.digest()

    legacy_first = compute_cache_path("skill", PROVIDER, "anchor", "local")
    legacy_second = compute_cache_path("skill", PROVIDER, "anchor", "local")
    assert legacy_first == legacy_second, "the old key is expected to collide here"

    # (b) Two different upstream ids that normalize to the same Library name.
    other_upstream = _key(upstream_id="archive/anchor")
    assert other_upstream.digest() != first.digest()
    assert compute_cache_path("skill", PROVIDER, "anchor", "local") == legacy_first

    # (c) Same content under a different transformation rule.
    transformed = _key(transformation_version="frontmatter-normalization/2")
    assert transformed.digest() != first.digest()

    store = ObjectStore(tmp_path / "cache")
    paths = {
        store.path_for(candidate)
        for candidate in (first, second, other_upstream, transformed)
    }
    assert len(paths) == 4


def test_tofu_drift_fails_closed(tmp_path: Path) -> None:
    """A re-fetch that differs from the pin names both digests and stops (AC6)."""
    store = TofuPinStore(tmp_path / "pins.json")
    identity = f"{PROVIDER}#kits/anchor"
    pinned = normalized_content_digest({"SKILL.md": b"anchor v1"})
    drifted = normalized_content_digest({"SKILL.md": b"anchor v2"})

    pin = store.pin(identity, pinned, observed_at=NOW)
    assert pin.normalized_content_digest == pinned
    assert "trust-on-first-use" in pin.describe()
    # A pin proves the bytes have not changed since first observation. It proves
    # nothing about upstream authenticity, and the record says so.
    assert pin.proves_upstream_authenticity is False

    # Re-observing the same bytes is not drift and does not rewrite the record.
    assert store.verify(identity, pinned).first_observed_at == NOW

    with pytest.raises(TofuDrift) as excinfo:
        store.verify(identity, drifted)
    drift = excinfo.value
    assert drift.pinned_digest == pinned
    assert drift.observed_digest == drifted
    assert pinned in str(drift) and drifted in str(drift)

    # Never auto-re-pinned: the stored pin is untouched after the refusal.
    assert store.pin_for(identity).normalized_content_digest == pinned
    reloaded = TofuPinStore(tmp_path / "pins.json")
    assert reloaded.pin_for(identity).normalized_content_digest == pinned

    # A second `pin` call is not a back door around the refusal.
    with pytest.raises(TofuDrift):
        store.pin(identity, drifted, observed_at=LATER)
    assert store.pin_for(identity).normalized_content_digest == pinned


def test_transformation_version_changes_object(tmp_path: Path) -> None:
    """Changing a transformation rule creates a new object, never rewrites one (AC9)."""
    upstream = {"SKILL.md": b"---\nname: anchor\n---\nbody\n"}
    digest = normalized_content_digest(upstream)
    store = ObjectStore(tmp_path / "cache")

    first_rule = Transformation(
        version="frontmatter-normalization/1",
        rule=lambda files: {path: content.upper() for path, content in files.items()},
        description="uppercase the marker file",
    )
    second_rule = Transformation(
        version="frontmatter-normalization/2",
        rule=lambda files: {path: content + b"# rule 2\n" for path, content in files.items()},
        description="append a rule marker",
    )

    first_key = _key(normalized_content_digest=digest, transformation_version=first_rule.version)
    second_key = _key(normalized_content_digest=digest, transformation_version=second_rule.version)

    first_object = store.materialize(first_key, first_rule.apply(upstream), created_at=NOW)
    second_object = store.materialize(second_key, second_rule.apply(upstream), created_at=LATER)

    assert first_object.path != second_object.path
    assert first_object.path.is_dir() and second_object.path.is_dir()
    # The first object's bytes are exactly what the first rule produced.
    assert store.read_content(first_key) == dict(first_rule.apply(upstream))
    assert store.read_content(second_key) == dict(second_rule.apply(upstream))
    assert store.verify(first_key).verified
    assert store.verify(second_key).verified


def test_cache_key_records_the_whole_adr_tuple() -> None:
    """Every tuple member is part of identity, and the round trip is lossless."""
    key = _key(upstream_revision="0123456789abcdef")
    assert key.tuple() == (
        PROVIDER,
        "kits/anchor",
        "0123456789abcdef",
        key.normalized_content_digest,
        "skill",
        IDENTITY_TRANSFORMATION.version,
    )
    assert CacheKey.from_dict(key.to_dict()) == key
    # A revisionless key is a distinct identity from a pinned one, so adopting a
    # revision can never silently reuse the trust-on-first-use object.
    assert _key(upstream_revision=None).digest() != key.digest()


def test_cache_key_members_are_length_framed() -> None:
    """Moving a character across a tuple boundary changes the identity.

    Without framing, `("a", "bc", ...)` and `("ab", "c", ...)` would digest
    identically and two different upstream items could share a cache object.
    """
    left = _key(provider_identity="a", upstream_id="bc")
    right = _key(provider_identity="ab", upstream_id="c")
    assert left.digest() != right.digest()


def test_materialize_never_overwrites_an_existing_object(tmp_path: Path) -> None:
    """An object is immutable: the same key re-materializes to the same bytes."""
    store = ObjectStore(tmp_path / "cache")
    key = _key()
    store.materialize(key, {"SKILL.md": b"anchor v1"}, created_at=NOW)
    again = store.materialize(key, {"SKILL.md": b"anchor v1"}, created_at=LATER)
    assert store.read_content(key) == {"SKILL.md": b"anchor v1"}
    assert again.created_at == NOW, "the first materialization is the durable one"

    with pytest.raises(ValueError, match="differ"):
        store.materialize(key, {"SKILL.md": b"substituted"}, created_at=LATER)
    assert store.read_content(key) == {"SKILL.md": b"anchor v1"}


def test_cache_key_refuses_a_non_text_revision() -> None:
    """A revision that only becomes an identity after stringification is two.

    Wave-1 review filed `upstream_revision=1` and `upstream_revision="1"` as two
    unequal keys with one digest and one path, so a pinned object could be
    addressed by a key that does not equal the key that created it.
    """
    with pytest.raises(ValueError, match="text or None"):
        _key(upstream_revision=1)
    with pytest.raises(ValueError, match="text or None"):
        _key(upstream_revision=True)


@pytest.mark.parametrize(
    "library_type", ["/absolute", "../escape", "skill/nested", "", "Skill"]
)
def test_cache_object_path_cannot_escape_the_cache_root(
    library_type: str, tmp_path: Path
) -> None:
    """A Library type is a name, never a path. Review materialized outside the root."""
    with pytest.raises(ValueError):
        _key(library_type=library_type)

    store = ObjectStore(tmp_path / "cache")
    root = store.objects_root.resolve()
    path = store.path_for(_key())
    assert root in path.parents


def test_concurrent_first_use_serializes_on_one_pin(tmp_path: Path) -> None:
    """Two first uses cannot both decide they are the first one (wave-1 F5).

    Atomic replacement makes the write indivisible and does nothing for the read
    that decided what to write. Review ran the two concurrently and both
    succeeded with different digests, so the trusted identity was chosen by
    whichever process finished last.
    """
    store = TofuPinStore(tmp_path / "pins.json")
    identity = f"{PROVIDER}#kits/anchor"
    first = normalized_content_digest({"SKILL.md": b"anchor v1"})
    second = normalized_content_digest({"SKILL.md": b"anchor v2"})

    start = threading.Barrier(2)
    results: list[object] = []
    lock = threading.Lock()

    def attempt(digest: str) -> None:
        start.wait(timeout=10)
        try:
            outcome: object = store.pin(identity, digest, observed_at=NOW)
        except TofuDrift as drift:
            outcome = drift
        with lock:
            results.append(outcome)

    threads = [
        threading.Thread(target=attempt, args=(first,)),
        threading.Thread(target=attempt, args=(second,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert len(results) == 2
    drifts = [item for item in results if isinstance(item, TofuDrift)]
    pins = [item for item in results if not isinstance(item, TofuDrift)]
    assert len(pins) == 1 and len(drifts) == 1
    assert store.pin_for(identity).normalized_content_digest == pins[0].normalized_content_digest


def test_a_corrupt_existing_object_is_never_reused(tmp_path: Path) -> None:
    """An install that meets a damaged object fails closed (wave-1 F6).

    Comparing descriptors alone let a corrupted object be reused and then
    reported as verified, so a damaged cache became an installed artifact with a
    clean status.
    """
    store = ObjectStore(tmp_path / "cache")
    key = _key()
    stored = store.materialize(key, {"SKILL.md": b"anchor v1"}, created_at=NOW)
    (stored.path / "content" / "SKILL.md").write_bytes(b"corrupted")

    with pytest.raises(CacheObjectCorrupt):
        store.materialize(key, {"SKILL.md": b"anchor v1"}, created_at=LATER)
    assert store.read_content(key) == {"SKILL.md": b"corrupted"}, "nothing is replaced"

    # Repair is explicit, proves the same identity, and refuses different bytes.
    with pytest.raises(ValueError, match="repair refused"):
        store.repair_object(key, {"SKILL.md": b"something else"}, created_at=LATER, operator="malte")
    store.repair_object(key, {"SKILL.md": b"anchor v1"}, created_at=LATER, operator="malte")
    assert store.verify(key).verified
    assert store.read_content(key) == {"SKILL.md": b"anchor v1"}


def test_staging_residue_from_a_dead_writer_is_swept(tmp_path: Path) -> None:
    """A hard kill leaves residue; the next materialization removes it (wave-1 F4).

    A `finally` block does not run after `SIGKILL`, so "leaves no partial object
    behind" held only for tidy failures until the store learned to scavenge.
    """
    store = ObjectStore(tmp_path / "cache")
    store.staging_root.mkdir(parents=True, exist_ok=True)

    child = os.fork()
    if child == 0:  # pragma: no cover - the child never returns to pytest
        residue = store.staging_root / f"{os.getpid()}-abandoned"
        (residue / "content").mkdir(parents=True)
        (residue / "content" / "SKILL.md").write_bytes(b"half a file")
        os._exit(0)
    os.waitpid(child, 0)

    assert store.temporary_entries() == (f"{child}-abandoned",)

    live = store.staging_root / f"{os.getpid()}-in-flight"
    live.mkdir(parents=True)

    swept = store.materialize(_key(), {"SKILL.md": b"anchor v1"}, created_at=NOW)
    assert swept.path.is_dir()
    remaining = store.temporary_entries()
    assert f"{child}-abandoned" not in remaining
    assert f"{os.getpid()}-in-flight" in remaining, "a live writer's work is untouched"


def test_read_verified_hands_back_the_bytes_it_verified(tmp_path: Path) -> None:
    """One read, one digest, one payload (wave-1 F7).

    Review replaced the stored file between a successful `verify` and the read
    that produced the installed bytes, so an unverified payload was installed
    under a verified report.
    """
    store = ObjectStore(tmp_path / "cache")
    key = _key()
    stored = store.materialize(key, {"SKILL.md": b"anchor v1"}, created_at=NOW)

    snapshot, report = store.read_verified(key)
    assert report.verified
    (stored.path / "content" / "SKILL.md").write_bytes(b"substituted after verification")
    assert snapshot["SKILL.md"] == b"anchor v1", "the snapshot is not a live view"
    with pytest.raises(TypeError):
        snapshot["SKILL.md"] = b"tampered"
    assert not store.read_verified(key)[1].verified


@pytest.mark.parametrize(
    ("left", "right"),
    [("dir/file.txt", "dir//file.txt"), ("a/b.txt", "./a/b.txt"), ("x.txt", "x.txt/")],
)
def test_filesystem_equivalent_member_paths_are_refused(
    left: str, right: str, tmp_path: Path
) -> None:
    """Two spellings of one destination are one member (wave-2 F8).

    Review supplied `dir/file.txt` and `dir//file.txt`: both passed the raw
    duplicate check, both wrote to the same place, and materialization returned
    success while publishing an object that immediately failed verification.
    """
    store = ObjectStore(tmp_path / "cache")
    with pytest.raises(ValueError, match="duplicate cached path"):
        store.materialize(
            _key(), {left: b"first", right: b"second"}, created_at=NOW
        )
    assert store.objects() == ()
    assert store.temporary_entries() == ()


def test_a_failed_repair_swap_rolls_back(tmp_path: Path, monkeypatch) -> None:
    """The repair swap restores the previous object when it cannot publish (wave-2 F9).

    Review failed the second rename and left the canonical path absent with the
    verified replacement already deleted, recoverable through no API at all.
    """
    store = ObjectStore(tmp_path / "cache")
    key = _key()
    stored = store.materialize(key, {"SKILL.md": b"anchor v1"}, created_at=NOW)
    (stored.path / "content" / "SKILL.md").write_bytes(b"corrupted")

    real_rename = os.rename
    calls = {"count": 0}

    def failing_rename(src, dst):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("the publishing rename failed")
        return real_rename(src, dst)

    monkeypatch.setattr(os, "rename", failing_rename)
    with pytest.raises(OSError, match="publishing rename"):
        store.repair_object(key, {"SKILL.md": b"anchor v1"}, created_at=LATER, operator="malte")
    monkeypatch.undo()

    # The canonical object is back where it was, damaged but present and
    # loadable, rather than absent and unrecoverable.
    assert store.load(key).path == stored.path
    assert store.read_content(key) == {"SKILL.md": b"corrupted"}
    assert store.quarantined() == ()

    # A successful repair leaves nothing quarantined either.
    store.repair_object(key, {"SKILL.md": b"anchor v1"}, created_at=LATER, operator="malte")
    assert store.verify(key).verified
    assert store.quarantined() == ()


def test_repin_refuses_another_sources_resolution(tmp_path: Path) -> None:
    """One source's healthy resolution never authorizes another's (wave-2 F6)."""
    from lib.providers.inventory import ProviderAvailability
    from lib.providers.offline import OfflineRefusal, ResolutionEvidence

    store = TofuPinStore(tmp_path / "pins.json")
    identity = "provider-b#kits/anchor"
    pinned = normalized_content_digest({"SKILL.md": b"anchor v1"})
    drifted = normalized_content_digest({"SKILL.md": b"anchor v2"})
    store.pin(identity, pinned, observed_at=NOW)

    def evidence(provider: str) -> ResolutionEvidence:
        return ResolutionEvidence(
            provider_identity=provider,
            availability=ProviderAvailability(state="available", observed_at=NOW),
            listed_identities=frozenset({identity}),
            complete=True,
        )

    with pytest.raises(OfflineRefusal, match="never authorizes substitution"):
        store.repin(
            identity,
            drifted,
            operator="malte",
            acknowledged_drift=(pinned, drifted),
            decided_at=LATER,
            availability=evidence("provider-a"),
        )
    assert store.pin_for(identity).normalized_content_digest == pinned

    replaced = store.repin(
        identity,
        drifted,
        operator="malte",
        acknowledged_drift=(pinned, drifted),
        decided_at=LATER,
        availability=evidence("provider-b"),
    )
    assert replaced.normalized_content_digest == drifted
    assert replaced.superseded_digests == (pinned,)


def test_integrity_verification_reports_both_digests(tmp_path: Path) -> None:
    """Verification names what was expected and what was found."""
    store = ObjectStore(tmp_path / "cache")
    key = _key()
    cache_object = store.materialize(key, {"SKILL.md": b"anchor v1"}, created_at=NOW)
    assert store.verify(key).verified

    (cache_object.path / "content" / "SKILL.md").write_bytes(b"tampered")
    report = store.verify(key)
    assert not report.verified
    assert report.expected_digest != report.observed_digest
    assert report.expected_digest in report.detail
    assert report.observed_digest in report.detail
