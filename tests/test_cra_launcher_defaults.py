"""Regression tests for cra launcher --yolo flag defaults."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


CRA_BIN = Path(__file__).resolve().parents[1] / "bin" / "cra"


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _write_agent_capture(tmp_path: Path) -> tuple[Path, Path, Path]:
    agent_mock = tmp_path / "agent-capture"
    argv_file = tmp_path / "agent-argv.json"
    called_file = tmp_path / "agent-called.txt"
    _write_executable(
        agent_mock,
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['AGENT_CALLED_FILE']).write_text('called', encoding='utf-8')\n"
        "pathlib.Path(os.environ['AGENT_ARGV_FILE']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n",
    )
    return agent_mock, argv_file, called_file


def _run_cra(tmp_path: Path, args: list[str]) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    agent_mock, argv_file, called_file = _write_agent_capture(tmp_path)
    home = tmp_path / "home"
    home.mkdir()

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["AGENT_BIN"] = str(agent_mock)
    env["AGENT_ARGV_FILE"] = str(argv_file)
    env["AGENT_CALLED_FILE"] = str(called_file)

    result = subprocess.run(
        [str(CRA_BIN), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env=env,
    )
    return result, argv_file, called_file


def test_cra_defaults_to_no_yolo_without_explicit_opt_in(tmp_path: Path) -> None:
    result, argv_file, called_file = _run_cra(tmp_path, ["Plain passthrough prompt"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--yolo" not in argv
    assert argv == ["Plain passthrough prompt"]


def test_cra_yolo_explicit_opt_in_forwards_flag_and_warns(tmp_path: Path) -> None:
    result, argv_file, called_file = _run_cra(tmp_path, ["--yolo", "Plain passthrough prompt"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--yolo" in argv
    assert argv == ["--yolo", "Plain passthrough prompt"]
    stderr = result.stderr.lower()
    assert "warning" in stderr
    assert "--yolo" in stderr
