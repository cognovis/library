"""Catalog contract for the canonical project-local cognovis-base Workspace."""

from __future__ import annotations

import sys
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.catalog import load_catalog  # noqa: E402
from lib.errors import LibraryError  # noqa: E402
from lib.workspace import resolve_workspace, resolve_workspace_closure  # noqa: E402
import library as library_cli  # noqa: E402


PREEXISTING_SKILL_NAMES = frozenset(
    """
    acpx-dispatch
    adr-gap
    agent-forge
    ai-readiness
    aidbox
    aidbox-ig-development
    aidbox-sql-on-fhir
    amazon
    angebotserstellung
    atomic-generate-types
    audit-citations
    bd-release-notes
    bead-execution-loop
    bead-metrics
    bead-reviewer
    billing-reviewer
    binary-explorer
    brand-forge
    bug-triage
    career-check
    claude-md-pruner
    cmux
    cmux-bead-dispatch
    cmux-browser
    cmux-customization
    cmux-diagnostics
    cmux-markdown
    cmux-settings
    cmux-workspace
    code-navigator
    cohesive-bead-chain
    collmex-cli
    compliance-reviewer
    compound
    context-discovery
    context-handoff
    cognovis-beads
    codex-guide
    council
    customer-invoice
    daily-brief
    entropy-scan
    event-log
    executive-pack
    fhir-emission
    fhir-ig-development
    fhir-validation
    file-inspect
    git-ops
    google-invoice
    gui-review
    hetzner-cloud
    home-infra
    hook-forge
    hs-search
    human-factors-reviewer
    impeccable
    ingest-content
    infra-principles
    inject-standards
    intake
    judge-eval
    linkedin
    local-vm
    mail-send
    mcp-forge
    memory-heartbeat
    mm-cli
    nbj-audit
    ob-cli
    ob-migrate
    ob-search
    ob-triage
    paperless-cli
    parallelize
    people-query
    piler-cli
    playwright-cli
    plugin-management
    portless
    project-context
    project-health
    project-setup
    pvs-schema-analysis
    python-dev
    python-test
    refactor-note
    retro
    review-conventions
    scenario-generator
    script-forge
    session-close
    skill-forge
    spec-developer
    spellcheck-test-engineer
    standard-forge
    standards
    stream-verification-ledger
    summarize
    sync-standards
    token-cost
    transcribe
    ui-cli
    vision
    vision-author
    vision-review
    workflow-forge
    workplan
    worktree-cleanup
    youtube-slide-extractor
    """.split()
)


def test_cognovis_base_is_a_minimal_cross_catalog_project_workspace() -> None:
    catalog = load_catalog(REPO_ROOT)
    workspace = resolve_workspace(catalog, "cognovis-library-core:cognovis-base")

    assert workspace.entry["status"] == "stable"
    assert workspace.entry["schema_version"] == 2
    assert {(root["type"], root["name"], root.get("catalog")) for root in workspace.entry["roots"]} == {
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

    assert {
        ("skill", "cognovis-beads"),
        ("skill", "inject-standards"),
        ("skill", "ob-cli"),
        ("skill", "executive-pack"),
    } <= set(closure.artifacts)
    assert set(closure.prerequisites) == set()

    schema = json.loads(
        (REPO_ROOT / "docs" / "schema" / "library.schema.json").read_text()
    )
    jsonschema.validate(yaml.safe_load((REPO_ROOT / "library.yaml").read_text()), schema)


def test_cognovis_base_publication_preserves_preexisting_catalog_skills() -> None:
    catalog = load_catalog(REPO_ROOT)

    names = {entry["name"] for entry in catalog["library"]["skills"]}
    assert PREEXISTING_SKILL_NAMES <= names
    assert len(names) == 112
    assert "library" in names


def test_library_skill_uses_a_bounded_project_install_source() -> None:
    catalog = load_catalog(REPO_ROOT)
    entry = next(
        skill for skill in catalog["library"]["skills"] if skill["name"] == "library"
    )

    assert entry["source"].endswith("/SKILL.md")
    assert entry["metadata"]["library"]["skill_bundle"] == "file"


def test_cognovis_base_refuses_when_the_production_pin_verifier_observes_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = load_catalog(REPO_ROOT)
    workspace = resolve_workspace(catalog, "cognovis-library-core:cognovis-base")

    monkeypatch.setattr(
        "lib.providers.wiring.source_revision",
        lambda identity, **_kwargs: "0" * 40,
    )

    with pytest.raises(LibraryError, match="pin drift"):
        resolve_workspace_closure(
            catalog,
            workspace,
            REPO_ROOT,
            "project",
            pin_verifier=library_cli._workspace_pin_verifier(catalog),
        )


def test_cognovis_base_catalog_entry_matches_its_canonical_manifest() -> None:
    catalog = yaml.safe_load((REPO_ROOT / "library.yaml").read_text())
    core_candidates = (
        Path("/Users/malte/code/.worktrees/cognovis-core/clc-1wis"),
        Path("/Users/malte/code/library/cognovis-core"),
    )
    core_root = next(
        path
        for path in core_candidates
        if (path / "workspaces" / "cognovis-base.yaml").is_file()
    )
    manifest = yaml.safe_load((core_root / "workspaces" / "cognovis-base.yaml").read_text())
    entry = next(
        workspace
        for workspace in catalog["library"]["workspaces"]
        if workspace["name"] == "cognovis-base"
    )

    for key in ("schema_version", "name", "version", "description", "status", "roots"):
        assert entry[key] == manifest[key]
    assert [item["alias"] for item in entry["catalogs"]] == [
        item["alias"] for item in manifest["catalogs"]
    ]
