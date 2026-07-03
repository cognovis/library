"""Regression tests for bead worktree runtime overlay bootstrap."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "bin" / "lib" / "worktree-bootstrap.zsh"
CLD_BIN = REPO_ROOT / "bin" / "cld"
CDX_BIN = REPO_ROOT / "bin" / "cdx"

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not available")


def _write_bootstrap_config(repo_root: Path) -> None:
    config = repo_root / ".agents" / "orchestrator-config.yml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "worktree_bootstrap:\n"
        "  symlink_from_main:\n"
        "    - .agents\n"
        "    - .claude/skills\n",
        encoding="utf-8",
    )


def _seed_main_overlay(repo_root: Path) -> None:
    _write_bootstrap_config(repo_root)
    (repo_root / ".agents" / "skills" / "beads" / "scripts").mkdir(parents=True)
    (repo_root / ".agents" / "skills" / "beads" / "SKILL.md").write_text(
        "---\nname: beads\n---\n",
        encoding="utf-8",
    )
    (repo_root / ".claude" / "skills").mkdir(parents=True)
    (repo_root / ".claude" / "skills" / "beads").symlink_to(
        repo_root / ".agents" / "skills" / "beads"
    )


def _write_git_mock(tmp_path: Path, repo_root: Path) -> tuple[Path, Path]:
    git_log = tmp_path / "git-argv.txt"
    git_mock = tmp_path / "git-mock"
    git_mock.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$GIT_ARGV_LOG\"\n"
        "if [ \"$1\" = rev-parse ] && [ \"$2\" = --show-toplevel ]; then\n"
        "  printf '%s\\n' \"$GIT_REPO_ROOT\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = fetch ] || [ \"$1\" = pull ]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = worktree ] && [ \"$2\" = list ]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = show-ref ]; then\n"
        "  exit 1\n"
        "fi\n"
        "if [ \"$1\" = worktree ] && [ \"$2\" = add ]; then\n"
        "  if [ \"$3\" = -b ]; then\n"
        "    mkdir -p \"$5\"\n"
        "  else\n"
        "    mkdir -p \"$3\"\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    git_mock.chmod(0o755)
    return git_mock, git_log


def _write_bd_mock(tmp_path: Path) -> Path:
    bd_mock = tmp_path / "bd-mock"
    bd_mock.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = config ] && [ \"$2\" = get ]; then\n"
        "  printf 'CL\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = show ]; then\n"
        "  printf '[{\"id\":\"CL-smoke\",\"status\":\"open\"}]\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = dolt ] && [ \"$2\" = pull ]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    bd_mock.chmod(0o755)
    return bd_mock


def test_helper_symlinks_configured_overlay_paths(tmp_path: Path) -> None:
    main = tmp_path / "main"
    worktree = tmp_path / "worktree"
    _seed_main_overlay(main)
    worktree.mkdir()

    result = subprocess.run(
        [
            "zsh",
            "-c",
            f"source {HELPER}; _bootstrap_worktree_from_main {main} {worktree}",
        ],
        capture_output=True,
        text=True,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )

    assert result.returncode == 0, result.stderr
    assert (worktree / ".agents").is_symlink()
    assert (worktree / ".agents").resolve() == (main / ".agents").resolve()
    assert (worktree / ".claude" / "skills").is_symlink()
    assert (worktree / ".claude" / "skills").resolve() == (
        main / ".claude" / "skills"
    ).resolve()


def test_helper_uses_default_overlay_paths_without_config(tmp_path: Path) -> None:
    main = tmp_path / "main"
    worktree = tmp_path / "worktree"
    (main / ".agents" / "skills" / "beads").mkdir(parents=True)
    (main / ".claude" / "skills").mkdir(parents=True)
    worktree.mkdir()

    result = subprocess.run(
        [
            "zsh",
            "-c",
            f"source {HELPER}; _bootstrap_worktree_from_main {main} {worktree}",
        ],
        capture_output=True,
        text=True,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )

    assert result.returncode == 0, result.stderr
    assert (worktree / ".agents").resolve() == (main / ".agents").resolve()
    assert (worktree / ".claude" / "skills").resolve() == (
        main / ".claude" / "skills"
    ).resolve()


def test_helper_excludes_created_overlay_symlinks_from_git_status(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")

    main = tmp_path / "main"
    worktree = tmp_path / "worktree"
    main.mkdir()
    subprocess.run(["git", "init"], cwd=main, check=True, capture_output=True)
    (main / ".agents" / "skills" / "beads").mkdir(parents=True)
    (main / ".claude" / "skills").mkdir(parents=True)
    worktree.mkdir()

    result = subprocess.run(
        [
            "zsh",
            "-c",
            f"source {HELPER}; _bootstrap_worktree_from_main {main} {worktree}",
        ],
        capture_output=True,
        text=True,
        env={
            "GIT_BIN": shutil.which("git") or "git",
            "HOME": str(tmp_path),
            "PATH": os.environ.get("PATH", ""),
        },
    )

    assert result.returncode == 0, result.stderr
    exclude = main / ".git" / "info" / "exclude"
    exclude_lines = exclude.read_text(encoding="utf-8").splitlines()
    assert ".agents" in exclude_lines
    assert ".claude/skills" in exclude_lines


def test_cdx_bq_bootstraps_overlay_after_worktree_creation(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo-root"
    (repo_root / ".git" / "info").mkdir(parents=True)
    _seed_main_overlay(repo_root)
    git_mock, git_log = _write_git_mock(tmp_path, repo_root)
    bd_mock = _write_bd_mock(tmp_path)

    codex_args = tmp_path / "codex-args.txt"
    codex_mock = tmp_path / "codex-mock"
    codex_mock.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" > \"$CODEX_ARGS_FILE\"\n",
        encoding="utf-8",
    )
    codex_mock.chmod(0o755)

    worktree_root = tmp_path / "worktrees"
    runtime = tmp_path / "beads-runtime"
    (runtime / "scripts").mkdir(parents=True)

    env = dict(os.environ)
    env.update(
        {
            "BD_BIN": str(bd_mock),
            "CODEX_BIN": str(codex_mock),
            "CODEX_ARGS_FILE": str(codex_args),
            "GIT_BIN": str(git_mock),
            "GIT_ARGV_LOG": str(git_log),
            "GIT_REPO_ROOT": str(repo_root),
            "CDX_WORKTREE_ROOT": str(worktree_root),
            "BEADS_RUNTIME_DIR": str(runtime),
            "CDX_COMPACT_CONTEXT_SCRIPT": str(tmp_path / "missing-compact-context.py"),
            "CLD_COMPACT_OUTPUT": "0",
            "HOME": str(tmp_path),
        }
    )

    result = subprocess.run(
        [str(CDX_BIN), "-bq", "CL-smoke"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    worktree = worktree_root / "bead-CL-smoke"
    assert (worktree / ".agents").is_symlink()
    assert (worktree / ".agents").resolve() == (repo_root / ".agents").resolve()
    assert (worktree / ".claude" / "skills").is_symlink()
    assert (worktree / ".claude" / "skills").resolve() == (
        repo_root / ".claude" / "skills"
    ).resolve()


def test_cld_bq_starts_claude_inside_bootstrapped_worktree(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo-root"
    (repo_root / ".git" / "info").mkdir(parents=True)
    _seed_main_overlay(repo_root)
    git_mock, git_log = _write_git_mock(tmp_path, repo_root)
    bd_mock = _write_bd_mock(tmp_path)

    claude_cwd = tmp_path / "claude-cwd.txt"
    claude_args = tmp_path / "claude-args.txt"
    claude_mock = tmp_path / "claude-mock"
    claude_mock.write_text(
        "#!/bin/sh\n"
        "pwd > \"$CLAUDE_CWD_FILE\"\n"
        "printf '%s\\n' \"$*\" > \"$CLAUDE_ARGS_FILE\"\n",
        encoding="utf-8",
    )
    claude_mock.chmod(0o755)

    env = {
        "BD_BIN": str(bd_mock),
        "CLAUDE_BIN": str(claude_mock),
        "CLAUDE_ARGS_FILE": str(claude_args),
        "CLAUDE_CWD_FILE": str(claude_cwd),
        "GIT_BIN": str(git_mock),
        "GIT_ARGV_LOG": str(git_log),
        "GIT_REPO_ROOT": str(repo_root),
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    }

    result = subprocess.run(
        [str(CLD_BIN), "-bq", "CL-smoke"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    worktree = repo_root / ".claude" / "worktrees" / "bead-CL-smoke"
    assert claude_cwd.read_text(encoding="utf-8").strip() == str(worktree)
    assert "--worktree" not in claude_args.read_text(encoding="utf-8")
    assert (worktree / ".agents").is_symlink()
    assert (worktree / ".agents").resolve() == (repo_root / ".agents").resolve()
    assert (worktree / ".claude" / "skills").is_symlink()
    assert (worktree / ".claude" / "skills").resolve() == (
        repo_root / ".claude" / "skills"
    ).resolve()
