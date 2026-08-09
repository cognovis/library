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

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.cache import compute_cache_path  # noqa: E402
from lib.providers.foreign_cache import (  # noqa: E402
    IDENTITY_TRANSFORMATION,
    CacheKey,
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
