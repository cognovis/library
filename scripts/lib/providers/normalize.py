"""Provider output -> normalized inventory, driven only by declared capabilities.

This module is the boundary the rest of the platform consumes. It contains no
provider name, no provider-kind conditional, and no upstream URL: every
behavioral difference between providers arrives through `capabilities()`.

The degradation rules, all of them declaration-driven:

| Absent capability | Behavior |
|---|---|
| `describe` | Fetch the content and classify it; recorded as a cost, never as a failure |
| `revision_of` | `upstream_revision` is `None` — the provider is revisionless |
| `verify` | Recorded as absent; the Library normalized digest is the only integrity proof |
| `rights_evidence` | Recorded rights are used unchanged; no evidence source is invented |

Nothing here catches an exception to discover a capability. A capability that
is declared but missing raises through this module on purpose: a lying
declaration is a defect in the adapter, and swallowing it would turn a broken
adapter into a silently degraded one.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Sequence

from .classification import (
    classification_for,
    executable_admission_for,
    library_name_for,
    library_type_for,
)
from .contract import (
    ItemDescription,
    OPTIONAL_CAPABILITIES,
    SourceProvider,
    validate_capability_declaration,
)
from .inventory import (
    NormalizedInventory,
    NormalizedItem,
    ProviderAvailability,
    Rights,
)

FETCH_THEN_CLASSIFY = "fetch-then-classify"


@dataclass(frozen=True)
class NormalizationCost:
    """A costlier path taken because a capability was not declared."""

    upstream_id: str
    capability: str
    path: str
    reason: str


@dataclass(frozen=True)
class NormalizationResult:
    """Normalized inventory plus what it cost and what was not available."""

    inventory: NormalizedInventory
    costs: tuple[NormalizationCost, ...]
    absent_capabilities: tuple[str, ...]
    provider_identity: str
    provider_availability: ProviderAvailability


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _observed_availability(provider: SourceProvider) -> ProviderAvailability:
    availability = provider.availability()
    return ProviderAvailability(
        state=availability.state,
        observed_at=availability.observed_at or _now(),
        reason=availability.reason,
    )


def normalize_inventory(
    provider: SourceProvider,
    *,
    selector: Any = None,
    rights: Rights | None = None,
    trust_state: str = "unreviewed",
) -> NormalizationResult:
    """Normalize one provider's inventory through its declared capabilities.

    Args:
        provider: Any adapter implementing the capability contract.
        selector: Provider-native selector passed through to `enumerate`.
        rights: Rights recorded for this source in catalog configuration.
            Slice 1 carries them; slice 2 (`CL-n7ex`) enforces them.
        trust_state: Recorded trust for this source.

    Returns:
        The normalized inventory, the costs paid for absent capabilities, and
        the capabilities the provider does not offer.
    """
    declared = validate_capability_declaration(provider)
    absent = tuple(sorted(OPTIONAL_CAPABILITIES - declared))
    identity = provider.identity()
    availability = _observed_availability(provider)
    recorded_rights = rights or Rights()

    if "rights_evidence" in declared:
        evidence = provider.rights_evidence()
        if evidence.located and evidence.source:
            recorded_rights = Rights(
                fetch_authorization=recorded_rights.fetch_authorization,
                install_rights=recorded_rights.install_rights,
                redistribution_rights=recorded_rights.redistribution_rights,
                derivative_rights=recorded_rights.derivative_rights,
                evidence_source=recorded_rights.evidence_source or evidence.source,
            )

    costs: list[NormalizationCost] = []
    items: list[NormalizedItem] = []

    for raw in provider.enumerate(selector):
        description, content = _describe(provider, declared, raw, costs)
        classification = classification_for(
            description.library_type,
            str(description.classification.get("type_basis", "provider-described")),
            content,
        )
        classification.update(
            {
                key: value
                for key, value in description.classification.items()
                if key not in classification
            }
        )
        if description.content_identity:
            classification["upstream_content_identity"] = description.content_identity

        revision = provider.revision_of(raw.upstream_id) if "revision_of" in declared else None

        items.append(
            NormalizedItem(
                provider_identity=identity,
                upstream_id=raw.upstream_id,
                upstream_name=raw.upstream_name,
                collection_membership=raw.collection_membership,
                upstream_revision=revision,
                library_type=description.library_type,
                library_name=library_name_for(raw.upstream_name),
                classification=classification,
                runtime_compatibility=description.runtime_compatibility,
                rights=recorded_rights,
                provider_availability=availability,
                executable_admission=executable_admission_for(description.library_type),
                trust_state=trust_state,
            )
        )

    return NormalizationResult(
        inventory=NormalizedInventory(items),
        costs=tuple(costs),
        absent_capabilities=absent,
        provider_identity=identity,
        provider_availability=availability,
    )


def _describe(
    provider: SourceProvider,
    declared: frozenset[str],
    raw: Any,
    costs: list[NormalizationCost],
) -> tuple[ItemDescription, bytes | None]:
    """Describe one item, paying the fetch-then-classify cost when needed."""
    if "describe" in declared:
        return provider.describe(raw.upstream_id), None

    content = provider.fetch(raw.upstream_id)
    costs.append(
        NormalizationCost(
            upstream_id=raw.upstream_id,
            capability="describe",
            path=FETCH_THEN_CLASSIFY,
            reason="the adapter does not declare describe, so content was fetched to classify",
        )
    )
    library_type, basis = library_type_for(raw.content_hint or raw.upstream_name)
    return (
        ItemDescription(
            upstream_id=raw.upstream_id,
            library_type=library_type,
            classification={"type_basis": basis},
        ),
        content,
    )


def normalized_types(items: Sequence[NormalizedItem]) -> tuple[str, ...]:
    """The distinct Library types present in a normalized item sequence."""
    return tuple(sorted({item.library_type for item in items}))
