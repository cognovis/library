"""Normalized inventory schema and qualified identity (CL-coif AC3, AC6).

ADR-0011 `Normalized Inventory and Admission State` fixes the normalized item
schema and the canonical qualified identity `<provider-identity>#<upstream-id>`.
These tests hold that contract: the field set, verbatim preservation of upstream
identity, and a lossless round trip through the qualified identity.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.inventory import (  # noqa: E402
    NormalizedInventory,
    NormalizedItem,
    ProviderAvailability,
    Rights,
    parse_qualified_identity,
    qualified_identity,
)


PROVIDER = "https://github.com/mattpocock/skills"


def _item(**overrides: object) -> NormalizedItem:
    base = dict(
        provider_identity=PROVIDER,
        upstream_id="skills/engineering/implement",
        upstream_name="implement",
        collection_membership=("skills", "engineering"),
        upstream_revision="84fdeffd12f2ee307994d1eb6feb48173b6e0502",
        library_type="skill",
        library_name="implement",
        classification={"skill_class": "procedure"},
        runtime_compatibility=("unknown",),
        rights=Rights(fetch_authorization="granted", evidence_source="upstream LICENSE"),
        provider_availability=ProviderAvailability(
            state="available", observed_at="2026-08-08T20:00:00Z"
        ),
    )
    base.update(overrides)
    return NormalizedItem(**base)  # type: ignore[arg-type]


def test_normalized_item_fields() -> None:
    """Every field ADR-0011 requires of a normalized item is present and typed."""
    item = _item()

    assert item.provider_identity == PROVIDER
    assert item.upstream_id == "skills/engineering/implement"
    assert item.upstream_name == "implement"
    assert item.collection_membership == ("skills", "engineering")
    assert item.upstream_revision == "84fdeffd12f2ee307994d1eb6feb48173b6e0502"
    assert item.library_type == "skill"
    assert item.library_name == "implement"
    assert item.classification == {"skill_class": "procedure"}
    assert item.runtime_compatibility == ("unknown",)
    assert item.rights.fetch_authorization == "granted"
    assert item.rights.install_rights == "unknown"
    assert item.rights.redistribution_rights == "unknown"
    assert item.rights.derivative_rights == "unknown"

    # The remaining ADR-0011 schema fields exist with conservative defaults;
    # their derivation is owned by later slices (see the module docstring).
    assert item.admission_state == "discoverable"
    assert item.block_reasons == ()
    assert item.executable_admission == "inert"
    assert item.trust_state == "unreviewed"
    assert item.cache_state == "absent"
    assert item.projection_eligibility == {
        "project_committed": "blocked",
        "machine_local": "blocked",
    }
    assert item.provider_availability.state == "available"
    assert item.provider_availability.observed_at == "2026-08-08T20:00:00Z"


def test_upstream_revision_is_nullable() -> None:
    """A revisionless provider records `None`, not a synthesized revision."""
    assert _item(upstream_revision=None).upstream_revision is None


def test_normalized_item_rejects_unknown_state_values() -> None:
    with pytest.raises(ValueError):
        _item(admission_state="probably-fine")
    with pytest.raises(ValueError):
        _item(rights=Rights(install_rights="maybe"))


def test_upstream_name_preserved() -> None:
    """Normalization never rewrites upstream identity to fit Library naming."""
    item = _item(
        upstream_id="skills/in-progress/Writing Beats",
        upstream_name="Writing Beats",
        library_name="writing-beats",
    )

    assert item.upstream_name == "Writing Beats"
    assert item.library_name == "writing-beats"
    assert item.to_dict()["upstream_name"] == "Writing Beats"
    assert NormalizedItem.from_dict(item.to_dict()).upstream_name == "Writing Beats"


def test_qualified_identity_round_trip() -> None:
    """provider -> qualified identity -> item, with no loss on the way back."""
    item = _item()
    inventory = NormalizedInventory([item])

    identity = item.qualified_identity()
    assert identity == f"{PROVIDER}#skills/engineering/implement"

    provider_identity, upstream_id = parse_qualified_identity(identity)
    assert provider_identity == item.provider_identity
    assert upstream_id == item.upstream_id

    resolved = inventory.resolve(identity)
    assert resolved == item
    assert resolved.to_dict() == item.to_dict()
    assert resolved.qualified_identity() == identity


def test_qualified_identity_splits_on_the_first_separator() -> None:
    """An upstream id may contain the separator; a provider identity may not."""
    identity = qualified_identity(PROVIDER, "kits/anchor#3")
    assert parse_qualified_identity(identity) == (PROVIDER, "kits/anchor#3")

    with pytest.raises(ValueError):
        qualified_identity("provider#with-separator", "item")


def test_inventory_refuses_duplicate_qualified_identity() -> None:
    with pytest.raises(ValueError):
        NormalizedInventory([_item(), _item(upstream_name="implement-again")])


def test_inventory_resolve_reports_unknown_identity() -> None:
    inventory = NormalizedInventory([_item()])
    with pytest.raises(KeyError):
        inventory.resolve(f"{PROVIDER}#skills/engineering/absent")
