#!/usr/bin/env python3
"""Claude Code SessionStart hook — inject matching standards into context.

Reads project context from cwd and CLAUDE.md, matches against library.yaml
triggers, and emits matched standards content as `additionalContext` in the
hook output JSON per Claude Code SessionStart contract.

Fail-open: any error short-circuits to exit 0 with empty output — never
blocks the session.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from _core import collect_matched_standards
except Exception as e:
    sys.stderr.write(f"standards-loader: import error {e}\n")
    sys.exit(0)


def main() -> None:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        event = {}

    cwd = Path(event.get("cwd") or ".")
    try:
        text = collect_matched_standards(cwd)
    except Exception as e:
        sys.stderr.write(f"standards-loader: runtime error {e}\n")
        sys.exit(0)

    if not text:
        sys.exit(0)

    out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }
    print(json.dumps(out))


if __name__ == "__main__":
    main()
