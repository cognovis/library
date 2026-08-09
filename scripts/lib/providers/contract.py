"""The source-provider capability contract (ADR-0011 `Adapter capabilities`).

There is no universal scanner. A provider adapter implements this contract; a
consumer asks `capabilities()` and degrades deterministically. It never probes
by catching exceptions and never branches on a provider's name or kind.

| Capability | Required | Absence behavior |
|---|---|---|
| `identity` | YES | - |
| `capabilities` | YES | - |
| `enumerate` | YES | - |
| `fetch` | YES | - |
| `auth_requirements` | YES | - |
| `availability` | YES | - |
| `describe` | NO | Fall back to `fetch` plus classification, recorded as a costlier path |
| `revision_of` | NO | The provider is revisionless; `upstream_revision` is `null` |
| `verify` | NO | The Library normalized digest is the only integrity proof |
| `rights_evidence` | NO | Rights stay `unknown` until a human records evidence |
| `item_rights_evidence` | NO | The provider is uniform; one rights answer covers every item |
| `member_manifest` | NO | Completeness rests on the adapter's declaration, which the install records as its weakest evidence |

`describe` is **optional and declared**, not "mandatory with a default".
ADR-0011's first table marked it `Required: YES` while also defining behavior
for its absence; both readings were defensible and the ambiguity was routed to
this slice (`CL-2p73` round-2 advisory A2). It is resolved here in favor of the
declared-optional reading, because AC2 requires absence behavior to be driven by
`capabilities()`, and a capability that is always present cannot be. A provider
that cannot cheaply describe an item is a costlier provider, never an excluded
one. The ADR table is amended to match.

`enumerate` is the required floor. A provider that cannot list without a local
checkout is not a provider under this contract; it is a local catalog, which the
platform already supports.

`describe` answers the Library **type** axis without content. It does not
answer every classification question: `classification.skill_class` is defined by
ADR-0011 as an upstream frontmatter property, which lives in content. A
description produced without content therefore carries no `skill_class` key at
all, rather than a third state value the ADR does not admit. Deriving it is an
explicit, costed content inspection — see `normalize.normalize_inventory`.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

REQUIRED_CAPABILITIES = frozenset(
    {
        "identity",
        "capabilities",
        "enumerate",
        "fetch",
        "auth_requirements",
        "availability",
    }
)

OPTIONAL_CAPABILITIES = frozenset(
    {
        "describe",
        "revision_of",
        "verify",
        "rights_evidence",
        "item_rights_evidence",
        "member_manifest",
    }
)

CAPABILITIES = REQUIRED_CAPABILITIES | OPTIONAL_CAPABILITIES

AVAILABILITY_STATES = ("available", "degraded", "unavailable")


class CapabilityNotDeclared(RuntimeError):
    """Raised when a caller invokes a capability the adapter does not declare.

    This is a programming error in the caller, never a control-flow signal.
    A consumer that reads `capabilities()` first can never see it, which is
    exactly why the base class raises instead of returning a neutral value:
    a silent `None` would let a consumer skip the declaration check and still
    appear to work.
    """


@dataclass(frozen=True)
class ProviderItem:
    """One item as the provider itself lists it, before any Library naming.

    `content_hint` is a provider-native pointer the adapter may use to fetch or
    classify the item (a blob path, an index key). It is opaque to consumers.
    """

    upstream_id: str
    upstream_name: str
    collection_membership: tuple[str, ...] = ()
    content_hint: str | None = None

    def __post_init__(self) -> None:
        for name in ("upstream_id", "upstream_name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ProviderItem.{name} is required")
        object.__setattr__(
            self, "collection_membership", tuple(self.collection_membership)
        )


@dataclass(frozen=True)
class ItemDescription:
    """Classification metadata for one item.

    `content_identity` is the provider's own identity for the described bytes
    (for example a Git blob sha) when it has one. It is not a Library digest.
    """

    upstream_id: str
    library_type: str
    classification: Mapping[str, str]
    runtime_compatibility: tuple[str, ...] = ("unknown",)
    content_identity: str | None = None

    def __post_init__(self) -> None:
        for name in ("upstream_id", "library_type"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ItemDescription.{name} is required")
        object.__setattr__(self, "classification", dict(self.classification))
        object.__setattr__(
            self, "runtime_compatibility", tuple(self.runtime_compatibility)
        )
        if not self.runtime_compatibility:
            raise ValueError("ItemDescription.runtime_compatibility must be non-empty")


@dataclass(frozen=True)
class FetchedFile:
    """One file of an item's content, at its item-relative path."""

    path: str
    content: bytes
    upstream_content_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("FetchedFile.path is required")
        if self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError(f"FetchedFile.path must be item-relative: {self.path!r}")
        if not isinstance(self.content, (bytes, bytearray)):
            raise ValueError("FetchedFile.content must be bytes")
        object.__setattr__(self, "content", bytes(self.content))


@dataclass(frozen=True)
class FetchedItem:
    """**Complete** immutable content for one item, at a pinned revision.

    An item is frequently a directory, not a file: the reference provider's
    `implement` skill ships `SKILL.md` **and** `agents/openai.yaml`. Returning
    only the marker file would silently drop the rest, and a cache built on that
    would materialize an incomplete item while reporting success. This type
    makes "complete" structural rather than a promise in a docstring.

    `primary_path` names the marker file classification is derived from.
    """

    upstream_id: str
    revision: str | None
    files: tuple[FetchedFile, ...]
    primary_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.upstream_id, str) or not self.upstream_id.strip():
            raise ValueError("FetchedItem.upstream_id is required")
        object.__setattr__(self, "files", tuple(self.files))
        if not self.files:
            raise ValueError("FetchedItem must carry at least one file")
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("FetchedItem file paths must be unique")
        if self.primary_path not in paths:
            raise ValueError(
                f"FetchedItem.primary_path {self.primary_path!r} is not among its files"
            )

    @property
    def primary(self) -> bytes:
        """Bytes of the marker file classification is derived from."""
        return next(item.content for item in self.files if item.path == self.primary_path)

    def paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files)


@dataclass(frozen=True)
class AuthRequirement:
    """A named credential *reference* and its scope. Never a value.

    ADR-0011 `Credential isolation`: no token, cookie, header, or private
    transport configuration is ever carried by this contract.
    """

    reference: str
    scope: str = ""
    required: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError("AuthRequirement.reference is required")


@dataclass(frozen=True)
class Availability:
    """Provider availability with the timestamp of the observation."""

    state: str
    observed_at: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in AVAILABILITY_STATES:
            raise ValueError(
                f"Availability.state must be one of {list(AVAILABILITY_STATES)}"
            )
        if not isinstance(self.observed_at, str) or not self.observed_at.strip():
            raise ValueError("Availability.observed_at is required")


@dataclass(frozen=True)
class RightsEvidence:
    """A machine-readable pointer to the provider's licensing evidence source.

    `located` is False when the provider publishes an evidence mechanism but this
    item or repository has none. That is a different fact from an adapter that
    does not declare `rights_evidence` at all, and the two must not collapse:
    the first says "looked, found nothing", the second says "cannot look".
    """

    located: bool
    source: str | None = None
    detail: str | None = None


class SourceProvider(abc.ABC):
    """The capability contract every source provider adapter implements."""

    # -- Required capabilities ------------------------------------------------

    @abc.abstractmethod
    def identity(self) -> str:
        """Canonical, stable provider identity. Display aliases resolve to it."""

    @abc.abstractmethod
    def capabilities(self) -> frozenset[str]:
        """The declared capability set, including which optional ones are present."""

    @abc.abstractmethod
    def enumerate(self, selector: Any = None) -> Sequence[ProviderItem]:
        """Remote-only listing of items. No local checkout, ever."""

    @abc.abstractmethod
    def fetch(self, upstream_id: str, revision: str | None = None) -> FetchedItem:
        """Complete immutable content for one item, pinned to `revision`.

        Complete means every file the item consists of, not just its marker
        file. A caller that passes `revision` gets that revision or an error;
        it never silently gets a different one.
        """

    @abc.abstractmethod
    def auth_requirements(self) -> Sequence[AuthRequirement]:
        """Named credential references and scopes. Never values."""

    @abc.abstractmethod
    def availability(self) -> Availability:
        """Current provider availability with its observation timestamp."""

    # -- Optional capabilities ------------------------------------------------

    def describe(self, upstream_id: str) -> ItemDescription:
        """Item metadata sufficient for classification without fetching content."""
        raise CapabilityNotDeclared(f"{type(self).__name__} does not declare describe")

    def revision_of(self, upstream_id: str) -> str:
        """Immutable upstream revision identity."""
        raise CapabilityNotDeclared(
            f"{type(self).__name__} does not declare revision_of"
        )

    def verify(self, content: bytes, expected: str) -> bool:
        """Provider-native integrity proof."""
        raise CapabilityNotDeclared(f"{type(self).__name__} does not declare verify")

    def rights_evidence(self) -> RightsEvidence:
        """Pointer to the provider's licensing evidence source, if it publishes one."""
        raise CapabilityNotDeclared(
            f"{type(self).__name__} does not declare rights_evidence"
        )

    def member_manifest(
        self, upstream_id: str, revision: str | None = None
    ) -> Sequence[str]:
        """The item-relative paths this item consists of, listed from the source.

        This is what lets an install state `CompletenessEvidence.from_manifest`
        rather than the adapter's own word. The two are not the same claim: a
        manifest read from the source is an independent list to check a retrieval
        against, while an adapter declaration says only "I believe I returned
        everything" -- and review demonstrated an adapter returning one file of a
        two-file item and having it pinned, cached, receipted, and projected.

        An adapter that does not declare it is not a lesser adapter; it is one
        whose source cannot list an item's members, and the install records that
        weaker evidence explicitly instead of letting it be the quiet default.
        """
        raise CapabilityNotDeclared(
            f"{type(self).__name__} does not declare member_manifest"
        )

    def item_rights_evidence(self, upstream_id: str) -> RightsEvidence:
        """Licensing evidence for **one item**, when the provider is not uniform.

        A single repository publishes one licence for everything it contains, so
        `rights_evidence` answers for the whole provider. An organization-level
        provider does not: ADR-0011 records the `disler` grant as per repository,
        with `live-bench` carrying no observed `LICENSE` at all. Without this
        capability the only way to express that is a provider-wide answer, which
        would let one repository's grant stand in for a sibling that has none --
        exactly the inheritance the ADR calls out.

        Declaring it is what makes a consumer ask per item. An adapter that does
        not declare it is stating that its provider is uniform, and the consumer
        uses `rights_evidence` unchanged.
        """
        raise CapabilityNotDeclared(
            f"{type(self).__name__} does not declare item_rights_evidence"
        )


def validate_capability_declaration(provider: SourceProvider) -> frozenset[str]:
    """Check that an adapter's declaration matches what it actually implements.

    A declaration is the whole basis on which consumers degrade, so a lying
    declaration is worse than a missing capability: the consumer takes the
    capable path and fails at the call. This catches it at registration time.

    Returns:
        The declared capability set.

    Raises:
        ValueError: when the declaration is not a valid capability set, omits a
            required capability, or declares an optional capability the adapter
            has not overridden.
    """
    declared = provider.capabilities()
    if not isinstance(declared, (set, frozenset)):
        raise ValueError("capabilities() must return a set of capability names")
    declared = frozenset(declared)

    unknown = sorted(declared - CAPABILITIES)
    if unknown:
        raise ValueError(f"unknown declared capabilities: {unknown}")

    missing = sorted(REQUIRED_CAPABILITIES - declared)
    if missing:
        raise ValueError(f"required capabilities are not declared: {missing}")

    unimplemented = sorted(
        name
        for name in declared & OPTIONAL_CAPABILITIES
        if getattr(type(provider), name) is getattr(SourceProvider, name)
    )
    if unimplemented:
        raise ValueError(
            f"capabilities declared but not implemented: {unimplemented}"
        )
    return declared
