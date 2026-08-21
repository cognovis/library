"""Catalog and installer contract for the owned ACPX dispatcher skill."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.resolver import resolve_requires  # noqa: E402


def _catalog() -> dict:
    return yaml.safe_load((REPO_ROOT / "library.yaml").read_text(encoding="utf-8"))


def _entry(catalog: dict, kind: str, name: str) -> dict:
    return next(entry for entry in catalog["library"][kind] if entry["name"] == name)


def _library_cli_root() -> Path:
    candidates = []
    configured = os.environ.get("LIBRARY_CLI_ROOT")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        (
            REPO_ROOT.parent / "library-cli",
            REPO_ROOT.parents[1] / "library-cli",
            REPO_ROOT.parents[2] / "library" / "library-cli",
        )
    )
    match = next(
        (
            path
            for path in candidates
            if (path / "pyproject.toml").is_file()
            and (path / "scripts" / "library.py").is_file()
        ),
        None,
    )
    if match is None:
        raise AssertionError("the separately shipped library-cli checkout is required")
    return match


def _source_catalog(catalog: dict, name: str) -> dict:
    return next(
        entry
        for entry in catalog["sources"]["catalogs"]
        if entry["name"] == name
    )


# clc-i19u: `ccore` owns the dispatch skill together with the transport command it
# documents, so the catalog must both register that repository as a skills source
# and serve the entry from it. A second copy in cognovis-core would drift.
def test_catalog_registers_ccore_as_a_skills_source() -> None:
    ccore = _source_catalog(_catalog(), "cognovis-ccore")

    assert ccore["source"] == "https://git.cognovis.de/cognovis/ccore"
    assert ccore["local_path"] == "/Users/malte/code/library/ccore"
    assert "skills" in ccore["content_types"]
    assert "acpx" in ccore["scope"]["topics"]
    assert "dispatch" in ccore["scope"]["topics"]


def test_catalog_resolves_repository_delivery_through_the_owned_transport(
    tmp_path: Path,
) -> None:
    catalog = _catalog()
    dispatch = _entry(catalog, "skills", "acpx-dispatch")
    pack = _entry(catalog, "skills", "executive-pack")
    loop = _entry(catalog, "skills", "bead-execution-loop")

    assert dispatch["source"] == (
        "https://git.cognovis.de/cognovis/ccore/raw/branch/main/"
        "skills/acpx-dispatch/SKILL.md"
    )
    assert dispatch["metadata"]["library"]["source_catalog"] == "cognovis-ccore"
    assert "skill:bead-execution-loop" in pack["requires"]
    assert "agent:bead-implementer" in loop["requires"]
    # clc-i19u: the entry's dependency edges are the ccore skill's own declared
    # contract, which `library catalog sync --source=cognovis-ccore` derives from
    # its `requires_standards`. The judge-layer and routing edges the entry used to
    # carry were never declared by the skill; they inflated every consumer's
    # closure and made an install of the transport skill build a judge agent.
    assert dispatch["requires"] == ["standard:mcp-client-timeout"]
    install_order = resolve_requires(
        catalog,
        "skill",
        "executive-pack",
        tmp_path,
    )
    assert ("skill", "bead-execution-loop") in install_order
    assert ("skill", "acpx-dispatch") in install_order


def test_daily_workspace_resolves_the_owned_transport_without_source_fixups(
    tmp_path: Path,
) -> None:
    """The published Daily Workspace resolves ACPX through its pinned provider."""
    project = tmp_path / "consumer"
    project.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(project)],
        capture_output=True,
        text=True,
        check=True,
    )

    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(_library_cli_root()),
            "library",
            "--catalog",
            str(REPO_ROOT / "library.yaml"),
            "workspace",
            "use",
            "cognovis-library-core:cognovis-daily",
            "--target-project",
            str(project),
            "--dry-run",
            "--json",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry-run"
    assert payload["blockers"] == []
    assert "skill:acpx-dispatch" in payload["artifacts"]
