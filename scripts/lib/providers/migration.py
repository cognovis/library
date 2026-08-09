"""Additive migration of legacy lock receipts and legacy cache objects (CL-m6cc).

ADR-0011 `Migration` states two rules and this module is both of them.

**Additive, never strict.** A receipt written before the foreign fields existed
stays valid and reads as `unknown`. The temptation is to reject it, and the cost
of rejecting it is concrete: the receipt is the only record that says what a
materialized projection is, so a migration that refuses old receipts pushes an
operator towards discarding exactly the evidence that makes a projection
attributable.

**Re-key by re-materialization, never by rename.** A legacy cache object is keyed
`<type>/<marketplace>/<name>@<commit14>` and carries no recorded normalized
digest and no transformation identity. Moving that directory into the tuple key
space would mint an identity it never had, and every later integrity check would
then confirm the fabrication. So the legacy object stays where it is, stays
usable, and the honest identity is recomputed from the provider on the next
install or repair. The accepted cost is stated rather than hidden: the first
post-migration operation may be slower and needs the provider to be reachable.

**Migration grants no deletion authority.** Not for a cache object, not for a
receipt, not for a projected file. That is enforced three ways here rather than
asserted once: this module imports no deletion or rename primitive, its plan and
outcome types carry structurally empty `renames`/`deletions`, and a run takes a
content census of the surfaces it touches and refuses when anything it saw
before the run is gone or changed afterwards.

A receipt that cannot be reconstructed is marked `unresolvable`, **retained**,
and prune-blocked. Unknown state is never converted into deletion authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .inventory import Rights
from .rights import projection_eligibility
from .state_files import atomic_write_text

MIGRATION_STATE_SCHEMA = "cognovis.legacy-cache-migration.v1"

#: The value an unresolved additive field reads as. It is deliberately the same
#: token the rights model uses: "nobody has looked" is one state, whether the
#: subject is a licence or a content digest.
UNKNOWN = "unknown"

#: A migrated receipt's `upstream_state`. The live receipt vocabulary is
#: `present` | `upstream-vanished`, and a migration has observed neither. Writing
#: `present` would be a claim about a provider nobody contacted, so a migrated
#: entry carries `unknown` and is therefore **not** loadable as a
#: `ForeignReceipt` until re-materialization gives it an observed state.
MIGRATED_UPSTREAM_STATE = UNKNOWN

#: The ADR-0011 foreign receipt fields, in the order `docs/lockfile-format.md`
#: documents them. Every one is additive; every absent one reads as unknown.
FOREIGN_RECEIPT_FIELDS: tuple[str, ...] = (
    "provider_identity",
    "upstream_id",
    "upstream_name",
    "collection_membership",
    "upstream_revision",
    "normalized_content_digest",
    "transformation_version",
    "rights",
    "executable_admission",
    "projection_eligibility",
    "upstream_state",
    "provider_availability",
    "projected_content_digest",
    "planned_targets",
    "completeness_evidence",
    "cache_key_digest",
)

#: The three facts a receipt needs before anything can be reproduced from it.
#: They are named rather than implied, because "unresolvable" has to say *what*
#: could not be resolved for an operator to have any move at all.
RECONSTRUCTION_FACTS: tuple[str, ...] = ("source", "content-digest", "catalog-identity")

#: The legacy Layer-B directory name shape: `<name>@<commit14 or tag>`.
_LEGACY_OBJECT_RE = re.compile(r"^(?P<name>.+)@(?P<tag>[^@/]+)$")

#: Tags the legacy key used for a source with no revision. They are tags, not
#: revisions, and recording one as a revision is the collision ADR-0011 names.
_REVISIONLESS_TAGS: frozenset[str] = frozenset({"local", ""})

#: The all-unknown rights a migration may reach. `granted` and `denied` require a
#: named evidence source (`CL-n7ex`) and a migration has looked at nothing, so
#: this is the only value it can honestly produce.
UNRESOLVED_RIGHTS = Rights(
    fetch_authorization=UNKNOWN,
    install_rights=UNKNOWN,
    redistribution_rights=UNKNOWN,
    derivative_rights=UNKNOWN,
)


class MigrationRefused(RuntimeError):
    """A migration would have lost something, so it did nothing instead."""


# -- receipt field migration ---------------------------------------------------


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _field_default(name: str) -> Any:
    """The honest value for one absent foreign field."""
    if name == "rights":
        return UNRESOLVED_RIGHTS.to_dict()
    if name == "projection_eligibility":
        # `unknown` is not a permissive middle state. Invariant 13 binds it to a
        # blocked committed projection, and deriving the eligibility here rather
        # than writing `unknown` means a migrated receipt cannot be read as
        # installable into a committed tree by a caller that treats an unknown
        # eligibility as "no opinion".
        return projection_eligibility(UNRESOLVED_RIGHTS, subject="migrated-legacy-receipt")
    if name in ("collection_membership", "planned_targets"):
        return []
    if name == "executable_admission":
        # Executable admission is bound to the projected content digest. A
        # migrated receipt has no recorded digest, so nothing was ever admitted
        # about its bytes: `pending` is the state that says exactly that.
        return "pending"
    if name == "upstream_state":
        return MIGRATED_UPSTREAM_STATE
    if name == "provider_availability":
        return {"state": UNKNOWN, "observed_at": None, "reason": "never observed"}
    return UNKNOWN


@dataclass(frozen=True)
class ForeignFieldView:
    """Every ADR-0011 foreign field of one receipt, unknown where absent.

    The view exists so that reading an unmigrated receipt is a *read*. A caller
    that had to migrate before it could read would have a mutation on the read
    path, and a read path that writes is a read path that fails during an outage
    -- which is when a receipt is most needed.
    """

    values: Mapping[str, Any]
    absent: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", dict(self.values))
        object.__setattr__(self, "absent", frozenset(self.absent))

    def __getitem__(self, name: str) -> Any:
        if name not in FOREIGN_RECEIPT_FIELDS:
            raise KeyError(f"{name!r} is not an ADR-0011 foreign receipt field")
        return self.values[name]

    def is_unknown(self, name: str) -> bool:
        """Whether this field is unresolved: absent from the receipt, or `unknown`."""
        if name not in FOREIGN_RECEIPT_FIELDS:
            raise KeyError(f"{name!r} is not an ADR-0011 foreign receipt field")
        return name in self.absent or self.values[name] == UNKNOWN

    def rights(self) -> Rights:
        """The four grants, all `unknown` when the receipt records none."""
        return Rights.from_dict(self.values["rights"])


def read_foreign_fields(entry: Mapping[str, Any]) -> ForeignFieldView:
    """Read one receipt's foreign fields without mutating it.

    Raises:
        ValueError: for anything that is not a receipt mapping, and for a
            structurally wrong recorded value. A damaged receipt is never read
            as an empty one: "no rights recorded" is the state that authorizes
            the least careful behavior downstream, so it must not be reachable
            by accident.
    """
    if not isinstance(entry, Mapping):
        raise ValueError("a receipt is a mapping; a malformed record is never read as one")
    values: dict[str, Any] = {}
    absent: list[str] = []
    for name in FOREIGN_RECEIPT_FIELDS:
        if name in entry and entry[name] is not None:
            values[name] = entry[name]
        else:
            values[name] = _field_default(name)
            absent.append(name)
    for name in ("rights", "projection_eligibility", "provider_availability"):
        if not isinstance(values[name], Mapping):
            raise ValueError(
                f"receipt field {name!r} must be a mapping; a damaged value is a "
                "refusal, never an empty default"
            )
    for name in ("collection_membership", "planned_targets"):
        if not isinstance(values[name], (list, tuple)):
            raise ValueError(f"receipt field {name!r} must be a list")
    return ForeignFieldView(values=values, absent=frozenset(absent))


def migrate_foreign_receipt_fields(entry: Mapping[str, Any]) -> dict[str, Any]:
    """One receipt with the foreign fields present, and nothing else changed.

    Purely additive and idempotent. A recorded value is never overwritten:
    replacing evidence with `unknown` is an honest-looking downgrade that erases
    the only proof an install ever had.
    """
    view = read_foreign_fields(entry)
    migrated = copy.deepcopy(dict(entry))
    for name in FOREIGN_RECEIPT_FIELDS:
        if name in view.absent:
            migrated[name] = copy.deepcopy(view[name])
    return migrated


# -- unresolvable receipts -----------------------------------------------------


@dataclass(frozen=True)
class LegacyResolution:
    """Whether one legacy receipt can be reconstructed, and what is missing."""

    state: str
    missing: tuple[str, ...]
    prune_blocked_reason: str | None
    #: Always true. A receipt is never discarded by this analysis, whatever it
    #: turns out to be missing. The field is recorded rather than implied so the
    #: guarantee is readable in the value an operator inspects.
    retained: bool = True

    def __post_init__(self) -> None:
        if self.state not in ("resolvable", "unresolvable"):
            raise ValueError(f"unknown legacy resolution state: {self.state!r}")
        object.__setattr__(self, "missing", tuple(self.missing))
        if self.retained is not True:
            raise ValueError("a legacy receipt is always retained")


#: A reconstructed content digest is a sha256 hex value, optionally prefixed.
#: Requiring the shape rather than "some non-empty text" is the repair for wave-1
#: F4: the migration writes the literal `unknown` into this very field, so a
#: non-blank check made migrating an unresolvable receipt turn it resolvable and
#: silently drop the retention and prune block that state exists to give it.
_DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST_RE.match(value.strip()))


def _has_content_digest(entry: Mapping[str, Any]) -> bool:
    if _is_digest(entry.get("normalized_content_digest")):
        return True
    if _is_digest(entry.get("checksum")):
        return True
    if _is_digest(entry.get("checksum_sha256")):
        return True
    if _is_digest(entry.get("content_sha256")):
        return True
    targets = entry.get("targets")
    if not isinstance(targets, (list, tuple)) or not targets:
        return False
    for target in targets:
        if not isinstance(target, Mapping):
            return False
        if target.get("kind") != "file":
            return False
        if not _is_digest(target.get("content_sha256")):
            return False
    return True


def legacy_receipt_resolution(entry: Mapping[str, Any]) -> LegacyResolution:
    """Classify one legacy receipt as reconstructible or `unresolvable`.

    The three facts are checked independently and all missing ones are reported,
    because an operator repairing a receipt needs the whole list, not the first
    failure.
    """
    if not isinstance(entry, Mapping):
        raise ValueError("a receipt is a mapping")
    missing: list[str] = []
    if _blank(entry.get("source")):
        missing.append("source")
    if not _has_content_digest(entry):
        missing.append("content-digest")
    if _blank(entry.get("catalog_identity")):
        missing.append("catalog-identity")
    if not missing:
        return LegacyResolution(
            state="resolvable", missing=(), prune_blocked_reason=None
        )
    return LegacyResolution(
        state="unresolvable",
        missing=tuple(missing),
        prune_blocked_reason=(
            "unresolvable-legacy-receipt: cannot reconstruct "
            f"{', '.join(missing)}. The receipt is retained and prune-blocked; "
            "unknown state is never converted into deletion authority"
        ),
    )


def prune_blocked(entry: Mapping[str, Any]) -> bool:
    """Whether a receipt records any reason deletion is blocked."""
    return not _blank(entry.get("prune_blocked_reason"))


@dataclass(frozen=True)
class LockMigrationOutcome:
    """Every receipt in, every receipt out, and which ones cannot be rebuilt."""

    entries: tuple[dict[str, Any], ...]
    resolutions: Mapping[str, LegacyResolution]
    unresolvable: tuple[str, ...]
    #: Structurally empty. A migration deletes no receipt, ever. Keeping the
    #: field means a future change that wanted deletion authority would have to
    #: change this type, in a diff a reviewer reads.
    deleted: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "unresolvable", tuple(self.unresolvable))
        object.__setattr__(self, "resolutions", dict(self.resolutions))
        if self.deleted:
            raise MigrationRefused(
                "a lock migration deletes no receipt; ADR-0010 Decision 6 and "
                "ADR-0011 `Migration` both restate it"
            )


def migrate_lock_receipts(
    entries: Sequence[Mapping[str, Any]]
) -> LockMigrationOutcome:
    """Migrate a whole lock scope's receipts additively, losing none of them.

    Raises:
        MigrationRefused: when two receipts share an id. Collapsing them into one
            record is a deletion wearing a dictionary's clothes, and the id is
            how every later operation addresses a receipt.
    """
    seen: list[str] = []
    migrated: list[dict[str, Any]] = []
    resolutions: dict[str, LegacyResolution] = {}
    unresolvable: list[str] = []

    for entry in entries:
        if not isinstance(entry, Mapping):
            raise MigrationRefused("every lock receipt must be a mapping")
        identity = entry.get("id")
        if _blank(identity):
            raise MigrationRefused("every lock receipt must carry an id")
        if identity in seen:
            raise MigrationRefused(
                f"two receipts share the id {identity!r}; a migration that merged "
                "them would delete one of them silently"
            )
        seen.append(str(identity))

        record = migrate_foreign_receipt_fields(entry)
        resolution = legacy_receipt_resolution(entry)
        resolutions[str(identity)] = resolution
        if resolution.state == "unresolvable":
            unresolvable.append(str(identity))
            if not prune_blocked(record):
                record["prune_blocked_reason"] = resolution.prune_blocked_reason
        migrated.append(record)

    return LockMigrationOutcome(
        entries=tuple(migrated),
        resolutions=resolutions,
        unresolvable=tuple(unresolvable),
    )


# -- content census ------------------------------------------------------------


def census(roots: Sequence[Path]) -> dict[str, str]:
    """A content fingerprint of every path under `roots`.

    Files are hashed, directories are marked, and a symlink **found during the
    walk** is recorded by its literal target rather than followed. Following
    would census a destination twice and would report a re-pointed link as
    unchanged whenever both destinations happened to match -- and most of the
    legacy projections ADR-0011 inventories are symlinks.

    A symlink named as a **root** is the opposite case and is followed: naming a
    root means "inventory this tree". Recording only the link meant a witness
    root inventoried nothing at all, so a deletion beneath it read as no change
    (wave-1 F3). The paths are recorded under the root the caller named, so the
    census answers about the tree the caller asked about.
    """
    recorded: dict[str, str] = {}
    for root in roots:
        named = Path(root)
        # Resolve only the root itself, so `roots=[link-to-tree]` inventories
        # the tree. Every path inside is still walked without following links.
        start = Path(os.path.realpath(named)) if named.is_symlink() else named
        _census_into(start, named, recorded)
    return recorded


def _census_into(path: Path, label: Path, recorded: dict[str, str]) -> None:
    if path.is_symlink():
        recorded[str(label)] = f"symlink:{os.readlink(path)}"
        return
    if not path.exists():
        return
    if path.is_dir():
        recorded[str(label)] = "directory"
        with os.scandir(path) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                _census_into(Path(entry.path), label / entry.name, recorded)
        return
    recorded[str(label)] = hashlib.sha256(path.read_bytes()).hexdigest()


# -- legacy cache objects ------------------------------------------------------


@dataclass(frozen=True)
class LegacyCacheObject:
    """One directory in the pre-ADR-0011 Layer-B layout."""

    path: Path
    library_type: str
    marketplace: str
    name: str
    revision_tag: str
    #: Always `None`. A legacy object records neither of these, which is the
    #: whole reason its tuple key cannot be computed from what is on disk. They
    #: are fields rather than a docstring so a reader of the value sees the gap.
    recorded_normalized_digest: None = None
    recorded_transformation_version: None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))

    def is_revisionless(self) -> bool:
        """Whether the legacy key degraded this object's version to a tag."""
        return self.revision_tag in _REVISIONLESS_TAGS


def scan_legacy_cache(cache_root: Path) -> tuple[LegacyCacheObject, ...]:
    """Every legacy cache object under a Layer-B root, in a stable order.

    `@local` is read as a tag, never as a revision. Recording it as a revision
    is exactly the identity the tuple key exists to stop fabricating.
    """
    root = Path(cache_root)
    found: list[LegacyCacheObject] = []
    if not root.is_dir():
        return ()
    for type_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
        library_type = type_dir.name[:-1] if type_dir.name.endswith("s") else type_dir.name
        for marketplace_dir in sorted(
            p for p in type_dir.iterdir() if p.is_dir() and not p.is_symlink()
        ):
            for object_dir in sorted(
                p for p in marketplace_dir.iterdir() if p.is_dir() and not p.is_symlink()
            ):
                matched = _LEGACY_OBJECT_RE.match(object_dir.name)
                if matched is None:
                    continue
                found.append(
                    LegacyCacheObject(
                        path=object_dir,
                        library_type=library_type,
                        marketplace=marketplace_dir.name,
                        name=matched.group("name"),
                        revision_tag=matched.group("tag"),
                    )
                )
    return tuple(found)


@dataclass(frozen=True)
class RematerializationRequest:
    """One legacy object owed an honest identity, and the terms of getting it."""

    legacy_path: str
    library_type: str
    marketplace: str
    name: str
    revision_tag: str
    reason: str
    #: The accepted cost, stated rather than discovered. Re-materialization
    #: fetches from the provider, so the first post-migration operation may be
    #: slower and needs the provider to be reachable.
    requires_provider: bool = True
    #: The legacy object stays usable in the meantime. There is no interval in
    #: which the old bytes are gone and the new ones do not exist yet.
    usable_meanwhile: bool = True
    #: Always `None`. The tuple key needs a normalized content digest and a
    #: transformation version, and a legacy object has neither, so the key
    #: cannot exist before the content is retrieved again.
    new_cache_key: None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "legacy_path": self.legacy_path,
            "library_type": self.library_type,
            "marketplace": self.marketplace,
            "name": self.name,
            "revision_tag": self.revision_tag,
            "reason": self.reason,
            "requires_provider": self.requires_provider,
            "usable_meanwhile": self.usable_meanwhile,
            "new_cache_key": self.new_cache_key,
        }


_REKEY_REASON = (
    "the legacy key records neither a normalized content digest nor a "
    "transformation version, so the tuple key cannot be derived from this "
    "directory; the identity is recomputed by retrieving the content again"
)


@dataclass(frozen=True)
class CacheMigrationPlan:
    """What a cache migration will do. It renames nothing and deletes nothing."""

    requests: tuple[RematerializationRequest, ...]
    renames: tuple[str, ...] = ()
    deletions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "requests", tuple(self.requests))
        if self.renames or self.deletions:
            raise MigrationRefused(
                "a cache migration renames nothing and deletes nothing: a rename "
                "into the tuple key space would mint a digest identity the object "
                "never had"
            )


def plan_cache_migration(cache_root: Path) -> CacheMigrationPlan:
    """Plan the re-materialization of every legacy object under a cache root."""
    return CacheMigrationPlan(
        requests=tuple(
            RematerializationRequest(
                legacy_path=str(item.path),
                library_type=item.library_type,
                marketplace=item.marketplace,
                name=item.name,
                revision_tag=item.revision_tag,
                reason=_REKEY_REASON,
            )
            for item in scan_legacy_cache(cache_root)
        )
    )


@dataclass(frozen=True)
class CacheMigrationOutcome:
    """What one migration run recomputed, what it still owes, and what it kept."""

    pending: tuple[RematerializationRequest, ...]
    rematerialized: tuple[str, ...]
    retained_legacy_paths: tuple[str, ...]
    renamed: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "pending", tuple(self.pending))
        object.__setattr__(self, "rematerialized", tuple(self.rematerialized))
        object.__setattr__(self, "retained_legacy_paths", tuple(self.retained_legacy_paths))
        if self.renamed or self.deleted:
            raise MigrationRefused("a cache migration renames nothing and deletes nothing")


def apply_cache_migration(
    plan: CacheMigrationPlan,
    *,
    state_path: Path,
    observed_at: str,
) -> CacheMigrationOutcome:
    """Record what every legacy object is owed. Touch nothing else.

    **This function takes no callback**, and that is the repair for a real
    defect rather than a simplification. The first version accepted a
    `rematerialize` callable, ran it, and then censused the witness roots to
    prove nothing was lost. Review supplied a callable that deleted a witnessed
    file: the census found it and the run refused -- with the file already gone,
    because a refusal is not a rollback. A guarantee enforced by inspection
    *after* an arbitrary caller has run is not a guarantee, it is a report.

    Migration therefore plans and records intent, and nothing more. The actual
    re-materialization is a separate act, performed by
    `rematerialize_legacy_object` through an `ObjectStore` that has no deletion
    path at all by construction. There is no window in which this function hands
    control to something that could destroy the thing it is protecting.

    The recorded intent is durable so a later `sync` or repair knows what is
    owed without re-deriving it from a directory layout that will disappear.
    """
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise ValueError("a migration run records the time it observed the cache")

    outcome = CacheMigrationOutcome(
        pending=tuple(plan.requests),
        rematerialized=(),
        retained_legacy_paths=tuple(request.legacy_path for request in plan.requests),
    )
    atomic_write_text(
        Path(state_path),
        json.dumps(
            {
                "schema": MIGRATION_STATE_SCHEMA,
                "observed_at": observed_at,
                "pending": [request.to_dict() for request in outcome.pending],
                "rematerialized": list(outcome.rematerialized),
                "retained_legacy_paths": list(outcome.retained_legacy_paths),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return outcome


def rematerialize_legacy_object(
    request: RematerializationRequest,
    *,
    cache_key: Any,
    content: Mapping[str, bytes],
    object_store: Any,
    observed_at: str,
) -> str:
    """Give one legacy object an honest identity, leaving it exactly where it is.

    The content is written into the content-addressed object store under a key
    the caller computed from the bytes it retrieved. The store has no deletion
    API, so this path cannot destroy anything even in principle -- which is the
    property that lets the legacy directory stay in place and stay usable while
    its replacement is built beside it.

    Args:
        cache_key: The tuple key, computed from the **retrieved** bytes. A legacy
            object records no normalized digest and no transformation version, so
            this key cannot be derived from what is on disk; deriving it from the
            path is the rename this whole section refuses.
        content: The retrieved bytes. Whatever produced them is the caller's
            business; nothing here reads the legacy directory as a source.

    Returns:
        The recomputed cache key digest.

    Raises:
        MigrationRefused: when the legacy object is not byte-identical
            afterwards. This is a verification of an invariant this function
            cannot violate on its own, not a guard around an untrusted callback:
            it catches a store implementation or a concurrent process that
            damaged the retained copy.
    """
    from .foreign_cache import ObjectStore

    if not isinstance(object_store, ObjectStore):
        # The store is the one collaborator this function calls, so an untyped
        # parameter here would reintroduce the arbitrary-callback boundary the
        # F3 repair removed from `apply_cache_migration` -- just wearing a
        # method name instead of a lambda. `ObjectStore` has no deletion path by
        # construction, and requiring the type is what makes that fact load
        # bearing rather than conventional.
        raise MigrationRefused(
            "re-materialization writes through the content-addressed ObjectStore, "
            "which has no deletion path by construction. A caller-supplied object "
            "with a `materialize` method is an arbitrary mutation hook, which is "
            "exactly what this path removed"
        )

    legacy = Path(request.legacy_path)
    before = census([legacy])
    object_store.materialize(cache_key, dict(content), created_at=observed_at)
    after = census([legacy])
    if after != before:
        changed = sorted(
            path for path, fingerprint in before.items() if after.get(path) != fingerprint
        ) or sorted(set(after) - set(before))
        raise MigrationRefused(
            f"the retained legacy object at {legacy} is no longer byte-identical "
            f"after re-materialization: {', '.join(changed)}. A legacy object is "
            "retained and usable until its replacement exists; nothing in this "
            "path may alter it"
        )
    return cache_key.digest()


__all__ = [
    "FOREIGN_RECEIPT_FIELDS",
    "MIGRATED_UPSTREAM_STATE",
    "MIGRATION_STATE_SCHEMA",
    "RECONSTRUCTION_FACTS",
    "UNKNOWN",
    "UNRESOLVED_RIGHTS",
    "CacheMigrationOutcome",
    "CacheMigrationPlan",
    "ForeignFieldView",
    "LegacyCacheObject",
    "LegacyResolution",
    "LockMigrationOutcome",
    "MigrationRefused",
    "RematerializationRequest",
    "apply_cache_migration",
    "census",
    "legacy_receipt_resolution",
    "migrate_foreign_receipt_fields",
    "migrate_lock_receipts",
    "plan_cache_migration",
    "rematerialize_legacy_object",
    "prune_blocked",
    "read_foreign_fields",
    "scan_legacy_cache",
]
