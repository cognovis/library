"""Local Git checkout inspection for repository-bounded platform operations."""

from __future__ import annotations

import subprocess
from pathlib import Path


def canonical_checkout_problem(
    repository: Path,
    *,
    expected_branch: str | None = None,
    expected_commit: str | None = None,
    expected_remote: str | None = None,
) -> str | None:
    """Return why a path is not a clean canonical Git worktree, if anything."""
    top_level = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if top_level.returncode != 0:
        return "path is not a Git worktree"
    if Path(top_level.stdout.strip()).resolve() != repository:
        return "path is not the Git worktree top-level"
    if not (repository / ".git").is_dir():
        return "path is a linked Git worktree, not the canonical checkout"
    branch = subprocess.run(
        ["git", "-C", str(repository), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if branch.returncode != 0:
        return "canonical checkout is detached"
    branch_name = branch.stdout.strip()
    if expected_branch is not None and branch_name != expected_branch:
        return f"canonical branch is {branch_name}; expected {expected_branch}"
    head = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD^{commit}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if head.returncode != 0:
        return "canonical checkout commit could not be inspected"
    head_commit = head.stdout.strip().lower()
    if expected_commit is not None and head_commit != expected_commit.lower():
        return f"canonical commit is {head_commit}; expected {expected_commit.lower()}"
    status = subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        return "Git status could not be inspected"
    if status.stdout:
        return "Git worktree has uncommitted changes"
    if expected_remote is not None:
        upstream = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        expected_upstream = f"{expected_remote}/{branch_name}"
        if upstream.returncode != 0 or upstream.stdout.strip() != expected_upstream:
            return f"canonical branch does not track {expected_upstream}"
        upstream_commit = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "@{upstream}^{commit}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if (
            upstream_commit.returncode != 0
            or upstream_commit.stdout.strip().lower() != head_commit
        ):
            return "canonical branch and its upstream do not serve the same commit"
        try:
            published = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "ls-remote",
                    "--exit-code",
                    expected_remote,
                    f"refs/heads/{branch_name}",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return f"published branch could not be verified from {expected_remote}"
        published_commit = (
            published.stdout.split(maxsplit=1)[0].lower()
            if published.returncode == 0 and published.stdout.strip()
            else ""
        )
        if published_commit != head_commit:
            return (
                f"published {expected_remote}/{branch_name} does not serve "
                f"{head_commit}"
            )
    return None
