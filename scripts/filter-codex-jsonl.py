#!/usr/bin/env python3
"""Filter noisy `codex exec --json` events for compact bead runs."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


MARKER_PREFIXES = (
    "### Phase Progress",
    "phase: ",
    "## LEAF_DISPATCH",
    "## CURSOR_AGENT_START",
    "## CURSOR_AGENT_EXIT",
    "## CURSOR_AGENT_STDERR_TAIL",
    "## ABORT_REASON",
    "## PARTIAL_REASON",
)


def _agent_message_limit() -> int:
    raw = os.environ.get("CDX_COMPACT_AGENT_MESSAGE_LIMIT", "2400").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 2400


def _marker_lines(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line.startswith(MARKER_PREFIXES)
    ]


def _bounded_text(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text.rstrip()
    return text[:limit].rstrip() + f"\n[cdx compact: truncated {len(text) - limit} chars]"


def _handle_command(item: dict[str, Any]) -> None:
    output = str(item.get("aggregated_output") or "")
    for line in _marker_lines(output):
        print(line)


def _handle_agent_message(item: dict[str, Any]) -> None:
    text = str(item.get("text") or "")
    markers = _marker_lines(text)
    if markers:
        for line in markers:
            print(line)
        return

    bounded = _bounded_text(text, _agent_message_limit())
    if bounded:
        print(bounded)


def filter_event(event: dict[str, Any]) -> None:
    event_type = str(event.get("type") or "")
    if event_type == "item.completed":
        item = event.get("item") or {}
        if not isinstance(item, dict):
            return
        item_type = str(item.get("type") or "")
        if item_type == "command_execution":
            _handle_command(item)
        elif item_type == "agent_message":
            _handle_agent_message(item)
    elif event_type in {"error", "turn.failed"}:
        message = event.get("message") or event.get("error") or event
        print(f"ERROR: {message}", file=sys.stderr)
    elif event_type == "turn.completed" and os.environ.get("CDX_COMPACT_USAGE") == "1":
        usage = event.get("usage") or {}
        if isinstance(usage, dict) and usage:
            print(
                "tokens used "
                f"input={usage.get('input_tokens', 0)} "
                f"output={usage.get('output_tokens', 0)} "
                f"reasoning={usage.get('reasoning_output_tokens', 0)}",
                file=sys.stderr,
            )


def main() -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # Suppress non-JSON Codex preambles in compact mode, for example:
            # "Reading additional input from stdin..."
            continue
        if isinstance(event, dict):
            filter_event(event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
