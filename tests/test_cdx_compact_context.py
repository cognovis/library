"""Tests for compact bead context rendering used by cdx."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compact-bead-context.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("compact_bead_context", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _field(envelope: dict, name: str) -> dict:
    return envelope["data"]["fields"][name]


def test_render_context_emits_untrusted_provenance_envelope() -> None:
    """Bead-controlled fields are serialized as data with trust metadata."""
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
            "acceptance_criteria": "Context is wrapped.",
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
    envelope = json.loads(rendered)
    fields = envelope["data"]["fields"]
    dependency_fields = envelope["data"]["dependencies"][0]["fields"]

    assert envelope["contract_version"] == "1"
    assert envelope["kind"] == "cdx.bead_context"
    assert envelope["classification"] == "untrusted"
    assert _field(envelope, "title") == {
        "source": "bead.title",
        "trust": "untrusted",
        "untrusted": True,
        "content_type": "text/plain",
        "value": "Parent bead",
    }
    assert fields["description"]["source"] == "bead.description"
    assert fields["description"]["trust"] == "untrusted"
    assert fields["description"]["untrusted"] is True
    assert fields["description"]["value"] == "Implement the parent."
    assert fields["acceptance_criteria"]["source"] == "bead.acceptance_criteria"
    assert fields["notes"]["source"] == "bead.notes"
    assert fields["labels"]["source"] == "bead.labels"
    assert fields["effort"]["value"] == "small"
    assert dependency_fields["title"]["source"] == "bead.dependencies[0].title"
    assert dependency_fields["title"]["trust"] == "untrusted"
    assert dependency_fields["title"]["value"] == "Child bead"
    assert "NESTED_DEPENDENCY_BODY_SHOULD_NOT_RENDER" not in rendered
    assert "NESTED_DEPENDENCY_NOTES_SHOULD_NOT_RENDER" not in rendered


def test_render_context_rejects_oversized_notes(monkeypatch) -> None:
    """Long volatile notes are rejected instead of silently truncated."""
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

    with pytest.raises(ValueError, match="bead.notes exceeds CDX_BEAD_CONTEXT_NOTES_LIMIT"):
        mod.render_context(payload)


def test_main_rejects_malformed_payload_with_clear_error() -> None:
    """Malformed stdin fails closed with a useful stderr message."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        input='"not a bead payload"',
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "compact-bead-context.py:" in result.stderr
    assert "bd payload must be object or list" in result.stderr
