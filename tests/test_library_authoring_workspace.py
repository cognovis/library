from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.catalog import load_catalog
from lib.workspace import resolve_workspace, resolve_workspace_closure


FORGE_ROOTS = {
    ("skill", "agent-forge"),
    ("skill", "hook-forge"),
    ("skill", "script-forge"),
    ("skill", "skill-forge"),
    ("skill", "standard-forge"),
}


def test_library_authoring_manifest_has_exact_platform_forge_roots() -> None:
    manifest = yaml.safe_load(
        (REPO_ROOT / "workspaces" / "library-authoring.yaml").read_text()
    )

    assert manifest["status"] == "stable"
    assert {(root["type"], root["name"]) for root in manifest["roots"]} == FORGE_ROOTS


def test_library_authoring_stable_evidence_names_distinct_consumers() -> None:
    evidence = json.loads(
        (REPO_ROOT / "workspaces" / "admission-evidence.json").read_text()
    )

    consumers = evidence["library-authoring"]["consumer_locks"]
    assert {consumer["repository"] for consumer in consumers} == {
        "cognovis/library",
        "cognovis/cognovis-pi",
    }
    for consumer in consumers:
        assert consumer["lock_path"] == ".library.lock"
        assert len(consumer["commit"]) == 40
        assert all(character in "0123456789abcdef" for character in consumer["commit"])
        assert type(consumer["schema_version"]) is int
        assert consumer["schema_version"] == 2


def test_library_authoring_roots_resolve_standalone() -> None:
    catalog = load_catalog(REPO_ROOT)
    workspace = resolve_workspace(catalog, "library-platform:library-authoring")

    closure = resolve_workspace_closure(catalog, workspace, REPO_ROOT, "project")

    # Since the CL-9yok recut nothing in this closure is satisfied from outside
    # the repository, so it carries no prerequisite at all.
    assert set(closure.artifacts) == FORGE_ROOTS | {
        ("standard", "agentic-primitives"),
        ("standard", "judge-layer"),
        ("standard", "primitive-placement"),
    }
    assert set(closure.prerequisites) == set()


def test_platform_lock_registers_baseline_daily_python_and_authoring_workspaces() -> None:
    lock = yaml.safe_load((REPO_ROOT / ".library.lock").read_text())

    assert {(root["type"], root["name"]) for root in lock["requested_roots"]} == {
        ("workspace", "cognovis-base"),
        ("workspace", "cognovis-daily"),
        ("workspace", "library-authoring"),
        ("workspace", "python-cli"),
    }
    # The committed receipt set is the union of those four closures. No receipt
    # of the retired parallel single-bead lifecycle survives in it.
    receipt_ids = {receipt["id"] for receipt in lock["receipts"]}
    assert receipt_ids == {
        "agent:bead-boundary-reviewer",
        "agent:bead-change-reviewer",
        "agent:bead-depth-reviewer",
        "agent:bead-implementer",
        "agent:bead-review-adjudicator",
        # Repository Delivery's on-demand advisors, reachable through
        # skill:executive-pack since the catalog entry regained the edges
        # clc-d8ol moved into the source SKILL.md.
        "agent:doc-changelog-updater",
        "agent:judge-default",
        "agent:plan-reviewer",
        "skill:acpx-dispatch",
        "skill:agent-forge",
        "skill:bead-execution-loop",
        "skill:bead-reviewer",
        "skill:bug-triage",
        "skill:cognovis-beads",
        "skill:context-handoff",
        "skill:dolt",
        "skill:executive-pack",
        "skill:hook-forge",
        "skill:inject-standards",
        "skill:intake",
        "skill:library",
        "skill:ob-cli",
        "skill:playwright-cli",
        "skill:python-dev",
        "skill:python-test",
        "skill:script-forge",
        "skill:session-close",
        "skill:skill-forge",
        "skill:standard-forge",
        "skill:summarize",
        "skill:workplan",
        "skill:worktree-cleanup",
        "standard:agentic-primitives",
        "standard:bead-hygiene",
        "standard:executive-pack",
        "standard:git",
        "standard:judge-layer",
        "standard:model-routing",
        "standard:primitive-placement",
        "standard:python-cli-patterns",
        "standard:tool-standards",
        "standard:workflow",
        "standard:worktree-subagent-discipline",
    }
    for receipt in lock["receipts"]:
        assert not Path(receipt["install_target"]).is_absolute()
        assert all(
            not Path(target["path"]).is_absolute()
            for target in receipt["targets"]
        )
        for bridge in receipt.get("bridge_symlinks") or []:
            bridge_path, separator, bridge_target = bridge.partition(" -> ")
            assert separator
            # The bridge lives in the repository; only where it points may leave
            # it. `installers/agent.py` deliberately points a Codex agent bridge
            # at the machine-local Layer-B cache file, so an agent receipt's
            # bridge target is absolute by construction. That exemption is
            # named, not open-ended: every other primitive keeps a
            # repository-relative target.
            assert not Path(bridge_path).is_absolute()
            if not receipt["id"].startswith("agent:"):
                assert not Path(bridge_target).is_absolute()
