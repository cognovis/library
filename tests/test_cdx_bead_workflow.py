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
            "row = {'kind': pathlib.Path(sys.argv[0]).name, 'phase_label': os.environ.get('PHASE_LABEL'), 'bead': os.environ.get('BEAD_ID'), 'model': os.environ.get('IMPL_MODEL'), 'prompt_has_context': 'compact context' in sys.argv[1]}\n"
            "with path.open('a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(row) + '\\n')\n"
            "print(f'## CURSOR_AGENT_START adapter=cursor-impl model={os.environ.get(\"IMPL_MODEL\", \"\")}', file=sys.stderr)\n"
            "print(f'SCRIPT_SLOT={os.environ.get(\"PHASE_LABEL\", \"\")}')\n"
            "print('## CURSOR_AGENT_EXIT adapter=cursor-impl exit=0', file=sys.stderr)\n",
            encoding="utf-8",
        )
    (scripts / "codex-exec.py").write_text(
        "import json, os, pathlib, sys\n"
        "path = pathlib.Path(os.environ['SLOT_CALLS_FILE'])\n"
        "row = {'kind': 'codex-exec.py', 'phase_label': os.environ.get('PHASE_LABEL'), 'bead': os.environ.get('BEAD_ID'), 'argv': sys.argv[1:]}\n"
        "with path.open('a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(row) + '\\n')\n"
        "print('LGTM')\n",
        encoding="utf-8",
    )
    return runtime, phase0_args, slot_calls


def _write_claude_mock(tmp_path: Path, *, fail_phase: str = "") -> Path:
    claude_mock = tmp_path / "claude-mock"
    claude_mock.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "prompt = sys.stdin.read()\n"
        "phase = os.environ.get('PHASE_LABEL', '')\n"
        "path = pathlib.Path(os.environ['SLOT_CALLS_FILE'])\n"
        "row = {'kind': 'claude', 'phase_label': phase, 'bead': os.environ.get('BEAD_ID'), 'argv': sys.argv[1:], 'prompt_has_context': 'compact context' in prompt}\n"
        "with path.open('a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(row) + '\\n')\n"
        "print(f'CLAUDE_SLOT={phase}')\n"
        "if phase == os.environ.get('FAIL_PHASE', ''):\n"
        "    sys.exit(7)\n",
        encoding="utf-8",
    )
    claude_mock.chmod(0o755)
    return claude_mock


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
    fail_phase: str = "",
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path]:
    runtime, phase0_args, slot_calls = _write_runtime(tmp_path, slots=slots)
    claude_mock = _write_claude_mock(tmp_path, fail_phase=fail_phase)
    uv_mock = _write_uv_mock(tmp_path)
    uv_argv_log = tmp_path / "uv-argv.jsonl"
    env = dict(os.environ)
    env["BEADS_RUNTIME_DIR"] = str(runtime)
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
    env["FAIL_PHASE"] = fail_phase
    env["UV_ARGV_LOG"] = str(uv_argv_log)
    env["PATH"] = f"{uv_mock.parent}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "CL-smoke", "--route-profile", "cdx-composer"],
        input="compact context",
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env=env,
    )
    return result, phase0_args, slot_calls, uv_argv_log


def _read_slot_calls(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _read_uv_calls(path: Path) -> list[list[str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_full_cdx_workflow_dispatches_all_core_slots(tmp_path: Path) -> None:
    result, phase0_args, slot_calls, uv_argv_log = _run_workflow(tmp_path)

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
    assert calls[1]["kind"] == "claude"
    assert "--agent" in calls[1]["argv"]
    assert "review-agent" in calls[1]["argv"]
    assert "verification-agent" in calls[2]["argv"]
    assert "session-close" in calls[3]["argv"]


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
    result, _phase0_args, slot_calls, _uv_argv_log = _run_workflow(tmp_path, slots)

    assert result.returncode == 0, result.stderr
    calls = _read_slot_calls(slot_calls)
    codex_call = calls[1]
    assert codex_call["kind"] == "codex-exec.py"
    assert codex_call["phase_label"] == "codex-adversarial"
    assert "--diff-range" in codex_call["argv"]
    assert "abc123...HEAD" in codex_call["argv"]
    assert "## LEAF_DISPATCH workflow=full slot=adversarial_review adapter=codex-exec" in result.stderr


def test_slot_failure_stops_before_later_slots(tmp_path: Path) -> None:
    result, _phase0_args, slot_calls, _uv_argv_log = _run_workflow(tmp_path, fail_phase="verification")

    assert result.returncode == 7
    calls = _read_slot_calls(slot_calls)
    assert [call["phase_label"] for call in calls] == [
        "implementation",
        "codex-adversarial",
        "verification",
    ]
    assert "session_close" not in result.stderr


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
    result, _phase0_args, slot_calls, _uv_argv_log = _run_workflow(tmp_path, slots)

    assert result.returncode == 1
    assert not slot_calls.exists()
    assert "cannot execute adapter 'opencode-agent'" in result.stderr
    assert "cursor-composer" in result.stderr
