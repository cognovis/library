"""The test suite must not be able to write into the operator's library state.

Guards CL-t71i. A pytest fixture entry was found in the operator's real
`~/.config/library/global.lock`, dated 2026-07-17, whose source and install target
both pointed into a deleted pytest tmpdir. The test had isolated itself with
`monkeypatch.setenv("HOME", tmp_path)`, but `GLOBAL_LOCKFILE` was a module-level
constant frozen at import, so the isolation never applied.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from lib import lockfile  # noqa: E402

LIBRARY_PY = SCRIPTS_DIR / "library.py"
LIBRARY_SPEC = importlib.util.spec_from_file_location("library_py_iso", LIBRARY_PY)
LIBRARY_MODULE = importlib.util.module_from_spec(LIBRARY_SPEC)
LIBRARY_SPEC.loader.exec_module(LIBRARY_MODULE)


# -- AC1: HOME set after import is honored ----------------------------------


def test_home_change_after_import_redirects_the_global_lockfile(tmp_path, monkeypatch):
    """The exact isolation a test performs, which used to be silently ignored."""
    monkeypatch.setenv("HOME", str(tmp_path))

    resolved = lockfile.find_lockfile(global_scope=True)

    assert resolved == tmp_path / ".config" / "library" / "global.lock"
    assert not str(resolved).startswith(str(Path("~").expanduser().parent / "malte")) or (
        tmp_path in resolved.parents
    )


def test_isolated_home_cannot_reach_the_operator_lockfile(tmp_path, monkeypatch):
    real = Path.home() / ".config" / "library" / "global.lock"
    monkeypatch.setenv("HOME", str(tmp_path))

    resolved = lockfile.find_lockfile(global_scope=True)

    assert resolved != real
    assert tmp_path in resolved.parents


def test_explicit_module_override_still_wins(tmp_path, monkeypatch):
    """Existing tests patch the attribute directly; that intent must not be
    overruled by re-resolving from the environment."""
    override = tmp_path / "patched.lock"
    monkeypatch.setattr(lockfile, "GLOBAL_LOCKFILE", override)
    monkeypatch.setenv("HOME", str(tmp_path / "elsewhere"))

    assert lockfile.find_lockfile(global_scope=True) == override


def test_default_resolution_without_isolation_is_unchanged():
    assert lockfile.find_lockfile(global_scope=True) == (
        Path.home() / ".config" / "library" / "global.lock"
    )


# -- AC2: a global-scope install under an isolated HOME stays contained ------


def test_global_scope_install_writes_only_inside_the_isolated_home(tmp_path, monkeypatch):
    """The regression itself: the 2026-07-17 entry came from exactly this shape."""
    from lib.installers.simple_file import install_simple_file

    real = Path.home() / ".config" / "library" / "global.lock"
    before = real.read_bytes() if real.exists() else None

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    src = tmp_path / "src" / "review-prep.py"
    src.parent.mkdir(parents=True)
    src.write_text("print('hi')\n", encoding="utf-8")
    catalog = {
        "default_dirs": {
            "scripts": [{"default": ".agents/scripts/"}, {"global": "~/.agents/scripts/"}]
        },
        "library": {
            "scripts": [{"name": "grp/review-prep", "source": str(src), "language": "python"}]
        },
    }

    install_simple_file(catalog, "script", "grp/review-prep", repo_root=tmp_path, scope="global")

    after = real.read_bytes() if real.exists() else None
    assert after == before, "a global-scope install under an isolated HOME touched the real lockfile"
    assert (home / ".config" / "library" / "global.lock").exists()


# -- AC3: an unresolvable entry is named, not folded into a vague warning ----


def test_unresolvable_entry_is_named_with_both_missing_paths(tmp_path):
    installed = [
        {
            "name": "grp/review-prep",
            "type": "script",
            "source": str(tmp_path / "gone" / "review-prep.py"),
            "install_target": str(tmp_path / "also-gone" / "review-prep.py"),
        }
    ]

    unresolvable, still_unknown = LIBRARY_MODULE._classify_unknown_entries(
        ["script:grp/review-prep"], installed
    )

    assert still_unknown == []
    assert len(unresolvable) == 1
    label, source, target = unresolvable[0]
    assert label == "script:grp/review-prep"
    assert "gone" in source and "also-gone" in target


def test_existing_paths_stay_unknown_upstream(tmp_path):
    source = tmp_path / "present.py"
    source.write_text("x\n", encoding="utf-8")
    installed = [
        {
            "name": "present",
            "type": "script",
            "source": str(source),
            "install_target": str(source),
        }
    ]

    unresolvable, still_unknown = LIBRARY_MODULE._classify_unknown_entries(
        ["script:present"], installed
    )

    assert unresolvable == []
    assert still_unknown == ["script:present"]


def test_remote_source_is_not_called_unresolvable():
    """A git URL is not a filesystem path; absence of a local file says nothing."""
    installed = [
        {
            "name": "remote-thing",
            "type": "skill",
            "source": "https://github.com/example/repo/blob/main/skills/x/SKILL.md",
            "install_target": "/nonexistent/target",
        }
    ]

    unresolvable, still_unknown = LIBRARY_MODULE._classify_unknown_entries(
        ["skill:remote-thing"], installed
    )

    assert unresolvable == []
    assert still_unknown == ["skill:remote-thing"]
