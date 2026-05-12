#!/usr/bin/env python3
"""Codex CLI SessionStart hook — inject matching standards into context.

Codex SessionStart hooks emit their stdout into the session preamble. Reads
project context from cwd, matches library.yaml triggers, prints matched
standards content directly.

Fail-open: any error → silent exit 0.
"""
from __future__ import annotations

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
        text = collect_matched_standards(Path.cwd())
    except Exception as e:
        sys.stderr.write(f"standards-loader: runtime error {e}\n")
        sys.exit(0)

    if text:
        print(text)


if __name__ == "__main__":
    main()
