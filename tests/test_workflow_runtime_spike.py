"""Spike tests for the ADR-0006 workflow runtime boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
WORKFLOW_SPEC = REPO_ROOT / "workflows" / "bead-context-pack.js"
ROUTE_PROFILE_CONFIG = Path.home() / ".agents" / "orchestrator-config.yml"

sys.path.insert(0, str(SCRIPTS_DIR))

from lib.workflow_runtime import (  # noqa: E402
    AgentExecutor,
    ClaudeAgentExecutor,
    JournalStore,
    ResumeContext,
    SpineConstraintChecker,
    WorkflowRuntime,
)


class DummyExecutor(AgentExecutor):
    adapter_name = "claude-agent"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def run(self, prompt: str, opts: dict[str, object]) -> dict[str, object]:
        self.calls.append((prompt, dict(opts)))
        return {
            "adapter": self.adapter_name,
            "prompt": prompt,
            "opts": dict(opts),
            "output": "dummy-result",
        }


class DummyCodexExecutor(DummyExecutor):
    adapter_name = "codex-exec"


def _write_single_leaf_spec(tmp_path: Path, opts: dict[str, object]) -> Path:
    spec_path = tmp_path / "single-leaf.js"
    spec_path.write_text(
        "\n".join(
            [
                'export const meta = {"name": "single-leaf"};',
                f'await agent("context pack", {json.dumps(opts, sort_keys=True)});',
            ]
        ),
        encoding="utf-8",
    )
    return spec_path


def _load_route_profiles() -> dict[str, object]:
    if not ROUTE_PROFILE_CONFIG.exists():
        pytest.skip(f"Route profile config not found: {ROUTE_PROFILE_CONFIG}")
    data = yaml.safe_load(ROUTE_PROFILE_CONFIG.read_text(encoding="utf-8")) or {}
    return data.get("route_profiles", {})


def test_spine_constraint_checker_detects_banned_operations() -> None:
    checker = SpineConstraintChecker()
    source = """
    export const meta = {"name": "bad"};
    const fs = require("fs");
    fs.readFileSync("/tmp/input", "utf8");
    spawn("bash", ["-lc", "echo nope"]);
    fetch("https://example.invalid");
    net.createConnection(1);
    const now = Date.now();
    const random = Math.random();
    const stamp = new Date();
    import "net";
    """
    violations = checker.find_violations(source)
    assert "filesystem require()" in violations
    assert "filesystem api" in violations
    assert "shell exec" in violations
    assert "network fetch" in violations
    assert "filesystem import net" in violations
    assert "network net module" in violations
    assert "Date.now" in violations
    assert "Math.random" in violations
    assert "new Date()" in violations


def test_spine_constraint_checker_allows_control_flow_and_agent_calls() -> None:
    checker = SpineConstraintChecker()
    source = """
    export const meta = {"name": "ok"};
    for (const item of items) {
      if (item.enabled) {
        await agent("do work", {"slot": "implementation"});
      }
    }
    """
    assert checker.find_violations(source) == []


def test_url_in_string_does_not_mask_banned_op() -> None:
    checker = SpineConstraintChecker()
    source = 'await agent("see https://x.com", {}); const r = Math.random();'
    violations = checker.find_violations(source)
    assert any("Math.random" in v for v in violations), "Math.random() after URL // must be detected"


def test_journal_store_caches_by_hash() -> None:
    store = JournalStore()
    prompt = "hello"
    opts = {"slot": "implementation", "readOnly": True}
    first_key = store.put(prompt, opts, {"value": 1})

    assert store.get(prompt, opts) == {"value": 1}
    assert first_key == store.key_for(prompt, opts)
    assert len(store.entries) == 1

    second_key = store.put(prompt, opts, {"value": 2})
    assert first_key == second_key
    assert store.get(prompt, opts) == {"value": 2}
    assert len(store.entries) == 1


def test_resume_context_persists_across_instantiations(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.json"
    first = ResumeContext(path=journal_path)
    first.journal.put("prompt", {"slot": "implementation"}, {"result": "cached"})
    first.save()

    second = ResumeContext(path=journal_path)
    assert second.journal.get("prompt", {"slot": "implementation"}) == {"result": "cached"}


def test_bead_context_pack_passes_constraint_checker() -> None:
    checker = SpineConstraintChecker()
    source = WORKFLOW_SPEC.read_text(encoding="utf-8")
    assert checker.find_violations(source) == []


def test_claude_agent_executor_maps_to_claude_agent_slot() -> None:
    executor = ClaudeAgentExecutor()
    command = executor.build_command("context pack", {"model": "claude-opus-4-7"})

    assert executor.adapter_name == "claude-agent"
    assert command[:3] == ["claude", "-p", "--output-format"]
    assert "json" in command
    assert "context pack" in command


def test_workflow_runtime_runs_read_only_spec_and_journals(tmp_path: Path) -> None:
    route_profiles = _load_route_profiles()
    journal_path = tmp_path / "workflow-journal.json"
    resume = ResumeContext(path=journal_path)
    executor = DummyExecutor()
    runtime = WorkflowRuntime(
        resume_context=resume,
        executor_registry={"claude-agent": executor},
    )

    result = runtime.run(
        WORKFLOW_SPEC,
        {
            "route_profile": "cdx-default",
            "workflow": "full",
            "route_profiles": route_profiles,
        },
    )

    assert result["status"] == "ok"
    assert result["meta"]["name"] == "bead-context-pack"
    assert len(result["leaf_results"]) == 1
    assert result["leaf_results"][0]["cached"] is False
    assert result["leaf_results"][0]["result"]["adapter"] == "claude-agent"
    assert executor.calls
    assert executor.calls[0][1]["slot_target"]["adapter"] == "claude-agent"

    second = runtime.run(
        WORKFLOW_SPEC,
        {
            "route_profile": "cdx-default",
            "workflow": "full",
            "route_profiles": route_profiles,
        },
    )
    assert second["leaf_results"][0]["cached"] is True
    assert len(executor.calls) == 1


def test_runtime_blocks_mutating_execution_for_unverified_adapter(tmp_path: Path) -> None:
    spec_path = _write_single_leaf_spec(
        tmp_path,
        {"adapter": "codex-exec", "readOnly": False},
    )
    runtime = WorkflowRuntime(
        executor_registry={"codex-exec": DummyCodexExecutor()},
    )

    with pytest.raises(ValueError, match="Mutating workflow execution") as exc_info:
        runtime.run(spec_path, {})

    assert exc_info.type.__name__ == "MutatingExecutionBlockedError"


def test_runtime_allows_readonly_for_any_adapter(tmp_path: Path) -> None:
    spec_path = _write_single_leaf_spec(
        tmp_path,
        {"adapter": "codex-exec", "readOnly": True},
    )
    executor = DummyCodexExecutor()
    runtime = WorkflowRuntime(
        executor_registry={"codex-exec": executor},
    )

    result = runtime.run(spec_path, {})

    assert result["status"] == "ok"
    assert result["leaf_results"][0]["result"]["adapter"] == "codex-exec"
    assert len(executor.calls) == 1


def test_runtime_journal_state_serializes_to_json(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.json"
    store = JournalStore(path=journal_path)
    store.put("prompt", {"slot": "implementation"}, {"result": "ok"})
    store.save()

    payload = json.loads(journal_path.read_text(encoding="utf-8"))
    assert "entries" in payload
    assert len(payload["entries"]) == 1

def test_runtime_blocks_unknown_adapter_with_absent_readonly(tmp_path: Path) -> None:
    """Fail-closed default: absent readOnly key + unknown adapter must be blocked."""
    spec_path = _write_single_leaf_spec(
        tmp_path,
        {"adapter": "unknown-future-adapter"},
    )
    # Register the executor so the test is not skipped due to a missing executor
    class UnknownExecutor(DummyExecutor):
        adapter_name = "unknown-future-adapter"

    runtime = WorkflowRuntime(
        executor_registry={"unknown-future-adapter": UnknownExecutor()},
    )

    with pytest.raises(ValueError, match="Mutating workflow execution") as exc_info:
        runtime.run(spec_path, {})

    assert exc_info.type.__name__ == "MutatingExecutionBlockedError"
