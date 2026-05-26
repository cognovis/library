"""Tests for compact bead context rendering used by cdx."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compact-bead-context.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("compact_bead_context", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_context_omits_nested_dependency_bodies() -> None:
    """Dependency summaries stay compact and do not include nested full descriptions."""
    mod = _load_module()
    payload = [
        {
            "id": "CL-parent",
            "title": "Parent bead",
            "status": "open",
            "issue_type": "task",
            "priority": 2,
            "assignee": "",
            "labels": ["stream:test"],
            "metadata": {"routing": {"routed_effort": "small"}},
            "description": "Implement the parent.",
            "notes": "short note",
            "dependencies": [
                {
                    "id": "CL-child",
                    "title": "Child bead",
                    "status": "closed",
                    "dependency_type": "discovered-from",
                    "description": "NESTED_DEPENDENCY_BODY_SHOULD_NOT_RENDER",
                    "notes": "NESTED_DEPENDENCY_NOTES_SHOULD_NOT_RENDER",
                }
            ],
        }
    ]

    rendered = mod.render_context(payload)

    assert "# Bead CL-parent: Parent bead" in rendered
    assert "- effort: small" in rendered
    assert "Implement the parent." in rendered
    assert "- CL-child: Child bead [closed; discovered-from]" in rendered
    assert "NESTED_DEPENDENCY_BODY_SHOULD_NOT_RENDER" not in rendered
    assert "NESTED_DEPENDENCY_NOTES_SHOULD_NOT_RENDER" not in rendered


def test_render_context_truncates_long_notes(monkeypatch) -> None:
    """Long volatile notes are bounded before they enter the Codex prompt."""
    mod = _load_module()
    monkeypatch.setenv("CDX_BEAD_CONTEXT_NOTES_LIMIT", "20")
    payload = {
        "id": "CL-note",
        "title": "Notes bead",
        "status": "open",
        "issue_type": "task",
        "priority": 2,
        "metadata": {},
        "description": "Short description",
        "notes": "x" * 50,
    }

    rendered = mod.render_context(payload)

    assert "x" * 20 in rendered
    assert "[truncated 30 chars]" in rendered
