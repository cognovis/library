"""Delivery contract for the default Cognovis project Workspace."""

from __future__ import annotations

from pathlib import Path
import sys

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.catalog import load_catalog  # noqa: E402
from lib.workspace import resolve_workspace, resolve_workspace_closure  # noqa: E402
import library as library_cli  # noqa: E402


EXPECTED_ARTIFACTS = {
    ("agent", "bead-boundary-reviewer"),
    ("agent", "bead-change-reviewer"),
    ("agent", "bead-depth-reviewer"),
    ("agent", "bead-implementer"),
    ("agent", "bead-loop-implementer"),
    ("agent", "bead-review-adjudicator"),
    ("agent", "doc-changelog-updater"),
    ("agent", "judge-default"),
    ("agent", "plan-reviewer"),
    ("skill", "acpx-dispatch"),
    ("skill", "bead-execution-loop"),
    ("skill", "bead-implementation-loop"),
    ("skill", "cognovis-beads"),
    ("skill", "executive-pack"),
    ("skill", "inject-standards"),
    ("skill", "library"),
    ("skill", "ob-cli"),
    ("standard", "executive-pack"),
    ("standard", "judge-layer"),
    ("standard", "model-routing"),
    ("standard", "workflow"),
}

EXPECTED_GLOBAL_PREREQUISITES = {
    ("script", "ccore"),
    ("skill", "session-close"),
    ("standard", "english-only"),
    ("standard", "no-emoji"),
}


def test_cognovis_base_resolves_the_complete_solo_and_pack_delivery_contract() -> None:
    catalog = load_catalog(REPO_ROOT)
    workspace = resolve_workspace(catalog, "library-platform:cognovis-base")

    assert workspace.entry["catalogs"] == [
        {
            "alias": "platform",
            "identity": "https://github.com/cognovis/library",
            "pin": {
                "kind": "commit",
                "value": "5797bbc3a256c517931ca6a77b93741654a1637d",
            },
        },
        {
            "alias": "core",
            "identity": "https://github.com/cognovis/library-core",
            "pin": {
                "kind": "commit",
                "value": "b7a54ca0da8bc0bc7acc5bacadd225ca1f1402bb",
            },
        },
        {
            "alias": "ccore",
            "identity": "https://github.com/cognovis/ccore",
            "pin": {
                "kind": "commit",
                "value": "ee0c185ce6dd9ddafbb23e72f858fe6eea3a37b1",
            },
        },
    ]
    assert {
        (root["type"], root["name"], root["catalog"])
        for root in workspace.entry["roots"]
    } == {
        ("skill", "library", "platform"),
        ("skill", "cognovis-beads", "core"),
        ("skill", "inject-standards", "core"),
        ("skill", "ob-cli", "core"),
        ("skill", "bead-implementation-loop", "core"),
        ("skill", "executive-pack", "core"),
    }

    closure = resolve_workspace_closure(
        catalog,
        workspace,
        REPO_ROOT,
        "project",
        pin_verifier=library_cli._workspace_pin_verifier(catalog),
    )

    assert set(closure.artifacts) == EXPECTED_ARTIFACTS
    assert set(closure.prerequisites) == EXPECTED_GLOBAL_PREREQUISITES


def test_readme_documents_the_launcher_and_propagation_contract() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    for command in (
        'cld -sb CL-123 -- "Focus on the API boundary."',
        'cdx --solo-bead CL-123 -- "Focus on the API boundary."',
        "cld -b CL-123",
        "cdx -b CL-123",
        "cld -ep CL-101,CL-102",
        "cdx --executive-pack CL-101,CL-102",
    ):
        assert command in readme

    for contract in (
        "GPT-5.6-sol with medium reasoning",
        "Opus implementation",
        "GPT-5.6-sol reviewer with high reasoning",
        "Kimi",
        "GPT-5.6 reviewer with high reasoning",
        "`bash install.sh` upgrades the global control plane",
        "`library init` or Workspace sync installs project-local Skills",
        "does not install global desired-state Skills",
        "must not overwrite `~/.agents/skills`",
        "Topic coordination is optional",
    ):
        assert contract in readme

    manifest = yaml.safe_load(
        (REPO_ROOT / "workspaces" / "cognovis-base.yaml").read_text(encoding="utf-8")
    )
    assert {root["name"] for root in manifest["roots"]} >= {
        "bead-implementation-loop",
        "executive-pack",
    }
