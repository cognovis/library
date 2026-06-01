#!/usr/bin/env python3
"""Tests for scripts/workflow-token-report.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "workflow_token_report", REPO_ROOT / "scripts" / "workflow-token-report.py"
)
wtr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wtr)


def _agent_jsonl(path: Path, usages: list[dict], model: str, tool_calls: int) -> None:
    lines = []
    for u in usages:
        content = [{"type": "tool_use", "name": "Bash"} for _ in range(tool_calls)]
        lines.append(json.dumps({"message": {"model": model, "usage": u, "content": content}}))
        tool_calls = 0  # tools only counted on the first turn for this fixture
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_parse_agent_sums_usage(tmp_path: Path) -> None:
    f = tmp_path / "agent-abc123.jsonl"
    _agent_jsonl(
        f,
        [
            {"input_tokens": 100, "output_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 1000},
            {"input_tokens": 50, "output_tokens": 20, "cache_read_input_tokens": 2000},
        ],
        model="claude-sonnet-4-6",
        tool_calls=3,
    )
    (tmp_path / "agent-abc123.meta.json").write_text(json.dumps({"label": "review:X"}), encoding="utf-8")

    row = wtr.parse_agent(str(f))
    assert row["agent"] == "abc123"
    assert row["label"] == "review:X"
    assert row["model"] == "claude-sonnet-4-6"
    assert row["in"] == 150
    assert row["out"] == 30
    assert row["cacheW"] == 5
    assert row["cacheR"] == 3000
    assert row["turns"] == 2
    assert row["tools"] == 3


def test_collect_sorts_by_output_desc(tmp_path: Path) -> None:
    _agent_jsonl(tmp_path / "agent-low.jsonl", [{"output_tokens": 5}], "m", 0)
    _agent_jsonl(tmp_path / "agent-high.jsonl", [{"output_tokens": 500}], "m", 0)
    rows = wtr.collect(str(tmp_path))
    assert [r["agent"] for r in rows] == ["high", "low"]


def test_main_json_output(tmp_path: Path, capsys) -> None:
    _agent_jsonl(tmp_path / "agent-a.jsonl", [{"output_tokens": 7, "input_tokens": 3}], "m", 1)
    rc = wtr.main([str(tmp_path), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["total"]["out"] == 7
    assert out["total"]["in"] == 3
    assert len(out["agents"]) == 1


def test_main_errors_on_empty_dir(tmp_path: Path) -> None:
    assert wtr.main([str(tmp_path)]) == 2
