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
    def fetch(self, upstream_id: str, revision: str | None = None) -> bytes:
        """Complete immutable content bytes for one item."""

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
