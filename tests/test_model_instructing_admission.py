"""Model-instructing foreign content is admission-required (ADR-0011, CL-lt51).

Human Decision HD-5 (Malte Sussdorff, 2026-08-10): content a model follows as
instructions -- Skills, Prompts, Agents, Standards -- is executed by the model in
an agent harness, and its realistic attack is prompt injection delivered through
an upstream update. Trust therefore binds to the pin, not to the steward, and a
foreign steward's model-instructing item requires the same digest-bound admission
decision an executable does.

What these tests hold down is the *boundary*: the requirement follows foreign
stewardship, and first-party catalog content is never blocked by it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.classification import (  # noqa: E402
    EXECUTABLE_TYPES,
    FIRST_PARTY,
    FOREIGN,
    MODEL_INSTRUCTING_TYPES,
    executable_admission_for,
    requires_admission,
    stewardship_of_classification,
    validated_stewardship,
)
from lib.providers.executable_admission import (  # noqa: E402
    ADMITTED,
    INERT,
    PENDING,
    AdmissionRecord,
    ExecutableAdmissionLedger,
    FirstPartyAdmission,
    InertContentNotAdmissible,
    content_digest,
)


class TestAdmissionRequiredPredicate:
    def test_foreign_model_instructing_content_requires_admission(self):
        for library_type in sorted(MODEL_INSTRUCTING_TYPES):
            assert requires_admission(library_type, FOREIGN) is True

    def test_first_party_model_instructing_content_does_not(self):
        for library_type in sorted(MODEL_INSTRUCTING_TYPES):
            assert requires_admission(library_type, FIRST_PARTY) is False

    def test_executable_content_requires_admission_under_either_stewardship(self):
        for library_type in sorted(EXECUTABLE_TYPES):
            assert requires_admission(library_type, FOREIGN) is True
            assert requires_admission(library_type, FIRST_PARTY) is True

    def test_unclassified_and_documentation_content_stays_inert(self):
        assert requires_admission("unclassified", FOREIGN) is False
        assert requires_admission("marketplace", FOREIGN) is False

    def test_an_unknown_stewardship_is_refused_rather_than_guessed(self):
        with pytest.raises(ValueError, match="stewardship"):
            requires_admission("skill", "probably-fine")
        with pytest.raises(ValueError, match="stewardship"):
            validated_stewardship(None)

    def test_absent_recorded_stewardship_reads_as_foreign(self):
        # "We could not determine who stewards this" must never be more
        # permissive than "somebody else does".
        assert stewardship_of_classification({}) == FOREIGN
        assert stewardship_of_classification({"stewardship": FIRST_PARTY}) == FIRST_PARTY

    def test_initial_state_follows_the_same_boundary(self):
        assert executable_admission_for("skill", FOREIGN) == "pending"
        assert executable_admission_for("skill", FIRST_PARTY) == "inert"
        assert executable_admission_for("workflow", FIRST_PARTY) == "pending"


class TestLedgerCoversModelInstructingContent:
    def _files(self):
        return {"SKILL.md": b"---\nname: upstream-skill\n---\n\nDo the thing.\n"}

    def test_a_foreign_skill_with_no_decision_is_pending_not_inert(self):
        ledger = ExecutableAdmissionLedger()
        assert (
            ledger.state_for(
                "steward#skills/x", content_digest(self._files()),
                library_type="skill",
                stewardship=FOREIGN,
            )
            == PENDING
        )

    def test_the_same_type_is_inert_for_first_party_content(self):
        ledger = ExecutableAdmissionLedger()
        assert (
            ledger.state_for(
                "cognovis#skills/x", content_digest(self._files()),
                library_type="skill",
                stewardship=FIRST_PARTY,
            )
            == INERT
        )

    def test_a_recorded_grant_admits_exactly_those_bytes(self):
        digest = content_digest(self._files())
        ledger = ExecutableAdmissionLedger()
        ledger.admit(
            "steward#skills/x",
            digest,
            library_type="skill",
            reviewer="malte",
            permission_surface=("reads the repository",),
            decided_at="2026-08-10T09:00:00Z",
            evidence="Read the whole skill body; it routes and does not instruct any tool use.",
        )
        assert (
            ledger.state_for(
                "steward#skills/x", digest, library_type="skill", stewardship=FOREIGN
            )
            == ADMITTED
        )
        other = content_digest({"SKILL.md": b"different bytes entirely\n"})
        assert (
            ledger.state_for(
                "steward#skills/x", other, library_type="skill", stewardship=FOREIGN
            )
            == PENDING
        )

    def test_recording_a_decision_for_first_party_inert_content_is_refused(self):
        ledger = ExecutableAdmissionLedger()
        with pytest.raises(InertContentNotAdmissible):
            ledger.admit(
                "cognovis#docs/readme",
                content_digest({"README.md": b"hello\n"}),
                library_type="marketplace",
                reviewer="malte",
                permission_surface=(),
                decided_at="2026-08-10T09:00:00Z",
                evidence="This is documentation and holds no trust to grant.",
            )

    def test_stewardship_is_required_at_the_gate_never_defaulted(self):
        ledger = ExecutableAdmissionLedger()
        with pytest.raises(TypeError):
            ledger.state_for("steward#skills/x", None, library_type="skill")

    def test_first_party_authority_answers_the_same_boundary(self):
        digest = content_digest(self._files())
        authority = FirstPartyAdmission({"cognovis#skills/x": digest})
        assert (
            authority.state_for(
                "cognovis#skills/x", digest, library_type="skill", stewardship=FIRST_PARTY
            )
            == INERT
        )
        assert (
            authority.state_for(
                "cognovis#skills/x", digest, library_type="skill", stewardship=FOREIGN
            )
            == ADMITTED
        )


class TestRecordVocabulary:
    def test_a_record_may_be_written_for_a_model_instructing_type(self):
        record = AdmissionRecord(
            qualified_identity="steward#skills/x",
            content_digest=content_digest({"SKILL.md": b"body\n"}),
            state=ADMITTED,
            reviewer="malte",
            permission_surface=(),
            decided_at="2026-08-10T09:00:00Z",
            evidence="Reviewed the full body of this skill and found no tool instructions.",
        )
        assert record.state == ADMITTED
