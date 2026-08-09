"""Tests for the shared launcher worktree-overlay resolver.

A fresh Git worktree does not carry the gitignored overlay directories that a
main checkout has (`.agents/`, `.claude/skills/`, `.env`). Both launchers must
bootstrap the same overlay set: `cdx` creates the symlinks itself after
`git worktree add`, and `cld` hands the resolved directory list to Claude Code's
native `worktree.symlinkDirectories` setting.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "worktree-overlays.py"
_CDX_BIN = _REPO_ROOT / "bin" / "cdx"
_CLD_BIN = _REPO_ROOT / "bin" / "cld"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("worktree_overlays", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="overlays")
def _overlays() -> ModuleType:
    return _load_module()


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _make_main(tmp_path: Path) -> Path:
    main = tmp_path / "main"
    (main / ".agents" / "skills").mkdir(parents=True)
    (main / ".agents" / "standards").mkdir(parents=True)
    (main / ".claude" / "skills").mkdir(parents=True)
    (main / ".env").write_text("TOKEN=value\n", encoding="utf-8")
    return main


def test_default_overlays_cover_the_documented_set(overlays: ModuleType) -> None:
    assert overlays.DEFAULT_OVERLAYS == (".agents", ".claude/skills", ".env")


def test_resolve_emits_whole_overlay_when_absent_from_worktree(
    overlays: ModuleType, tmp_path: Path
) -> None:
    main = _make_main(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    resolved = overlays.resolve_overlays(main, overlays.DEFAULT_OVERLAYS, overlays.worktree_probe(worktree))

    assert resolved == [".agents", ".claude/skills", ".env"]


def test_resolve_descends_into_overlay_roots_the_worktree_already_owns(
    overlays: ModuleType, tmp_path: Path
) -> None:
    """A partly tracked overlay root must not be replaced, only filled in.

    In marketplace repositories `.agents/` holds tracked content, so it exists in
    a fresh worktree while its gitignored children do not. Linking only the root
    would silently do nothing there.
    """
    main = _make_main(tmp_path)
    worktree = tmp_path / "worktree"
    (worktree / ".agents" / "standards").mkdir(parents=True)

    resolved = overlays.resolve_overlays(main, overlays.DEFAULT_OVERLAYS, overlays.worktree_probe(worktree))

    assert resolved == [".agents/skills", ".claude/skills", ".env"]


def test_resolve_skips_sources_missing_from_the_main_checkout(
    overlays: ModuleType, tmp_path: Path
) -> None:
    main = tmp_path / "main"
    (main / ".claude" / "skills").mkdir(parents=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    resolved = overlays.resolve_overlays(main, overlays.DEFAULT_OVERLAYS, overlays.worktree_probe(worktree))

    assert resolved == [".claude/skills"]


def test_resolve_rejects_absolute_and_traversing_overlays(
    overlays: ModuleType, tmp_path: Path
) -> None:
    main = _make_main(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    probe = overlays.worktree_probe(worktree)

    for unsafe in ("/etc", "../outside", ".agents/../../outside", ""):
        with pytest.raises(ValueError):
            overlays.resolve_overlays(main, (unsafe,), probe)


def test_index_probe_treats_tracked_paths_as_present(
    overlays: ModuleType, tmp_path: Path
) -> None:
    main = _make_main(tmp_path)
    probe = overlays.index_probe([".agents/standards/judge.md", "README.md"])

    resolved = overlays.resolve_overlays(main, overlays.DEFAULT_OVERLAYS, probe)

    assert resolved == [".agents/skills", ".claude/skills", ".env"]


def test_link_creates_relative_symlinks_that_resolve_into_main(
    tmp_path: Path,
) -> None:
    main = _make_main(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    result = _run_script("link", "--main", str(main), "--worktree", str(worktree))

    assert result.returncode == 0, result.stderr
    for rel in (".agents", ".claude/skills", ".env"):
        link = worktree / rel
        assert link.is_symlink(), f"{rel} is not a symlink"
        assert not os.path.isabs(os.readlink(link)), f"{rel} must be a relative symlink"
        assert link.resolve() == (main / rel).resolve()


def test_link_never_replaces_an_existing_worktree_path(tmp_path: Path) -> None:
    main = _make_main(tmp_path)
    worktree = tmp_path / "worktree"
    (worktree / ".env").parent.mkdir(parents=True, exist_ok=True)
    (worktree / ".env").write_text("LOCAL=1\n", encoding="utf-8")

    result = _run_script("link", "--main", str(main), "--worktree", str(worktree))

    assert result.returncode == 0, result.stderr
    assert not (worktree / ".env").is_symlink()
    assert (worktree / ".env").read_text(encoding="utf-8") == "LOCAL=1\n"


def test_link_leaves_no_dangling_symlink_for_a_missing_source(tmp_path: Path) -> None:
    main = tmp_path / "main"
    main.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    result = _run_script("link", "--main", str(main), "--worktree", str(worktree))

    assert result.returncode == 0, result.stderr
    assert sorted(os.listdir(worktree)) == []


def test_resolve_json_emits_directories_only_for_the_claude_setting(
    tmp_path: Path,
) -> None:
    main = _make_main(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    result = _run_script(
        "resolve",
        "--main",
        str(main),
        "--worktree",
        str(worktree),
        "--directories-only",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [".agents", ".claude/skills"]


def test_both_launchers_bootstrap_through_the_shared_resolver() -> None:
    """AC2 parity: neither launcher may carry its own overlay list."""
    cdx_source = _CDX_BIN.read_text(encoding="utf-8")
    cld_source = _CLD_BIN.read_text(encoding="utf-8")

    assert "scripts/worktree-overlays.py" in cdx_source
    assert "scripts/worktree-overlays.py" in cld_source
    for source in (cdx_source, cld_source):
        assert ".agents .claude/skills" not in source


def test_link_skips_a_dangling_source_symlink(tmp_path: Path) -> None:
    """AC3: a source that does not resolve must not become a dangling link."""
    main = tmp_path / "main"
    (main / ".claude" / "skills").mkdir(parents=True)
    (main / ".agents").symlink_to(tmp_path / "missing-target")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    result = _run_script("link", "--main", str(main), "--worktree", str(worktree))

    assert result.returncode == 0, result.stderr
    assert not os.path.lexists(worktree / ".agents")
    assert (worktree / ".claude" / "skills").is_symlink()


def test_link_refuses_to_escape_the_worktree_through_a_symlinked_ancestor(
    tmp_path: Path,
) -> None:
    """A symlinked overlay root must not let a child link land outside."""
    main = _make_main(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".agents").symlink_to(outside)

    result = _run_script("link", "--main", str(main), "--worktree", str(worktree))

    assert result.returncode == 0, result.stderr
    assert sorted(os.listdir(outside)) == []


def test_resolve_does_not_descend_into_a_symlinked_worktree_path(
    overlays: ModuleType, tmp_path: Path
) -> None:
    main = _make_main(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".agents").symlink_to(outside)

    resolved = overlays.resolve_overlays(
        main, overlays.DEFAULT_OVERLAYS, overlays.worktree_probe(worktree)
    )

    assert resolved == [".claude/skills", ".env"]


def test_index_resolution_keeps_a_nested_overlay_whose_parent_is_untracked(
    overlays: ModuleType, tmp_path: Path
) -> None:
    """Pin the shape cld hands to Claude Code when no .claude path is tracked.

    Claude Code creates these symlinks itself and is not known to create a
    missing parent directory, so the overlay may not materialize in that
    repository shape. Emitting the narrow path is still strictly better than
    widening to `.claude`, which would link the main checkout's own
    `.claude/worktrees` into the worktree.
    """
    main = _make_main(tmp_path)

    resolved = overlays.resolve_overlays(
        main, overlays.DEFAULT_OVERLAYS, overlays.index_probe(["README.md"])
    )

    assert resolved == [".agents", ".claude/skills", ".env"]
