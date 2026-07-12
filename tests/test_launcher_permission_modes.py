"""Regression tests for cld launcher permission defaults."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


CLD_BIN = Path(__file__).resolve().parents[1] / "bin" / "cld"
UNTRUSTED_MARKER = "ZZZ_UNTRUSTED_BEAD_FIELD_MARKER_ZZZ"


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _write_claude_capture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    claude_mock = tmp_path / "claude-capture"
    argv_file = tmp_path / "claude-argv.json"
    prompt_file = tmp_path / "claude-prompt.txt"
    called_file = tmp_path / "claude-called.txt"
    _write_executable(
        claude_mock,
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['CLAUDE_CALLED_FILE']).write_text('called', encoding='utf-8')\n"
        "pathlib.Path(os.environ['CLAUDE_ARGV_FILE']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        "prompt = sys.argv[-1] if len(sys.argv) > 1 else ''\n"
        "pathlib.Path(os.environ['CLAUDE_PROMPT_FILE']).write_text(prompt, encoding='utf-8')\n",
    )
    return claude_mock, argv_file, prompt_file, called_file


def _write_bd_mock(tmp_path: Path) -> tuple[Path, Path]:
    bd_mock = tmp_path / "bd-mock"
    bd_log = tmp_path / "bd-argv.jsonl"
    _write_executable(
        bd_mock,
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "log = pathlib.Path(os.environ['BD_ARGV_LOG'])\n"
        "with log.open('a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(args) + '\\n')\n"
        "if args[:3] == ['config', 'get', 'issue_prefix']:\n"
        "    print('CL')\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['dolt', 'pull']:\n"
        "    raise SystemExit(0)\n"
        "if len(args) >= 2 and args[0] == 'show':\n"
        "    bead_id = args[1]\n"
        "    if '--children' in args:\n"
        "        print(json.dumps({bead_id: []}))\n"
        "    else:\n"
        "        print(json.dumps([{\n"
        "            'id': bead_id,\n"
        "            'status': os.environ.get('BD_STATUS', 'open'),\n"
        f"            'title': 'title {UNTRUSTED_MARKER}',\n"
        f"            'description': 'description {UNTRUSTED_MARKER}',\n"
        f"            'notes': 'notes {UNTRUSTED_MARKER}',\n"
        f"            'acceptance_criteria': 'acceptance {UNTRUSTED_MARKER}',\n"
        "        }]))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(0)\n",
    )
    return bd_mock, bd_log


def _write_cld_path_mocks(tmp_path: Path) -> None:
    _write_executable(
        tmp_path / "git",
        "#!/bin/sh\n"
        "exit 0\n",
    )
    _write_executable(
        tmp_path / "cmux",
        "#!/bin/sh\n"
        "exit 1\n",
    )


def _run_cld(tmp_path: Path, args: list[str]) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path, Path]:
    claude_mock, argv_file, prompt_file, called_file = _write_claude_capture(tmp_path)
    bd_mock, bd_log = _write_bd_mock(tmp_path)
    _write_cld_path_mocks(tmp_path)
    home = tmp_path / "home"
    home.mkdir()

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_BIN"] = str(claude_mock)
    env["CLAUDE_ARGV_FILE"] = str(argv_file)
    env["CLAUDE_PROMPT_FILE"] = str(prompt_file)
    env["CLAUDE_CALLED_FILE"] = str(called_file)
    env["BD_BIN"] = str(bd_mock)
    env["BD_ARGV_LOG"] = str(bd_log)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(CLD_BIN), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env=env,
    )
    return result, argv_file, prompt_file, called_file, bd_log


def _argv_has_permission_auto(argv: list[str]) -> bool:
    return any(left == "--permission-mode" and right == "auto" for left, right in zip(argv, argv[1:]))


@pytest.mark.parametrize(
    "args",
    [
        ["Plain passthrough prompt"],
        ["-b", "CL-safe"],
        ["-bq", "CL-safe"],
        ["-br", "CL-safe"],
    ],
)
def test_cld_defaults_to_permission_auto_without_dangerous_skip(
    tmp_path: Path,
    args: list[str],
) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--dangerously-skip-permissions" not in argv
    assert _argv_has_permission_auto(argv)


@pytest.mark.parametrize(
    "args",
    [
        ["--skip-perms", "Plain passthrough prompt"],
        ["--skip-perms", "-b", "CL-safe"],
        ["--skip-perms", "-bq", "CL-safe"],
        ["--skip-perms", "-br", "CL-safe"],
    ],
)
def test_cld_skip_perms_explicitly_uses_dangerous_skip_and_warns(
    tmp_path: Path,
    args: list[str],
) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--dangerously-skip-permissions" in argv
    assert not _argv_has_permission_auto(argv)
    stderr = result.stderr.lower()
    assert "warning" in stderr
    assert "dangerously-skip-permissions" in stderr


@pytest.mark.parametrize(
    "args",
    [
        ["-b", "CL-safe", "--route-profile", "cld-composer", "--force-tier", "infra"],
        ["-bq", "CL-safe", "--route-profile", "cld-composer", "--force-tier", "infra"],
    ],
)
def test_cld_bead_prompt_does_not_embed_raw_bead_fields(
    tmp_path: Path,
    args: list[str],
) -> None:
    result, _argv_file, prompt_file, called_file, bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    bd_calls = [json.loads(line) for line in bd_log.read_text(encoding="utf-8").splitlines()]
    assert any(call[:2] == ["show", "CL-safe"] for call in bd_calls)
    prompt = prompt_file.read_text(encoding="utf-8")
    assert "Bead ID: CL-safe" in prompt
    assert "Portless namespace: CL-safe" in prompt
    assert UNTRUSTED_MARKER not in prompt
