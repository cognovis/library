#!/usr/bin/env python3
"""Render compact bead context for cdx launcher prompts."""

from __future__ import annotations

import json
import sys
from typing import Any


def _untrusted_field(source: str, value: Any, *, content_type: str = "text/plain") -> dict[str, Any]:
    return {
        "source": source,
        "trust": "untrusted",
        "untrusted": True,
        "content_type": content_type,
        "value": value,
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


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
    labels_value = bead.get("labels") or []
    if not isinstance(labels_value, list):
        raise ValueError(f"bead.labels must be list, got {type(labels_value).__name__}")
    labels = [_text(label) for label in labels_value]
    deps = bead.get("dependencies") or []
    if not isinstance(deps, list):
        raise ValueError(f"bead.dependencies must be list, got {type(deps).__name__}")

    acceptance = _text(bead.get("acceptance_criteria", ""))
    description = _text(bead.get("description", ""))
    notes = _text(bead.get("notes", ""))
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
                        _text(dep.get("title", "")),
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

    return json.dumps(envelope, indent=2, sort_keys=True) + "\n"


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
