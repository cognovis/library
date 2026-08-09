"""What the shipped CLI does with a schema v2 manifest (CL-dbam, wave-2 repair).

A v2 Workspace resolves, validates, and previews in this slice. It does not
install: the current installer path fetches each member from the live catalog and
would honor no declared pin at all, so installing now would present a pinned
manifest whose install was not pinned.

Round 1 raised this as an orphaned API -- `gate_workspace_mutation` existed with
no production caller. The refusal is therefore asserted end to end through the
real CLI process, not through a unit call, because "the library refuses to
install this" is a claim about the program an operator runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"

CORE_SOURCE = "https://example.invalid/core"
UPSTREAM_SOURCE = "https://example.invalid/upstream"


def _run(project: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(LIBRARY_PY), *args],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )


def _write_v2_fixture(project: Path) -> Path:
    """A project catalog publishing one cross-catalog v2 Workspace."""
    core = project / "team-core"
    upstream = project / "upstream-core"
    for root, names in ((core, ("python-dev",)), (upstream, ("helper",))):
        for name in names:
            skill = root / "skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\nversion: 1.0.0\n---\n# {name}\n"
            )
    manifest = {
        "schema_version": 2,
        "name": "engineering",
        "version": "1.0.0",
        "description": "Engineering baseline across two catalogs.",
        "status": "experimental",
        "catalogs": [
            {
                "alias": "core",
                "identity": CORE_SOURCE,
                "pin": {"kind": "commit", "value": "a" * 40},
            },
            {
                "alias": "upstream",
                "identity": UPSTREAM_SOURCE,
                "pin": {"kind": "inventory-snapshot", "value": "b" * 64},
            },
        ],
        "roots": [
            {"type": "skill", "name": "python-dev", "catalog": "core"},
            {"type": "skill", "name": "helper", "catalog": "upstream"},
        ],
    }
    workspaces = core / "workspaces"
    workspaces.mkdir()
    manifest_path = workspaces / "engineering.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest))

    catalog = {
        "catalog_identity": "https://example.invalid/platform",
        "default_dirs": {
            "skills": [
                {"default": ".agents/skills/", "global": "~/.agents/skills/"},
            ]
        },
        "sources": {
            "catalogs": [
                {
                    "name": "team-core",
                    "source": CORE_SOURCE,
                    "local_path": str(core),
                    "content_types": ["skills", "workspaces"],
                },
                {
                    "name": "upstream-core",
                    "source": UPSTREAM_SOURCE,
                    "local_path": str(upstream),
                    "content_types": ["skills"],
                },
            ],
            "marketplaces": [],
        },
        "library": {
            "skills": [
                {
                    "name": "python-dev",
                    "description": "python-dev skill.",
                    "version": "1.0.0",
                    "source": str(core / "skills" / "python-dev" / "SKILL.md"),
                    "metadata": {"library": {"source_catalog": "team-core"}},
                },
                {
                    "name": "helper",
                    "description": "helper skill.",
                    "version": "1.0.0",
                    "source": str(upstream / "skills" / "helper" / "SKILL.md"),
                    "metadata": {"library": {"source_catalog": "upstream-core"}},
                },
            ],
            "workspaces": [
                {
                    **manifest,
                    "source": str(manifest_path),
                    "metadata": {
                        "library": {
                            "source_catalog": "team-core",
                            "inventory": "convention-scan",
                        }
                    },
                }
            ],
        },
    }
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    return manifest_path


def test_the_cli_validates_a_v2_manifest_and_refuses_to_install_it(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    manifest_path = _write_v2_fixture(project)

    validated = _run(project, home, "workspace", "validate", str(manifest_path), "--json")
    assert validated.returncode == 0, validated.stderr or validated.stdout

    used = _run(
        project,
        home,
        "workspace",
        "use",
        "team-core:engineering",
        "--scope",
        "project",
        "--json",
    )

    assert used.returncode != 0
    message = (used.stdout or "") + (used.stderr or "")
    assert "verified against their sources" in message or "not yet installable" in message
    # Nothing was written: no lock, no skills, no partial projection.
    assert not (project / ".library.lock").exists()
    assert not (project / ".agents" / "skills").exists()


def test_the_cli_rejects_a_v1_manifest_carrying_a_catalog_qualifier(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    manifest_path = _write_v2_fixture(project)
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["schema_version"] = 1
    manifest.pop("catalogs")
    manifest_path.write_text(yaml.safe_dump(manifest))

    validated = _run(project, home, "workspace", "validate", str(manifest_path), "--json")

    assert validated.returncode != 0
    payload = json.loads(validated.stdout or "{}") if validated.stdout else {}
    message = str(payload.get("message", "")) + (validated.stderr or "")
    assert "schema_version 2" in message
