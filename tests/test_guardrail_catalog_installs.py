#!/usr/bin/env python3
"""Install/remove smoke tests for cataloged healthcare guardrails."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"

HEALTHCARE_GUARDRAILS = [
    "gitleaks-guard",
    "beads-version-gate",
    "inject-standards-on-agent",
    "session-catchup",
]


def make_stub_binaries(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("gitleaks", "bd", "jq", "zsh", "git"):
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    return bin_dir


def run_library(
    home: Path,
    target_project: Path,
    *args: str,
    path_prefix: Path | None = None,
    path: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    if path is not None:
        env["PATH"] = path
    elif path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    command = [
        sys.executable,
        str(LIBRARY_PY),
        *args,
        "--target-project",
        str(target_project),
        "--json",
    ]
    if len(args) >= 2 and args[1] == "use" and "--harness" not in args:
        command.extend(["--harness", "claude_code"])
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
    )


def hook_origins(settings_path: Path) -> set[str]:
    if not settings_path.exists():
        return set()
    data = json.loads(settings_path.read_text())
    origins: set[str] = set()
    for groups in (data.get("hooks") or {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                origin = hook.get("_origin")
                if origin:
                    origins.add(origin)
    return origins


def test_healthcare_guardrails_install_and_remove(tmp_path: Path) -> None:
    home = tmp_path / "home"
    target_project = tmp_path / "fresh-project"
    bin_dir = make_stub_binaries(tmp_path)
    home.mkdir()
    target_project.mkdir()
    settings_path = home / ".claude" / "settings.json"

    for name in HEALTHCARE_GUARDRAILS:
        install = run_library(
            home,
            target_project,
            "guardrail",
            "use",
            name,
            path_prefix=bin_dir,
        )
        assert install.returncode == 0, install.stderr or install.stdout
        assert name in hook_origins(settings_path)

        remove = run_library(
            home,
            target_project,
            "guardrail",
            "remove",
            name,
            path_prefix=bin_dir,
        )
        assert remove.returncode == 0, remove.stderr or remove.stdout
        assert name not in hook_origins(settings_path)


def test_gitleaks_guard_refuses_install_without_binary(tmp_path: Path) -> None:
    home = tmp_path / "home"
    target_project = tmp_path / "fresh-project"
    empty_bin = tmp_path / "empty-bin"
    home.mkdir()
    target_project.mkdir()
    empty_bin.mkdir()

    result = run_library(
        home,
        target_project,
        "guardrail",
        "use",
        "gitleaks-guard",
        path=str(empty_bin),
    )

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "missing required runtime binaries" in output
    assert "gitleaks" in output


def test_gitleaks_guard_runtime_fails_closed_without_binary(tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    env = os.environ.copy()
    env["PATH"] = str(empty_bin)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
    }

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "guardrails" / "gitleaks-guard" / "claude-code.py"),
        ],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 2
    assert "BLOCKED: gitleaks is required" in result.stderr


@pytest.mark.parametrize("name", HEALTHCARE_GUARDRAILS)
@pytest.mark.parametrize("harness", ("codex", "all"))
def test_healthcare_guardrails_refuse_unsupported_codex_dry_run(
    name: str,
    harness: str,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    target_project = tmp_path / "fresh-project"
    home.mkdir()
    target_project.mkdir()

    result = run_library(
        home,
        target_project,
        "guardrail",
        "use",
        name,
        "--dry-run",
        "--harness",
        harness,
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert "codex_status=not-supported" in payload["reason"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "clc-ad4.7: project-scoped guardrail installs still route through "
        "home harness settings instead of project-local harness settings."
    ),
)
@pytest.mark.parametrize("name", HEALTHCARE_GUARDRAILS)
def test_healthcare_guardrails_project_scope_harness_all_is_project_local(
    name: str,
    tmp_path: Path,
) -> None:
    """Fresh-project integration check for clc-ad4.7 path handling."""
    home = tmp_path / "home"
    target_project = tmp_path / "fresh-project"
    bin_dir = make_stub_binaries(tmp_path)
    home.mkdir()
    target_project.mkdir()

    result = run_library(
        home,
        target_project,
        "guardrail",
        "use",
        name,
        "--scope",
        "project",
        "--harness",
        "all",
        path_prefix=bin_dir,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert (target_project / ".claude" / "settings.json").exists()
    assert not (home / ".claude" / "settings.json").exists()
