"""The SSH clone fallback must start from an empty directory.

Guards CL-k33k. `clone_github_repo` tries HTTPS first, then SSH. The cognovis
remotes are private, so the HTTPS attempt always fails -- but git creates and
partially populates the target before failing. The old code retried into that
same dirty path, so git refused with "already exists and is not an empty
directory". The fallback could therefore never succeed, and that misleading
message masked the real error.

The blast radius was total: `library sync` reported `0 refreshed` with a
per-entry ERROR for every GitHub-sourced primitive, so sources and installed
copies drifted silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.errors import SourceError  # noqa: E402
from lib.source import clone_github_repo  # noqa: E402


class _Result:
    def __init__(self, returncode: int, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr


def test_ssh_fallback_receives_an_empty_directory(monkeypatch):
    """The real bug: git leaves the target non-empty after a failed clone."""
    seen: list[tuple[str, bool]] = []

    def fake_run(cmd, capture_output=False, text=False):
        url, target = cmd[-2], Path(cmd[-1])
        # Record whether the target was empty when this attempt started.
        was_empty = target.is_dir() and not any(target.iterdir())
        seen.append((url, was_empty))
        if url.startswith("https://"):
            # Reproduce git's behavior: populate the target, then fail.
            (target / ".git").mkdir(parents=True, exist_ok=True)
            return _Result(128, "fatal: could not read Username")
        (target / ".git").mkdir(parents=True, exist_ok=True)
        return _Result(0)

    monkeypatch.setattr("lib.source.subprocess.run", fake_run)

    tmp = clone_github_repo("https://github.com/cognovis/library-core.git")

    assert len(seen) == 2, "expected an HTTPS attempt then an SSH fallback"
    assert seen[0][0].startswith("https://")
    assert seen[1][0] == "git@github.com:cognovis/library-core.git"
    assert seen[1][1], "SSH fallback must start from an empty directory"
    assert tmp.is_dir()


def test_branch_is_passed_to_both_attempts(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(cmd, capture_output=False, text=False):
        commands.append(cmd)
        Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
        (Path(cmd[-1]) / ".git").mkdir(exist_ok=True)
        return _Result(128 if cmd[-2].startswith("https://") else 0, "boom")

    monkeypatch.setattr("lib.source.subprocess.run", fake_run)

    clone_github_repo("https://github.com/cognovis/library-core.git", "dev")

    for cmd in commands:
        assert "--branch" in cmd and cmd[cmd.index("--branch") + 1] == "dev"


def test_both_transports_failing_names_the_real_errors(monkeypatch):
    """The HTTPS cause must survive; it was previously overwritten by the retry."""

    def fake_run(cmd, capture_output=False, text=False):
        target = Path(cmd[-1])
        target.mkdir(parents=True, exist_ok=True)
        (target / ".git").mkdir(exist_ok=True)
        if cmd[-2].startswith("https://"):
            return _Result(128, "could not read Username for 'https://github.com'")
        return _Result(128, "Permission denied (publickey)")

    monkeypatch.setattr("lib.source.subprocess.run", fake_run)

    with pytest.raises(SourceError) as excinfo:
        clone_github_repo("https://github.com/cognovis/library-core.git")

    message = str(excinfo.value)
    assert "could not read Username" in message
    assert "Permission denied (publickey)" in message
    assert "already exists" not in message


def test_temp_dir_is_removed_when_both_transports_fail(monkeypatch):
    captured: list[Path] = []

    def fake_run(cmd, capture_output=False, text=False):
        target = Path(cmd[-1])
        target.mkdir(parents=True, exist_ok=True)
        captured.append(target)
        return _Result(128, "nope")

    monkeypatch.setattr("lib.source.subprocess.run", fake_run)

    with pytest.raises(SourceError):
        clone_github_repo("https://github.com/cognovis/library-core.git")

    assert captured, "expected at least one clone attempt"
    assert not captured[0].exists(), "failed clone must not leak a temp directory"
