"""Catalog contract for the canonical project-local cognovis-base Workspace."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
CORE_WORKSPACE_SOURCE_COMMIT = "e329ee68c6a7d34a9aec8cc523659c9e7b79ff26"


def _core_root() -> Path:
    candidates = []
    configured = os.environ.get("COGNOVIS_CORE")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        (
            REPO_ROOT.parent / "cognovis-core",
            REPO_ROOT.parents[1] / "cognovis-core",
            REPO_ROOT.parents[2] / "library" / "cognovis-core",
        )
    )
    return next(
        path
        for path in candidates
        if (path / "workspaces" / "cognovis-base.yaml").is_file()
    )


def _library_cli_root() -> Path:
    candidates = []
    configured = os.environ.get("LIBRARY_CLI_ROOT")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        (
            REPO_ROOT.parent / "library-cli",
            REPO_ROOT.parents[1] / "library-cli",
            REPO_ROOT.parents[2] / "library" / "library-cli",
        )
    )
    match = next(
        (
            path
            for path in candidates
            if (path / "pyproject.toml").is_file()
            and (path / "scripts" / "library.py").is_file()
        ),
        None,
    )
    if match is None:
        raise AssertionError(
            "the separately shipped library-cli checkout is required for Workspace MoC"
        )
    return match


def _core_manifest_at(name: str) -> dict:
    result = subprocess.run(
        [
            "git",
            "show",
            f"{CORE_WORKSPACE_SOURCE_COMMIT}:workspaces/{name}.yaml",
        ],
        cwd=_core_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(result.stdout)


def test_cognovis_base_is_a_minimal_cross_catalog_project_workspace() -> None:
    catalog = load_catalog(REPO_ROOT)
    workspace = resolve_workspace(catalog, "cognovis-library-core:cognovis-base")

    assert workspace.entry["status"] == "experimental"
    assert workspace.entry["schema_version"] == 2
    assert {(root["type"], root["name"], root.get("catalog")) for root in workspace.entry["roots"]} == {
        ("skill", "cognovis-beads", "core"),
        ("skill", "inject-standards", "core"),
        ("skill", "ob-cli", "core"),
        ("skill", "session-capture", "core"),
        ("skill", "summarize", "core"),
        ("skill", "context-handoff", "core"),
        ("standard", "workflow/agent-session-capture", "core"),
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
        ("skill", "session-capture"),
        ("skill", "summarize"),
        ("skill", "context-handoff"),
        ("standard", "workflow/agent-session-capture"),
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
    assert len(names) == 113
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


@pytest.mark.parametrize("name", ("cognovis-base", "cognovis-daily"))
def test_cognovis_project_workspace_matches_its_current_core_manifest(name: str) -> None:
    catalog = yaml.safe_load((REPO_ROOT / "library.yaml").read_text())
    manifest = _core_manifest_at(name)
    entry = next(
        workspace
        for workspace in catalog["library"]["workspaces"]
        if workspace["name"] == name
    )

    for key, value in manifest.items():
        if key == "metadata":
            continue
        assert entry[key] == value
    expected_metadata = dict(manifest.get("metadata") or {})
    expected_metadata["library"] = {
        "source_catalog": "cognovis-library-core",
        "inventory": "manual",
        "source_commit": CORE_WORKSPACE_SOURCE_COMMIT,
    }
    assert entry["metadata"] == expected_metadata
    assert entry["source"] == (
        "https://git.cognovis.de/cognovis/library-core/raw/commit/"
        f"{CORE_WORKSPACE_SOURCE_COMMIT}/workspaces/{name}.yaml"
    )


@pytest.mark.parametrize("name", ("cognovis-base", "cognovis-daily"))
def test_external_library_cli_validates_current_project_workspace(
    name: str, tmp_path: Path
) -> None:
    cli_root = _library_cli_root()

    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(cli_root),
            "library",
            "--catalog",
            str(REPO_ROOT / "library.yaml"),
            "workspace",
            "validate",
            f"cognovis-library-core:{name}",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout) == {
        "operation": "validate",
        "status": "valid",
        "reference": f"cognovis-library-core:{name}",
    }

    project = tmp_path / name
    project.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    isolated_home = tmp_path / "home"
    shutil.copytree(
        _core_root() / "agent-bases",
        isolated_home / ".agents" / "agent-bases",
    )
    environment = {
        **os.environ,
        "HOME": str(isolated_home),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    environment.pop("VIRTUAL_ENV", None)
    dry_run = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(cli_root),
            "library",
            "--catalog",
            str(REPO_ROOT / "library.yaml"),
            "workspace",
            "use",
            f"cognovis-library-core:{name}",
            "--target-project",
            str(project),
            "--dry-run",
            "--json",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert dry_run.returncode == 0, dry_run.stderr or dry_run.stdout
    payload = json.loads(dry_run.stdout)
    assert payload["status"] == "dry-run"
    assert payload["blockers"] == []

    applied = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(cli_root),
            "library",
            "--catalog",
            str(REPO_ROOT / "library.yaml"),
            "workspace",
            "use",
            f"cognovis-library-core:{name}",
            "--target-project",
            str(project),
            "--json",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert json.loads(applied.stdout)["status"] == "applied"
