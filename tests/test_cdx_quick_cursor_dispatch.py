"""Tests for deterministic cdx-composer quick cursor dispatch."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cdx-quick-cursor-dispatch.py"


def _write_runtime(tmp_path: Path, *, adapter: str = "cursor-composer") -> tuple[Path, Path, Path]:
    """Create a fake beads runtime and return runtime, phase0 args, cursor called paths."""
    runtime = tmp_path / "beads-runtime"
    scripts = runtime / "scripts"
    scripts.mkdir(parents=True)
    phase0_args = tmp_path / "phase0-args.txt"
    cursor_called = tmp_path / "cursor-called.txt"

    (scripts / "phase0-claim.py").write_text(
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['PHASE0_ARGS_FILE']).write_text('\\n'.join(sys.argv[1:]), encoding='utf-8')\n"
        "payload = {\n"
        "  'bead_id': sys.argv[1],\n"
        "  'run_id': 'run-123',\n"
        "  'pre_impl_sha': 'abc123',\n"
        "  'route_decision': {'impl_model': 'composer-2.5', 'reviewer_model': 'claude-opus-4-8'},\n"
        "  'execution_plan': {'profile': 'cdx-composer', 'workflow': 'quick', 'slots': {'quick': {'implementation': {'adapter': 'cursor-composer', 'harness': 'cursor', 'model': 'composer-2.5'}}}},\n"
        "  'claim_status': 'CLAIMED',\n"
        "}\n"
        "print(json.dumps(payload))\n",
        encoding="utf-8",
    )
    (scripts / "resolve_slot_dispatch.py").write_text(
        f"print('ADAPTER={adapter}')\n"
        "print('HARNESS=cursor')\n"
        "print('MODEL=composer-2.5')\n"
        "print('SOURCE=slot')\n",
        encoding="utf-8",
    )
    (scripts / "cursor-impl.py").write_text(
        "import os, pathlib, sys\n"
        "pathlib.Path(os.environ['CURSOR_CALLED_FILE']).write_text('called', encoding='utf-8')\n"
        "prompt = sys.argv[1]\n"
        "print(f'## CURSOR_AGENT_START adapter=cursor-impl model={os.environ.get(\"IMPL_MODEL\", \"\")}', file=sys.stderr)\n"
        "print(f'CURSOR_ENV_BEAD_ID={os.environ.get(\"BEAD_ID\", \"\")}')\n"
        "print(f'CURSOR_ENV_RUN_ID={os.environ.get(\"RUN_ID\", \"\")}')\n"
        "print(f'CURSOR_ENV_WORKSPACE={os.environ.get(\"WORKSPACE\", \"\")}')\n"
        "print(f'PROMPT_HAS_CONTEXT={\"compact context\" in prompt}')\n"
        "print('## CURSOR_AGENT_EXIT adapter=cursor-impl exit=0', file=sys.stderr)\n",
        encoding="utf-8",
    )
    return runtime, phase0_args, cursor_called


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


def _read_uv_calls(path: Path) -> list[list[str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_fix_cl_8832_dispatches_cdx_composer_quick_to_cursor_impl(tmp_path: Path) -> None:
    """CL-8832: cdx-composer quick dispatch must reach cursor-impl, not Codex/GPT fallback."""
    runtime, phase0_args, cursor_called = _write_runtime(tmp_path)
    uv_mock = _write_uv_mock(tmp_path)
    uv_argv_log = tmp_path / "uv-argv.jsonl"
    env = dict(os.environ)
    env["BEADS_RUNTIME_DIR"] = str(runtime)
    env["PHASE0_ARGS_FILE"] = str(phase0_args)
    env["CURSOR_CALLED_FILE"] = str(cursor_called)
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

    assert result.returncode == 0, result.stderr
    assert cursor_called.exists()
    uv_calls = _read_uv_calls(uv_argv_log)
    assert uv_calls[0][:5] == [
        "run",
        "--with",
        "pyyaml",
        "python",
        str(runtime / "scripts" / "phase0-claim.py"),
    ]
    assert "--line=cdx" in phase0_args.read_text(encoding="utf-8")
    assert "--tier=quick" in phase0_args.read_text(encoding="utf-8")
    assert "--bq" in phase0_args.read_text(encoding="utf-8")
    assert "--route-profile=cdx-composer" in phase0_args.read_text(encoding="utf-8")
    assert "## LEAF_DISPATCH workflow=quick slot=implementation adapter=cursor-composer" in result.stderr
    assert "harness=cursor" in result.stderr
    assert "model=composer-2.5" in result.stderr
    assert "source=slot" in result.stderr
    assert "## CURSOR_AGENT_START adapter=cursor-impl model=composer-2.5" in result.stderr
    assert "## CURSOR_AGENT_EXIT adapter=cursor-impl exit=0" in result.stderr
    assert "CURSOR_ENV_BEAD_ID=CL-smoke" in result.stdout
    assert "CURSOR_ENV_RUN_ID=run-123" in result.stdout
    assert f"CURSOR_ENV_WORKSPACE={tmp_path}" in result.stdout
    assert "PROMPT_HAS_CONTEXT=True" in result.stdout


def test_empty_slot_model_falls_back_to_auto(tmp_path: Path) -> None:
    """When the profile slot omits model, quick dispatch uses auto."""
    runtime = tmp_path / "beads-runtime"
    scripts = runtime / "scripts"
    scripts.mkdir(parents=True)
    cursor_called = tmp_path / "cursor-called.txt"
    uv_mock = _write_uv_mock(tmp_path)

    (scripts / "phase0-claim.py").write_text(
        "import json, sys\n"
        "payload = {\n"
        "  'bead_id': sys.argv[1],\n"
        "  'run_id': 'run-123',\n"
        "  'pre_impl_sha': 'abc123',\n"
        "  'route_decision': {'impl_model': 'composer-2.5'},\n"
        "  'execution_plan': {'profile': 'cdx-composer', 'workflow': 'quick', 'slots': {'quick': {'implementation': {'adapter': 'cursor-composer', 'harness': 'cursor', 'model': ''}}}},\n"
        "  'claim_status': 'CLAIMED',\n"
        "}\n"
        "print(json.dumps(payload))\n",
        encoding="utf-8",
    )
    (scripts / "resolve_slot_dispatch.py").write_text(
        "print('ADAPTER=cursor-composer')\n"
        "print('HARNESS=cursor')\n"
        "print('MODEL=')\n"
        "print('SOURCE=slot')\n",
        encoding="utf-8",
    )
    (scripts / "cursor-impl.py").write_text(
        "import os, pathlib, sys\n"
        "pathlib.Path(os.environ['CURSOR_CALLED_FILE']).write_text('called', encoding='utf-8')\n"
        "print(f'IMPL_MODEL={os.environ.get(\"IMPL_MODEL\", \"\")}', file=sys.stderr)\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["BEADS_RUNTIME_DIR"] = str(runtime)
    env["CURSOR_CALLED_FILE"] = str(cursor_called)
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

    assert result.returncode == 0, result.stderr
    assert cursor_called.exists()
    assert "model=auto" in result.stderr
    assert "IMPL_MODEL=auto" in result.stderr


def test_refuses_non_cursor_slot_without_fallback(tmp_path: Path) -> None:
    """A bad cdx-composer slot must fail closed instead of silently using Codex/GPT."""
    runtime, _phase0_args, cursor_called = _write_runtime(tmp_path, adapter="codex-impl")
    uv_mock = _write_uv_mock(tmp_path)
    env = dict(os.environ)
    env["BEADS_RUNTIME_DIR"] = str(runtime)
    env["PHASE0_ARGS_FILE"] = str(tmp_path / "phase0-args.txt")
    env["CURSOR_CALLED_FILE"] = str(cursor_called)
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

    assert result.returncode == 1
    assert not cursor_called.exists()
    assert "not cursor-composer" in result.stderr
    assert "refusing Codex/GPT fallback" in result.stderr
