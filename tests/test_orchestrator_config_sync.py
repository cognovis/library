"""Tests for bin/lib/orchestrator-config-sync.zsh (CL-0w6e follow-up).

The global ~/.agents/orchestrator-config.yml has no catalog-managed deploy, so
the cld/cdx launchers self-heal it from the canonical catalog source on every
launch. These tests exercise the zsh helper directly with a fake HOME.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER = REPO_ROOT / "bin" / "lib" / "orchestrator-config-sync.zsh"

CLONE_REL = ".local/share/library/cognovis-library-core/.agents/orchestrator-config.yml"
SIBLING_REL = "code/library/cognovis-core/.agents/orchestrator-config.yml"
DST_REL = ".agents/orchestrator-config.yml"

pytestmark = pytest.mark.skipif(
    shutil.which("zsh") is None, reason="zsh not available"
)


def _run(home: Path) -> subprocess.CompletedProcess:
    """Source the helper and run _sync_orchestrator_config with HOME=home."""
    return subprocess.run(
        ["zsh", "-c", f"source {HELPER}; _sync_orchestrator_config"],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )


def _seed_source(home: Path, rel: str, content: str) -> Path:
    src = home / rel
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(content, encoding="utf-8")
    return src


def test_helper_exists_and_defines_function() -> None:
    assert HELPER.is_file(), f"missing: {HELPER}"
    result = subprocess.run(
        ["zsh", "-c", f"source {HELPER}; typeset -f _sync_orchestrator_config >/dev/null"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_copies_when_destination_missing(tmp_path: Path) -> None:
    _seed_source(tmp_path, CLONE_REL, "model_tiers: {known_models: [claude-opus-4-8]}\n")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    dst = tmp_path / DST_REL
    assert dst.is_file()
    assert "claude-opus-4-8" in dst.read_text()
    assert "refreshed" in result.stderr


def test_idempotent_no_op_when_current(tmp_path: Path) -> None:
    _seed_source(tmp_path, CLONE_REL, "x: 1\n")
    first = _run(tmp_path)
    assert "refreshed" in first.stderr
    second = _run(tmp_path)
    assert second.returncode == 0
    assert second.stderr.strip() == "", "second run must be a silent no-op"


def test_recopies_when_stale(tmp_path: Path) -> None:
    src = _seed_source(tmp_path, CLONE_REL, "fresh: true\n")
    dst = tmp_path / DST_REL
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("stale: true\n", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 0
    assert dst.read_text() == src.read_text()


def test_silent_skip_when_no_source(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0
    assert result.stderr.strip() == ""
    assert not (tmp_path / DST_REL).exists()


def test_falls_back_to_sibling_checkout(tmp_path: Path) -> None:
    # No installed clone; only the dev sibling checkout is present.
    _seed_source(tmp_path, SIBLING_REL, "from_sibling: true\n")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    dst = tmp_path / DST_REL
    assert dst.is_file()
    assert "from_sibling" in dst.read_text()


def test_clone_takes_priority_over_sibling(tmp_path: Path) -> None:
    _seed_source(tmp_path, CLONE_REL, "from_clone: true\n")
    _seed_source(tmp_path, SIBLING_REL, "from_sibling: true\n")
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "from_clone" in (tmp_path / DST_REL).read_text()
