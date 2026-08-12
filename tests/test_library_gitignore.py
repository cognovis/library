from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY = REPO_ROOT / "scripts" / "library.py"
BEGIN = "# BEGIN Library-managed project installs"
END = "# END Library-managed project installs"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "--quiet")
    _git(path, "config", "user.name", "Library Test")
    _git(path, "config", "user.email", "library@example.invalid")
    return path


def _write_lock(repo: Path, installed: list[dict]) -> None:
    (repo / ".library.lock").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "migration": {"prune_ack_required": False},
                "requested_roots": [],
                "receipts": [],
                "prerequisites": [],
                "installed": installed,
            }
        ),
        encoding="utf-8",
    )


def _run_library(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(repo / "home")
    return subprocess.run(
        ["uv", "run", str(LIBRARY), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _managed_block(repo: Path) -> str:
    content = (repo / ".gitignore").read_text(encoding="utf-8")
    return content[content.index(BEGIN) : content.index(END) + len(END)]


def test_use_writes_project_targets_and_bridge_symlinks_only(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    source = repo / "source-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("# Impeccable\n", encoding="utf-8")
    (repo / "library.yaml").write_text(
        yaml.safe_dump(
            {
                "default_dirs": {
                    "skills": [
                        {"default": ".agents/skills/"},
                        {"global": str(repo / "home/.agents/skills/")},
                        {"claude_bridge": ".claude/skills/"},
                    ]
                },
                "library": {
                    "skills": [
                        {
                            "name": "impeccable",
                            "description": "Test skill",
                            "source": str(source / "SKILL.md"),
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    result = _run_library(repo, "skill", "use", "impeccable", "--json")

    assert result.returncode == 0, result.stderr
    use_payload = json.loads(result.stdout)
    assert use_payload["gitignore"]["managed_paths"] == [
        ".library.lock",
        ".library.lock.lock",
        ".library.lock.workspace-lock",
        ".agents/skills/impeccable/",
        ".claude/skills/impeccable",
    ]
    lock = yaml.safe_load((repo / ".library.lock").read_text(encoding="utf-8"))
    lock["installed"].extend(
        [
            {
                "name": "global-only",
                "type": "skill",
                "scope": "global",
                "install_target": str(repo / ".agents/skills/global-only"),
            },
            {
                "name": "outside",
                "type": "skill",
                "scope": "project",
                "install_target": str(outside),
            },
        ]
    )
    (repo / ".library.lock").write_text(yaml.safe_dump(lock), encoding="utf-8")
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.gitignore import reconcile_project_gitignore

    outcome = reconcile_project_gitignore(repo)
    assert outcome["managed_paths"] == [
        ".library.lock",
        ".library.lock.lock",
        ".library.lock.workspace-lock",
        ".agents/skills/impeccable/",
        ".claude/skills/impeccable",
    ]
    block = _managed_block(repo)
    assert "/.agents/skills/impeccable/" in block
    assert "/.claude/skills/impeccable" in block
    assert "global-only" not in block
    assert "outside" not in block


def test_sync_writes_lock_artifacts_and_current_project_targets(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _write_lock(
        repo,
        [
            {
                "name": "current",
                "type": "skill",
                "scope": "project",
                "install_target": ".agents/skills/current/",
                "source": "https://example.invalid/library.git",
                "source_commit": "deadbeef",
            }
        ],
    )

    result = _run_library(repo, "sync", "--scope", "project", "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["gitignore"]["managed_paths"] == [
        ".library.lock",
        ".library.lock.lock",
        ".library.lock.workspace-lock",
        ".agents/skills/current/",
    ]
    assert _managed_block(repo).splitlines()[1:4] == [
        "/.library.lock",
        "/.library.lock.lock",
        "/.library.lock.workspace-lock",
    ]


def test_reconcile_preserves_user_content_and_prunes_stale_entries(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text(
        f"dist/\n\n{BEGIN}\n/.agents/skills/stale/\n{END}\n\n.env\n",
        encoding="utf-8",
    )
    _write_lock(
        repo,
        [
            {
                "name": "current",
                "type": "skill",
                "scope": "project",
                "install_target": ".agents/skills/current/",
            }
        ],
    )
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.gitignore import reconcile_project_gitignore

    first = reconcile_project_gitignore(repo)
    content = (repo / ".gitignore").read_text(encoding="utf-8")
    second = reconcile_project_gitignore(repo)

    assert first["updated"] is True
    assert second["updated"] is False
    assert (repo / ".gitignore").read_text(encoding="utf-8") == content
    assert content.count(BEGIN) == 1
    assert content.count(END) == 1
    assert "dist/" in content and ".env" in content
    assert "stale" not in content
    assert "/.agents/skills/current/" in content


def test_tracked_paths_warn_without_untracking_and_dry_run_is_immutable(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    target = repo / ".agents" / "skills" / "tracked"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Tracked\n", encoding="utf-8")
    _write_lock(
        repo,
        [
            {
                "name": "tracked",
                "type": "skill",
                "scope": "project",
                "install_target": ".agents/skills/tracked/",
            }
        ],
    )
    _git(repo, "add", ".agents/skills/tracked/SKILL.md")
    before_index = _git(repo, "ls-files").stdout

    result = _run_library(repo, "sync", "--scope", "project", "--json")
    payload = json.loads(result.stdout)
    after_normal = _git(repo, "ls-files").stdout
    human = _run_library(repo, "sync", "--scope", "project")
    gitignore_before_dry_run = (repo / ".gitignore").read_text(encoding="utf-8")
    dry_run = _run_library(
        repo, "sync", "--scope", "project", "--dry-run", "--json"
    )

    assert result.returncode == 0
    assert payload["gitignore"]["tracked_paths"] == [
        ".agents/skills/tracked/SKILL.md"
    ]
    assert any("--untrack" in warning for warning in payload["warnings"])
    assert "Warning:" in human.stdout
    assert "--untrack" in human.stdout
    assert ".agents/skills/tracked/SKILL.md" in human.stdout
    assert before_index == after_normal
    assert (repo / ".gitignore").read_text(encoding="utf-8") == gitignore_before_dry_run
    assert _git(repo, "ls-files").stdout == after_normal
    assert "gitignore" not in json.loads(dry_run.stdout)


def test_untrack_removes_managed_paths_from_index_but_keeps_files(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    managed = repo / ".agents" / "skills" / "tracked" / "SKILL.md"
    managed.parent.mkdir(parents=True)
    managed.write_text("# Tracked\n", encoding="utf-8")
    unrelated = repo / "README.md"
    unrelated.write_text("Keep tracked\n", encoding="utf-8")
    _write_lock(
        repo,
        [
            {
                "name": "tracked",
                "type": "skill",
                "scope": "project",
                "install_target": ".agents/skills/tracked/",
            }
        ],
    )
    _git(repo, "add", ".agents/skills/tracked/SKILL.md", "README.md")

    result = _run_library(
        repo, "sync", "--scope", "project", "--untrack", "--json"
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["gitignore"]["untracked_paths"] == [
        ".agents/skills/tracked/SKILL.md"
    ]
    assert managed.exists()
    assert unrelated.exists()
    assert _git(repo, "ls-files").stdout.splitlines() == ["README.md"]
