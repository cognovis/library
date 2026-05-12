#!/usr/bin/env python3
"""Codex CLI SessionStart hook -- inject a compact standards index.

Codex SessionStart hooks emit stdout into the session preamble. To avoid
polluting every prompt with large standards documents, this hook prints a short
index by default. Set STANDARDS_LOADER_MODE=full to print matched content.

Fail-open: any error → silent exit 0.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from _core import collect_matched_standards, collect_matched_standards_index
except Exception as e:
    sys.stderr.write(f"standards-loader: import error {e}\n")
    sys.exit(0)


def main() -> None:
    try:
        if os.environ.get("STANDARDS_LOADER_MODE") == "full":
            text = collect_matched_standards(Path.cwd())
        else:
            text = collect_matched_standards_index(Path.cwd())
    except Exception as e:
        sys.stderr.write(f"standards-loader: runtime error {e}\n")
        sys.exit(0)

    if text:
        print(text)


if __name__ == "__main__":
    main()
