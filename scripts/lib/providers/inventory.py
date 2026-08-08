"""Normalized inventory: the item schema ADR-0011 fixes, and its identity.

Normalization preserves upstream identity and adds Library-owned
classification. It never rewrites upstream identity to make it fit.

Slice ownership of the ADR-0011 schema table, stated explicitly so an absent
derivation is never mistaken for a missing field:

| Field | Populated by |
|---|---|
| `provider_identity`, `upstream_id`, `upstream_name`, `collection_membership` | slice 1, from `enumerate()` |
| `upstream_revision` | slice 1, from `revision_of()` when declared; `None` otherwise |
| `library_type`, `library_name`, `classification`, `runtime_compatibility` | slice 1, from `describe()` or the fetch-then-classify path |
| `rights` | slice 1 carries the recorded grants; enforcement is slice 2 (`CL-n7ex`) |
| `provider_availability` | slice 1, from `availability()` with its observation timestamp |
| `admission_state`, `block_reasons`, `executable_admission`, `trust_state`, `projection_eligibility` | slice 2 (`CL-n7ex`) derives them; slice 1 records the conservative default |
| `cache_state` | slice 3 (`CL-y5z4`) derives it; slice 1 records `absent` |

The defaults are conservative on purpose: slice 1 cannot certify that anything
is installable, trusted, cached, or projectable, so it never claims it.

One reading is recorded rather than assumed. The ADR marks `block_reasons`
"YES when not `installable`". A `blocked` item without a reason is
unqueryable, so that is enforced here. A `discoverable` item is *not* given a
synthetic reason: the admission evaluation that could produce one is slice 2,
and inventing `license-unknown` for an item nobody has evaluated would put a
false evidence-bearing reason into a closed vocabulary whose entries each
"carry the evidence that produced it". Empty is the honest value until slice 2
evaluates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, Sequence

#: `<provider-identity>#<upstream-id>`; see ADR-0011 `Consumers of provider identity`.
QUALIFIED_SEPARATOR = "#"

ADMISSION_STATES = ("discoverable", "installable", "blocked")
EXECUTABLE_ADMISSION_STATES = ("inert", "admitted", "pending", "refused")
TRUST_STATES = ("first-party", "reviewed", "unreviewed")
CACHE_STATES = ("absent", "materialized", "verified")
AVAILABILITY_STATES = ("available", "degraded", "unavailable")
RIGHTS_STATES = ("granted", "denied", "unknown")
PROJECTION_TARGETS = ("project_committed", "machine_local")
PROJECTION_STATES = ("allowed", "blocked", "operator-opt-in-required")

#: The closed, ordered block-reason vocabulary of ADR-0011 `Typed block reasons`.
BLOCK_REASONS = (
    "license-unknown",
    "license-denied",
    "redistribution-blocked",
    "authentication-required",
    "incompatible-runtime",
    "executable-admission-pending",
    "untrusted-source",
    "content-unavailable",
)


def _one_of(value: str, allowed: Sequence[str], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} must be one of {list(allowed)}, got {value!r}")
    return value


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value


def qualified_identity(provider_identity: str, upstream_id: str) -> str:
    """Compose the canonical qualified identity for one item.

    The provider identity may not contain the separator; the upstream id may,
    because it is provider-native and opaque to the Library. Parsing therefore
    splits on the *first* separator, which is what makes the round trip lossless.
    """
    _required_text(provider_identity, "provider_identity")
    _required_text(upstream_id, "upstream_id")
    if QUALIFIED_SEPARATOR in provider_identity:
        raise ValueError(
            "provider_identity must not contain "
            f"{QUALIFIED_SEPARATOR!r}: {provider_identity!r}"
        )
    return f"{provider_identity}{QUALIFIED_SEPARATOR}{upstream_id}"


def parse_qualified_identity(value: str) -> tuple[str, str]:
    """Split a qualified identity back into provider identity and upstream id."""
    _required_text(value, "qualified identity")
    provider_identity, separator, upstream_id = value.partition(QUALIFIED_SEPARATOR)
    if not separator or not provider_identity or not upstream_id:
        raise ValueError(
            f"not a qualified identity <provider>{QUALIFIED_SEPARATOR}<upstream-id>: {value!r}"
        )
    return provider_identity, upstream_id


@dataclass(frozen=True)
class Rights:
    """The four independent grants of ADR-0011 `Distribution Rights`.

    Slice 1 records them. Slice 2 (`CL-n7ex`) composes them into projection
    decisions; nothing here enforces anything.
    """

    fetch_authorization: str = "unknown"
    install_rights: str = "unknown"
    redistribution_rights: str = "unknown"
    derivative_rights: str = "unknown"
    evidence_source: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "fetch_authorization",
            "install_rights",
            "redistribution_rights",
            "derivative_rights",
        ):
            _one_of(getattr(self, name), RIGHTS_STATES, f"rights.{name}")
        if self.evidence_source is not None and not str(self.evidence_source).strip():
            raise ValueError("rights.evidence_source must be text or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetch_authorization": self.fetch_authorization,
            "install_rights": self.install_rights,
            "redistribution_rights": self.redistribution_rights,
            "derivative_rights": self.derivative_rights,
            "evidence_source": self.evidence_source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Rights":
        known = {
            "fetch_authorization",
            "install_rights",
            "redistribution_rights",
            "derivative_rights",
            "evidence_source",
        }
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown rights fields: {unknown}")
        return cls(**{key: data[key] for key in known if key in data})


@dataclass(frozen=True)
class ProviderAvailability:
    """`availability()` as observed, with the timestamp of the observation.

    ADR-0011 `Freshness and provider availability`: an inventory entry never
    presents a cached observation as a current one.
    """

    state: str
    observed_at: str
    reason: str | None = None

    def __post_init__(self) -> None:
        _one_of(self.state, AVAILABILITY_STATES, "provider_availability.state")
        _required_text(self.observed_at, "provider_availability.observed_at")
        if self.reason is not None and not str(self.reason).strip():
            raise ValueError("provider_availability.reason must be text or None")

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "observed_at": self.observed_at, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderAvailability":
        unknown = sorted(set(data) - {"state", "observed_at", "reason"})
        if unknown:
            raise ValueError(f"unknown provider_availability fields: {unknown}")
        return cls(
            state=data["state"],
            observed_at=data["observed_at"],
            reason=data.get("reason"),
        )


def _default_projection_eligibility() -> dict[str, str]:
    """Blocked on both targets until slice 2 derives the real eligibility."""
    return {target: "blocked" for target in PROJECTION_TARGETS}


@dataclass(frozen=True)
class NormalizedItem:
    """One item of normalized inventory, per the ADR-0011 schema table."""

    provider_identity: str
    upstream_id: str
    upstream_name: str
    collection_membership: tuple[str, ...]
    upstream_revision: str | None
    library_type: str
    library_name: str
    classification: Mapping[str, str]
    runtime_compatibility: tuple[str, ...]
    rights: Rights
    provider_availability: ProviderAvailability
    admission_state: str = "discoverable"
    block_reasons: tuple[str, ...] = ()
    executable_admission: str = "inert"
    trust_state: str = "unreviewed"
    cache_state: str = "absent"
    projection_eligibility: Mapping[str, str] = field(
        default_factory=_default_projection_eligibility
    )

    def __post_init__(self) -> None:
        _required_text(self.provider_identity, "provider_identity")
        _required_text(self.upstream_id, "upstream_id")
        _required_text(self.upstream_name, "upstream_name")
        _required_text(self.library_type, "library_type")
        _required_text(self.library_name, "library_name")
        if QUALIFIED_SEPARATOR in self.provider_identity:
            raise ValueError(
                f"provider_identity must not contain {QUALIFIED_SEPARATOR!r}"
            )
        if self.upstream_revision is not None:
            _required_text(self.upstream_revision, "upstream_revision")

        object.__setattr__(self, "collection_membership", tuple(self.collection_membership))
        object.__setattr__(self, "runtime_compatibility", tuple(self.runtime_compatibility))
        object.__setattr__(self, "block_reasons", tuple(self.block_reasons))
        object.__setattr__(self, "classification", dict(self.classification))
        object.__setattr__(self, "projection_eligibility", dict(self.projection_eligibility))

        if not self.runtime_compatibility:
            raise ValueError("runtime_compatibility must declare at least one value")
        if not isinstance(self.rights, Rights):
            raise ValueError("rights must be a Rights value")
        if not isinstance(self.provider_availability, ProviderAvailability):
            raise ValueError("provider_availability must be a ProviderAvailability value")

        _one_of(self.admission_state, ADMISSION_STATES, "admission_state")
        _one_of(
            self.executable_admission, EXECUTABLE_ADMISSION_STATES, "executable_admission"
        )
        _one_of(self.trust_state, TRUST_STATES, "trust_state")
        _one_of(self.cache_state, CACHE_STATES, "cache_state")
        for reason in self.block_reasons:
            _one_of(reason, BLOCK_REASONS, "block_reasons entry")
        if self.admission_state == "blocked" and not self.block_reasons:
            raise ValueError("a blocked item must record at least one block reason")
        if sorted(self.projection_eligibility) != sorted(PROJECTION_TARGETS):
            raise ValueError(
                f"projection_eligibility must cover exactly {list(PROJECTION_TARGETS)}"
            )
        for target, state in self.projection_eligibility.items():
            _one_of(state, PROJECTION_STATES, f"projection_eligibility.{target}")

    def qualified_identity(self) -> str:
        """This item's canonical `<provider-identity>#<upstream-id>`."""
        return qualified_identity(self.provider_identity, self.upstream_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_identity": self.provider_identity,
            "upstream_id": self.upstream_id,
            "upstream_name": self.upstream_name,
            "collection_membership": list(self.collection_membership),
            "upstream_revision": self.upstream_revision,
            "library_type": self.library_type,
            "library_name": self.library_name,
            "classification": dict(self.classification),
            "runtime_compatibility": list(self.runtime_compatibility),
            "rights": self.rights.to_dict(),
            "provider_availability": self.provider_availability.to_dict(),
            "admission_state": self.admission_state,
            "block_reasons": list(self.block_reasons),
            "executable_admission": self.executable_admission,
            "trust_state": self.trust_state,
            "cache_state": self.cache_state,
            "projection_eligibility": dict(self.projection_eligibility),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NormalizedItem":
        payload = dict(data)
        known = {
            "provider_identity",
            "upstream_id",
            "upstream_name",
            "collection_membership",
            "upstream_revision",
            "library_type",
            "library_name",
            "classification",
            "runtime_compatibility",
            "rights",
            "provider_availability",
            "admission_state",
            "block_reasons",
            "executable_admission",
            "trust_state",
            "cache_state",
            "projection_eligibility",
        }
        unknown = sorted(set(payload) - known)
        if unknown:
            raise ValueError(f"unknown normalized item fields: {unknown}")
        missing = sorted(known - set(payload))
        if missing:
            raise ValueError(f"missing normalized item fields: {missing}")
        payload["collection_membership"] = tuple(payload["collection_membership"])
        payload["runtime_compatibility"] = tuple(payload["runtime_compatibility"])
        payload["block_reasons"] = tuple(payload["block_reasons"])
        payload["rights"] = Rights.from_dict(payload["rights"])
        payload["provider_availability"] = ProviderAvailability.from_dict(
            payload["provider_availability"]
        )
        return cls(**payload)


class NormalizedInventory:
    """An index of normalized items keyed by canonical qualified identity."""

    def __init__(self, items: Iterable[NormalizedItem]) -> None:
        index: dict[str, NormalizedItem] = {}
        ordered: list[NormalizedItem] = []
        for item in items:
            identity = item.qualified_identity()
            if identity in index:
                raise ValueError(f"duplicate qualified identity: {identity}")
            index[identity] = item
            ordered.append(item)
        self._index = index
        self._items = tuple(ordered)

    def resolve(self, identity: str) -> NormalizedItem:
        """Return the item for a qualified identity.

        Raises:
            KeyError: when no item carries that identity.
            ValueError: when the identity is not well formed.
        """
        parse_qualified_identity(identity)
        try:
            return self._index[identity]
        except KeyError as exc:
            raise KeyError(f"no inventory item for qualified identity: {identity}") from exc

    def identities(self) -> tuple[str, ...]:
        return tuple(self._index)

    def __iter__(self) -> Iterator[NormalizedItem]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, identity: object) -> bool:
        return identity in self._index
