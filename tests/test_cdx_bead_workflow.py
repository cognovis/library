"""Tests for deterministic cdx full-bead workflow dispatch."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cdx-bead-workflow.py"


def _write_runtime(tmp_path: Path, *, adapter: str = "cursor-composer") -> tuple[Path, Path, Path]:
    runtime = tmp_path / "beads-runtime"
    scripts = runtime / "scripts"
    scripts.mkdir(parents=True)
    phase0_args = tmp_path / "phase0-args.txt"
    adapter_called = tmp_path / "adapter-called.txt"

    (scripts / "phase0-claim.py").write_text(
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['PHASE0_ARGS_FILE']).write_text('\\n'.join(sys.argv[1:]), encoding='utf-8')\n"
        "payload = {\n"
        "  'bead_id': sys.argv[1],\n"
        "  'run_id': 'run-full-123',\n"
        "  'pre_impl_sha': 'abc123',\n"
        "  'route_decision': {'tier': 'paul', 'impl_model': 'composer-2.5', 'reviewer_model': 'claude-opus-4-7'},\n"
        "  'execution_plan': {'profile': 'cdx-composer', 'workflow': 'full', 'slots': {'full': {'implementation': {'adapter': 'cursor-composer', 'harness': 'cursor', 'model': 'composer-2.5'}}}},\n"
        "  'claim_status': 'CLAIMED',\n"
        "}\n"
        "print(json.dumps(payload))\n",
        encoding="utf-8",
    )
    (scripts / "resolve_slot_dispatch.py").write_text(
        f"print('ADAPTER={adapter}')\n"
        "print('HARNESS=cursor')\n"
        "print('MODEL=composer-2.5')\n"
        "print('REASONING_EFFORT=')\n"
        "print('TIMEOUT_SEC=3600')\n"
        "print('SOURCE=slot')\n",
        encoding="utf-8",
    )
    for script_name in ("cursor-impl.py", "codex-impl.py"):
        (scripts / script_name).write_text(
            "import os, pathlib, sys\n"
            "pathlib.Path(os.environ['ADAPTER_CALLED_FILE']).write_text(sys.argv[0], encoding='utf-8')\n"
            "prompt = sys.argv[1]\n"
            "print(f'## CURSOR_AGENT_START adapter=cursor-impl model={os.environ.get(\"IMPL_MODEL\", \"\")}', file=sys.stderr)\n"
            "print(f'ADAPTER_ENV_BEAD_ID={os.environ.get(\"BEAD_ID\", \"\")}')\n"
            "print(f'ADAPTER_ENV_RUN_ID={os.environ.get(\"RUN_ID\", \"\")}')\n"
            "print(f'ADAPTER_ENV_WORKSPACE={os.environ.get(\"WORKSPACE\", \"\")}')\n"
            "print(f'PROMPT_HAS_CONTEXT={\"compact context\" in prompt}')\n"
            "print('## CURSOR_AGENT_EXIT adapter=cursor-impl exit=0', file=sys.stderr)\n",
            encoding="utf-8",
        )
    return runtime, phase0_args, adapter_called


def test_full_cdx_workflow_dispatches_implementation_slot_to_cursor(tmp_path: Path) -> None:
    runtime, phase0_args, adapter_called = _write_runtime(tmp_path)
    env = dict(os.environ)
    env["BEADS_RUNTIME_DIR"] = str(runtime)
    env["PHASE0_ARGS_FILE"] = str(phase0_args)
    env["ADAPTER_CALLED_FILE"] = str(adapter_called)

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "CL-smoke", "--route-profile", "cdx-composer"],
        input="compact context",
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert adapter_called.exists()
    phase0_text = phase0_args.read_text(encoding="utf-8")
    assert "--line=cdx" in phase0_text
    assert "--tier=auto" in phase0_text
    assert "--bq" not in phase0_text
    assert "--route-profile=cdx-composer" in phase0_text
    assert "phase: 0 | name: route_decision | status: complete | route: PAUL" in result.stderr
    assert "## WORKFLOW_PLAN profile=cdx-composer workflow=full" in result.stderr
    assert "phase: 5 | name: p5_impl | status: in_progress | iteration: 1" in result.stderr
    assert "## LEAF_DISPATCH workflow=full slot=implementation adapter=cursor-composer" in result.stderr
    assert "harness=cursor" in result.stderr
    assert "model=composer-2.5" in result.stderr
    assert "source=slot" in result.stderr
    assert "## CURSOR_AGENT_START adapter=cursor-impl model=composer-2.5" in result.stderr
    assert "## CURSOR_AGENT_EXIT adapter=cursor-impl exit=0" in result.stderr
    assert "ADAPTER_ENV_BEAD_ID=CL-smoke" in result.stdout
    assert "ADAPTER_ENV_RUN_ID=run-full-123" in result.stdout
    assert f"ADAPTER_ENV_WORKSPACE={tmp_path}" in result.stdout
    assert "PROMPT_HAS_CONTEXT=True" in result.stdout


def test_full_cdx_workflow_fails_closed_for_unsupported_adapter(tmp_path: Path) -> None:
    runtime, _phase0_args, adapter_called = _write_runtime(tmp_path, adapter="claude-agent")
    env = dict(os.environ)
    env["BEADS_RUNTIME_DIR"] = str(runtime)
    env["PHASE0_ARGS_FILE"] = str(tmp_path / "phase0-args.txt")
    env["ADAPTER_CALLED_FILE"] = str(adapter_called)

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "CL-smoke", "--route-profile", "cdx-default"],
        input="compact context",
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode == 1
    assert not adapter_called.exists()
    assert "cannot execute adapter 'claude-agent'" in result.stderr
    assert "cursor-composer" in result.stderr
