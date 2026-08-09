"""Provider registration. It answers where content may be found, and nothing else.

ADR-0011 Invariant: *marketplace registration answers where content may be
found; normalized inventory answers what is available; Workspace roots answer
what is installed.* Registration therefore creates no cache object, no receipt,
and no projection — `RegistrationOutcome` reports those three as empty, and
`tests/test_source_provider_contract.py::test_registration_installs_nothing`
proves the filesystem agrees.

The rules enforced here are the API-level counterpart of the
`marketplace_entry` JSON Schema, which governs a catalog *file*.
`tests/test_library_yaml_provider_fields.py` holds the two in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

from .inventory import RIGHTS_STATES

#: The provider kinds ADR-0011 `Provider kinds` admits.
PROVIDER_KINDS = ("git-repo", "git-org", "mcp-content", "hosted-index")

#: Kinds whose enumeration is organization-wide and therefore requires an
#: explicit, Library-owned allowlist. Without it the inventory would be a
#: function of someone else's repository creation.
ALLOWLIST_REQUIRED_KINDS = ("git-org",)

RIGHTS_GRANTS = (
    "fetch_authorization",
    "install_rights",
    "redistribution_rights",
    "derivative_rights",
)


class RegistrationError(ValueError):
    """A provider registration was refused. Nothing was mutated."""


@dataclass(frozen=True)
class RegistrationOutcome:
    """What registration produced. The last three are always empty."""

    marketplace: Mapping[str, Any]
    provider_identity: str
    cache_objects: tuple[str, ...] = ()
    receipts: tuple[str, ...] = ()
    projections: tuple[str, ...] = ()


def canonical_provider_identity(source: str) -> str:
    """The canonical stored identity for a source, never a display alias.

    ADR-0011 `Consumers of provider identity`: locks, conflict diagnostics,
    ownership, audit, and prune decisions all use this form. Storing an alias
    beside it would let one provider produce two record sets.
    """
    if not isinstance(source, str) or not source.strip():
        raise RegistrationError("a provider registration needs a source identity")
    identity = source.strip().rstrip("/")
    if identity.endswith(".git"):
        identity = identity[: -len(".git")]
    if "#" in identity:
        raise RegistrationError(
            f"a provider identity must not contain '#': {identity!r}"
        )
    return identity


def _validate_rights(rights: Any) -> None:
    if rights is None:
        return
    if not isinstance(rights, Mapping):
        raise RegistrationError("rights must be a mapping of grants")
    unknown = sorted(
        set(rights) - set(RIGHTS_GRANTS) - {"evidence_source", "grant_evidence"}
    )
    if unknown:
        raise RegistrationError(f"unknown rights fields: {unknown}")
    for grant in RIGHTS_GRANTS:
        if grant in rights and rights[grant] not in RIGHTS_STATES:
            raise RegistrationError(
                f"rights.{grant} must be one of {list(RIGHTS_STATES)}, "
                f"got {rights[grant]!r}"
            )

    shared = rights.get("evidence_source")
    if shared is not None and (not isinstance(shared, str) or not shared.strip()):
        raise RegistrationError("rights.evidence_source must be text")

    # Per-grant evidence is the representation ADR-0011 actually describes:
    # four grants, each with a named source. Registration accepting only the
    # shared fallback would have refused the very entry shape the reference
    # provider needs -- a granted fetch on a subscriber endpoint beside three
    # grants resting on nothing.
    grant_evidence = rights.get("grant_evidence")
    if grant_evidence is not None and not isinstance(grant_evidence, Mapping):
        raise RegistrationError("rights.grant_evidence must be a mapping of grants")
    evidence_map: Mapping[str, Any] = grant_evidence or {}
    unknown_evidence = sorted(set(evidence_map) - set(RIGHTS_GRANTS))
    if unknown_evidence:
        raise RegistrationError(f"unknown rights evidence grants: {unknown_evidence}")
    for grant, source in evidence_map.items():
        if not isinstance(source, str) or not source.strip():
            raise RegistrationError(f"rights.grant_evidence[{grant!r}] must be text")

    # ADR-0011 records each grant "with a named evidence source" (CL-n7ex). A
    # catalog entry that resolves a grant without one would construct a `Rights`
    # value the gate refuses, so it is refused here instead -- at registration,
    # where the person who wrote the entry can still fix it.
    unevidenced = sorted(
        grant
        for grant in RIGHTS_GRANTS
        if rights.get(grant, "unknown") != "unknown"
        and not str(evidence_map.get(grant) or "").strip()
        and not str(shared or "").strip()
    )
    if unevidenced:
        raise RegistrationError(
            f"rights {unevidenced} are resolved but no evidence source is recorded; "
            "record 'unknown' when there is no named source"
        )


def validate_provider_entry(entry: Mapping[str, Any]) -> str:
    """Validate one marketplace entry and return its canonical identity."""
    if not isinstance(entry, Mapping):
        raise RegistrationError("a marketplace entry must be a mapping")
    if not str(entry.get("name") or "").strip():
        raise RegistrationError("a marketplace entry needs a name")

    provider_kind = entry.get("provider_kind")
    if provider_kind is not None and provider_kind not in PROVIDER_KINDS:
        raise RegistrationError(
            f"unknown provider_kind {provider_kind!r}; "
            f"ADR-0011 admits {list(PROVIDER_KINDS)}"
        )

    if provider_kind in ALLOWLIST_REQUIRED_KINDS:
        allowlist = entry.get("allowlist")
        if not isinstance(allowlist, (list, tuple)) or not allowlist:
            raise RegistrationError(
                f"provider_kind {provider_kind!r} requires a non-empty allowlist: "
                "organization-level enumeration without one makes the inventory a "
                "function of someone else's repository creation"
            )
        if any(not str(item).strip() for item in allowlist):
            raise RegistrationError("allowlist entries must be non-empty")

    auth_ref = entry.get("auth_ref")
    if auth_ref is not None and not str(auth_ref).strip():
        raise RegistrationError("auth_ref must name a credential reference")

    _validate_rights(entry.get("rights"))
    return canonical_provider_identity(str(entry.get("source") or ""))


def register_provider(
    catalog_data: MutableMapping[str, Any], entry: Mapping[str, Any]
) -> RegistrationOutcome:
    """Register one source provider in `sources.marketplaces`.

    Validation happens before any mutation, so a refused registration leaves the
    catalog exactly as it was.

    Raises:
        RegistrationError: on an invalid entry or a duplicate provider identity.
    """
    identity = validate_provider_entry(entry)

    sources = catalog_data.setdefault("sources", {})
    if not isinstance(sources, MutableMapping):
        raise RegistrationError("catalog `sources` must be a mapping")
    marketplaces = sources.setdefault("marketplaces", [])
    if not isinstance(marketplaces, list):
        raise RegistrationError("catalog `sources.marketplaces` must be a list")

    for existing in marketplaces:
        if not isinstance(existing, Mapping):
            continue
        if str(existing.get("name")) == str(entry.get("name")):
            raise RegistrationError(f"marketplace {entry.get('name')!r} is already registered")
        existing_source = existing.get("source")
        if existing_source and canonical_provider_identity(str(existing_source)) == identity:
            raise RegistrationError(
                f"provider identity {identity} is already registered as "
                f"{existing.get('name')!r}; one provider must not carry two identities"
            )

    registered = dict(entry)
    marketplaces.append(registered)
    return RegistrationOutcome(marketplace=registered, provider_identity=identity)
