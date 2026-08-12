from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
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


def _write_v2_lock(
    repo: Path, *, receipts: list[dict], installed: list[dict] | None = None
) -> None:
    (repo / ".library.lock").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "migration": {"prune_ack_required": False},
                "requested_roots": [],
                "receipts": receipts,
                "prerequisites": [],
                "installed": installed or [],
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
        ".agents/skills/impeccable",
        ".agents/skills/impeccable/SKILL.md",
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
        ".agents/skills/impeccable",
        ".agents/skills/impeccable/SKILL.md",
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
    dry_run = _run_library(repo, "sync", "--scope", "project", "--dry-run", "--json")

    assert result.returncode == 0
    assert payload["gitignore"]["tracked_paths"] == [".agents/skills/tracked/SKILL.md"]
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

    result = _run_library(repo, "sync", "--scope", "project", "--untrack", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["gitignore"]["untracked_paths"] == [
        ".agents/skills/tracked/SKILL.md"
    ]
    assert managed.exists()
    assert unrelated.exists()
    assert _git(repo, "ls-files").stdout.splitlines() == ["README.md"]


def test_marker_text_embedded_in_user_prose_is_preserved(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    prose = (
        f"Documentation mentions {BEGIN} inline.\r\n"
        f"It also mentions {END} without declaring a managed block.\r\n"
    )
    (repo / ".gitignore").write_text(prose, encoding="utf-8", newline="")
    _write_lock(repo, [])
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.gitignore import reconcile_project_gitignore

    reconcile_project_gitignore(repo)

    with (repo / ".gitignore").open(encoding="utf-8", newline="") as handle:
        content = handle.read()
    assert content.startswith(prose)
    assert content.count(BEGIN) == 2
    assert content.count(END) == 2
    assert content.replace(prose, "", 1).startswith("\r\n" + BEGIN + "\r\n")


@pytest.mark.parametrize(
    "malformed",
    [
        f"{BEGIN}\n/path\n",
        f"{END}\n",
        f"{BEGIN}\n{BEGIN}\n{END}\n{END}\n",
        f"{BEGIN}\n{END}\n{BEGIN}\n{END}\n",
    ],
    ids=["unmatched-begin", "unmatched-end", "nested", "duplicate"],
)
def test_malformed_managed_markers_fail_without_writing(
    tmp_path: Path, malformed: str
) -> None:
    repo = _init_repo(tmp_path / "repo")
    gitignore = repo / ".gitignore"
    gitignore.write_text(malformed, encoding="utf-8")
    _write_lock(repo, [])
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.errors import LibraryError
    from lib.gitignore import reconcile_project_gitignore

    with pytest.raises(LibraryError):
        reconcile_project_gitignore(repo)

    assert gitignore.read_text(encoding="utf-8") == malformed


def test_special_names_are_ignored_and_untracked_literally(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    managed_names = [
        "star*name",
        "question?name",
        "bracket[name]",
        "!bang",
        "#hash",
        "back\\slash",
        ":colon",
    ]
    siblings = [
        "starXname",
        "questionXname",
        "bracketn",
        "bang",
        "hash",
        "backslash",
        "colon",
    ]
    entries = []
    for name in [*managed_names, *siblings]:
        path = repo / name / "content.txt"
        path.parent.mkdir()
        path.write_text(name, encoding="utf-8")
    for name in managed_names:
        entries.append(
            {
                "name": name,
                "type": "skill",
                "scope": "project",
                "install_target": f"{name}/",
            }
        )
    _write_lock(repo, entries)
    _git(
        repo,
        "add",
        "-f",
        "--",
        *(f":(top,literal){name}" for name in [*managed_names, *siblings]),
    )
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.gitignore import _tracked_managed_paths, reconcile_project_gitignore

    expected_tracked = {f"{name}/content.txt" for name in managed_names}
    assert (
        set(_tracked_managed_paths(repo, [f"{name}/" for name in managed_names]))
        == expected_tracked
    )

    result = reconcile_project_gitignore(repo, untrack=True)

    assert set(managed_names).issubset(
        {path.rstrip("/") for path in result["managed_paths"]}
    )
    tracked = set(_git(repo, "ls-files").stdout.splitlines())
    for name in managed_names:
        exact = f"{name}/content.txt"
        ignored = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "--no-index", "-q", "--stdin"],
            input="./" + exact + "\n",
            capture_output=True,
            text=True,
            check=False,
        )
        assert ignored.returncode == 0, exact
        assert exact in result["untracked_paths"]
        assert (repo / exact).exists()
        assert exact not in tracked
    for name in siblings:
        sibling = f"{name}/content.txt"
        check = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "check-ignore",
                "--no-index",
                "-q",
                "--",
                "./" + sibling,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert check.returncode == 1
        assert sibling in tracked
        assert (repo / sibling).exists()


def test_sync_uses_receipt_targets_when_installed_projection_is_empty(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    target_specs = [
        ("generated/file.txt", "file"),
        ("generated/directory", "directory"),
        ("bridges/tool", "symlink"),
    ]
    for relative, kind in target_specs:
        path = repo / relative
        if kind == "directory":
            path.mkdir(parents=True)
            (path / "member.txt").write_text("directory", encoding="utf-8")
        elif kind == "symlink":
            path.parent.mkdir(parents=True)
            path.symlink_to("../generated/file.txt")
        else:
            path.parent.mkdir(parents=True)
            path.write_text("file", encoding="utf-8")
    _write_v2_lock(
        repo,
        receipts=[
            {
                "id": "skill:receipt-only@1.0.0",
                "type": "skill",
                "name": "receipt-only",
                "scope": "project",
                "catalog_identity": "https://example.invalid/catalog",
                "resolved_version": "1.0.0",
                "verified": True,
                "adopted": False,
                "targets": [
                    {"path": relative, "kind": kind} for relative, kind in target_specs
                ],
                "owners_cache": ["skill:receipt-only"],
            }
        ],
        installed=[],
    )
    tracked_files = [
        "generated/file.txt",
        "generated/directory/member.txt",
        "bridges/tool",
    ]
    _git(repo, "add", "-f", "--", *tracked_files)

    warning_result = _run_library(repo, "sync", "--scope", "project", "--json")

    assert warning_result.returncode == 0, warning_result.stderr
    warning_payload = json.loads(warning_result.stdout)
    assert warning_payload["gitignore"]["managed_paths"][-3:] == [
        "generated/file.txt",
        "generated/directory",
        "bridges/tool",
    ]
    assert warning_payload["gitignore"]["tracked_paths"] == sorted(tracked_files)
    assert any("--untrack" in warning for warning in warning_payload["warnings"])

    untrack_result = _run_library(
        repo, "sync", "--scope", "project", "--untrack", "--json"
    )

    assert untrack_result.returncode == 0, untrack_result.stderr
    untrack_payload = json.loads(untrack_result.stdout)
    assert untrack_payload["gitignore"]["untracked_paths"] == sorted(tracked_files)
    assert _git(repo, "ls-files").stdout == ""
    for relative in tracked_files:
        assert (repo / relative).exists() or (repo / relative).is_symlink()


def test_receipt_targets_override_stale_installed_projection(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    current = repo / "current.txt"
    stale = repo / "stale.txt"
    current.write_text("current", encoding="utf-8")
    stale.write_text("stale", encoding="utf-8")
    _write_v2_lock(
        repo,
        receipts=[
            {
                "id": "prompt:current@1.0.0",
                "type": "prompt",
                "name": "current",
                "scope": "project",
                "catalog_identity": "https://example.invalid/catalog",
                "resolved_version": "1.0.0",
                "verified": True,
                "adopted": False,
                "targets": [{"path": "current.txt", "kind": "file"}],
                "owners_cache": ["prompt:current"],
            }
        ],
        installed=[
            {
                "name": "stale",
                "type": "prompt",
                "scope": "project",
                "install_target": "stale.txt",
            }
        ],
    )
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.gitignore import reconcile_project_gitignore

    result = reconcile_project_gitignore(repo)

    assert "current.txt" in result["managed_paths"]
    assert "stale.txt" not in result["managed_paths"]


def test_whitespace_target_names_remain_exact_for_ignore_and_untrack(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    managed_targets = [
        " leading-file",
        "trailing-file ",
        " leading-dir/",
        "trailing-dir /",
    ]
    siblings = ["leading-file", "trailing-file", "leading-dir", "trailing-dir"]
    tracked_managed: list[str] = []
    for target in managed_targets:
        if target.endswith("/"):
            member = target + "member.txt"
            path = repo / member
        else:
            member = target
            path = repo / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(target, encoding="utf-8")
        tracked_managed.append(member)
    for sibling in siblings:
        path = repo / sibling
        path.write_text(sibling, encoding="utf-8")
    _write_v2_lock(
        repo,
        receipts=[
            {
                "id": "skill:whitespace@1.0.0",
                "type": "skill",
                "name": "whitespace",
                "scope": "project",
                "catalog_identity": "https://example.invalid/catalog",
                "resolved_version": "1.0.0",
                "verified": True,
                "adopted": False,
                "targets": [
                    {
                        "path": target,
                        "kind": "directory" if target.endswith("/") else "file",
                    }
                    for target in managed_targets
                ],
                "owners_cache": ["skill:whitespace"],
            }
        ],
    )
    _git(
        repo,
        "add",
        "-f",
        "--",
        *(f":(top,literal){path}" for path in [*tracked_managed, *siblings]),
    )
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.gitignore import reconcile_project_gitignore

    warning = reconcile_project_gitignore(repo)

    assert warning["managed_paths"][-4:] == managed_targets
    assert warning["tracked_paths"] == sorted(tracked_managed)
    for path in tracked_managed:
        check = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "--no-index", "-q", "--stdin"],
            input="./" + path + "\n",
            capture_output=True,
            text=True,
            check=False,
        )
        assert check.returncode == 0, path
    for sibling in siblings:
        check = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "--no-index", "-q", "--", sibling],
            capture_output=True,
            text=True,
            check=False,
        )
        assert check.returncode == 1, sibling

    untracked = reconcile_project_gitignore(repo, untrack=True)

    assert untracked["untracked_paths"] == sorted(tracked_managed)
    assert set(_git(repo, "ls-files").stdout.splitlines()) == set(siblings)
    for path in [*tracked_managed, *siblings]:
        assert (repo / path).exists()


@pytest.mark.parametrize(
    ("unsafe", "reason"),
    [
        ("line\nfeed", "line break"),
        ("carriage\rreturn", "line break"),
        ("crlf\r\npath", "line break"),
        ("nul\x00path", "NUL"),
    ],
)
@pytest.mark.parametrize("lock_shape", ["receipt", "legacy"])
def test_unsafe_line_break_paths_fail_before_gitignore_or_index_mutation(
    tmp_path: Path, unsafe: str, reason: str, lock_shape: str
) -> None:
    repo = _init_repo(tmp_path / "repo")
    tracked = repo / "tracked.txt"
    tracked.write_text("tracked", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    gitignore = repo / ".gitignore"
    original_gitignore = (
        b"user-rule/\r\n\r\n"
        + BEGIN.encode()
        + b"\r\n/.library.lock\r\n"
        + END.encode()
        + b"\r\n"
    )
    gitignore.write_bytes(original_gitignore)
    index_before = _git(repo, "ls-files", "--stage").stdout

    if lock_shape == "receipt":
        _write_v2_lock(
            repo,
            receipts=[
                {
                    "id": "prompt:unsafe@1.0.0",
                    "type": "prompt",
                    "name": "unsafe",
                    "scope": "project",
                    "catalog_identity": "https://example.invalid/catalog",
                    "resolved_version": "1.0.0",
                    "verified": True,
                    "adopted": False,
                    "targets": [{"path": unsafe, "kind": "file"}],
                    "owners_cache": ["prompt:unsafe"],
                }
            ],
        )
    else:
        _write_v2_lock(
            repo,
            receipts=[],
            installed=[
                {
                    "name": "unsafe",
                    "type": "prompt",
                    "scope": "project",
                    "install_target": unsafe,
                    "bridge_symlinks": [f"{unsafe}-bridge -> safe-target"],
                }
            ],
        )

    result = _run_library(repo, "sync", "--scope", "project", "--untrack", "--json")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert reason in payload["message"]
    assert ".library.lock" in payload["message"]
    assert gitignore.read_bytes() == original_gitignore
    assert _git(repo, "ls-files", "--stage").stdout == index_before
    assert tracked.exists()

    human = _run_library(repo, "sync", "--scope", "project", "--untrack")

    assert human.returncode != 0
    assert reason in human.stderr
    assert ".library.lock" in human.stderr
    assert gitignore.read_bytes() == original_gitignore
    assert _git(repo, "ls-files", "--stage").stdout == index_before
