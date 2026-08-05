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


def test_library_authoring_stable_evidence_names_two_committed_consumers() -> None:
    evidence = json.loads(
        (REPO_ROOT / "workspaces" / "admission-evidence.json").read_text()
    )

    assert evidence["library-authoring"]["consumer_locks"] == [
        {
            "repository": "cognovis/library",
            "lock_path": ".library.lock",
            "commit": "0449abc628915c4ace93ed447458646052382ff1",
            "schema_version": 2,
        },
        {
            "repository": "cognovis/cognovis-pi",
            "lock_path": ".library.lock",
            "commit": "2fcc0e8c386d742fb9169fbac9870a8ba6bbb8d8",
            "schema_version": 2,
        },
    ]


def test_library_authoring_roots_resolve_standalone() -> None:
    catalog = load_catalog(REPO_ROOT)
    workspace = resolve_workspace(catalog, "library-platform:library-authoring")

    closure = resolve_workspace_closure(catalog, workspace, REPO_ROOT, "project")

    assert set(closure.artifacts) == FORGE_ROOTS | {
        ("standard", "agentic-primitives"),
        ("standard", "primitive-placement"),
    }
    assert set(closure.prerequisites) == {
        ("standard", "english-only"),
        ("standard", "no-emoji"),
    }


def test_platform_lock_registers_python_and_authoring_workspaces() -> None:
    lock = yaml.safe_load((REPO_ROOT / ".library.lock").read_text())

    assert {(root["type"], root["name"]) for root in lock["requested_roots"]} == {
        ("workspace", "library-authoring"),
        ("workspace", "python-cli"),
    }
    assert {receipt["id"] for receipt in lock["receipts"]} == {
        "skill:agent-forge",
        "skill:hook-forge",
        "skill:python-dev",
        "skill:python-test",
        "skill:script-forge",
        "skill:skill-forge",
        "skill:standard-forge",
        "standard:agentic-primitives",
        "standard:primitive-placement",
        "standard:python-cli-patterns",
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
            assert not Path(bridge_path).is_absolute()
            assert not Path(bridge_target).is_absolute()
