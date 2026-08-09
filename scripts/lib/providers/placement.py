"""Placement Records for the ADR-0011 reference items.

A Placement Record answers, for one artifact: which marketplace stewards it,
what its upstream identity is, which plane and primitive it belongs to, how it is
classified, what runtimes it supports, its executable admission, and its rights.

This module is **curated data, not policy**. It transcribes ADR-0011
`Placement Records` so a real item's recorded placement can be asserted rather
than constructed in a test fixture. It sits beside the provider adapters because
naming an upstream artifact is legitimate at the adapter boundary and nowhere
else.

The one field it is load-bearing for is `classification.skill_class`. That value
is **not derivable from upstream content**: ADR-0011 classifies `implement` as
`procedure` and `ask-matt` as `navigator` while both ship the same
`disable-model-invocation: true` frontmatter flag. It was briefly derived from
that flag, and adversarial review showed the rule was simply wrong. So the
Library curates it, this module is where the curation lives, and an item with no
record here carries `classification.skill_class_source: not-curated` rather than
a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .inventory import Rights
from .reference_rights import SKILLS_REPO_IDENTITY

#: The first-party catalog that stewards the platform-owned counterpart item.
FIRST_PARTY_CATALOG_IDENTITY = "https://github.com/cognovis/library-core"


@dataclass(frozen=True)
class PlacementRecord:
    """One artifact's recorded placement, per the ADR-0011 table."""

    steward_identity: str
    upstream_id: str | None
    plane: str
    primitive: str
    skill_class: str | None
    runtime_compatibility: tuple[str, ...]
    executable_admission: str
    rights_note: str

    def __post_init__(self) -> None:
        if self.executable_admission not in ("inert", "admitted", "pending", "refused"):
            raise ValueError(
                f"unknown executable admission {self.executable_admission!r}"
            )
        object.__setattr__(
            self, "runtime_compatibility", tuple(self.runtime_compatibility)
        )


PLACEMENT_RECORDS: Mapping[str, PlacementRecord] = {
    "implement": PlacementRecord(
        steward_identity=SKILLS_REPO_IDENTITY,
        upstream_id="skills/engineering/implement",
        plane="dev",
        primitive="skill",
        skill_class="procedure",
        runtime_compatibility=("claude-code", "codex"),
        executable_admission="inert",
        rights_note="granted (MIT)",
    ),
    "ask-matt": PlacementRecord(
        steward_identity=SKILLS_REPO_IDENTITY,
        upstream_id="skills/engineering/ask-matt",
        plane="dev",
        primitive="skill",
        skill_class="navigator",
        runtime_compatibility=("claude-code", "codex"),
        executable_admission="inert",
        rights_note="granted (MIT)",
    ),
    "ask-malte": PlacementRecord(
        steward_identity=FIRST_PARTY_CATALOG_IDENTITY,
        upstream_id=None,
        plane="dev",
        primitive="skill",
        skill_class="navigator",
        runtime_compatibility=("claude-code", "codex", "pi"),
        executable_admission="inert",
        rights_note="first-party",
    ),
}


def curated_skill_classes(provider_identity: str) -> dict[str, str]:
    """Curated `skill_class` per upstream id, for one provider.

    Returned keyed by upstream id because that is what `normalize_inventory`
    consumes. A provider with no curated records gets an empty mapping, and every
    one of its skills records `skill_class_source: not-curated`.
    """
    return {
        record.upstream_id: record.skill_class
        for record in PLACEMENT_RECORDS.values()
        if record.steward_identity == provider_identity
        and record.upstream_id
        and record.skill_class
    }


def placement_for(library_name: str) -> PlacementRecord | None:
    """The recorded placement for one Library name, or `None` when uncurated."""
    return PLACEMENT_RECORDS.get(library_name)


def first_party_placements() -> tuple[str, ...]:
    """Library names whose steward is a first-party catalog rather than a provider."""
    return tuple(
        sorted(
            name
            for name, record in PLACEMENT_RECORDS.items()
            if record.upstream_id is None
        )
    )


def rights_note_for(library_name: str, rights: Rights) -> str:
    """A one-line reconciliation of a placement's rights note with recorded rights.

    The ADR table records a human-readable note; `Rights` records the machine
    state. Keeping them in one sentence is how a drift between the two becomes
    visible instead of being discovered when a projection is unexpectedly
    blocked.
    """
    record = placement_for(library_name)
    note = record.rights_note if record else "no placement record"
    grants = ", ".join(grant.describe() for grant in rights.grants())
    return f"{library_name}: placement notes {note}; recorded {grants}"
