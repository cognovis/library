#!/usr/bin/env python3
"""Render compact bead context for cdx launcher prompts."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


DEFAULT_TEXT_LIMIT = 12000
DEFAULT_NOTES_LIMIT = 2000
DEFAULT_ENVELOPE_LIMIT = 50000


def _untrusted_field(source: str, value: Any, *, content_type: str = "text/plain") -> dict[str, Any]:
    return {
        "source": source,
        "trust": "untrusted",
        "untrusted": True,
        "content_type": content_type,
        "value": value,
    }


def _read_limit(name: str, default: int) -> int:
    try:
        limit = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if limit < 1:
        raise ValueError(f"{name} must be greater than zero")
    return limit


def _limit_text(value: Any, limit: int, source: str, limit_name: str) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    raise ValueError(f"{source} exceeds {limit_name} ({len(text)} > {limit})")


def _metadata_value(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if value is None and isinstance(metadata.get("routing"), dict):
        value = metadata["routing"].get(f"routed_{key}")
    return str(value or "")


def render_context(payload: Any) -> str:
    """Render bd show --json payload as an untrusted-data envelope."""
    if isinstance(payload, list):
        if not payload:
            raise ValueError("bd payload is empty")
        bead = payload[0]
    elif isinstance(payload, dict):
        bead = payload
    else:
        raise ValueError(f"bd payload must be object or list, got {type(payload).__name__}")

    if not isinstance(bead, dict):
        raise ValueError(f"bd bead entry must be object, got {type(bead).__name__}")

    metadata = bead.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"bead.metadata must be object, got {type(metadata).__name__}")
    text_limit = _read_limit("CDX_BEAD_CONTEXT_TEXT_LIMIT", DEFAULT_TEXT_LIMIT)
    notes_limit = _read_limit("CDX_BEAD_CONTEXT_NOTES_LIMIT", DEFAULT_NOTES_LIMIT)
    envelope_limit = _read_limit("CDX_BEAD_CONTEXT_ENVELOPE_LIMIT", DEFAULT_ENVELOPE_LIMIT)
    labels_value = bead.get("labels") or []
    if not isinstance(labels_value, list):
        raise ValueError(f"bead.labels must be list, got {type(labels_value).__name__}")
    labels = [
        _limit_text(label, text_limit, f"bead.labels[{index}]", "CDX_BEAD_CONTEXT_TEXT_LIMIT")
        for index, label in enumerate(labels_value)
    ]
    deps = bead.get("dependencies") or []
    if not isinstance(deps, list):
        raise ValueError(f"bead.dependencies must be list, got {type(deps).__name__}")

    acceptance = _limit_text(
        bead.get("acceptance_criteria", ""),
        text_limit,
        "bead.acceptance_criteria",
        "CDX_BEAD_CONTEXT_TEXT_LIMIT",
    )
    description = _limit_text(
        bead.get("description", ""),
        text_limit,
        "bead.description",
        "CDX_BEAD_CONTEXT_TEXT_LIMIT",
    )
    notes = _limit_text(
        bead.get("notes", ""),
        notes_limit,
        "bead.notes",
        "CDX_BEAD_CONTEXT_NOTES_LIMIT",
    )
    dependencies = []
    for index, dep in enumerate(deps):
        if not isinstance(dep, dict):
            raise ValueError(f"bead.dependencies[{index}] must be object, got {type(dep).__name__}")
        dependencies.append(
            {
                "source": f"bead.dependencies[{index}]",
                "trust": "untrusted",
                "untrusted": True,
                "fields": {
                    "id": _untrusted_field(
                        f"bead.dependencies[{index}].id",
                        str(dep.get("id", "") or ""),
                    ),
                    "title": _untrusted_field(
                        f"bead.dependencies[{index}].title",
                        _limit_text(
                            dep.get("title", ""),
                            text_limit,
                            f"bead.dependencies[{index}].title",
                            "CDX_BEAD_CONTEXT_TEXT_LIMIT",
                        ),
                    ),
                    "status": _untrusted_field(
                        f"bead.dependencies[{index}].status",
                        str(dep.get("status", "") or ""),
                    ),
                    "dependency_type": _untrusted_field(
                        f"bead.dependencies[{index}].dependency_type",
                        str(dep.get("dependency_type", "") or ""),
                    ),
                },
            }
        )

    envelope = {
        "contract_version": "1",
        "kind": "cdx.bead_context",
        "classification": "untrusted",
        "data": {
            "fields": {
                "id": _untrusted_field("bead.id", str(bead.get("id", "") or "")),
                "title": _untrusted_field("bead.title", str(bead.get("title", "") or "")),
                "status": _untrusted_field("bead.status", str(bead.get("status", "") or "")),
                "issue_type": _untrusted_field(
                    "bead.issue_type",
                    str(bead.get("issue_type", "") or ""),
                ),
                "priority": _untrusted_field(
                    "bead.priority",
                    str(bead.get("priority", "") or ""),
                ),
                "effort": _untrusted_field(
                    "bead.metadata.effort",
                    _metadata_value(metadata, "effort") or "unset",
                ),
                "assignee": _untrusted_field(
                    "bead.assignee",
                    str(bead.get("assignee", "") or "unassigned"),
                ),
                "labels": _untrusted_field("bead.labels", labels, content_type="application/json"),
                "acceptance_criteria": _untrusted_field("bead.acceptance_criteria", acceptance),
                "description": _untrusted_field("bead.description", description),
                "notes": _untrusted_field("bead.notes", notes),
            },
            "dependencies": dependencies,
        },
        "meta": {
            "producer": "compact-bead-context.py",
            "source": "bd show --json",
        },
    }

    rendered = json.dumps(envelope, indent=2, sort_keys=True) + "\n"
    if len(rendered) > envelope_limit:
        raise ValueError(
            f"bead context envelope exceeds CDX_BEAD_CONTEXT_ENVELOPE_LIMIT "
            f"({len(rendered)} > {envelope_limit})"
        )
    return rendered


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
