"""What the shipped CLI does with a schema v2 manifest.

Slice 5 (`CL-dbam`) resolved, validated, and previewed a v2 Workspace and
**refused** to install it, because three things were missing: the declared pin
verified against its source, the members normalized into inventory items, and
the executable-admission gate in the write path.

Slice 6 (`CL-mvet`) supplies all three, so the blanket refusal is replaced by
the checks it was standing in for. What is asserted here is the replacement, not
its absence:

- a source that cannot say what it currently serves refuses, and writes nothing;
- a pin that no longer matches its source is fail-closed drift naming both
  values, and is never silently re-pinned;
- a verified pin installs, through the mutation gate.

All three run the real CLI process rather than a unit call, because "the library
installs (or refuses) this" is a claim about the program an operator runs.
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


def _commit_repository(root: Path) -> str:
    """Make one catalog checkout a real repository and return its HEAD."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for command in (
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "catalog content"],
    ):
        subprocess.run(command, cwd=root, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    )
    return head.stdout.strip()


def _pin_manifest_to_sources(project: Path, manifest_path: Path) -> dict[str, str]:
    """Commit both catalog checkouts and pin the manifest to what they serve."""
    heads = {
        "core": _commit_repository(project / "team-core"),
        "upstream": _commit_repository(project / "upstream-core"),
    }
    manifest = yaml.safe_load(manifest_path.read_text())
    for declared in manifest["catalogs"]:
        declared["pin"] = {"kind": "commit", "value": heads[declared["alias"]]}
    manifest_path.write_text(yaml.safe_dump(manifest))

    catalog = yaml.safe_load((project / "library.yaml").read_text())
    for entry in catalog["library"]["workspaces"]:
        if entry.get("name") == manifest["name"]:
            entry["catalogs"] = manifest["catalogs"]
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))
    return heads


def test_a_v2_manifest_whose_source_cannot_answer_refuses_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """A source that cannot say what it serves is refused, not assumed current.

    The declared catalogs here are plain directories, not tracked working trees.
    "No answer" is never "the pin still holds", so the whole closure is refused
    before any mutation.
    """
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    manifest_path = _write_v2_fixture(project)

    validated = _run(project, home, "workspace", "validate", str(manifest_path), "--json")
    assert validated.returncode == 0, validated.stderr or validated.stdout

    used = _run(
        project, home, "workspace", "use", "team-core:engineering", "--scope", "project",
        "--json",
    )

    assert used.returncode != 0
    message = (used.stdout or "") + (used.stderr or "")
    assert "could not be verified" in message
    # Nothing was written: no lock, no skills, no partial projection.
    assert not (project / ".library.lock").exists()
    assert not (project / ".agents" / "skills").exists()


def test_a_verified_pin_installs_a_v2_workspace(tmp_path: Path) -> None:
    """With both pins verified against real sources, the closure materializes.

    This is the removal of the slice-5 refusal, asserted as an installation
    rather than as the absence of an error message.
    """
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    manifest_path = _write_v2_fixture(project)
    _pin_manifest_to_sources(project, manifest_path)

    used = _run(
        project, home, "workspace", "use", "team-core:engineering", "--scope", "project",
        "--json",
    )

    assert used.returncode == 0, used.stdout + used.stderr
    payload = json.loads(used.stdout)
    assert payload["status"] == "applied"
    assert (project / ".library.lock").exists()
    assert (project / ".agents" / "skills" / "python-dev").exists()
    assert (project / ".agents" / "skills" / "helper").exists()


def test_pin_drift_is_fail_closed_and_never_re_pinned(tmp_path: Path) -> None:
    """A source that moved refuses, names both values, and writes nothing."""
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    manifest_path = _write_v2_fixture(project)
    heads = _pin_manifest_to_sources(project, manifest_path)

    # The source moves after the manifest was pinned.
    (project / "team-core" / "skills" / "python-dev" / "NOTES.md").write_text("moved\n")
    subprocess.run(["git", "add", "-A"], cwd=project / "team-core", check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "upstream moved"], cwd=project / "team-core", check=True
    )

    used = _run(
        project, home, "workspace", "use", "team-core:engineering", "--scope", "project",
        "--json",
    )

    assert used.returncode != 0
    message = (used.stdout or "") + (used.stderr or "")
    assert "pin drift" in message
    assert heads["core"] in message, "the refusal names the declared pin"
    assert not (project / ".library.lock").exists()
    # And the manifest still declares the original pin: drift is never resolved
    # by quietly adopting whatever the source now serves.
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["catalogs"][0]["pin"]["value"] == heads["core"]


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
