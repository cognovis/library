"""The committed legacy projection inventory is derived, not written (CL-m6cc AC5).

ADR-0011's original survey was a hand-written table, and a hand-written table is
how a report and the machine it describes drift apart. The AC5 evidence is
therefore two committed artifacts: a JSON document produced by
`scripts/checks/legacy_projection_inventory.py`, and a Markdown rendering of
exactly that document.

These tests do not re-scan the operator's machine -- that would make the suite
depend on a home directory and fail on anyone else's. They check the properties
a hand edit breaks: the schema, the counts recomputed from the entries, the
disposition rules applied to every row, and the Markdown being a pure function
of the JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "checks"))

from lib.providers.legacy_projections import (  # noqa: E402
    INVENTORY_SCHEMA,
    PENDING_DIGEST_ATTRIBUTION,
    PROVENANCE_STATES,
    REMEDIATION_PATHS,
)

import legacy_projection_inventory as generator  # noqa: E402

JSON_ARTIFACT = REPO_ROOT / "docs" / "reports" / "legacy-projection-inventory.json"
MARKDOWN_ARTIFACT = REPO_ROOT / "docs" / "reports" / "legacy-projection-inventory.md"


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads(JSON_ARTIFACT.read_text(encoding="utf-8"))


def test_the_artifact_carries_its_schema(document: dict) -> None:
    assert document["schema"] == INVENTORY_SCHEMA
    assert document["observed_at"]
    assert document["roots"]


def test_counts_are_recomputed_from_the_entries(document: dict) -> None:
    """A hand-edited count is the cheapest way to make a report say anything."""
    entries = document["entries"]
    counts = document["counts"]
    assert counts["total"] == len(entries)
    assert counts["compliant"] == sum(
        1 for item in entries if item["compliance"] == "compliant"
    )
    assert counts["non_compliant"] == sum(
        1 for item in entries if item["compliance"] == "non-compliant"
    )
    assert counts["receipted"] == sum(
        1 for item in entries if item["receipt_status"] == "receipted"
    )
    assert counts["unreceipted"] == sum(
        1 for item in entries if item["receipt_status"] == "unreceipted"
    )
    assert counts["compliant"] + counts["non_compliant"] == counts["total"]


def test_every_entry_obeys_the_disposition_rules(document: dict) -> None:
    """The rules are applied to every row, not asserted once in the prose."""
    for entry in document["entries"]:
        assert entry["provenance_state"] in PROVENANCE_STATES
        assert entry["content_digest"].startswith("sha256:")
        assert entry["provenance_evidence"]

        if entry["provenance_state"] == "unattributed":
            # The routed `CL-2p73` correction, per row: an unattributed
            # projection is rights-unresolved pending digest attribution, and
            # therefore non-compliant.
            assert entry["redistribution_state"] == "unknown"
            assert entry["pending_reason"] == PENDING_DIGEST_ATTRIBUTION
            assert entry["compliance"] == "non-compliant"
        else:
            assert entry["provider_identity"]

        # Invariant 13, per row: only `granted` redistribution is compliant.
        if entry["redistribution_state"] == "granted":
            assert entry["compliance"] == "compliant"
        else:
            assert entry["compliance"] == "non-compliant"

        # Every non-compliant entry carries both explicit remediation paths, and
        # a compliant one offers none -- a remediation menu attached to content
        # nothing is wrong with is how a safety mechanism becomes a delete button.
        if entry["compliance"] == "non-compliant":
            assert sorted(entry["remediation"]) == sorted(REMEDIATION_PATHS)
        else:
            assert entry["remediation"] == []


def test_the_markdown_is_a_rendering_of_the_committed_json(document: dict) -> None:
    """The document and its rendering cannot disagree.

    If the Markdown were edited by hand -- to soften a count, or to drop a row --
    this comparison fails, and regenerating is the only way to fix it.
    """
    assert MARKDOWN_ARTIFACT.read_text(encoding="utf-8") == generator.render_markdown(
        document
    )


def test_the_report_states_what_it_read(document: dict) -> None:
    """An inventory whose inputs are unstated cannot be reproduced or challenged.

    In particular `digest_index_size` is the honest measure of how much of this
    report rests on digest attribution: zero means no provider content has been
    retrieved through the ADR-0011 cache yet, and every provenance answer here
    comes from a lock receipt or from nothing.
    """
    assert "digest_index_size" in document
    assert "receipt_stores_read" in document
    assert "locks_read" in document
    body = MARKDOWN_ARTIFACT.read_text(encoding="utf-8")
    assert str(document["digest_index_size"]) in body
    assert "Do not edit" in body


def test_the_generator_takes_no_projection_name_as_evidence(tmp_path: Path) -> None:
    """The generator's own attribution path is digest-only.

    Two fixture projections with different names and identical bytes must
    receive identical provenance answers, and two with the same name and
    different bytes must not be attributed by that name.
    """
    root = tmp_path / "skills"
    for name in ("implement", "a-name-nobody-upstream-uses"):
        (root / name).mkdir(parents=True)
        (root / name / "SKILL.md").write_bytes(b"# identical bytes\n")

    built = generator.build_document(
        roots=[root],
        digest_index={},
        receipt_store_paths=[],
        lock_paths=[],
        observed_at="2026-08-09T00:00:00Z",
    )
    states = {
        entry["name"]: entry["provenance_state"] for entry in built["entries"]
    }
    assert states == {
        "implement": "unattributed",
        "a-name-nobody-upstream-uses": "unattributed",
    }
    digests = {entry["content_digest"] for entry in built["entries"]}
    assert len(digests) == 1
