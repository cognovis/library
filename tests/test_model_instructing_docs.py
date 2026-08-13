"""No shipped document still says foreign model-instructing content is inert.

ADR-0011 Invariant 12 as amended by `CL-lt51` (Human Decision HD-5, Malte
Sussdorff, 2026-08-10). AC4 of that bead is a documentation claim, so it is
checked mechanically rather than asserted in prose: a contract document that
still classifies a foreign steward's Skill or Prompt as inert would hand the
superseded rule to whoever reads it next, and the code would silently disagree
with the document that governs it.

What is checked is deliberately narrow. These tests do not grade the writing;
they hold down four facts: the decision is recorded where decisions live, the
amended invariant is reproduced in full, each contract document states the new
rule, and no document contradicts it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

DOCS = REPO_ROOT / "docs"
ADR = DOCS / "adr" / "heterogeneous-marketplace-workspaces.md"

#: The documents that carry the admission contract to a reader.
CONTRACT_DOCUMENTS = (
    ADR,
    DOCS / "PRIMITIVES.md",
    DOCS / "primitives" / "marketplace.md",
    DOCS / "lockfile-format.md",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestTheDecisionIsRecorded:
    def test_the_adr_records_hd5_with_its_maker_and_date(self):
        human_decisions = _text(ADR).split("## Human Decisions", 1)[1]
        row = next(
            line for line in human_decisions.splitlines() if line.strip().startswith("| HD-5")
        )
        assert "Malte Sussdorff, 2026-08-10" in row
        assert "Final" in row
        assert "model-instructing" in row.lower()

    def test_the_amended_invariant_is_reproduced_in_full(self):
        body = _text(ADR)
        assert "Invariant 12 (executable admission), as amended by `CL-lt51`" in body
        # A reader with only this repository can see both what the invariant said
        # and what changed, which is the whole reason the ADR reproduces the
        # invariants it cites instead of pointing at the bead tracker.
        assert "Skills, Prompts, Agents, Standards" in body
        assert "The amendment to Invariant 12 is recorded, not silent." in body

    def test_the_adr_states_the_boundary_and_the_migration_rule(self):
        body = _text(ADR)
        section = body.split("#### Model-instructing foreign content", 1)[1]
        assert "Foreign stewardship only" in section
        assert "First-party catalog content" in section
        assert "never removed" in section, (
            "a migration that classifies must say it deletes nothing"
        )


class TestEveryContractDocumentStatesTheRule:
    @pytest.mark.parametrize("path", CONTRACT_DOCUMENTS, ids=lambda p: p.name)
    def test_the_document_names_the_amendment(self, path: Path):
        body = _text(path)
        assert "CL-lt51" in body, f"{path} does not record which slice changed this"
        assert "model-instructing" in body.lower()

    def test_the_marketplace_primitive_documents_the_update_flow(self):
        body = _text(DOCS / "primitives" / "marketplace.md")
        for verb in (
            "library marketplace update",
            "update-show",
            "update-approve",
            "update-reject",
        ):
            assert verb in body
        assert "risk *reduction* rather than" in body or "risk reduction" in body
        assert "byte-identical" in body

    def test_the_adr_documents_the_update_flow_as_a_human_gate(self):
        body = _text(ADR)
        section = body.split("### Foreign update admission", 1)[1].split("### Mixed", 1)[0]
        assert "No verdict value adopts anything" in section
        assert "never skips the review or the gate" in section
        assert "not a passed review" in section
        assert "byte-identical" in section


class TestNoDocumentContradictsIt:
    #: Sentences that would tell a reader the superseded rule. Each is a real
    #: phrasing that existed in this repository before `CL-lt51`.
    CONTRADICTIONS = (
        re.compile(r"prompt content is inert", re.IGNORECASE),
        re.compile(r"Inert Prompt, Standard, and documentation content", re.IGNORECASE),
        re.compile(r"\bPrompts?\b[^.\n]{0,40}\bare inert\b", re.IGNORECASE),
        re.compile(r"\bSkills?\b[^.\n]{0,40}\bis inert\b", re.IGNORECASE),
    )

    def test_no_shipped_document_states_the_superseded_rule(self):
        offenders: list[str] = []
        for path in sorted(DOCS.rglob("*.md")):
            body = _text(path)
            for pattern in self.CONTRADICTIONS:
                for match in pattern.finditer(body):
                    offenders.append(f"{path}: {match.group(0)!r}")
        assert offenders == [], (
            "these documents still classify foreign model-instructing content as "
            f"inert: {offenders}"
        )

class TestTheDocumentedVocabularyMatchesTheCode:
    def test_every_documented_type_is_actually_admission_required(self):
        from lib.providers.classification import (
            FIRST_PARTY,
            FOREIGN,
            MODEL_INSTRUCTING_TYPES,
            requires_admission,
        )

        section = _text(ADR).split("#### Model-instructing foreign content", 1)[1]
        row = next(line for line in section.splitlines() if "Covered types" in line)
        documented = set(re.findall(r"`([a-z-]+)`", row))

        assert documented == set(MODEL_INSTRUCTING_TYPES), (
            "the ADR's covered-type list and the implemented vocabulary have "
            f"drifted: document {sorted(documented)}, code {sorted(MODEL_INSTRUCTING_TYPES)}"
        )
        for library_type in documented:
            assert requires_admission(library_type, FOREIGN) is True
            assert requires_admission(library_type, FIRST_PARTY) is False

    def test_the_primitives_page_lists_the_same_types(self):
        from lib.providers.classification import MODEL_INSTRUCTING_TYPES

        section = _text(DOCS / "PRIMITIVES.md").split(
            "### Foreign model-instructing content", 1
        )[1]
        heading = section.split("\n\n", 2)[1]
        # The page names primitives the way a reader knows them, so the check is
        # coverage rather than an exact string match on the internal type ids.
        for library_type in MODEL_INSTRUCTING_TYPES:
            spoken = library_type.replace("-", " ")
            assert spoken.lower() in heading.lower().replace("-", " "), (
                f"{library_type} is admission-required in code and is not listed here"
            )
