"""Production tests for the ADR-0006 workflow runtime."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

from lib.workflow_runtime import AgentExecutor, SpineConstraintChecker, WorkflowRuntime  # noqa: E402


def test_agent_extraction_ignores_commented_calls() -> None:
    """AC2: agent() calls in line comments must not be extracted."""
    source = textwrap.dedent(
        """
        export const meta = {"name": "t"};
        // await agent("this is a comment", {})
        /* await agent("block comment", {"slot": "impl"}) */
        await agent("real call", {"slot": "implementation"});
        """
    )

    calls = WorkflowRuntime._extract_agent_calls(source)

    assert len(calls) == 1
    assert calls[0]["prompt"] == "real call"


def test_agent_extraction_ignores_string_literals() -> None:
    """AC2: agent() text inside string literals must not be extracted."""
    source = textwrap.dedent(
        """
        export const meta = {"name": "t"};
        const example = 'await agent("inside string", {})';
        await agent("real", {"slot": "impl"});
        """
    )

    calls = WorkflowRuntime._extract_agent_calls(source)

    assert len(calls) == 1
    assert calls[0]["prompt"] == "real"


def test_spine_checker_detects_banned_op_in_template_literal_interpolation() -> None:
    """AC3: banned ops inside ${...} template interpolation must be detected."""
    checker = SpineConstraintChecker()
    source = (
        'export const meta = {"name": "t"};\n'
        'const url = `prefix-${fetch("https://evil.invalid")}-suffix`;'
    )

    violations = checker.find_violations(source)

    assert "network fetch" in violations


def test_spine_checker_detects_date_now_in_template_literal() -> None:
    """AC3: Date.now() inside template literal interpolation must be detected."""
    checker = SpineConstraintChecker()
    source = 'export const meta = {"name": "t"};\nconst ts = `time-${Date.now()}`;'

    violations = checker.find_violations(source)

    assert "Date.now" in violations


def test_spine_checker_allows_text_in_template_literal_without_banned_calls() -> None:
    """AC3: template literal text like 'fetch' as a word must not trigger."""
    checker = SpineConstraintChecker()
    source = 'export const meta = {"name": "t"};\nconst msg = `data fetch complete`;'

    violations = checker.find_violations(source)

    assert "network fetch" not in violations


def test_workflow_runtime_cli_help() -> None:
    """AC1: workflow_runtime.py --help must exit 0 and mention read-only."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "lib" / "workflow_runtime.py"), "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    help_text = result.stdout.lower()
    assert "read-only" in help_text or "readonly" in help_text or "read" in help_text


def test_workflow_runtime_cli_runs_spec(tmp_path: Path) -> None:
    """AC1: CLI must run a workflow spec and output JSON."""
    spec = tmp_path / "simple.js"
    spec.write_text(
        'export const meta = {"name": "test"};\n'
        'await agent("hello", {"readOnly": true, "slot": "implementation"});\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "lib" / "workflow_runtime.py"), str(spec)],
        capture_output=True,
        text=True,
        cwd=str(SCRIPTS_DIR.parent),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["status"] == "ok"
    assert output["meta"]["name"] == "test"


def test_route_profile_slot_dispatch_uses_slot_target_adapter(tmp_path: Path) -> None:
    """AC4: slot target adapter is resolved from route profile without model-prefix inference."""
    route_profiles = {
        "cld-default": {
            "slots": {
                "full": {
                    "implementation": {
                        "adapter": "codex-exec",
                        "harness": "cld",
                        "model": "gpt-5.5",
                    }
                }
            }
        }
    }

    class CapturingExecutor(AgentExecutor):
        adapter_name = "codex-exec"

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def run(self, prompt: str, opts: dict[str, object]) -> dict[str, object]:
            self.calls.append((prompt, opts))
            return {"adapter": self.adapter_name, "output": "captured"}

    exec_registry = {"codex-exec": CapturingExecutor()}
    runtime = WorkflowRuntime(
        executor_registry=exec_registry,
        constraint_checker=SpineConstraintChecker(),
    )
    spec_path = tmp_path / "dispatch.js"
    spec_path.write_text(
        'export const meta = {"name": "t"};\n'
        'await agent("dispatch test", {"readOnly": true, "slot": "implementation"});\n',
        encoding="utf-8",
    )
    args = {
        "route_profile": "cld-default",
        "route_profiles": route_profiles,
        "workflow": "full",
        "readOnly": True,
    }

    result = runtime.run(spec_path, args)

    assert result["status"] == "ok"
    leaf = result["leaf_results"][0]
    assert leaf["opts"]["slot_target"]["adapter"] == "codex-exec"
    capturing = exec_registry["codex-exec"]
    assert len(capturing.calls) == 1


def test_route_profile_dispatch_does_not_infer_adapter_from_model_prefix(tmp_path: Path) -> None:
    """AC4: model name prefix must not be used to infer adapter."""
    route_profiles = {
        "cld-default": {
            "slots": {
                "full": {
                    "implementation": {
                        "adapter": "claude-agent",
                        "harness": "cld",
                        "model": "gpt-5.5",
                    }
                }
            }
        }
    }

    class TrackingExecutor(AgentExecutor):
        adapter_name = "claude-agent"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def run(self, prompt: str, opts: dict[str, object]) -> dict[str, object]:
            self.calls.append(prompt)
            return {"adapter": self.adapter_name, "output": "tracked"}

    exec_registry = {"claude-agent": TrackingExecutor()}
    runtime = WorkflowRuntime(executor_registry=exec_registry)
    spec_path = tmp_path / "prefix.js"
    spec_path.write_text(
        'export const meta = {"name": "t"};\n'
        'await agent("prefix test", {"readOnly": true, "slot": "implementation"});\n',
        encoding="utf-8",
    )
    args = {
        "route_profile": "cld-default",
        "route_profiles": route_profiles,
        "workflow": "full",
        "readOnly": True,
    }

    runtime.run(spec_path, args)

    tracker = exec_registry["claude-agent"]
    assert len(tracker.calls) == 1
    assert tracker.calls[0] == "prefix test"
