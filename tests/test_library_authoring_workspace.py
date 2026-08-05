from __future__ import annotations

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

    assert {(root["type"], root["name"]) for root in manifest["roots"]} == FORGE_ROOTS


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
