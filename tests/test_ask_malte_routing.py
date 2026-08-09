"""The platform-owned navigator placement routes from catalog data only.

CL-mvet AC9. ADR-0011 `Placement Records` constrains `ask-malte` rather than
merely recommending: it resolves candidates through catalog data and canonical
context pointers, and it must not hard-code provider names, sibling-repository
paths, or a routing table of repositories.

The test that matters is the negative one. It is easy to write a router that
happens to produce catalog-derived answers on the author's machine; what is
being proven here is that it *cannot* produce any other kind.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.catalog import load_catalog  # noqa: E402
from lib.providers.placement import (  # noqa: E402
    FIRST_PARTY_CATALOG_IDENTITY,
    PLACEMENT_RECORDS,
    curated_skill_classes,
    first_party_placements,
)
from lib.providers.reference_rights import SKILLS_REPO_IDENTITY  # noqa: E402
from lib.routing import (  # noqa: E402
    ContextPointer,
    RoutingAnswer,
    RoutingCandidate,
    RoutingNotCatalogDerived,
    resolve_context_pointers,
    route,
)

#: Names that exist nowhere in this repository, so a router that returns them
#: can only have read them from the catalog handed to it in that run.
INVENTED_CATALOG = "kaerbannog-catalog"
INVENTED_IDENTITY = "https://example.invalid/kaerbannog/rabbit-of-caerbannog"

#: Real names a hard-coded routing table would plausibly contain. None of them
#: is registered in the fabricated catalog below, so any appearance is invention.
NAMES_NOT_IN_THE_FABRICATED_CATALOG = (
    "cognovis-core",
    "sussdorff-core",
    "cognovis-library-core",
    "library-platform",
    "github.com",
    SKILLS_REPO_IDENTITY,
)


def _fabricated_catalog() -> dict[str, object]:
    """A catalog with one registered source, named nothing like a real one."""
    return {
        "sources": {
            "catalogs": [{"name": INVENTED_CATALOG, "source": INVENTED_IDENTITY}],
            "marketplaces": [],
        },
        "library": {
            "skills": [
                {
                    "name": "holy-hand-grenade",
                    "description": "Count to three when a bead review needs a verdict.",
                    "tags": ["review", "bead"],
                    "metadata": {
                        "library": {
                            "source_catalog": INVENTED_CATALOG,
                            "catalog_identity": INVENTED_IDENTITY,
                        }
                    },
                }
            ],
            "agents": [],
            "workspaces": [],
            "prompts": [],
            "standards": [],
        },
    }


# ---------------------------------------------------------------------------
# AC9 — routing is catalog-derived
# ---------------------------------------------------------------------------


def test_no_hardcoded_repository_knowledge(tmp_path: Path) -> None:
    """A routing answer names only sources it read from the catalog in that run.

    The catalog handed in registers exactly one source, under a name that appears
    nowhere in this repository. Every real catalog and repository name a routing
    table might have been seeded with is therefore absent from the input, and the
    assertion is that all of them are absent from the output too.
    """
    catalog = _fabricated_catalog()
    answer = route(catalog, "which skill reviews a bead", repo_root=tmp_path)
    rendered = answer.render()

    assert answer.candidates, "the fabricated catalog does contain a match"
    assert answer.candidates[0].name == "holy-hand-grenade"
    assert answer.catalogs_read == (INVENTED_CATALOG,)
    assert set(answer.named_sources()) == {INVENTED_CATALOG, INVENTED_IDENTITY}
    assert INVENTED_CATALOG in rendered

    for name in NAMES_NOT_IN_THE_FABRICATED_CATALOG:
        assert name not in rendered, (
            f"{name!r} is not in the catalog this run read, so naming it would be "
            "a claim about somebody else's machine"
        )


def test_fewer_catalogs_narrows_the_answer_instead_of_widening_it(tmp_path: Path) -> None:
    """With nothing registered, the answer is narrower — never confidently wrong."""
    empty = {"sources": {"catalogs": [], "marketplaces": []}, "library": {"skills": []}}
    answer = route(empty, "which skill reviews a bead", repo_root=tmp_path)

    assert answer.candidates == ()
    assert answer.unmatched
    assert answer.catalogs_read == ()
    rendered = answer.render()
    assert "No catalog entry matched" in rendered
    for name in NAMES_NOT_IN_THE_FABRICATED_CATALOG:
        assert name not in rendered


def test_an_answer_naming_an_unread_source_is_refused() -> None:
    """The rule is enforced on the rendered answer, not just on its fields.

    Constructed directly rather than through `route`, because the point is that
    the guard would catch a future regression *inside* `route` -- a check that
    only runs on inputs it already trusts proves nothing.
    """
    smuggled = RoutingAnswer(
        query="which skill reviews a bead",
        candidates=(
            RoutingCandidate(
                primitive="skill",
                name="holy-hand-grenade",
                catalog_name="a-catalog-nobody-registered",
                catalog_identity="https://example.invalid/unregistered",
                summary="",
                score=5,
                matched_terms=("review",),
            ),
        ),
        catalogs_read=(INVENTED_CATALOG,),
        identities_read=(INVENTED_IDENTITY,),
        context_pointers=(),
    )
    with pytest.raises(RoutingNotCatalogDerived):
        smuggled.assert_catalog_derived()


def test_absent_context_pointers_are_reported_not_substituted(tmp_path: Path) -> None:
    """A pointer that is not on this machine contributes nothing, loudly."""
    pointers = resolve_context_pointers(
        tmp_path, pointers=(("navigation", "AGENTS.md"), ("primitives", "docs/X.md"))
    )
    assert all(not pointer.present for pointer in pointers)

    answer = route(
        _fabricated_catalog(),
        "which skill reviews a bead",
        repo_root=tmp_path,
        context_pointers=pointers,
    )
    rendered = answer.render()
    assert "absent" in rendered
    assert any("contributed nothing" in note.render() for note in answer.notes)


def test_routing_reads_the_real_catalog_without_naming_anything_unread() -> None:
    """The same guard holds against this repository's own live catalog."""
    catalog = load_catalog(REPO_ROOT)
    answer = route(catalog, "review a bead against its specification", repo_root=REPO_ROOT)
    answer.assert_catalog_derived()
    assert answer.candidates, "this repository's catalog does contain review skills"
    for candidate in answer.candidates:
        assert candidate.catalog_name in answer.catalogs_read


# ---------------------------------------------------------------------------
# The placement record itself
# ---------------------------------------------------------------------------


def test_placement_records_transcribe_the_adr_table() -> None:
    """The three ADR-0011 Placement Records, including the platform-owned one."""
    assert set(PLACEMENT_RECORDS) == {"implement", "ask-matt", "ask-malte"}

    assert PLACEMENT_RECORDS["implement"].skill_class == "procedure"
    assert PLACEMENT_RECORDS["ask-matt"].skill_class == "navigator"
    assert PLACEMENT_RECORDS["implement"].steward_identity == SKILLS_REPO_IDENTITY

    platform_owned = PLACEMENT_RECORDS["ask-malte"]
    assert platform_owned.steward_identity == FIRST_PARTY_CATALOG_IDENTITY
    assert platform_owned.upstream_id is None, "first-party: there is no upstream"
    assert platform_owned.skill_class == "navigator"
    assert "pi" in platform_owned.runtime_compatibility
    assert first_party_placements() == ("ask-malte",)

    # The curated classes are keyed by upstream id for the provider that stewards
    # them, and the first-party record contributes none.
    curated = curated_skill_classes(SKILLS_REPO_IDENTITY)
    assert curated == {
        "skills/engineering/implement": "procedure",
        "skills/engineering/ask-matt": "navigator",
    }
    assert curated_skill_classes(FIRST_PARTY_CATALOG_IDENTITY) == {}


def test_context_pointer_describes_its_own_state(tmp_path: Path) -> None:
    """A pointer states whether it was read, so an absent one cannot pass as read."""
    present = tmp_path / "AGENTS.md"
    present.write_text("rules\n")
    pointer = ContextPointer(label="rules", path=present, present=True)
    assert "read" in pointer.describe()
    assert "absent" in ContextPointer(
        label="rules", path=tmp_path / "missing.md", present=False
    ).describe()
