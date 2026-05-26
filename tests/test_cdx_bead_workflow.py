"""Tests for deterministic cdx full-bead workflow dispatch."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cdx-bead-workflow.py"


def _write_runtime(
    tmp_path: Path,
    *,
    slots: dict[str, dict[str, str]] | None = None,
) -> tuple[Path, Path, Path]:
    runtime = tmp_path / "beads-runtime"
    scripts = runtime / "scripts"
    scripts.mkdir(parents=True)
    phase0_args = tmp_path / "phase0-args.txt"
    slot_calls = tmp_path / "slot-calls.jsonl"
    slots = slots or {
        "implementation": {
            "adapter": "cursor-composer",
            "harness": "cursor",
            "model": "composer-2.5",
        },
        "adversarial_review": {
            "adapter": "claude-agent",
            "harness": "claude",
            "model": "claude-opus-4-7",
        },
        "verification": {
            "adapter": "claude-agent",
            "harness": "claude",
            "model": "claude-opus-4-7",
        },
        "session_close": {
            "adapter": "claude-agent",
            "harness": "claude",
            "model": "claude-sonnet-4-6",
        },
    }

    (scripts / "phase0-claim.py").write_text(
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['PHASE0_ARGS_FILE']).write_text('\\n'.join(sys.argv[1:]), encoding='utf-8')\n"
        "slots = json.loads(os.environ['PHASE0_SLOTS'])\n"
        "payload = {\n"
        "  'bead_id': sys.argv[1],\n"
        "  'run_id': 'run-full-123',\n"
        "  'pre_impl_sha': 'abc123',\n"
        "  'route_decision': {'tier': 'paul', 'impl_model': 'composer-2.5', 'reviewer_model': 'claude-opus-4-7'},\n"
        "  'execution_plan': {'profile': 'cdx-composer', 'workflow': 'full', 'slots': {'full': slots}},\n"
        "  'claim_status': 'CLAIMED',\n"
        "}\n"
        "print(json.dumps(payload))\n",
        encoding="utf-8",
    )
    (scripts / "resolve_slot_dispatch.py").write_text(
        "import json, os, sys\n"
        "slot = sys.argv[2]\n"
        "data = json.loads(os.environ['PHASE0_SLOTS'])[slot]\n"
        "print(f\"ADAPTER={data['adapter']}\")\n"
        "print(f\"HARNESS={data['harness']}\")\n"
        "print(f\"MODEL={data['model']}\")\n"
        "print('REASONING_EFFORT=')\n"
        "print('TIMEOUT_SEC=3600')\n"
        "print('SOURCE=slot')\n",
        encoding="utf-8",
    )
    for script_name in ("cursor-impl.py", "codex-impl.py"):
        (scripts / script_name).write_text(
            "import json, os, pathlib, sys\n"
            "path = pathlib.Path(os.environ['SLOT_CALLS_FILE'])\n"
            "prompt = sys.argv[1]\n"
            "row = {\n"
            "    'kind': pathlib.Path(sys.argv[0]).name,\n"
            "    'phase_label': os.environ.get('PHASE_LABEL'),\n"
            "    'bead': os.environ.get('BEAD_ID'),\n"
            "    'model': os.environ.get('IMPL_MODEL'),\n"
            "    'prompt_has_context': 'compact context' in prompt,\n"
            "    'prompt_has_phase1_context': 'phase1 context bundle' in prompt,\n"
            "    'prompt_has_phase2_context': 'Deterministic Phase 2 Scope Check' in prompt,\n"
            "    'prompt_has_phase3_context': 'Deterministic Phase 3 Architecture Review' in prompt,\n"
            "    'prompt_has_standards': 'standard full content' in prompt,\n"
            "}\n"
            "with path.open('a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(row) + '\\n')\n"
            "print(\n"
            "    f'## CURSOR_AGENT_START adapter=cursor-impl model={os.environ.get(\"IMPL_MODEL\", \"\")}',\n"
            "    file=sys.stderr,\n"
            ")\n"
            "print(f'SCRIPT_SLOT={os.environ.get(\"PHASE_LABEL\", \"\")}')\n"
            "print('## CURSOR_AGENT_EXIT adapter=cursor-impl exit=0', file=sys.stderr)\n",
            encoding="utf-8",
        )
    (scripts / "context_provider.py").write_text(
        "import json, sys\n"
        "payload = {\n"
        "  'provider': 'fallback',\n"
        "  'provider_status': 'ok',\n"
        "  'confidence': 'high',\n"
        "  'primary_files': ['src/app.py'],\n"
        "  'test_files': ['tests/test_app.py'],\n"
        "  'summary': 'phase1 context bundle',\n"
        "}\n"
        "print(json.dumps(payload))\n",
        encoding="utf-8",
    )
    (scripts / "codex-exec.py").write_text(
        "import json, os, pathlib, sys\n"
        "path = pathlib.Path(os.environ['SLOT_CALLS_FILE'])\n"
        "row = {\n"
        "    'kind': 'codex-exec.py',\n"
        "    'phase_label': os.environ.get('PHASE_LABEL'),\n"
        "    'bead': os.environ.get('BEAD_ID'),\n"
        "    'argv': sys.argv[1:],\n"
        "}\n"
        "with path.open('a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(row) + '\\n')\n"
        "print('LGTM')\n",
        encoding="utf-8",
    )
    return runtime, phase0_args, slot_calls


def _write_inject_runner(tmp_path: Path) -> Path:
    runner = tmp_path / "inject-standards-runner.py"
    runner.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        "full_out = ''\n"
        "paths_out = ''\n"
        "for arg in sys.argv[1:]:\n"
        "    if arg.startswith('--full-out='):\n"
        "        full_out = arg.split('=', 1)[1]\n"
        "    if arg.startswith('--paths-out='):\n"
        "        paths_out = arg.split('=', 1)[1]\n"
        "pathlib.Path(full_out).write_text('standard full content\\n', encoding='utf-8')\n"
        "pathlib.Path(paths_out).write_text('/standards/example.md\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    return runner


def _write_metrics_module(tmp_path: Path) -> tuple[Path, Path]:
    metrics_dir = tmp_path / "metrics-lib"
    metrics_dir.mkdir()
    calls_path = tmp_path / "metrics-calls.jsonl"
    (metrics_dir / "metrics.py").write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "DB_PATH = Path(os.environ.get('METRICS_DB_PATH', 'metrics.db'))\n"
        "def insert_agent_call(**kwargs):\n"
        "    path = Path(os.environ['METRICS_CALLS_FILE'])\n"
        "    with path.open('a', encoding='utf-8') as f:\n"
        "        f.write(json.dumps(kwargs, sort_keys=True, default=str) + '\\n')\n"
        "    return 1\n",
        encoding="utf-8",
    )
    return metrics_dir, calls_path


def _write_claude_mock(tmp_path: Path, *, fail_phase: str = "") -> Path:
    claude_mock = tmp_path / "claude-mock"
    claude_mock.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "prompt = sys.stdin.read()\n"
        "phase = os.environ.get('PHASE_LABEL', '')\n"
        "path = pathlib.Path(os.environ['SLOT_CALLS_FILE'])\n"
        "row = {\n"
        "    'kind': 'claude',\n"
        "    'phase_label': phase,\n"
        "    'bead': os.environ.get('BEAD_ID'),\n"
        "    'argv': sys.argv[1:],\n"
        "    'prompt_has_context': 'compact context' in prompt,\n"
        "    'prompt_has_phase1_context': 'phase1 context bundle' in prompt,\n"
        "    'prompt_has_phase2_context': 'Deterministic Phase 2 Scope Check' in prompt,\n"
        "    'prompt_has_phase3_context': 'Deterministic Phase 3 Architecture Review' in prompt,\n"
        "    'prompt_has_standards': 'standard full content' in prompt,\n"
        "}\n"
        "with path.open('a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(row) + '\\n')\n"
        "print(f'CLAUDE_SLOT={phase}')\n"
        "if phase == os.environ.get('FAIL_PHASE', ''):\n"
        "    sys.exit(7)\n",
        encoding="utf-8",
    )
    claude_mock.chmod(0o755)
    return claude_mock


def _write_bd_mock(tmp_path: Path) -> tuple[Path, Path]:
    bd_mock = tmp_path / "bd-mock"
    bd_log = tmp_path / "bd-argv.jsonl"
    bd_mock.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "path = pathlib.Path(os.environ['BD_ARGV_LOG'])\n"
        "with path.open('a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    bd_mock.chmod(0o755)
    return bd_mock, bd_log


def _write_uv_mock(tmp_path: Path) -> Path:
    uv_mock = tmp_path / "uv"
    uv_mock.write_text(
        f"#!{sys.executable}\n"
        "import json, os, subprocess, sys\n"
        "log = os.environ.get('UV_ARGV_LOG')\n"
        "if log:\n"
        "    with open(log, 'a', encoding='utf-8') as f:\n"
        "        f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "args = sys.argv[1:]\n"
        "if not args or args[0] != 'run':\n"
        "    raise SystemExit(64)\n"
        "args = args[1:]\n"
        "while len(args) >= 2 and args[0] == '--with':\n"
        "    args = args[2:]\n"
        "if not args or args[0] != 'python':\n"
        "    raise SystemExit(65)\n"
        "raise SystemExit(subprocess.call([sys.executable, *args[1:]]))\n",
        encoding="utf-8",
    )
    uv_mock.chmod(0o755)
    return uv_mock


def _run_workflow(
    tmp_path: Path,
    slots: dict[str, dict[str, str]] | None = None,
    *,
    bead_context: str = "compact context",
    fail_phase: str = "",
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path, Path, Path]:
    runtime, phase0_args, slot_calls = _write_runtime(tmp_path, slots=slots)
    claude_mock = _write_claude_mock(tmp_path, fail_phase=fail_phase)
    bd_mock, bd_log = _write_bd_mock(tmp_path)
    inject_runner = _write_inject_runner(tmp_path)
    metrics_dir, metrics_calls = _write_metrics_module(tmp_path)
    uv_mock = _write_uv_mock(tmp_path)
    uv_argv_log = tmp_path / "uv-argv.jsonl"
    env = dict(os.environ)
    env["BEADS_RUNTIME_DIR"] = str(runtime)
    env["INJECT_STANDARDS_RUNNER"] = str(inject_runner)
    env["METRICS_DIR_OVERRIDE"] = str(metrics_dir)
    env["METRICS_CALLS_FILE"] = str(metrics_calls)
    env["PHASE0_ARGS_FILE"] = str(phase0_args)
    env["PHASE0_SLOTS"] = json.dumps(slots or {
        "implementation": {
            "adapter": "cursor-composer",
            "harness": "cursor",
            "model": "composer-2.5",
        },
        "adversarial_review": {
            "adapter": "claude-agent",
            "harness": "claude",
            "model": "claude-opus-4-7",
        },
        "verification": {
            "adapter": "claude-agent",
            "harness": "claude",
            "model": "claude-opus-4-7",
        },
        "session_close": {
            "adapter": "claude-agent",
            "harness": "claude",
            "model": "claude-sonnet-4-6",
        },
    })
    env["SLOT_CALLS_FILE"] = str(slot_calls)
    env["CLAUDE_BIN"] = str(claude_mock)
    env["BD_BIN"] = str(bd_mock)
    env["BD_ARGV_LOG"] = str(bd_log)
    env["FAIL_PHASE"] = fail_phase
    env["UV_ARGV_LOG"] = str(uv_argv_log)
    env["PATH"] = f"{uv_mock.parent}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "CL-smoke", "--route-profile", "cdx-composer"],
        input=bead_context,
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env=env,
    )
    return result, phase0_args, slot_calls, uv_argv_log, metrics_calls, bd_log


def _read_slot_calls(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _read_uv_calls(path: Path) -> list[list[str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _read_metrics_calls(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _read_bd_calls(path: Path) -> list[list[str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_full_cdx_workflow_dispatches_all_core_slots(tmp_path: Path) -> None:
    result, phase0_args, slot_calls, uv_argv_log, metrics_calls, bd_log = _run_workflow(tmp_path)

    assert result.returncode == 0, result.stderr
    uv_calls = _read_uv_calls(uv_argv_log)
    assert uv_calls[0][:5] == [
        "run",
        "--with",
        "pyyaml",
        "python",
        str(tmp_path / "beads-runtime" / "scripts" / "phase0-claim.py"),
    ]
    phase0_text = phase0_args.read_text(encoding="utf-8")
    assert "--line=cdx" in phase0_text
    assert "--tier=auto" in phase0_text
    assert "--bq" not in phase0_text
    assert "--route-profile=cdx-composer" in phase0_text
    assert "phase: 0 | name: route_decision | status: complete | route: PAUL" in result.stderr
    assert "## WORKFLOW_PLAN profile=cdx-composer workflow=full" in result.stderr
    assert "phase: 1 | name: context | status: in_progress" in result.stderr
    assert "phase: 1 | name: context | status: complete" in result.stderr
    assert "phase: 2 | name: scope_check | status: in_progress" in result.stderr
    assert "phase: 2 | name: scope_check | status: complete" in result.stderr
    assert "phase: 3 | name: architecture_review | status: in_progress" in result.stderr
    assert "phase: 3 | name: architecture_review | status: complete | result: skipped" in result.stderr
    assert "phase: 4 | name: standards_preamble | status: complete" in result.stderr
    assert "WORKFLOW_DEGRADED" not in result.stderr
    assert "## WORKFLOW_EVENT " in result.stderr
    assert "phase=1 name=context status=complete" in result.stderr
    assert "phase=2 name=scope_check status=complete" in result.stderr
    assert "phase=3 name=architecture_review status=complete" in result.stderr
    assert "duration_ms=" in result.stderr
    for phase_name in ("p5_impl", "codex_adversarial", "verification", "session_close"):
        assert f"name: {phase_name} | status: in_progress" in result.stderr
    for slot_name in ("implementation", "adversarial_review", "verification", "session_close"):
        assert f"## LEAF_DISPATCH workflow=full slot={slot_name}" in result.stderr
    assert "adapter=cursor-composer" in result.stderr
    assert "adapter=claude-agent" in result.stderr
    assert "## CURSOR_AGENT_START adapter=cursor-impl model=composer-2.5" in result.stderr
    assert "## CURSOR_AGENT_EXIT adapter=cursor-impl exit=0" in result.stderr

    calls = _read_slot_calls(slot_calls)
    assert [call["phase_label"] for call in calls] == [
        "implementation",
        "codex-adversarial",
        "verification",
        "session-close",
    ]
    assert calls[0]["kind"] == "cursor-impl.py"
    assert calls[0]["prompt_has_context"] is True
    assert calls[0]["prompt_has_phase1_context"] is True
    assert calls[0]["prompt_has_phase2_context"] is True
    assert calls[0]["prompt_has_phase3_context"] is True
    assert calls[0]["prompt_has_standards"] is True
    assert calls[1]["kind"] == "claude"
    assert "--agent" in calls[1]["argv"]
    assert "review-agent" in calls[1]["argv"]
    assert "verification-agent" in calls[2]["argv"]
    assert "session-close" in calls[3]["argv"]

    metrics = _read_metrics_calls(metrics_calls)
    assert [call["phase_label"] for call in metrics] == [
        "codex-adversarial",
        "verification",
        "session-close",
    ]
    assert metrics[0]["run_id"] == "run-full-123"
    assert metrics[0]["bead_id"] == "CL-smoke"
    assert metrics[0]["agent_label"] == "claude-agent-full-adversarial_review"
    assert metrics[0]["model"] == "claude-opus-4-7"
    assert metrics[0]["exit_code"] == 0

    bd_calls = _read_bd_calls(bd_log)
    assert any(call[:3] == ["update", "CL-smoke", "--append-notes"] for call in bd_calls)
    assert any("Pre-mortem: level=" in call[-1] for call in bd_calls)


def test_codex_exec_slot_uses_runtime_helper_and_diff_range(tmp_path: Path) -> None:
    slots = {
        "implementation": {
            "adapter": "cursor-composer",
            "harness": "cursor",
            "model": "composer-2.5",
        },
        "adversarial_review": {
            "adapter": "codex-exec",
            "harness": "codex",
            "model": "gpt-5.5",
        },
        "verification": {
            "adapter": "claude-agent",
            "harness": "claude",
            "model": "claude-opus-4-7",
        },
        "session_close": {
            "adapter": "claude-agent",
            "harness": "claude",
            "model": "claude-sonnet-4-6",
        },
    }
    result, _phase0_args, slot_calls, _uv_argv_log, _metrics_calls, _bd_log = _run_workflow(tmp_path, slots)

    assert result.returncode == 0, result.stderr
    calls = _read_slot_calls(slot_calls)
    codex_call = calls[1]
    assert codex_call["kind"] == "codex-exec.py"
    assert codex_call["phase_label"] == "codex-adversarial"
    assert "--diff-range" in codex_call["argv"]
    assert "abc123...HEAD" in codex_call["argv"]
    assert "## LEAF_DISPATCH workflow=full slot=adversarial_review adapter=codex-exec" in result.stderr


def test_architecture_signal_runs_phase3_review_before_implementation(tmp_path: Path) -> None:
    bead_context = (
        "compact context\n"
        "- effort: large\n"
        "## Description\n"
        "Refactor the workflow adapter boundary across API modules.\n"
    )
    result, _phase0_args, slot_calls, _uv_argv_log, metrics_calls, bd_log = _run_workflow(
        tmp_path,
        bead_context=bead_context,
    )

    assert result.returncode == 0, result.stderr
    assert "phase: 3 | name: architecture_review | status: in_progress" in result.stderr
    assert "phase: 3 | name: architecture_review | status: complete | result: clean" in result.stderr
    assert "## LEAF_DISPATCH workflow=full slot=architecture_review adapter=claude-agent" in result.stderr

    calls = _read_slot_calls(slot_calls)
    assert [call["phase_label"] for call in calls] == [
        "architecture-review",
        "implementation",
        "codex-adversarial",
        "verification",
        "session-close",
    ]
    assert calls[0]["kind"] == "claude"
    assert "review-agent" in calls[0]["argv"]
    assert calls[1]["prompt_has_phase3_context"] is True

    metrics = _read_metrics_calls(metrics_calls)
    assert [call["phase_label"] for call in metrics] == [
        "architecture-review",
        "codex-adversarial",
        "verification",
        "session-close",
    ]
    assert metrics[0]["agent_label"] == "claude-agent-full-architecture_review"

    bd_calls = _read_bd_calls(bd_log)
    assert any("Architecture review: status=clean" in call[-1] for call in bd_calls)


def test_architecture_review_failure_stops_before_implementation(tmp_path: Path) -> None:
    bead_context = (
        "compact context\n"
        "- effort: large\n"
        "## Description\n"
        "Refactor the workflow adapter boundary across API modules.\n"
    )
    result, _phase0_args, slot_calls, _uv_argv_log, metrics_calls, _bd_log = _run_workflow(
        tmp_path,
        bead_context=bead_context,
        fail_phase="architecture-review",
    )

    assert result.returncode == 7
    calls = _read_slot_calls(slot_calls)
    assert [call["phase_label"] for call in calls] == ["architecture-review"]
    assert "phase: 5 | name: p5_impl" not in result.stderr
    metrics = _read_metrics_calls(metrics_calls)
    assert [call["phase_label"] for call in metrics] == ["architecture-review"]
    assert metrics[0]["exit_code"] == 7


def test_slot_failure_stops_before_later_slots(tmp_path: Path) -> None:
    result, _phase0_args, slot_calls, _uv_argv_log, metrics_calls, _bd_log = _run_workflow(
        tmp_path,
        fail_phase="verification",
    )

    assert result.returncode == 7
    calls = _read_slot_calls(slot_calls)
    assert [call["phase_label"] for call in calls] == [
        "implementation",
        "codex-adversarial",
        "verification",
    ]
    assert "session_close" not in result.stderr
    metrics = _read_metrics_calls(metrics_calls)
    assert [call["phase_label"] for call in metrics] == [
        "codex-adversarial",
        "verification",
    ]
    assert metrics[-1]["exit_code"] == 7


def test_full_cdx_workflow_fails_closed_for_unsupported_adapter(tmp_path: Path) -> None:
    slots = {
        "implementation": {
            "adapter": "opencode-agent",
            "harness": "opencode",
            "model": "opencode",
        },
        "adversarial_review": {
            "adapter": "claude-agent",
            "harness": "claude",
            "model": "claude-opus-4-7",
        },
        "verification": {
            "adapter": "claude-agent",
            "harness": "claude",
            "model": "claude-opus-4-7",
        },
        "session_close": {
            "adapter": "claude-agent",
            "harness": "claude",
            "model": "claude-sonnet-4-6",
        },
    }
    result, _phase0_args, slot_calls, _uv_argv_log, _metrics_calls, _bd_log = _run_workflow(tmp_path, slots)

    assert result.returncode == 1
    assert not slot_calls.exists()
    assert "cannot execute adapter 'opencode-agent'" in result.stderr
    assert "cursor-composer" in result.stderr
