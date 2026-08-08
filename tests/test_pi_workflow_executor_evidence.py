"""Tests for the ADR-0011 Pi Workflow executor evidence checks (CL-2p73, AC3).

ADR-0011 may supersede ADR-0006 only when an objective, executable evidence
threshold is met. These tests pin the check identities, the threshold function,
and the artifact shape so the recorded verdict cannot drift from the checks that
produced it.

They also enforce the property that adversarial review found missing in the first
draft: **every threshold check has a reachable `pass` path**. A check hard-coded
to fail would weld the ADR's re-entry gate shut and make its "the verdict flips
automatically when the world changes" claim false. Each check therefore gets a
paired pass/fail test against synthetic contexts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "checks"))

import pi_workflow_executor_evidence as pwe  # noqa: E402

CONSTITUTIVE = ("PWE-2", "PWE-3", "PWE-4", "PWE-5")
MIGRATION = ("PWE-6", "PWE-7", "PWE-8")
THRESHOLD_CHECKS = CONSTITUTIVE + MIGRATION

PI_HELP_WITHOUT_EXECUTOR = """
Usage:
  pi [options] [@files...] [messages...]

Commands:
  pi install <source>          Install extension source
  pi remove <source>           Remove extension source
  pi list                      List installed extensions
  pi config                    Open TUI
  pi auth <command>            Print credentials

Options:
  --continue, -c               Continue previous session
  --resume, -r                 Select a session to resume
"""

PI_HELP_WITH_EXECUTOR = PI_HELP_WITHOUT_EXECUTOR.replace(
    "  pi list                      List installed extensions",
    "  pi list                      List installed extensions\n"
    "  pi workflow <spec>           Execute a workflow spec",
)


def _context(**overrides):
    base = dict(
        repo_root=REPO_ROOT,
        pi_executable="/usr/local/bin/pi",
        pi_version="0.84.1",
        pi_help=PI_HELP_WITHOUT_EXECUTOR,
        subcommand_help={},
        spec_runner=lambda entrypoint, spec: (1, ""),
        env={},
        projection_roots=(),
        lock_search_roots=(),
    )
    base.update(overrides)
    return pwe.Context(**base)


def _run(check_id, ctx, shared=None):
    check = next(item for item in pwe.CHECKS if item.check_id == check_id)
    return check.runner(ctx, shared if shared is not None else {})


# ---------------------------------------------------------------- identities


def test_check_identities_are_stable_and_complete() -> None:
    ids = [check.check_id for check in pwe.CHECKS]
    assert ids == ["PWE-1", "PWE-2", "PWE-3", "PWE-4", "PWE-5", "PWE-6", "PWE-7", "PWE-8"]
    for check in pwe.CHECKS:
        assert check.title.strip()
        assert check.method.strip()


def test_constitutive_and_migration_partition_matches_threshold() -> None:
    assert pwe.CONSTITUTIVE_CHECKS == CONSTITUTIVE
    assert pwe.MIGRATION_CHECKS == MIGRATION
    assert "PWE-1" not in THRESHOLD_CHECKS


# ---------------------------------------------------------------- threshold


def test_threshold_supersedes_only_when_every_required_check_passes() -> None:
    all_pass = {check_id: "pass" for check_id in THRESHOLD_CHECKS} | {"PWE-1": "pass"}
    assert pwe.evaluate_threshold(all_pass)["verdict"] == "supersede-adr-0006"

    result = pwe.evaluate_threshold(all_pass | {"PWE-4": "unavailable"})
    assert result["verdict"] == "retain-adr-0006"
    assert result["failed_checks"] == ["PWE-4"]

    result = pwe.evaluate_threshold(all_pass | {"PWE-7": "fail"})
    assert result["verdict"] == "retain-adr-0006"
    assert result["failed_checks"] == ["PWE-7"]


def test_threshold_ignores_context_check_outcome() -> None:
    outcomes = {check_id: "pass" for check_id in THRESHOLD_CHECKS} | {"PWE-1": "unavailable"}
    assert pwe.evaluate_threshold(outcomes)["verdict"] == "supersede-adr-0006"


def test_threshold_rejects_an_incomplete_outcome_map() -> None:
    with pytest.raises(ValueError):
        pwe.evaluate_threshold({"PWE-2": "pass"})


# ------------------------------------------------- every check can pass/fail


@pytest.mark.parametrize("check_id", THRESHOLD_CHECKS)
def test_every_threshold_check_has_a_reachable_pass_path(check_id, tmp_path) -> None:
    """No threshold check may be hard-coded to fail.

    This is the regression guard for the review finding that three checks could
    never return `pass`, which would make the ADR's documented re-entry condition
    unreachable.
    """
    ctx, shared = _passing_fixture(check_id, tmp_path)
    result, evidence = _run(check_id, ctx, shared)
    assert result == pwe.PASS, f"{check_id} could not pass: {evidence}"
    assert evidence.strip()


@pytest.mark.parametrize("check_id", THRESHOLD_CHECKS)
def test_every_threshold_check_has_a_reachable_fail_path(check_id, tmp_path) -> None:
    ctx, shared = _failing_fixture(check_id, tmp_path)
    result, evidence = _run(check_id, ctx, shared)
    assert result == pwe.FAIL, f"{check_id} could not fail: {evidence}"
    assert evidence.strip()


def _fake_repo(tmp_path: Path, *, pi_target: bool, pi_gate: bool, verified_adapter: bool) -> Path:
    root = tmp_path / "repo"
    (root / "scripts" / "lib" / "installers").mkdir(parents=True)
    workflow_entry = '    install_subdir="workflows",\n'
    if pi_target:
        workflow_entry += '    pi_install_subdir="pi/workflows",\n'
    (root / "scripts" / "lib" / "primitives.py").write_text(
        'PRIMITIVES = (\n    PrimitiveInfo(\n        name="workflow",\n'
        f"{workflow_entry}"
        '    ),\n    PrimitiveInfo(\n        name="pi-extension",\n    ),\n)\n',
        encoding="utf-8",
    )
    gate = (
        "def _pi_parse_gate(name):\n    return True\n\n\n"
        "def install(name):\n    return _pi_parse_gate(name)\n"
        if pi_gate
        else ""
    )
    (root / "scripts" / "lib" / "installers" / "simple_file.py").write_text(
        '"""Workflow installer."""\n'
        "# export const meta and node --check are mentioned only in this comment\n"
        f"{gate}"
        'NATIVE = "export const meta"\nCMD = "node --check"\n',
        encoding="utf-8",
    )
    status = '"claude-agent": "verified",' if verified_adapter else '"claude-agent": "blocked",'
    (root / "scripts" / "lib" / "workflow_runtime.py").write_text(
        f"ADAPTER_PRESERVATION_STATUS = {{{status} \"codex-exec\": \"blocked\"}}\n",
        encoding="utf-8",
    )
    (root / "library.yaml").write_text("library:\n  workflows: []\n", encoding="utf-8")
    return root


def _design_doc(tmp_path: Path, *, inert: bool) -> Path:
    """Create a sibling `cognovis-pi` design document relative to a fake repo."""
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    docs = tmp_path / "cognovis-pi" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    body = "# Pi harness\n\nThe extension owns a pack state machine.\n"
    if not inert:
        body += "\n- Git and Beads adapters\n- Evidence store\n"
    (docs / "native-executive-pack-harness.md").write_text(body, encoding="utf-8")
    return repo


def _passing_fixture(check_id: str, tmp_path: Path):
    if check_id == "PWE-2":
        return _context(
            pi_help=PI_HELP_WITH_EXECUTOR,
            spec_runner=lambda entrypoint, spec: (0, "PWE_GLOBALS=agent,pipeline\n"),
        ), {}
    if check_id == "PWE-3":
        shared = {
            "executor_entrypoint": "workflow",
            "executor_output": "PWE_GLOBALS=" + ",".join(pwe.WORKFLOW_GLOBALS),
        }
        return _context(pi_help=PI_HELP_WITH_EXECUTOR), shared
    if check_id == "PWE-4":
        return (
            _context(
                pi_help=PI_HELP_WITH_EXECUTOR,
                subcommand_help={
                    "workflow": "  --journal <dir>   Run journal location\n  --resume   Resume a run\n"
                },
            ),
            {"executor_entrypoint": "workflow"},
        )
    if check_id == "PWE-5":
        return _context(repo_root=_design_doc(tmp_path, inert=True)), {}
    if check_id == "PWE-6":
        root = _fake_repo(tmp_path, pi_target=True, pi_gate=False, verified_adapter=False)
        projections = tmp_path / "projections"
        projections.mkdir(exist_ok=True)
        (projections / "alpha.js").write_text("// alpha\n", encoding="utf-8")
        (root / ".library.lock").write_text(
            "receipts:\n- id: workflow:alpha\n  type: workflow\n  name: alpha\n", encoding="utf-8"
        )
        return _context(repo_root=root, projection_roots=(projections,)), {}
    if check_id == "PWE-7":
        root = _fake_repo(tmp_path, pi_target=False, pi_gate=True, verified_adapter=False)
        return _context(repo_root=root), {}
    if check_id == "PWE-8":
        root = _fake_repo(tmp_path, pi_target=False, pi_gate=False, verified_adapter=True)
        return _context(repo_root=root), {}
    raise AssertionError(check_id)


def _failing_fixture(check_id: str, tmp_path: Path):
    if check_id == "PWE-2":
        return _context(pi_help=PI_HELP_WITHOUT_EXECUTOR), {}
    if check_id == "PWE-3":
        return _context(), {}
    if check_id == "PWE-4":
        return _context(), {}
    if check_id == "PWE-5":
        return _context(repo_root=_design_doc(tmp_path, inert=False)), {}
    if check_id == "PWE-6":
        root = _fake_repo(tmp_path, pi_target=False, pi_gate=False, verified_adapter=False)
        return _context(repo_root=root), {}
    if check_id == "PWE-7":
        root = _fake_repo(tmp_path, pi_target=False, pi_gate=False, verified_adapter=False)
        return _context(repo_root=root), {}
    if check_id == "PWE-8":
        root = _fake_repo(tmp_path, pi_target=False, pi_gate=False, verified_adapter=False)
        return _context(repo_root=root, env={"CLAUDE_CODE_WORKFLOWS": "0"}), {}
    raise AssertionError(check_id)


# ------------------------------------------------------- specific behaviors


def test_pwe2_requires_execution_not_just_a_documented_command() -> None:
    """A documented entrypoint is necessary but not sufficient."""
    ctx = _context(pi_help=PI_HELP_WITH_EXECUTOR, spec_runner=lambda e, s: (1, "boom"))
    result, evidence = _run("PWE-2", ctx)
    assert result == pwe.FAIL
    assert "none executed a canonical probe spec" in evidence


def test_pwe2_publishes_the_entrypoint_for_dependent_checks() -> None:
    shared: dict = {}
    ctx = _context(pi_help=PI_HELP_WITH_EXECUTOR, spec_runner=lambda e, s: (0, "PWE_GLOBALS=agent"))
    assert _run("PWE-2", ctx, shared)[0] == pwe.PASS
    assert shared["executor_entrypoint"] == "workflow"


def test_pwe3_fails_when_globals_are_partially_injected() -> None:
    shared = {"executor_entrypoint": "workflow", "executor_output": "PWE_GLOBALS=agent,parallel"}
    result, evidence = _run("PWE-3", _context(), shared)
    assert result == pwe.FAIL
    assert "missing" in evidence


def test_pwe4_rejects_conversational_session_resume_as_run_resume() -> None:
    """`--continue`/`--resume` on the top-level session surface must not pass."""
    ctx = _context(pi_help=PI_HELP_WITH_EXECUTOR, subcommand_help={"workflow": "  --help\n"})
    result, evidence = _run("PWE-4", ctx, {"executor_entrypoint": "workflow"})
    assert result == pwe.FAIL
    assert "journal" in evidence.lower()


def test_pwe7_ignores_a_gate_mentioned_only_in_a_comment(tmp_path) -> None:
    """The old marker-string check could be satisfied by a comment."""
    root = _fake_repo(tmp_path, pi_target=False, pi_gate=False, verified_adapter=False)
    installer = root / "scripts" / "lib" / "installers" / "simple_file.py"
    installer.write_text(
        installer.read_text(encoding="utf-8") + "# TODO: add pi workflow gate here\n",
        encoding="utf-8",
    )
    assert _run("PWE-7", _context(repo_root=root))[0] == pwe.FAIL


def test_pwe8_passes_on_the_canonical_native_executor(tmp_path) -> None:
    """ADR-0006's canonical executor is the native tool, not the Library runtime."""
    root = _fake_repo(tmp_path, pi_target=False, pi_gate=False, verified_adapter=False)
    ctx = _context(repo_root=root, env={"CLAUDE_CODE_WORKFLOWS": "1"})
    result, evidence = _run("PWE-8", ctx)
    assert result == pwe.PASS
    assert "native Workflow tool" in evidence


def test_a_fully_capable_world_reaches_supersession(tmp_path) -> None:
    """End-to-end proof that the re-entry condition is reachable, not welded shut."""
    root = _fake_repo(tmp_path, pi_target=True, pi_gate=True, verified_adapter=True)
    docs = tmp_path / "cognovis-pi" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "native-executive-pack-harness.md").write_text(
        "# Pi harness\n\nThe spine is inert.\n", encoding="utf-8"
    )
    ctx = _context(
        repo_root=root,
        pi_help=PI_HELP_WITH_EXECUTOR,
        subcommand_help={"workflow": "  --journal <dir>\n  --resume\n"},
        spec_runner=lambda e, s: (0, "PWE_GLOBALS=" + ",".join(pwe.WORKFLOW_GLOBALS)),
        env={"CLAUDE_CODE_WORKFLOWS": "1"},
    )
    payload = pwe.run_checks(root, ctx=ctx)
    assert payload["verdict"] == "supersede-adr-0006", payload["checks"]
    assert payload["failed_checks"] == []


# ------------------------------------------------------------- artifact shape


def test_run_produces_a_typed_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence.json"
    exit_code = pwe.main(["--repo-root", str(REPO_ROOT), "--output", str(artifact)])
    assert exit_code in (0, 2)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["schema"] == "cognovis.pi-workflow-executor-evidence.v1"
    assert payload["bead_id"] == "CL-2p73"
    assert payload["verdict"] in ("supersede-adr-0006", "retain-adr-0006")
    assert [item["check_id"] for item in payload["checks"]] == [c.check_id for c in pwe.CHECKS]
    for item in payload["checks"]:
        assert item["result"] in pwe.RESULTS
        assert item["evidence"].strip()


def test_committed_artifact_matches_the_recorded_adr_verdict() -> None:
    """The ADR quotes this artifact; a drifted artifact must fail the suite."""
    artifact = REPO_ROOT / "docs" / "research" / "pi-workflow-executor-evidence.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["schema"] == "cognovis.pi-workflow-executor-evidence.v1"
    assert payload["constitutive_checks"] == list(CONSTITUTIVE)
    assert payload["migration_checks"] == list(MIGRATION)
    # Identities, titles, and outcome vocabulary must all be intact, so a
    # hand-edited artifact fails on content and not only on the verdict field.
    assert [item["check_id"] for item in payload["checks"]] == [c.check_id for c in pwe.CHECKS]
    assert [item["title"] for item in payload["checks"]] == [c.title for c in pwe.CHECKS]
    for item in payload["checks"]:
        assert item["result"] in pwe.RESULTS
        assert item["evidence"].strip()
    outcomes = {item["check_id"]: item["result"] for item in payload["checks"]}
    recomputed = pwe.evaluate_threshold(outcomes)
    assert recomputed["verdict"] == payload["verdict"]
    assert recomputed["failed_checks"] == payload["failed_checks"]
    assert recomputed["threshold"] == payload["threshold"]


def test_pwe6_rejects_receipt_counts_that_do_not_cover_the_projections(tmp_path) -> None:
    """Coverage must be per projection, not a count comparison.

    Regression guard for the round-2 finding that `len(materialized) - len(receipts)`
    could certify coverage no projection actually had: five receipts for unrelated
    workflows in other repositories must not cover four uncovered projections.
    """
    root = _fake_repo(tmp_path, pi_target=True, pi_gate=False, verified_adapter=False)
    projections = tmp_path / "projections"
    projections.mkdir()
    for name in ("bead-review", "quick-fix", "stream-review", "bead-context-pack"):
        (projections / f"{name}.js").write_text("// x\n", encoding="utf-8")
    other = tmp_path / "other-repo"
    other.mkdir()
    (other / ".library.lock").write_text(
        "receipts:\n"
        + "".join(
            f"- id: workflow:unrelated-{i}\n  type: workflow\n  name: unrelated-{i}\n"
            for i in range(5)
        ),
        encoding="utf-8",
    )
    ctx = _context(
        repo_root=root,
        projection_roots=(projections,),
        lock_search_roots=(tmp_path,),
    )
    result, evidence = _run("PWE-6", ctx)
    assert result == pwe.FAIL
    assert "no matching workflow receipt by name" in evidence
    assert "bead-review" in evidence


def test_pwe7_rejects_a_gate_that_is_defined_but_never_called(tmp_path) -> None:
    """A defined-but-unreached gate is dead code, not a deploy gate."""
    root = _fake_repo(tmp_path, pi_target=False, pi_gate=False, verified_adapter=False)
    installer = root / "scripts" / "lib" / "installers" / "simple_file.py"
    installer.write_text(
        installer.read_text(encoding="utf-8") + "def _pi_parse_gate(name):\n    return True\n",
        encoding="utf-8",
    )
    result, evidence = _run("PWE-7", _context(repo_root=root))
    assert result == pwe.FAIL
    assert "never calls it" in evidence
