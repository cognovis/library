"""Launcher boundary tests for implementer and isolated reviewer roles."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


CLD_BIN = Path(__file__).resolve().parents[1] / "bin" / "cld"


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _run_cld(
    tmp_path: Path,
    args: list[str],
    *,
    review_exit: int = 0,
    log_cmux: bool = False,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path]:
    claude_argv = tmp_path / "claude-argv.json"
    review_argv = tmp_path / "review-argv.json"
    cmux_log = tmp_path / "cmux-argv.jsonl"
    claude = _write_executable(
        tmp_path / "claude",
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['CLAUDE_ARGV']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n",
    )
    review = _write_executable(
        tmp_path / "review-client",
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['REVIEW_ARGV']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        "print('review report')\n"
        f"raise SystemExit({review_exit})\n",
    )
    bd = _write_executable(
        tmp_path / "bd",
        "#!/bin/sh\n"
        "if [ \"$1 $2 $3\" = \"config get issue_prefix\" ]; then echo CL; fi\n"
        "if [ \"$1\" = \"show\" ]; then echo '[{\"id\":\"'$2'\",\"status\":\"open\"}]'; fi\n"
        "exit 0\n",
    )
    _write_executable(tmp_path / "git", "#!/bin/sh\nexit 0\n")
    if log_cmux:
        _write_executable(
            tmp_path / "cmux",
            f"#!{sys.executable}\n"
            "import json, pathlib, sys\n"
            f"path = pathlib.Path({str(cmux_log)!r})\n"
            "with path.open('a', encoding='utf-8') as stream: stream.write(json.dumps(sys.argv[1:]) + '\\n')\n",
        )
    else:
        _write_executable(tmp_path / "cmux", "#!/bin/sh\nexit 1\n")

    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{tmp_path}{os.pathsep}{env['PATH']}",
            "CLAUDE_BIN": str(claude),
            "BD_BIN": str(bd),
            "CLD_BEAD_REVIEW_CLIENT": str(review),
            "CLAUDE_ARGV": str(claude_argv),
            "REVIEW_ARGV": str(review_argv),
        }
    )
    result = subprocess.run(
        [str(CLD_BIN), *args],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, claude_argv, review_argv, cmux_log


def _flag_value(argv: list[str], flag: str) -> str | None:
    for index, value in enumerate(argv):
        if value == flag and index + 1 < len(argv):
            return argv[index + 1]
        if value.startswith(f"{flag}="):
            return value.split("=", 1)[1]
    return None


def test_review_delegates_to_shared_client_without_invoking_claude(tmp_path: Path) -> None:
    result, claude_argv, review_argv, _ = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    assert not claude_argv.exists()
    argv = json.loads(review_argv.read_text(encoding="utf-8"))
    assert _flag_value(argv, "--lead-family") == "claude"
    assert _flag_value(argv, "--bead-id") == "CL-safe"
    assert _flag_value(argv, "--repo-dir") == str(tmp_path)
    assert "--model" not in argv
    assert "--provider" not in argv
    assert "--adapter" not in argv
    assert "--tools" not in argv
    assert "--allowedTools" not in argv
    assert "--dangerously-skip-permissions" not in argv


def test_review_does_not_pin_a_concrete_model(tmp_path: Path) -> None:
    result, _, review_argv, _ = _run_cld(tmp_path, ["-br", "CL-safe"])
    assert result.returncode == 0, result.stderr
    argv = json.loads(review_argv.read_text(encoding="utf-8"))
    assert "--model" not in argv
    assert _flag_value(argv, "--lead-family") == "claude"


def test_review_rejects_permission_bypass(tmp_path: Path) -> None:
    result, claude_argv, review_argv, _ = _run_cld(
        tmp_path, ["--skip-perms", "-br", "CL-safe"]
    )
    assert result.returncode == 2
    assert "incompatible" in result.stderr
    assert not claude_argv.exists()
    assert not review_argv.exists()


def test_review_flashes_coordinator_after_shared_client_returns(tmp_path: Path) -> None:
    result, _, _, cmux_log = _run_cld(
        tmp_path,
        [
            "-br",
            "CL-safe",
            "--coordinator-workspace",
            "workspace:15",
            "--coordinator-surface",
            "surface:33",
        ],
        log_cmux=True,
    )
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in cmux_log.read_text(encoding="utf-8").splitlines()]
    assert ["trigger-flash", "--surface", "surface:33"] in calls


def test_review_propagates_client_failure_and_still_flashes(tmp_path: Path) -> None:
    result, _, _, cmux_log = _run_cld(
        tmp_path,
        [
            "-br",
            "CL-safe",
            "--coordinator-workspace",
            "workspace:15",
            "--coordinator-surface",
            "surface:33",
        ],
        review_exit=17,
        log_cmux=True,
    )
    assert result.returncode == 17
    calls = [json.loads(line) for line in cmux_log.read_text(encoding="utf-8").splitlines()]
    assert ["trigger-flash", "--surface", "surface:33"] in calls


@pytest.mark.parametrize(
    ("args", "execution_mode"),
    [
        (["-b", "CL-safe"], "auto"),
        (["-bq", "CL-safe"], "quick"),
    ],
)
def test_implementer_modes_keep_auto_permissions_and_worktree(
    tmp_path: Path, args: list[str], execution_mode: str
) -> None:
    result, claude_argv, review_argv, _ = _run_cld(tmp_path, args)
    assert result.returncode == 0, result.stderr
    assert not review_argv.exists()
    argv = json.loads(claude_argv.read_text(encoding="utf-8"))
    assert _flag_value(argv, "--permission-mode") == "auto"
    assert _flag_value(argv, "--worktree") == "bead-CL-safe"
    assert _flag_value(argv, "--agent") is None
    prompt = argv[-1]
    assert "bead-implementation-loop" in prompt
    assert f"execution_mode={execution_mode}" in prompt
    assert "canonical Session Close" in prompt


def test_plain_launcher_only_bypasses_permissions_on_explicit_request(tmp_path: Path) -> None:
    safe, safe_argv, _, _ = _run_cld(tmp_path, ["hello"])
    assert safe.returncode == 0
    assert _flag_value(json.loads(safe_argv.read_text()), "--permission-mode") == "auto"

    other = tmp_path / "other"
    other.mkdir()
    dangerous, dangerous_argv, _, _ = _run_cld(other, ["--skip-perms", "hello"])
    assert dangerous.returncode == 0
    assert "--dangerously-skip-permissions" in json.loads(dangerous_argv.read_text())
    assert "WARNING" in dangerous.stderr
