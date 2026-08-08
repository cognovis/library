"""Tests for the ADR Pi Workflow executor evidence checks (CL-2p73, AC3).

The ADR may supersede ADR-0006 only when an objective, executable evidence
threshold is met. These tests pin the check identities, the threshold function,
and the artifact shape so the recorded verdict cannot drift from the checks that
produced it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "checks"))

import pi_workflow_executor_evidence  # noqa: E402

CONSTITUTIVE = ("PWE-2", "PWE-3", "PWE-4", "PWE-5")
MIGRATION = ("PWE-6", "PWE-7", "PWE-8")


def test_check_identities_are_stable_and_complete() -> None:
    ids = [check.check_id for check in pi_workflow_executor_evidence.CHECKS]
    assert ids == [
        "PWE-1",
        "PWE-2",
        "PWE-3",
        "PWE-4",
        "PWE-5",
        "PWE-6",
        "PWE-7",
        "PWE-8",
    ]
    for check in pi_workflow_executor_evidence.CHECKS:
        assert check.title.strip()
        assert check.method.strip()


def test_constitutive_and_migration_partition_matches_threshold() -> None:
    assert pi_workflow_executor_evidence.CONSTITUTIVE_CHECKS == CONSTITUTIVE
    assert pi_workflow_executor_evidence.MIGRATION_CHECKS == MIGRATION
    # PWE-1 is runtime context, never a threshold input.
    assert "PWE-1" not in CONSTITUTIVE + MIGRATION


def test_threshold_supersedes_only_when_every_required_check_passes() -> None:
    evaluate = pi_workflow_executor_evidence.evaluate_threshold
    all_pass = {check_id: "pass" for check_id in CONSTITUTIVE + MIGRATION}
    all_pass["PWE-1"] = "pass"
    assert evaluate(all_pass)["verdict"] == "supersede-adr-0006"

    one_unavailable = dict(all_pass)
    one_unavailable["PWE-4"] = "unavailable"
    result = evaluate(one_unavailable)
    assert result["verdict"] == "retain-adr-0006"
    assert result["failed_checks"] == ["PWE-4"]

    one_failed = dict(all_pass)
    one_failed["PWE-7"] = "fail"
    result = evaluate(one_failed)
    assert result["verdict"] == "retain-adr-0006"
    assert result["failed_checks"] == ["PWE-7"]


def test_threshold_ignores_context_check_outcome() -> None:
    evaluate = pi_workflow_executor_evidence.evaluate_threshold
    outcomes = {check_id: "pass" for check_id in CONSTITUTIVE + MIGRATION}
    outcomes["PWE-1"] = "unavailable"
    assert evaluate(outcomes)["verdict"] == "supersede-adr-0006"


def test_threshold_rejects_an_incomplete_outcome_map() -> None:
    evaluate = pi_workflow_executor_evidence.evaluate_threshold
    with pytest.raises(ValueError):
        evaluate({"PWE-2": "pass"})


def test_run_produces_a_typed_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence.json"
    exit_code = pi_workflow_executor_evidence.main(
        ["--repo-root", str(REPO_ROOT), "--output", str(artifact)]
    )
    assert exit_code in (0, 2)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["schema"] == "cognovis.pi-workflow-executor-evidence.v1"
    assert payload["bead_id"] == "CL-2p73"
    assert payload["verdict"] in ("supersede-adr-0006", "retain-adr-0006")
    assert [item["check_id"] for item in payload["checks"]] == [
        check.check_id for check in pi_workflow_executor_evidence.CHECKS
    ]
    for item in payload["checks"]:
        assert item["result"] in ("pass", "fail", "unavailable")
        assert item["evidence"].strip()


def test_committed_artifact_matches_the_recorded_adr_verdict() -> None:
    """The ADR quotes this artifact; a drifted artifact must fail the suite."""
    artifact = REPO_ROOT / "docs" / "research" / "pi-workflow-executor-evidence.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    outcomes = {item["check_id"]: item["result"] for item in payload["checks"]}
    recomputed = pi_workflow_executor_evidence.evaluate_threshold(outcomes)
    assert recomputed["verdict"] == payload["verdict"]
    assert recomputed["failed_checks"] == payload["failed_checks"]
