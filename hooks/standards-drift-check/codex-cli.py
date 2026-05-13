#!/usr/bin/env python3
"""
Codex CLI SessionStart adapter for standards-drift-check.

Bead: CL-c2d

Reads the SessionStart event from stdin (JSON), scans project + global
AGENTS.md / CLAUDE.md files for STANDARD block drift, and writes one warning
line per drifted standard to stdout.

Codex CLI reads stdout lines as session preamble content.
Fail-open: any error → exit 0 with no output (never blocks the session).
Target runtime: <50ms.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

_t0 = time.perf_counter()

try:
    from _core import run_drift_check
except Exception as exc:
    sys.stderr.write(f"standards-drift-check: import error {exc}\n")
    sys.exit(0)


def main() -> None:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        event = {}

    cwd = Path(event.get("cwd") or ".")

    try:
        warnings = run_drift_check(cwd)
    except Exception as exc:
        sys.stderr.write(f"standards-drift-check: runtime error {exc}\n")
        sys.exit(0)

    elapsed_ms = (time.perf_counter() - _t0) * 1000
    if elapsed_ms > 50:
        sys.stderr.write(f"standards-drift-check: runtime {elapsed_ms:.0f}ms exceeds 50ms target\n")

    for warning in warnings:
        print(warning)


if __name__ == "__main__":
    main()
