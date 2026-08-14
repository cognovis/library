"""Regression coverage for launcher-owned Cognovis Core authority resolution."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "bin" / "lib" / "bead-loop-authority.zsh"
PACKAGED_HELPER = REPO_ROOT / "scripts" / "bin" / "lib" / "bead-loop-authority.zsh"
SYSTEM_GIT = shutil.which("git")
REQUIRED_FILES = (
    "skills/bead-implementation-loop/SKILL.md",
    "skills/bead-execution-loop/SKILL.md",
    "agents/bead-loop-implementer.md",
)


def _write_core_repo(root: Path, marker: str) -> str:
    assert SYSTEM_GIT is not None
    for relative in REQUIRED_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{marker}: {relative}\n", encoding="utf-8")
    subprocess.run([SYSTEM_GIT, "init", "-q", root], check=True)
    subprocess.run([SYSTEM_GIT, "-C", root, "add", "."], check=True)
    subprocess.run(
        [
            SYSTEM_GIT,
            "-C",
            root,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            marker,
        ],
        check=True,
    )
    return subprocess.run(
        [SYSTEM_GIT, "-C", root, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _resolve(home: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["BEAD_LOOP_AUTHORITY_GIT_BIN"] = str(SYSTEM_GIT)
    env.pop("COGNOVIS_CORE_AUTHORITY_ROOT", None)
    return subprocess.run(
        [
            "zsh",
            "-c",
            f'source "{HELPER}"; _resolve_bead_loop_authority; '
            'printf "%s\\n%s\\n%s\\n" "$BEAD_LOOP_AUTHORITY_ROOT" '
            '"$BEAD_LOOP_AUTHORITY_REVISION" "$BEAD_LOOP_AUTHORITY_SOURCE"',
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_regression_canonical_checkout_wins_over_catalog_and_home_projection(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    canonical = home / "code" / "library" / "cognovis-core"
    catalog = home / ".local" / "share" / "library" / "cognovis-library-core"
    canonical_revision = _write_core_repo(canonical, "current canonical")
    _write_core_repo(catalog, "older catalog")
    stale = home / ".agents" / "skills" / "bead-implementation-loop" / "SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale home projection\n", encoding="utf-8")

    result = _resolve(home)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(canonical),
        canonical_revision,
        "canonical checkout",
    ]


def test_dirty_canonical_authority_falls_back_to_clean_catalog_clone(tmp_path: Path) -> None:
    home = tmp_path / "home"
    canonical = home / "code" / "library" / "cognovis-core"
    catalog = home / ".local" / "share" / "library" / "cognovis-library-core"
    _write_core_repo(canonical, "dirty canonical")
    catalog_revision = _write_core_repo(catalog, "clean catalog")
    (canonical / REQUIRED_FILES[0]).write_text("uncommitted policy\n", encoding="utf-8")

    result = _resolve(home)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(catalog),
        catalog_revision,
        "installed catalog clone",
    ]


def test_packaged_authority_helper_matches_source_layout() -> None:
    assert PACKAGED_HELPER.read_bytes() == HELPER.read_bytes()
