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
| `rights` | slice 1 carries the recorded grants; slice 2 (`CL-n7ex`) adds per-grant evidence and enforcement |
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

Slice 2 (`CL-n7ex`) makes two schema fields carry what the ADR always said they
carry, rather than adding a parallel record beside them:

- `block_reasons` holds ordered `BlockReason` values, not bare strings. The ADR
  schema table says "Ordered, typed" and `Typed block reasons` says each reason
  "carries the evidence that produced it". A reason whose evidence lives in a
  separate transient object is not queryable after the fact, which is precisely
  what `blocked` being "a first-class, queryable state" rules out.
- `Rights` records evidence **per grant**. The four grants are independent, and
  the ADR requires each to resolve "with a named evidence source"; one shared
  string cannot say that a fetch grant rests on a reachable subscriber endpoint
  while a redistribution grant rests on nothing at all. The shared
  `evidence_source` is retained as the fallback for grants with no specific
  evidence, so slice-1 records stay readable unchanged.
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

#: Minimum length for a block reason's evidence. A floor against placeholders.
MIN_EVIDENCE_LENGTH = 16

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


#: The four grants of ADR-0011 `Distribution Rights`, in the ADR's own order.
RIGHTS_GRANTS = (
    "fetch_authorization",
    "install_rights",
    "redistribution_rights",
    "derivative_rights",
)


@dataclass(frozen=True)
class RightsGrant:
    """One grant, resolved, with the evidence source that resolved it.

    This is the unit ADR-0011 describes: "Four grants are recorded
    independently, each with a named evidence source". `evidence_source` is
    `None` only when nothing at all has been recorded -- which is itself the
    evidence for `unknown`, and is reported as such rather than hidden.
    """

    name: str
    state: str
    evidence_source: str | None = None

    def __post_init__(self) -> None:
        if self.name not in RIGHTS_GRANTS:
            raise ValueError(f"unknown rights grant: {self.name!r}")
        _one_of(self.state, RIGHTS_STATES, f"rights.{self.name}")

    def describe(self) -> str:
        """`<grant>=<state>; evidence source: <source>`, for display and evidence."""
        source = self.evidence_source or "none recorded"
        return f"{self.name}={self.state}; evidence source: {source}"


@dataclass(frozen=True)
class Rights:
    """The four independent grants of ADR-0011 `Distribution Rights`.

    The grants are stored flat so that a single grant is readable without
    unpacking a nested structure, and evidence is stored beside them in
    `grant_evidence`. `evidence_source` remains the item-level fallback for
    grants with no specific evidence of their own.

    Slice 1 recorded the grants. Slice 2 (`CL-n7ex`) composes them into
    projection, retention, and derivative decisions in `providers.rights`;
    nothing in this module enforces anything.
    """

    fetch_authorization: str = "unknown"
    install_rights: str = "unknown"
    redistribution_rights: str = "unknown"
    derivative_rights: str = "unknown"
    evidence_source: str | None = None
    grant_evidence: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in RIGHTS_GRANTS:
            _one_of(getattr(self, name), RIGHTS_STATES, f"rights.{name}")
        if self.evidence_source is not None and not str(self.evidence_source).strip():
            raise ValueError("rights.evidence_source must be text or None")
        evidence = dict(self.grant_evidence)
        unknown = sorted(set(evidence) - set(RIGHTS_GRANTS))
        if unknown:
            raise ValueError(f"unknown rights evidence grants: {unknown}")
        for name, source in evidence.items():
            if not isinstance(source, str) or not source.strip():
                raise ValueError(f"rights.grant_evidence[{name!r}] must be text")
        object.__setattr__(self, "grant_evidence", evidence)

        # A resolved grant with no named evidence source is not a recorded grant.
        # ADR-0011 requires each grant to resolve "with a named evidence source",
        # and review demonstrated the consequence of not enforcing it: an
        # all-`granted` rights value invented at a call site authorized a
        # committed projection, durable retention, and a derivative with nothing
        # behind it. `unknown` is the state for "nobody has looked", and it is
        # reachable without evidence precisely so that this one is not.
        for name in RIGHTS_GRANTS:
            state = getattr(self, name)
            if state == "unknown":
                continue
            if not (evidence.get(name) or self.evidence_source):
                raise ValueError(
                    f"rights.{name}={state} requires a named evidence source; "
                    "record 'unknown' when there is none"
                )

    def grant(self, name: str) -> RightsGrant:
        """Resolve one grant independently, with its own evidence source."""
        if name not in RIGHTS_GRANTS:
            raise ValueError(
                f"unknown rights grant {name!r}; ADR-0011 records {list(RIGHTS_GRANTS)}"
            )
        return RightsGrant(
            name=name,
            state=getattr(self, name),
            evidence_source=self.grant_evidence.get(name) or self.evidence_source,
        )

    def grants(self) -> tuple[RightsGrant, ...]:
        """All four grants, in the ADR's order."""
        return tuple(self.grant(name) for name in RIGHTS_GRANTS)

    def with_grant(
        self, name: str, state: str, *, evidence: str | None = None
    ) -> "Rights":
        """A copy with one grant changed. Every other grant is untouched.

        Rights are immutable because a grant that can be edited in place is a
        grant whose evidence can drift away from its value without any record.
        For the same reason, resolving a grant to `granted` or `denied` requires
        its own evidence, and relaxing one to `unknown` discards the evidence
        that justified the previous value instead of leaving it to describe a
        state that no longer holds.
        """
        if name not in RIGHTS_GRANTS:
            raise ValueError(
                f"unknown rights grant {name!r}; ADR-0011 records {list(RIGHTS_GRANTS)}"
            )
        _one_of(state, RIGHTS_STATES, f"rights.{name}")
        if state != "unknown" and not (evidence or "").strip():
            raise ValueError(
                f"resolving rights.{name} to {state!r} requires its own evidence; "
                "the evidence recorded for a previous value does not justify this one"
            )
        evidence_map = dict(self.grant_evidence)
        evidence_map.pop(name, None)
        if evidence is not None:
            evidence_map[name] = evidence
        values = {grant: getattr(self, grant) for grant in RIGHTS_GRANTS}
        values[name] = state
        return Rights(
            **values,
            evidence_source=self.evidence_source,
            grant_evidence=evidence_map,
        )

    def evidence_map(self) -> dict[str, str | None]:
        """Each grant mapped to the evidence source that resolved it."""
        return {grant.name: grant.evidence_source for grant in self.grants()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetch_authorization": self.fetch_authorization,
            "install_rights": self.install_rights,
            "redistribution_rights": self.redistribution_rights,
            "derivative_rights": self.derivative_rights,
            "evidence_source": self.evidence_source,
            "grant_evidence": dict(self.grant_evidence),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Rights":
        known = {*RIGHTS_GRANTS, "evidence_source", "grant_evidence"}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown rights fields: {unknown}")
        return cls(**{key: data[key] for key in known if key in data})


@dataclass(frozen=True)
class BlockReason:
    """One typed block reason with the evidence that produced it.

    ADR-0011 `Typed block reasons` closes the vocabulary and requires evidence
    on every entry. Both halves are enforced here rather than at the call site:
    a reason with no evidence is unactionable, and a reason outside the
    vocabulary is unqueryable, so neither may be constructed at all.
    """

    reason: str
    evidence: str
    detail: str | None = None

    def __post_init__(self) -> None:
        _one_of(self.reason, BLOCK_REASONS, "block reason")
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise ValueError(
                f"block reason {self.reason!r} must carry the evidence that produced it"
            )
        # A floor against a placeholder, not a judge of meaning. Review showed
        # that "non-empty" admitted `evidence="e"`, which satisfies the letter of
        # the contract and none of its purpose. Real evidence names a thing and
        # says something about it, so it is at least two words. Whether the
        # sentence is *true* stays a review question; no validator settles that.
        stripped = self.evidence.strip()
        if len(stripped) < MIN_EVIDENCE_LENGTH or " " not in stripped:
            raise ValueError(
                f"block reason {self.reason!r} evidence {self.evidence!r} is a "
                "placeholder; record what was observed and where it came from"
            )
        if self.detail is not None and not str(self.detail).strip():
            raise ValueError("block reason detail must be text or None")

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "evidence": self.evidence, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BlockReason":
        if not isinstance(data, Mapping):
            raise ValueError(
                "a block reason must be an object carrying its reason and evidence, "
                "not a bare vocabulary value"
            )
        unknown = sorted(set(data) - {"reason", "evidence", "detail"})
        if unknown:
            raise ValueError(f"unknown block reason fields: {unknown}")
        missing = sorted({"reason", "evidence"} - set(data))
        if missing:
            raise ValueError(f"missing block reason fields: {missing}")
        return cls(
            reason=data["reason"],
            evidence=data["evidence"],
            detail=data.get("detail"),
        )


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
    block_reasons: tuple[BlockReason, ...] = ()
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
            if not isinstance(reason, BlockReason):
                raise ValueError(
                    "block_reasons entries must be BlockReason values carrying "
                    "their evidence"
                )
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

    def block_reason_values(self) -> tuple[str, ...]:
        """Just the vocabulary values, for querying "what did I not get"."""
        return tuple(reason.reason for reason in self.block_reasons)

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
            "block_reasons": [reason.to_dict() for reason in self.block_reasons],
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
        payload["block_reasons"] = tuple(
            reason if isinstance(reason, BlockReason) else BlockReason.from_dict(reason)
            for reason in payload["block_reasons"]
        )
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
