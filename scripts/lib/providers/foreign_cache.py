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

import contextlib
import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Iterator, Mapping

from .executable_admission import content_digest, validated_digest
from .inventory import ProviderAvailability
from .offline import OfflineRefusal, ResolutionEvidence, require_operation
from .state_files import (
    atomic_write_text,
    exclusive_lock,
    owner_pid,
    process_is_alive,
    scoped_lock_path,
)

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
#: Marks a damaged object a repair set aside. Discoverable on purpose.
QUARANTINE_SUFFIX = ".quarantined-"
#: A storage bucket segment. The bucket is derived from `library_type`, which is
#: caller-supplied text, so it is constrained to one safe path segment. Review
#: materialized an object outside the cache root by supplying an absolute
#: `library_type`; a value that can address the filesystem is not a type name.
_SAFE_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


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


class CacheObjectCorrupt(RuntimeError):
    """A stored object's bytes no longer match its recorded digest.

    Fail-closed rather than self-healing. Review demonstrated the alternative:
    an install that found an existing descriptor reused a corrupted object and
    then reported the receipt as verified, so a damaged cache became an
    installed artifact with a clean status. Repair exists, but it is
    `ObjectStore.repair_object` and it is explicit.
    """

    def __init__(self, key_digest: str, detail: str) -> None:
        super().__init__(
            f"cache object {key_digest} failed verification and was not reused: "
            f"{detail}. Repair it explicitly, or delete nothing and investigate; "
            "a corrupt object is never silently replaced."
        )
        self.key_digest = key_digest
        self.detail = detail


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
        if self.upstream_revision is not None:
            # Strictly text or null. Review filed the integer 1 and the string
            # "1" as two unequal keys with one identity: every member is
            # stringified before framing, so a non-text member produces a second
            # key value that addresses the first key's object.
            if not isinstance(self.upstream_revision, str):
                raise ValueError(
                    "CacheKey.upstream_revision must be text or None, not "
                    f"{type(self.upstream_revision).__name__}; a value that only "
                    "becomes an identity after stringification is two identities"
                )
            if not self.upstream_revision.strip():
                raise ValueError(
                    "CacheKey.upstream_revision is either an identity or None; an "
                    "empty string would make a revisionless item look pinned"
                )
        if not _SAFE_SEGMENT_RE.match(self.library_type):
            raise ValueError(
                f"CacheKey.library_type {self.library_type!r} is not a safe storage "
                "segment; a Library type is a lowercase name, never a path"
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


def normalized_member_path(path: object) -> str:
    """One item-relative member path in exactly one spelling, or a refusal.

    Two spellings of one destination are two logical members that occupy one
    file. Review supplied `dir/file.txt` and `dir//file.txt`: both passed the
    duplicate check, both wrote to the same place, and materialization returned
    success while publishing an object that immediately failed verification.
    Aliases are therefore collapsed here and then rejected as duplicates by the
    caller, rather than discovered by the filesystem after the digest is fixed.
    """
    if not isinstance(path, str) or not path.strip():
        raise ValueError("every cached file needs an item-relative path")
    if "\\" in path:
        raise ValueError(f"cached path must use forward separators: {path!r}")
    if path.startswith("/"):
        raise ValueError(f"cached path must be item-relative: {path!r}")
    segments = [segment for segment in path.split("/") if segment not in ("", ".")]
    if not segments or any(segment == ".." for segment in segments):
        raise ValueError(f"cached path must be item-relative: {path!r}")
    return "/".join(segments)


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
        """The object path for one key, proven to stay beneath the cache root.

        `CacheKey` already refuses a path-bearing `library_type`, and this is the
        second half of the same guarantee: the resolved destination is checked
        rather than assumed, so a future key member can never address the
        filesystem even if its own validation is relaxed.
        """
        candidate = (self.objects_root / f"{key.library_type}s" / key.digest()).resolve()
        root = self.objects_root.resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError(
                f"cache object path for {key.digest()} resolves outside the cache "
                f"root: {candidate}"
            )
        return candidate

    def exists(self, key: CacheKey) -> bool:
        return (self.path_for(key) / DESCRIPTOR_NAME).is_file()

    def temporary_entries(self) -> tuple[str, ...]:
        """Staging entries present right now. A healthy store has none."""
        if not self.staging_root.is_dir():
            return ()
        return tuple(sorted(entry.name for entry in self.staging_root.iterdir()))

    def sweep_staging(self) -> tuple[str, ...]:
        """Remove staging entries whose writer is gone, and name what was removed.

        A staging entry is by construction a never-visible partial object, so
        discarding it destroys nothing an operator could reference. What it must
        not destroy is a *live* writer's work, which is why each entry carries
        the writing process id and only entries whose writer no longer exists are
        swept.

        This exists because a `finally` block does not run after a hard kill.
        Review killed a materializer mid-write and left permanent residue that no
        later run would ever clean up, which turns AC2's "leaves no partial
        object behind" into a promise that holds only for tidy failures.
        """
        if not self.staging_root.is_dir():
            return ()
        swept: list[str] = []
        for entry in sorted(self.staging_root.iterdir()):
            owner = owner_pid(entry.name)
            if owner is None or owner == os.getpid() or process_is_alive(owner):
                continue
            shutil.rmtree(entry, ignore_errors=True)
            swept.append(entry.name)
        self._prune_empty_staging_root()
        return tuple(swept)

    def objects(self) -> tuple[CacheObject, ...]:
        """Every complete object in the store."""
        if not self.objects_root.is_dir():
            return ()
        found = []
        for descriptor in sorted(self.objects_root.rglob(DESCRIPTOR_NAME)):
            if QUARANTINE_SUFFIX in descriptor.parent.name:
                # A quarantined object is retained evidence, not a cache entry.
                continue
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
            CacheObjectCorrupt: when the key already holds an object whose bytes
                no longer match its own recorded digest. Reuse is refused rather
                than repaired, because an install that silently reuses damaged
                bytes reports success over content nobody verified.
        """
        if not isinstance(created_at, str) or not created_at.strip():
            raise ValueError("materialize requires the observation time of the write")

        self.sweep_staging()
        if self.exists(key):
            # Verify the stored bytes before reusing them. Comparing descriptors
            # alone proved insufficient: a corrupted object kept its descriptor
            # and was reused, and the resulting receipt claimed verification.
            report = self.verify(key)
            if not report.verified:
                raise CacheObjectCorrupt(key.digest(), report.detail)

        staged = self.staging_root / f"{os.getpid()}-{uuid.uuid4().hex}"
        try:
            written = self._stage(staged, files)
            # Digest what is on disk, not what was handed in. An object is
            # published only if the staged tree reproduces the digest recorded
            # in its descriptor, so a write that silently lost or merged a
            # member never becomes a visible object.
            on_disk = self._staged_content(staged)
            projected_digest = normalized_content_digest(on_disk)
            if projected_digest != normalized_content_digest(written):
                raise CacheObjectConflict(
                    "staged content does not reproduce the offered members; the "
                    "object was not published"
                )
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
            member = normalized_member_path(path)
            if member in written:
                raise ValueError(
                    f"duplicate cached path: {path!r} resolves to {member!r}, which "
                    "another member already occupies"
                )
            if not isinstance(content, (bytes, bytearray)):
                raise ValueError(f"content for {path!r} must be bytes")
            destination = content_root / member
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bytes(content))
            written[member] = bytes(content)
        if not written:
            raise ValueError("a cache object holds at least one file")
        return written

    def _staged_content(self, staged: Path) -> dict[str, bytes]:
        content_root = staged / CONTENT_DIRECTORY
        return {
            str(path.relative_to(content_root)): path.read_bytes()
            for path in sorted(content_root.rglob("*"))
            if path.is_file()
        }

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
            report = self.verify(descriptor.key)
            if not report.verified:
                raise CacheObjectCorrupt(descriptor.key.digest(), report.detail) from None
            return existing
        del written
        return descriptor

    def repair_object(
        self,
        key: CacheKey,
        files: Mapping[str, bytes],
        *,
        created_at: str,
        operator: str,
    ) -> CacheObject:
        """Replace a corrupt object with bytes that prove the same identity.

        This is the only path that replaces stored bytes, and it is deliberately
        not reachable from `materialize`: silent self-healing is
        indistinguishable from silent substitution at the moment it matters.

        The swap is the dangerous part and it is protected on both sides. The
        damaged object is renamed into a discoverable quarantine, the
        replacement is renamed into its place, and a failure of that second
        rename rolls the quarantine back. Review injected exactly that failure
        against the earlier version and left the canonical object absent with
        the verified replacement already deleted, recoverable through no API at
        all. If the rollback also fails, both paths are named in the error and
        `quarantined` lists what remains.

        Raises:
            ValueError: when the offered bytes do not reproduce the stored
                object's recorded digest, or when no operator is named.
            CacheObjectMissing: when there is nothing to repair.
            CacheObjectCorrupt: when the swap failed and could not be rolled
                back; the message names every path that still holds content.
        """
        if not isinstance(operator, str) or not operator.strip():
            raise ValueError("a cache repair records the operator who authorized it")
        stored = self.load(key)
        offered = normalized_content_digest(files)
        if offered != stored.projected_content_digest:
            raise ValueError(
                f"repair refused: the offered bytes digest to {offered} but the "
                f"stored object records {stored.projected_content_digest}; a repair "
                "restores the recorded object, it does not redefine it"
            )
        staged = self.staging_root / f"{os.getpid()}-{uuid.uuid4().hex}"
        quarantine = stored.path.with_name(
            f"{stored.path.name}{QUARANTINE_SUFFIX}{uuid.uuid4().hex}"
        )
        published = False
        try:
            written = self._stage(staged, files)
            descriptor = CacheObject(
                key=key,
                path=stored.path,
                projected_content_digest=normalized_content_digest(written),
                created_at=created_at,
                native_verification=stored.native_verification,
            )
            (staged / DESCRIPTOR_NAME).write_text(
                json.dumps(descriptor.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.rename(stored.path, quarantine)
            try:
                os.rename(staged, stored.path)
                published = True
            except OSError as exc:
                try:
                    os.rename(quarantine, stored.path)
                except OSError:
                    raise CacheObjectCorrupt(
                        key.digest(),
                        "the repair swap failed and could not be rolled back; the "
                        f"damaged object is at {quarantine} and the verified "
                        f"replacement is at {staged}",
                    ) from exc
                raise
        finally:
            if not published:
                shutil.rmtree(staged, ignore_errors=True)
            self._prune_empty_staging_root()
        shutil.rmtree(quarantine, ignore_errors=True)
        return descriptor

    def quarantined(self) -> tuple[Path, ...]:
        """Damaged objects a repair set aside, in case one has to be inspected.

        A quarantine that nothing can list is a deletion with extra steps.
        """
        if not self.objects_root.is_dir():
            return ()
        return tuple(
            sorted(
                path
                for path in self.objects_root.rglob(f"*{QUARANTINE_SUFFIX}*")
                if path.is_dir()
            )
        )

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
        return self.read_verified(key)[1]

    def read_verified(
        self, key: CacheKey
    ) -> tuple[Mapping[str, bytes], IntegrityReport]:
        """Read the object **once** and verify exactly the bytes that were read.

        The returned snapshot is immutable and is the only content a caller
        should install. Reading twice -- once to verify, once to use -- is a
        check-to-use window, and review walked through it: the stored file was
        replaced between a `verify` that returned true and the read that
        produced the installed bytes, so an unverified payload was installed
        under a verified report.
        """
        stored = self.load(key)
        snapshot = MappingProxyType(dict(self.read_content(key)))
        observed = normalized_content_digest(snapshot)
        verified = observed == stored.projected_content_digest
        detail = (
            f"expected {stored.projected_content_digest}, observed {observed} "
            f"at {stored.path}"
        )
        report = IntegrityReport(
            key_digest=key.digest(),
            path=stored.path,
            expected_digest=stored.projected_content_digest,
            observed_digest=observed,
            verified=verified,
            detail=("integrity verified: " if verified else "integrity failed: ") + detail,
        )
        return snapshot, report


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

    @contextlib.contextmanager
    def identity_lock(self, qualified_identity: str) -> Iterator[None]:
        """Serialize everything one identity's trust decision governs.

        Locking only the compare-and-write serializes the pin file and nothing
        else. Review paused an install after it had verified the old pin,
        re-pinned the identity to different bytes, and let the install finish:
        the durable pin and the installed content described different content,
        which is the substitution the pin exists to make impossible. An install
        therefore holds this lock across verification, materialization, the
        receipt, and activation, and a re-pin waits for it.
        """
        with exclusive_lock(scoped_lock_path(self.path, qualified_identity)):
            yield

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
        atomic_write_text(self.path, json.dumps(payload, indent=2, sort_keys=True) + "\n")

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
        with exclusive_lock(self.path):
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

        The decision and the write happen under one lock, so two concurrent
        first uses cannot each decide they are the first one.

        Returns:
            The pin and whether this call created it.
        """
        validated_digest(digest)
        with exclusive_lock(self.path):
            existing = self._load().get(qualified_identity)
            if existing is None:
                recorded = self._pin_locked(
                    qualified_identity, digest, observed_at=observed_at
                )
                return recorded, True
            if existing.normalized_content_digest != digest:
                raise TofuDrift(
                    qualified_identity, existing.normalized_content_digest, digest
                )
            return existing, False

    def _pin_locked(
        self, qualified_identity: str, digest: str, *, observed_at: str
    ) -> TofuPin:
        pins = self._load()
        recorded = TofuPin(
            qualified_identity=qualified_identity,
            normalized_content_digest=digest,
            first_observed_at=observed_at,
        )
        pins[qualified_identity] = recorded
        self._save(pins)
        return recorded

    def repin(
        self,
        qualified_identity: str,
        digest: str,
        *,
        operator: str,
        acknowledged_drift: tuple[str, str],
        decided_at: str,
        availability: ProviderAvailability | ResolutionEvidence,
    ) -> TofuPin:
        """Replace a pin after an explicit operator decision about named drift.

        Every argument here is a barrier against the one failure ADR-0011 forbids
        everywhere: automatic re-pinning, which converts detectable drift into
        undetectable silent substitution.

        Args:
            acknowledged_drift: The exact `(pinned, observed)` pair the operator
                was shown. A mismatch refuses, so an acknowledgement of one drift
                cannot authorize a different substitution.
            availability: Source-scoped resolution evidence **for this
                identity's own source**. Review re-pinned one source's item on
                another source's healthy resolution, so a reachable source could
                authorize substitution for an unreachable one.

        Raises:
            OfflineRefusal: when the source is not reachable, or when the
                evidence describes a different source.
            ValueError: when the acknowledgement does not match the recorded pin
                and the offered digest, or when nothing is pinned.
        """
        require_operation("re-pin", availability)
        owner = qualified_identity.partition("#")[0]
        if not isinstance(availability, ResolutionEvidence):
            raise OfflineRefusal(
                "re-pin",
                "would-substitute-pinned-content",
                "a re-pin needs source-scoped resolution evidence for this "
                "identity, not transport reachability alone",
            )
        if availability.provider_identity != owner:
            raise OfflineRefusal(
                "re-pin",
                "would-substitute-pinned-content",
                f"{qualified_identity} belongs to {owner!r} but the evidence "
                f"describes {availability.provider_identity!r}; one source's "
                "resolution never authorizes substitution for another's",
            )
        validated_digest(digest)
        if not isinstance(operator, str) or not operator.strip():
            raise ValueError("a re-pin records the operator who decided it")
        with self.identity_lock(qualified_identity), exclusive_lock(self.path):
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
    "CacheObjectCorrupt",
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
