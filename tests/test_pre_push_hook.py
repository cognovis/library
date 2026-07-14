"""Runtime tests for the managed gitleaks pre-push hook."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_HOOK = REPO_ROOT / "prime" / "hooks" / "pre-push.sh"
ZERO_SHA = "0" * 40


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _link_system_tools(fake_bin: Path) -> None:
    for tool in ("cat", "dirname", "mktemp", "rm"):
        tool_path = shutil.which(tool)
        if tool_path:
            (fake_bin / tool).symlink_to(tool_path)


def _copy_hook(tmp: Path) -> Path:
    hooks_dir = tmp / "hooks"
    hooks_dir.mkdir()
    hook_path = hooks_dir / "pre-push"
    shutil.copy2(SOURCE_HOOK, hook_path)
    hook_path.chmod(0o755)
    return hook_path


def _write_fake_tools(fake_bin: Path) -> None:
    fake_bin.mkdir()
    _link_system_tools(fake_bin)
    _write_executable(
        fake_bin / "timeout",
        "#!/bin/bash\n"
        "printf '%s\\n' \"$*\" >> \"$TIMEOUT_LOG\"\n"
        "shift\n"
        "exec \"$@\"\n",
    )
    _write_executable(
        fake_bin / "gitleaks",
        "#!/bin/bash\n"
        "printf '%s\\n' \"$*\" >> \"$GITLEAKS_LOG\"\n"
        "if [[ -n \"${GITLEAKS_FAIL_ON:-}\" && \"$*\" == *\"$GITLEAKS_FAIL_ON\"* ]]; then\n"
        "  exit 1\n"
        "fi\n"
        "exit \"${GITLEAKS_EXIT_CODE:-0}\"\n",
    )


def _run_hook(hook_path: Path, stdin: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(hook_path), *args],
        input=stdin,
        text=True,
        capture_output=True,
        cwd=hook_path.parent.parent,
        env=env,
        check=False,
    )


def _base_env(tmp: Path) -> dict[str, str]:
    fake_bin = tmp / "bin"
    _write_fake_tools(fake_bin)
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(fake_bin),
            "TIMEOUT_LOG": str(tmp / "timeout.log"),
            "GITLEAKS_LOG": str(tmp / "gitleaks.log"),
        }
    )
    return env


def test_pre_push_scans_clean_range_then_chains_with_replayed_stdin_and_args() -> None:
    """A clean outgoing ref runs gitleaks first, then chains once with original input and args."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        hook_path = _copy_hook(tmp)
        env = _base_env(tmp)
        env["CHAIN_LOG"] = str(tmp / "chain.log")
        env["CHAIN_STDIN_LOG"] = str(tmp / "chain.stdin")
        _write_executable(
            hook_path.parent / "pre-push.local",
            "#!/bin/bash\n"
            "printf 'args:%s|%s\\n' \"$1\" \"$2\" >> \"$CHAIN_LOG\"\n"
            "cat > \"$CHAIN_STDIN_LOG\"\n"
            "exit \"${CHAIN_EXIT_CODE:-0}\"\n",
        )
        local_sha = "a" * 40
        remote_sha = "b" * 40
        stdin = f"refs/heads/main {local_sha} refs/heads/main {remote_sha}\n"

        result = _run_hook(hook_path, stdin, env, "origin", "git@example.test:repo.git")

        assert result.returncode == 0, result.stderr
        assert (tmp / "gitleaks.log").read_text().strip() == (
            f"git --no-banner --redact --log-opts={remote_sha}..{local_sha}"
        )
        assert (tmp / "chain.log").read_text() == "args:origin|git@example.test:repo.git\n"
        assert (tmp / "chain.stdin").read_text() == stdin


def test_pre_push_blocks_finding_before_chained_hook_runs() -> None:
    """A gitleaks finding blocks the push and does not invoke the sidecar hook."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        hook_path = _copy_hook(tmp)
        env = _base_env(tmp)
        env["GITLEAKS_EXIT_CODE"] = "1"
        env["CHAIN_LOG"] = str(tmp / "chain.log")
        _write_executable(
            hook_path.parent / "pre-push.local",
            "#!/bin/bash\n"
            "printf 'chained\\n' >> \"$CHAIN_LOG\"\n",
        )
        stdin = f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}\n"

        result = _run_hook(hook_path, stdin, env, "origin", "url")

        assert result.returncode != 0
        assert not (tmp / "chain.log").exists()


def test_pre_push_handles_new_branch_deletion_and_empty_stdin_bounds() -> None:
    """New branches use --not --remotes, deletions are skipped, and empty stdin passes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        hook_path = _copy_hook(tmp)
        env = _base_env(tmp)
        new_sha = "c" * 40
        delete_remote_sha = "d" * 40
        stdin = (
            f"refs/heads/new {new_sha} refs/heads/new {ZERO_SHA}\n"
            f"refs/heads/old {ZERO_SHA} refs/heads/old {delete_remote_sha}\n"
        )

        result = _run_hook(hook_path, stdin, env, "origin", "url")
        empty_result = _run_hook(hook_path, "", env, "origin", "url")

        assert result.returncode == 0, result.stderr
        assert empty_result.returncode == 0, empty_result.stderr
        assert (tmp / "gitleaks.log").read_text().splitlines() == [
            f"git --no-banner --redact --log-opts={new_sha} --not --remotes",
        ]


def test_pre_push_fails_closed_on_malformed_input_without_chaining() -> None:
    """A present but malformed stdin line is rejected before scanning or chaining."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        hook_path = _copy_hook(tmp)
        env = _base_env(tmp)
        env["CHAIN_LOG"] = str(tmp / "chain.log")
        _write_executable(
            hook_path.parent / "pre-push.local",
            "#!/bin/bash\n"
            "printf 'chained\\n' >> \"$CHAIN_LOG\"\n",
        )

        result = _run_hook(hook_path, "not four fields\n", env, "origin", "url")

        assert result.returncode != 0
        assert "malformed pre-push input" in result.stderr
        assert not (tmp / "gitleaks.log").exists()
        assert not (tmp / "chain.log").exists()


def test_pre_push_fails_closed_without_timeout_or_gtimeout() -> None:
    """The hook refuses to run gitleaks when no timeout command can bound runtime."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        hook_path = _copy_hook(tmp)
        fake_bin = tmp / "bin"
        fake_bin.mkdir()
        _link_system_tools(fake_bin)
        _write_executable(fake_bin / "gitleaks", "#!/bin/bash\nexit 0\n")
        env = os.environ.copy()
        env["PATH"] = str(fake_bin)
        stdin = f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}\n"

        result = _run_hook(hook_path, stdin, env, "origin", "url")

        assert result.returncode != 0
        assert "cannot bound gitleaks runtime" in result.stderr


def test_pre_push_fails_closed_without_gitleaks() -> None:
    """Missing gitleaks is a setup failure and blocks the push."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        hook_path = _copy_hook(tmp)
        fake_bin = tmp / "bin"
        fake_bin.mkdir()
        _link_system_tools(fake_bin)
        _write_executable(fake_bin / "timeout", "#!/bin/bash\nexit 0\n")
        env = os.environ.copy()
        env["PATH"] = str(fake_bin)
        stdin = f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}\n"

        result = _run_hook(hook_path, stdin, env, "origin", "url")

        assert result.returncode != 0
        assert "gitleaks not found" in result.stderr
