"""Supported harness contract coverage for ADR-0012."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_active_cli_and_catalog_projection_metadata_exclude_retired_harnesses() -> None:
    cli = (REPO_ROOT / "scripts" / "library.py").read_text(encoding="utf-8")
    catalog = (REPO_ROOT / "library.yaml").read_text(encoding="utf-8")

    assert '"pi", "all"' in cli
    assert '"cursor_bridge"' not in (REPO_ROOT / "scripts" / "lib" / "paths.py").read_text(encoding="utf-8")
    assert "cursor_bridge:" not in catalog
    assert "default_opencode:" not in catalog
    assert "global_opencode:" not in catalog


def test_library_skill_shows_evidence_recommendation_confirmation_then_cli_fixture() -> None:
    skill = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "## Representative flow" in skill
    assert "Evidence:" in skill
    assert "Recommendation:" in skill
    assert "Confirmation:" in skill
    assert "library workspace use cognovis-library-core:python-cli --scope project" in skill


def test_mcp_projection_selection_excludes_retired_harnesses() -> None:
    installer = (REPO_ROOT / "scripts" / "lib" / "installers" / "mcp_installer.py").read_text(
        encoding="utf-8"
    )

    assert '_WRITABLE_MCP_HARNESSES = ["claude_code", "codex"]' in installer


def test_current_operator_docs_exclude_retired_harness_authoring_blocks() -> None:
    current_docs = (
        "AGENTS.md",
        "cookbook/add-guardrail.md",
        "cookbook/add-mcp.md",
        "cookbook/install.md",
        "cookbook/remove-guardrail.md",
        "cookbook/use-guardrail.md",
    )
    retired_harnesses = ("opencode", "antigravity", "cursor")

    for relative in current_docs:
        content = (REPO_ROOT / relative).read_text(encoding="utf-8").lower()
        assert not any(harness in content for harness in retired_harnesses), relative


def test_workspace_docs_and_portability_table_are_project_only_and_well_formed() -> None:
    workspace = (REPO_ROOT / "docs/primitives/workspace.md").read_text(encoding="utf-8")
    assert "global lobby" not in workspace
    assert "global-scoped" not in workspace
    assert "project|global" not in workspace

    rows = [
        line
        for line in (REPO_ROOT / "docs/ARCHITECTURE.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("|")
    ]
    header_index = rows.index("| Primitive | Claude Code | Codex CLI | Pi | Portability |")
    portability_rows = rows[header_index : header_index + 11]
    assert all(len(row.split("|")) - 2 == 5 for row in portability_rows)
