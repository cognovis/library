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
    ("agent", "bead-review-adjudicator"),
    # The two advisors Repository Delivery invokes on demand. clc-d8ol moved
    # them into the source SKILL.md's `requires:`; the catalog entry has to
    # carry the same edges or a consumer repository installs a delivery skill
    # whose own closure cannot satisfy what it declares.
    ("agent", "doc-changelog-updater"),
    ("agent", "plan-reviewer"),
    ("skill", "acpx-dispatch"),
    ("skill", "bead-execution-loop"),
    ("skill", "cognovis-beads"),
    ("skill", "executive-pack"),
    ("skill", "inject-standards"),
    ("skill", "library"),
    ("skill", "ob-cli"),
    ("skill", "session-close"),
    ("standard", "executive-pack"),
    # clc-i19u: the transport skill declares `requires_standards:
    # [mcp-client-timeout]` and nothing else, so aligning its catalog entry with
    # that contract is what pulls this standard into the closure -- and what drops
    # agent:judge-default and standard:judge-layer out of it. Those two were here
    # only because the retired cognovis-core copy's entry claimed edges the skill
    # never declared; no other member of this Workspace requires them.
    ("standard", "mcp-client-timeout"),
    ("standard", "model-routing"),
    ("standard", "workflow"),
}

# ccore is a PATH binary declared through runtime_requirements, exactly like
# bd and git; since the CL-9yok recut the delivery closure carries no global
# prerequisite at all.
EXPECTED_GLOBAL_PREREQUISITES = set()


def test_cognovis_base_resolves_the_complete_solo_and_pack_delivery_contract() -> None:
    catalog = load_catalog(REPO_ROOT)
    workspace = resolve_workspace(catalog, "library-platform:cognovis-base")

    assert workspace.entry["catalogs"] == [
        {
            "alias": "platform",
            "identity": "https://github.com/cognovis/library",
            "pin": {
                "kind": "commit",
                "value": "aaca41ffea3e1db9937054f6a8f7f597f729cfb6",
            },
        },
        {
            "alias": "core",
            "identity": "https://github.com/cognovis/library-core",
            "pin": {
                "kind": "commit",
                "value": "a4e69a2b0d971ff4023103aaf2457bf04859bc5f",
            },
        },
        # clc-i19u: the closure reaches skill:acpx-dispatch, which ccore serves
        # beside the `ccore acpx` command the skill documents.
        {
            "alias": "ccore",
            "identity": "https://github.com/cognovis/ccore",
            "pin": {
                "kind": "commit",
                "value": "fc6162a9a1734c77e7cb2733c3160665f71d5220",
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
        ("skill", "executive-pack", "core"),
        ("skill", "session-close", "core"),
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
        "executive-pack",
    }
