#!/usr/bin/env python3
"""Per-agent token usage report for a Claude Code Workflow run.

The task-completion notification only exposes aggregate subagent tokens. This
script reads a workflow run's per-agent transcripts
(``subagents/workflows/wf_*/agent-*.jsonl``) and breaks usage down by agent so
you can see which agents dominate cost and which prose-heavy steps are
candidates to move into deterministic code.

Usage:
    uv run python scripts/workflow-token-report.py <wf_run_dir> [--json]

``<wf_run_dir>`` is the directory containing ``agent-*.jsonl`` files (printed by
the Workflow tool as "Transcript dir"). Cost-relevant columns: ``out`` (output
tokens, the dominant driver), ``in``, ``cacheW`` (cache writes), ``cacheR``
(cache reads, cheap but volume-revealing), plus turn and tool-call counts.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys


def parse_agent(path: str) -> dict:
    """Sum token usage and activity counts for one agent transcript."""
    aid = os.path.basename(path).replace("agent-", "").replace(".jsonl", "")
    meta_path = path.replace(".jsonl", ".meta.json")
    label = ""
    if os.path.exists(meta_path):
        try:
            meta = json.load(open(meta_path, encoding="utf-8"))
            label = meta.get("label") or meta.get("agentType") or ""
        except (ValueError, OSError):
            pass

    totals = {"in": 0, "out": 0, "cacheW": 0, "cacheR": 0, "turns": 0, "tools": 0}
    model = ""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message") or {}
            usage = msg.get("usage") or {}
            if usage:
                totals["in"] += usage.get("input_tokens", 0)
                totals["out"] += usage.get("output_tokens", 0)
                totals["cacheW"] += usage.get("cache_creation_input_tokens", 0)
                totals["cacheR"] += usage.get("cache_read_input_tokens", 0)
                totals["turns"] += 1
                if msg.get("model"):
                    model = msg["model"]
            content = msg.get("content")
            if isinstance(content, list):
                totals["tools"] += sum(
                    1 for c in content if isinstance(c, dict) and c.get("type") == "tool_use"
                )
    return {"agent": aid, "label": label, "model": model, **totals}


def collect(run_dir: str) -> list[dict]:
    rows = [parse_agent(p) for p in sorted(glob.glob(os.path.join(run_dir, "agent-*.jsonl")))]
    rows.sort(key=lambda r: -r["out"])  # output tokens drive cost most
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", help="Workflow run dir containing agent-*.jsonl")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.run_dir):
        print(f"ERROR: not a directory: {args.run_dir}", file=sys.stderr)
        return 2

    rows = collect(args.run_dir)
    if not rows:
        print(f"ERROR: no agent-*.jsonl files in {args.run_dir}", file=sys.stderr)
        return 2

    keys = ("in", "out", "cacheW", "cacheR", "turns", "tools")
    grand = {k: sum(r[k] for r in rows) for k in keys}

    if args.json:
        print(json.dumps({"agents": rows, "total": grand}, indent=2))
        return 0

    print(f"{'agent':18} {'model':16} {'in':>9} {'out':>8} {'cacheW':>9} {'cacheR':>11} {'turns':>5} {'tools':>5}  label")
    for r in rows:
        print(
            f"{r['agent'][:18]:18} {r['model'][:16]:16} {r['in']:>9} {r['out']:>8} "
            f"{r['cacheW']:>9} {r['cacheR']:>11} {r['turns']:>5} {r['tools']:>5}  {r['label']}"
        )
    print(
        f"{'TOTAL':18} {'':16} {grand['in']:>9} {grand['out']:>8} "
        f"{grand['cacheW']:>9} {grand['cacheR']:>11} {grand['turns']:>5} {grand['tools']:>5}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
