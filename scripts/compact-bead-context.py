#!/usr/bin/env python3
"""Render compact bead context for cdx launcher prompts."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


DEFAULT_TEXT_LIMIT = 12000
DEFAULT_NOTES_LIMIT = 2000


def _limit_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit].rstrip()}\n\n[truncated {omitted} chars]"


def _metadata_value(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if value is None and isinstance(metadata.get("routing"), dict):
        value = metadata["routing"].get(f"routed_{key}")
    return str(value or "")


def render_context(payload: Any) -> str:
    """Render bd show --json payload as compact Markdown."""
    if isinstance(payload, list):
        if not payload:
            raise ValueError("bd payload is empty")
        bead = payload[0]
    elif isinstance(payload, dict):
        bead = payload
    else:
        raise ValueError(f"bd payload must be object or list, got {type(payload).__name__}")

    metadata = bead.get("metadata") or {}
    labels = ", ".join(bead.get("labels") or [])
    deps = bead.get("dependencies") or []
    text_limit = int(os.environ.get("CDX_BEAD_CONTEXT_TEXT_LIMIT", DEFAULT_TEXT_LIMIT))
    notes_limit = int(os.environ.get("CDX_BEAD_CONTEXT_NOTES_LIMIT", DEFAULT_NOTES_LIMIT))

    lines = [
        f"# Bead {bead.get('id', '')}: {bead.get('title', '')}".rstrip(),
        "",
        f"- status: {bead.get('status', '')}",
        f"- type: {bead.get('issue_type', '')}",
        f"- priority: {bead.get('priority', '')}",
        f"- effort: {_metadata_value(metadata, 'effort') or 'unset'}",
        f"- assignee: {bead.get('assignee', '') or 'unassigned'}",
    ]
    if labels:
        lines.append(f"- labels: {labels}")

    acceptance = str(bead.get("acceptance_criteria") or "").strip()
    if acceptance:
        lines.extend(["", "## Acceptance Criteria", acceptance])

    description = _limit_text(bead.get("description", ""), text_limit)
    if description:
        lines.extend(["", "## Description", description])

    notes = _limit_text(bead.get("notes", ""), notes_limit)
    if notes:
        lines.extend(["", "## Notes", notes])

    if deps:
        lines.extend(["", "## Dependencies"])
        for dep in deps:
            dep_id = dep.get("id", "")
            dep_title = dep.get("title", "")
            dep_status = dep.get("status", "")
            dep_type = dep.get("dependency_type", "")
            lines.append(f"- {dep_id}: {dep_title} [{dep_status}; {dep_type}]")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    try:
        payload = json.load(sys.stdin, strict=False)
        sys.stdout.write(render_context(payload))
    except Exception as exc:
        print(f"compact-bead-context.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
