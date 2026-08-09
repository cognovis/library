"""Durable cache identity and materialization (ADR-0011 `Cache Transaction`).

The cache key is a tuple, not a path convention:

```text
(provider_identity, upstream_id, upstream_revision | null,
 normalized_content_digest, library_type, transformation_version)
```

The defect it replaces is **within one source**, not across two of them. The
released key `<type>/<marketplace>/<name>@<commit14>` already separates
marketplaces into path segments, so the often-repeated cross-source collision
claim is false. The three real collisions, and the tuple member that separates
each:

| Collision | Separated by |
|---|---|
| Same source and name, different content, because every revisionless version pins to one fallback tag and overwrites in place | `normalized_content_digest` |
| Two different upstream ids that normalize to one Library name | `upstream_id` |
| The same content reached under two transformation rules | `transformation_version` |

`normalized_content_digest` is a Library-computed digest over normalized content
bytes, and it is the **only** integrity proof the Library relies on. A native
proof from an adapter's `verify` is recorded as supplementary evidence.

**Which bytes the digest covers, stated because both readings are defensible.**
The digest covers the *upstream* bytes, not the transformed ones. It is the
subject of the trust-on-first-use pin, and a pin has to be comparable against
what a later re-fetch returns; a pin over transformed bytes would silently
change meaning whenever a transformation rule changed. The transformed bytes are
what a cache object *stores*, because those are the bytes an outage has to be
able to reproduce, and they carry their own `projected_content_digest` as the
integrity proof of the stored object. For the identity transformation the two
digests are equal, which is why the distinction is easy to lose and worth
stating.

**Digest boundary with executable admission.** `normalized_content_digest` is
`executable_admission.content_digest`, adopted rather than forked. Slice 2 left
that choice open and required only that admission stay bound to content; two
independent digests over the same bytes would have created exactly the gap that
binding exists to close -- a decision recorded against one identity while the
cache stores another.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .executable_admission import content_digest, validated_digest
from .inventory import ProviderAvailability
from .offline import OfflineRefusal, require_operation

CACHE_OBJECT_SCHEMA = "cognovis.foreign-cache-object.v1"
PIN_STORE_SCHEMA = "cognovis.trust-on-first-use-pins.v1"

#: Sub-directory holding the item's stored bytes inside a cache object.
CONTENT_DIRECTORY = "content"
#: Sidecar naming the whole key tuple, so an object is self-describing.
DESCRIPTOR_NAME = "object.json"
#: Where a materialization is assembled before it becomes visible.
STAGING_DIRECTORY = "incoming"
#: Where completed objects live.
OBJECTS_DIRECTORY = "objects"


def normalized_content_digest(files: Mapping[str, bytes]) -> str:
    """The Library digest over one item's complete normalized content.

    Normalization is the length-framed canonical encoding of every
    (item-relative path, bytes) pair in sorted order. It is deliberately not an
    archive digest: two callers must reach the same value without agreeing on a
    container format, timestamps, or file ordering.
    """
    return content_digest(files)


class CacheObjectMissing(KeyError):
    """No cache object exists for this key."""


class CacheObjectConflict(ValueError):
    """A key already holds different bytes than the ones offered.

    An object is immutable. Reaching this means two different contents claim one
    identity, which is a key defect and not a race to be resolved by overwriting.
    """


@dataclass(frozen=True)
class Transformation:
    """A mechanical, reproducible projection applied to unmodified upstream bytes.

    A transformation is **not** an adaptation. It rewrites shape -- frontmatter
    normalization, path rewriting, a harness bridge layout -- and a material
    adaptation instead produces a first-party derivative governed by
    `providers.rights`.

    `version` names the exact rule and is part of the cache key, so changing a
    rule produces a new object instead of rewriting one that was materialized
    under the old rule.
    """

    version: str
    rule: Callable[[Mapping[str, bytes]], Mapping[str, bytes]] | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("Transformation.version is required")

    def apply(self, files: Mapping[str, bytes]) -> dict[str, bytes]:
        """Project upstream bytes into the bytes a cache object stores."""
        if self.rule is None:
            return {path: bytes(content) for path, content in files.items()}
        projected = self.rule(files)
        if not projected:
            raise ValueError(
                f"transformation {self.version!r} produced no files; a projection "
                "that empties an item is a rule defect, not an empty item"
            )
        return {path: bytes(content) for path, content in projected.items()}


#: Installed bytes are upstream bytes. Recorded explicitly rather than left as an
#: absent value, because "no transformation" is itself a transformation identity
#: and an absent one would make every unrecorded object look interchangeable.
IDENTITY_TRANSFORMATION = Transformation(
    version="identity/1",
    description="upstream bytes are stored and installed verbatim",
)


def _framed(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return f"{len(encoded)}:".encode("ascii") + encoded


@dataclass(frozen=True)
class CacheKey:
    """The ADR-0011 cache identity tuple."""

    provider_identity: str
    upstream_id: str
    upstream_revision: str | None
    normalized_content_digest: str
    library_type: str
    transformation_version: str

    def __post_init__(self) -> None:
        for name in (
            "provider_identity",
            "upstream_id",
            "library_type",
            "transformation_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"CacheKey.{name} is required")
        if self.upstream_revision is not None and not str(self.upstream_revision).strip():
            raise ValueError(
                "CacheKey.upstream_revision is either an identity or None; an empty "
                "string would make a revisionless item look pinned"
            )
        validated_digest(self.normalized_content_digest)

    def tuple(self) -> tuple[str, str, str | None, str, str, str]:
        return (
            self.provider_identity,
            self.upstream_id,
            self.upstream_revision,
            self.normalized_content_digest,
            self.library_type,
            self.transformation_version,
        )

    def digest(self) -> str:
        """A stable identity over the whole tuple.

        Every member is length-framed, so moving a character across a member
        boundary changes the identity. Without framing, `("a", "bc", ...)` and
        `("ab", "c", ...)` would hash alike and two different upstream items
        could share one cache object.
        """
        accumulator = hashlib.sha256()
        accumulator.update(_framed(CACHE_OBJECT_SCHEMA))
        for member in self.tuple():
            # A null revision is framed as its own marker rather than as an
            # empty string, so a revisionless identity can never collide with a
            # pinned one whose revision happens to be empty.
            accumulator.update(b"\x00" if member is None else _framed(str(member)))
        return accumulator.hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_identity": self.provider_identity,
            "upstream_id": self.upstream_id,
            "upstream_revision": self.upstream_revision,
            "normalized_content_digest": self.normalized_content_digest,
            "library_type": self.library_type,
            "transformation_version": self.transformation_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CacheKey":
        known = {
            "provider_identity",
            "upstream_id",
            "upstream_revision",
            "normalized_content_digest",
            "library_type",
            "transformation_version",
        }
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown cache key fields: {unknown}")
        missing = sorted(known - set(data))
        if missing:
            raise ValueError(f"missing cache key fields: {missing}")
        return cls(**{name: data[name] for name in known})

    def qualified_identity(self) -> str:
        return f"{self.provider_identity}#{self.upstream_id}"


@dataclass(frozen=True)
class CacheObject:
    """One complete, immutable, self-describing cache object."""

    key: CacheKey
    path: Path
    projected_content_digest: str
    created_at: str
    native_verification: str | None = None

    @property
    def content_path(self) -> Path:
        return self.path / CONTENT_DIRECTORY

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CACHE_OBJECT_SCHEMA,
            "key": self.key.to_dict(),
            "key_digest": self.key.digest(),
            "projected_content_digest": self.projected_content_digest,
            "created_at": self.created_at,
            "native_verification": self.native_verification,
        }


@dataclass(frozen=True)
class IntegrityReport:
    """Local integrity of one cache object, naming both digests."""

    key_digest: str
    path: Path
    expected_digest: str
    observed_digest: str
    verified: bool
    detail: str


def _as_pairs(files: Mapping[str, bytes] | Iterable[tuple[str, bytes]]):
    if isinstance(files, Mapping):
        return iter(sorted(files.items()))
    return iter(files)


class ObjectStore:
    """Content-addressed storage for complete foreign cache objects.

    Materialization is a two-phase write: the object is assembled under a
    staging directory and then moved into place with a single rename. A crash
    therefore leaves either nothing or a complete object, never a half-written
    one that a later run would read as cached and install.
    """

    def __init__(self, base: Path) -> None:
        self.base = Path(base)

    # -- layout ---------------------------------------------------------------

    @property
    def objects_root(self) -> Path:
        return self.base / OBJECTS_DIRECTORY

    @property
    def staging_root(self) -> Path:
        return self.base / STAGING_DIRECTORY

    def path_for(self, key: CacheKey) -> Path:
        return self.objects_root / f"{key.library_type}s" / key.digest()

    def exists(self, key: CacheKey) -> bool:
        return (self.path_for(key) / DESCRIPTOR_NAME).is_file()

    def temporary_entries(self) -> tuple[str, ...]:
        """Staging entries left behind. A healthy store has none."""
        if not self.staging_root.is_dir():
            return ()
        return tuple(sorted(entry.name for entry in self.staging_root.iterdir()))

    def objects(self) -> tuple[CacheObject, ...]:
        """Every complete object in the store."""
        if not self.objects_root.is_dir():
            return ()
        found = []
        for descriptor in sorted(self.objects_root.rglob(DESCRIPTOR_NAME)):
            found.append(self._read_descriptor(descriptor))
        return tuple(found)

    # -- writing --------------------------------------------------------------

    def materialize(
        self,
        key: CacheKey,
        files: Mapping[str, bytes] | Iterable[tuple[str, bytes]],
        *,
        created_at: str,
        native_verification: str | None = None,
    ) -> CacheObject:
        """Write one complete object, atomically, or write nothing at all.

        `files` may be a mapping or a stream of pairs. A stream that raises part
        way through is exactly the truncation case this ordering exists for: the
        partial content is discarded with the staging directory and no object
        becomes visible.

        Re-materializing identical bytes under the same key is a no-op that
        returns the object already stored, including its original
        `created_at` -- the first materialization is the durable one.

        Raises:
            CacheObjectConflict: when the key already holds different bytes.
        """
        if not isinstance(created_at, str) or not created_at.strip():
            raise ValueError("materialize requires the observation time of the write")

        staged = self.staging_root / uuid.uuid4().hex
        try:
            written = self._stage(staged, files)
            projected_digest = normalized_content_digest(written)
            descriptor = CacheObject(
                key=key,
                path=self.path_for(key),
                projected_content_digest=projected_digest,
                created_at=created_at,
                native_verification=native_verification,
            )
            (staged / DESCRIPTOR_NAME).write_text(
                json.dumps(descriptor.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return self._publish(staged, descriptor, written)
        finally:
            shutil.rmtree(staged, ignore_errors=True)
            self._prune_empty_staging_root()

    def _stage(
        self,
        staged: Path,
        files: Mapping[str, bytes] | Iterable[tuple[str, bytes]],
    ) -> dict[str, bytes]:
        content_root = staged / CONTENT_DIRECTORY
        content_root.mkdir(parents=True)
        written: dict[str, bytes] = {}
        for path, content in _as_pairs(files):
            if not isinstance(path, str) or not path.strip():
                raise ValueError("every cached file needs an item-relative path")
            if path.startswith("/") or ".." in path.split("/"):
                raise ValueError(f"cached path must be item-relative: {path!r}")
            if path in written:
                raise ValueError(f"duplicate cached path: {path!r}")
            if not isinstance(content, (bytes, bytearray)):
                raise ValueError(f"content for {path!r} must be bytes")
            destination = content_root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bytes(content))
            written[path] = bytes(content)
        if not written:
            raise ValueError("a cache object holds at least one file")
        return written

    def _publish(
        self, staged: Path, descriptor: CacheObject, written: Mapping[str, bytes]
    ) -> CacheObject:
        final = descriptor.path
        final.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(staged, final)
        except OSError:
            if not self.exists(descriptor.key):
                raise
            existing = self._read_descriptor(final / DESCRIPTOR_NAME)
            if existing.projected_content_digest != descriptor.projected_content_digest:
                raise CacheObjectConflict(
                    f"cache object {descriptor.key.digest()} already holds bytes that "
                    f"differ from the offered ones: stored "
                    f"{existing.projected_content_digest}, offered "
                    f"{descriptor.projected_content_digest}"
                ) from None
            return existing
        del written
        return descriptor

    def _prune_empty_staging_root(self) -> None:
        try:
            if self.staging_root.is_dir() and not any(self.staging_root.iterdir()):
                self.staging_root.rmdir()
        except OSError:  # pragma: no cover - a concurrent writer owns it
            pass

    # -- reading --------------------------------------------------------------

    def _read_descriptor(self, descriptor_path: Path) -> CacheObject:
        payload = json.loads(descriptor_path.read_text(encoding="utf-8"))
        if payload.get("schema") != CACHE_OBJECT_SCHEMA:
            raise ValueError(
                f"unexpected cache object schema in {descriptor_path}: {payload.get('schema')}"
            )
        return CacheObject(
            key=CacheKey.from_dict(payload["key"]),
            path=descriptor_path.parent,
            projected_content_digest=payload["projected_content_digest"],
            created_at=payload["created_at"],
            native_verification=payload.get("native_verification"),
        )

    def load(self, key: CacheKey) -> CacheObject:
        descriptor_path = self.path_for(key) / DESCRIPTOR_NAME
        if not descriptor_path.is_file():
            raise CacheObjectMissing(
                f"no cache object for {key.qualified_identity()} at {key.digest()}"
            )
        stored = self._read_descriptor(descriptor_path)
        if stored.key != key:
            raise CacheObjectConflict(
                f"cache object at {descriptor_path.parent} describes a different key"
            )
        return stored

    def read_content(self, key: CacheKey) -> dict[str, bytes]:
        stored = self.load(key)
        content_root = stored.content_path
        content: dict[str, bytes] = {}
        for path in sorted(content_root.rglob("*")):
            if path.is_file():
                content[str(path.relative_to(content_root))] = path.read_bytes()
        return content

    def verify(self, key: CacheKey) -> IntegrityReport:
        """Recompute the stored bytes' digest and report both values.

        A report rather than a bare boolean, because ADR-0011 keeps verified
        local integrity and remote freshness as separate reported facts and an
        operator needs to see what was expected next to what was found.
        """
        stored = self.load(key)
        observed = normalized_content_digest(self.read_content(key))
        verified = observed == stored.projected_content_digest
        detail = (
            f"expected {stored.projected_content_digest}, observed {observed} "
            f"at {stored.path}"
        )
        return IntegrityReport(
            key_digest=key.digest(),
            path=stored.path,
            expected_digest=stored.projected_content_digest,
            observed_digest=observed,
            verified=verified,
            detail=("integrity verified: " if verified else "integrity failed: ") + detail,
        )


class TofuDrift(RuntimeError):
    """A re-fetch whose digest differs from the trust-on-first-use pin.

    Fail-closed by construction: it is never silently accepted, never
    auto-upgraded, and never overwrites the pinned object. It names **both**
    digests, because "content changed" without them cannot be acted on.
    """

    def __init__(self, qualified_identity: str, pinned: str, observed: str) -> None:
        super().__init__(
            f"trust-on-first-use drift for {qualified_identity}: pinned {pinned}, "
            f"observed {observed}. The pinned object is unchanged and nothing was "
            "re-pinned; resolving this is an explicit operator decision."
        )
        self.qualified_identity = qualified_identity
        self.pinned_digest = pinned
        self.observed_digest = observed


@dataclass(frozen=True)
class TofuPin:
    """The first observed digest for a pin-only source, recorded as such.

    It proves the bytes have not changed since first observation. It proves
    nothing about upstream authenticity, and `proves_upstream_authenticity`
    records that in the data rather than in a comment, so a consumer cannot
    read a pin as provenance.
    """

    qualified_identity: str
    normalized_content_digest: str
    first_observed_at: str
    superseded_digests: tuple[str, ...] = field(default_factory=tuple)
    repinned_by: str | None = None
    repinned_at: str | None = None

    proves_upstream_authenticity: bool = False

    def __post_init__(self) -> None:
        for name in ("qualified_identity", "first_observed_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"TofuPin.{name} is required")
        validated_digest(self.normalized_content_digest)
        object.__setattr__(self, "superseded_digests", tuple(self.superseded_digests))
        if self.proves_upstream_authenticity:
            raise ValueError(
                "a trust-on-first-use pin never proves upstream authenticity"
            )

    def describe(self) -> str:
        return (
            f"trust-on-first-use pin for {self.qualified_identity}: "
            f"{self.normalized_content_digest} first observed at "
            f"{self.first_observed_at}; proves only that the bytes have not "
            "changed since then"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualified_identity": self.qualified_identity,
            "normalized_content_digest": self.normalized_content_digest,
            "first_observed_at": self.first_observed_at,
            "superseded_digests": list(self.superseded_digests),
            "repinned_by": self.repinned_by,
            "repinned_at": self.repinned_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TofuPin":
        return cls(
            qualified_identity=data["qualified_identity"],
            normalized_content_digest=data["normalized_content_digest"],
            first_observed_at=data["first_observed_at"],
            superseded_digests=tuple(data.get("superseded_digests") or ()),
            repinned_by=data.get("repinned_by"),
            repinned_at=data.get("repinned_at"),
        )


class TofuPinStore:
    """Durable trust-on-first-use pins.

    Every read goes to the file and every write replaces it atomically, so the
    pin a caller checks is the pin on disk. An in-memory copy would let a
    process hold a pin that a repair or a second process already changed.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, TofuPin]:
        if not self.path.is_file():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema") != PIN_STORE_SCHEMA:
            raise ValueError(f"unexpected pin store schema: {payload.get('schema')}")
        return {
            identity: TofuPin.from_dict(record)
            for identity, record in payload["pins"].items()
        }

    def _save(self, pins: Mapping[str, TofuPin]) -> None:
        payload = {
            "schema": PIN_STORE_SCHEMA,
            "pins": {identity: pin.to_dict() for identity, pin in sorted(pins.items())},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staged = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.staged")
        try:
            staged.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(staged, self.path)
        finally:
            staged.unlink(missing_ok=True)

    def pins(self) -> tuple[TofuPin, ...]:
        return tuple(self._load().values())

    def pin_for(self, qualified_identity: str) -> TofuPin | None:
        return self._load().get(qualified_identity)

    def pin(
        self, qualified_identity: str, digest: str, *, observed_at: str
    ) -> TofuPin:
        """Record a first-use pin, or confirm the existing one.

        Raises:
            TofuDrift: when a pin exists for different bytes. `pin` is not a back
                door around `verify`: a caller that retries the write path after
                a failed comparison must hit the same refusal.
        """
        validated_digest(digest)
        pins = self._load()
        existing = pins.get(qualified_identity)
        if existing is not None:
            if existing.normalized_content_digest != digest:
                raise TofuDrift(
                    qualified_identity, existing.normalized_content_digest, digest
                )
            return existing
        recorded = TofuPin(
            qualified_identity=qualified_identity,
            normalized_content_digest=digest,
            first_observed_at=observed_at,
        )
        pins[qualified_identity] = recorded
        self._save(pins)
        return recorded

    def verify(self, qualified_identity: str, digest: str) -> TofuPin:
        """Compare a freshly observed digest against the pin.

        Raises:
            KeyError: when nothing is pinned for this identity.
            TofuDrift: when the observed digest differs.
        """
        validated_digest(digest)
        existing = self._load().get(qualified_identity)
        if existing is None:
            raise KeyError(f"no trust-on-first-use pin for {qualified_identity}")
        if existing.normalized_content_digest != digest:
            raise TofuDrift(
                qualified_identity, existing.normalized_content_digest, digest
            )
        return existing

    def verify_or_pin(
        self, qualified_identity: str, digest: str, *, observed_at: str
    ) -> tuple[TofuPin, bool]:
        """Verify against an existing pin, or record the first-use pin.

        Returns:
            The pin and whether this call created it.
        """
        existing = self.pin_for(qualified_identity)
        if existing is None:
            return self.pin(qualified_identity, digest, observed_at=observed_at), True
        return self.verify(qualified_identity, digest), False

    def repin(
        self,
        qualified_identity: str,
        digest: str,
        *,
        operator: str,
        acknowledged_drift: tuple[str, str],
        decided_at: str,
        availability: ProviderAvailability,
    ) -> TofuPin:
        """Replace a pin after an explicit operator decision about named drift.

        Every argument here is a barrier against the one failure ADR-0011 forbids
        everywhere: automatic re-pinning, which converts detectable drift into
        undetectable silent substitution.

        Args:
            acknowledged_drift: The exact `(pinned, observed)` pair the operator
                was shown. A mismatch refuses, so an acknowledgement of one drift
                cannot authorize a different substitution.
            availability: The source observation. A re-pin needs a reachable
                source; the offline table refuses otherwise.

        Raises:
            OfflineRefusal: when the source is not reachable.
            ValueError: when the acknowledgement does not match the recorded pin
                and the offered digest, or when nothing is pinned.
        """
        require_operation("re-pin", availability)
        validated_digest(digest)
        if not isinstance(operator, str) or not operator.strip():
            raise ValueError("a re-pin records the operator who decided it")
        pins = self._load()
        existing = pins.get(qualified_identity)
        if existing is None:
            raise KeyError(f"no trust-on-first-use pin for {qualified_identity}")
        if tuple(acknowledged_drift) != (existing.normalized_content_digest, digest):
            raise ValueError(
                "the acknowledged drift does not match this pin and these bytes: "
                f"recorded {(existing.normalized_content_digest, digest)}, "
                f"acknowledged {tuple(acknowledged_drift)}"
            )
        replacement = TofuPin(
            qualified_identity=qualified_identity,
            normalized_content_digest=digest,
            first_observed_at=existing.first_observed_at,
            superseded_digests=(
                *existing.superseded_digests,
                existing.normalized_content_digest,
            ),
            repinned_by=operator,
            repinned_at=decided_at,
        )
        pins[qualified_identity] = replacement
        self._save(pins)
        return replacement


__all__ = [
    "CACHE_OBJECT_SCHEMA",
    "IDENTITY_TRANSFORMATION",
    "CacheKey",
    "CacheObject",
    "CacheObjectConflict",
    "CacheObjectMissing",
    "IntegrityReport",
    "ObjectStore",
    "OfflineRefusal",
    "TofuDrift",
    "TofuPin",
    "TofuPinStore",
    "Transformation",
    "normalized_content_digest",
]
