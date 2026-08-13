"""The v2 mutation write path installs from the gate's bytes, not from a source.

ADR-0011 slice 6 bridged the gap between the mutation gate and the installers by
*comparing* the admitted snapshot against a re-read of the source. A comparison
reports a difference; it cannot prevent one, and the ADR recorded that an edit
landing after a member's own pre-check was published and then reported.

This closes it by removing the second read. The gate's frozen content is
published atomically into an admitted-content root, that publication is hashed at
its final paths, and every member's installer is bound to it — so the bytes an
installer can reach are the admitted bytes, and no source edit is visible to it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.executable_admission import content_digest  # noqa: E402
from lib.workspace import (  # noqa: E402
    AdmittedPublicationMismatch,
    assert_published_admitted,
    publish_admitted_members,
)


class _Item:
    """The two fields the publication layout needs from a normalized item."""

    def __init__(self, library_type: str, library_name: str, identity: str) -> None:
        self.library_type = library_type
        self.library_name = library_name
        self._identity = identity

    def qualified_identity(self) -> str:
        return self._identity


HELPER = _Item("skill", "helper", "https://example.invalid/upstream#skill/helper")
PYTHON_DEV = _Item("skill", "python-dev", "https://example.invalid/core#skill/python-dev")

CONTENTS = {
    HELPER.qualified_identity(): {"SKILL.md": b"---\nname: helper\n---\n# helper\n"},
    PYTHON_DEV.qualified_identity(): {
        "SKILL.md": b"---\nname: python-dev\n---\n# python-dev\n",
        "reference.md": b"# reference\n",
    },
}


def test_the_gate_frozen_content_is_published_and_hashed_at_its_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "admitted"
    published = publish_admitted_members(root, [HELPER, PYTHON_DEV], CONTENTS)

    assert set(published) == set(CONTENTS)
    for identity, member_root in published.items():
        for relative, payload in CONTENTS[identity].items():
            assert (member_root / relative).read_bytes() == payload
    # The post-activation check reads the published paths, so it passes here and
    # is not a restatement of the argument.
    assert_published_admitted(published, CONTENTS)


def test_a_published_member_edited_afterwards_fails_the_assertion(
    tmp_path: Path,
) -> None:
    root = tmp_path / "admitted"
    published = publish_admitted_members(root, [HELPER, PYTHON_DEV], CONTENTS)

    (published[HELPER.qualified_identity()] / "SKILL.md").write_bytes(b"# not admitted\n")

    with pytest.raises(AdmittedPublicationMismatch) as mismatch:
        assert_published_admitted(published, CONTENTS)
    assert HELPER.qualified_identity() in str(mismatch.value)


def test_a_removed_published_member_fails_the_assertion(tmp_path: Path) -> None:
    root = tmp_path / "admitted"
    published = publish_admitted_members(root, [HELPER, PYTHON_DEV], CONTENTS)

    (published[PYTHON_DEV.qualified_identity()] / "reference.md").unlink()

    with pytest.raises(AdmittedPublicationMismatch):
        assert_published_admitted(published, CONTENTS)


def test_the_publication_digest_is_the_gate_admitted_digest(tmp_path: Path) -> None:
    """Not a digest this layer invented: the same function the gate admitted with."""
    root = tmp_path / "admitted"
    published = publish_admitted_members(root, [HELPER], CONTENTS)
    member_root = published[HELPER.qualified_identity()]
    on_disk = {
        path.relative_to(member_root).as_posix(): path.read_bytes()
        for path in sorted(member_root.rglob("*"))
        if path.is_file()
    }
    assert content_digest(on_disk) == content_digest(CONTENTS[HELPER.qualified_identity()])


# -- the binding an installer actually reads ---------------------------------


def _v2_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A project whose Workspace composes one member from each of two catalogs."""
    project = tmp_path / "project"
    home = tmp_path / "home"
    core = tmp_path / "core"
    upstream = tmp_path / "upstream"
    for path in (project, home, core, upstream):
        path.mkdir(parents=True)

    for root, skill in ((core, "python-dev"), (upstream, "helper")):
        directory = root / "skills" / skill
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: {skill} skill.\nversion: 1.0.0\n---\n"
            f"# {skill}\n"
        )

    heads = {}
    for alias, root in (("core", core), ("upstream", upstream)):
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        for command in (
            ["git", "config", "user.email", "test@example.invalid"],
            ["git", "config", "user.name", "Test"],
            ["git", "add", "-A"],
            ["git", "commit", "-q", "-m", "catalog content"],
        ):
            subprocess.run(command, cwd=root, check=True)
        heads[alias] = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    manifest = {
        "schema_version": 2,
        "name": "engineering",
        "version": "1.0.0",
        "description": "Engineering baseline across two catalogs.",
        "status": "experimental",
        "catalogs": [
            {
                "alias": "core",
                "identity": "https://example.invalid/core",
                "pin": {"kind": "commit", "value": heads["core"]},
            },
            {
                "alias": "upstream",
                "identity": "https://example.invalid/upstream",
                "pin": {"kind": "commit", "value": heads["upstream"]},
            },
        ],
        "roots": [
            {"type": "skill", "name": "python-dev", "catalog": "core"},
            {"type": "skill", "name": "helper", "catalog": "upstream"},
        ],
    }
    workspaces = core / "workspaces"
    workspaces.mkdir()
    (workspaces / "engineering.yaml").write_text(yaml.safe_dump(manifest))

    catalog = {
        "catalog_identity": "https://example.invalid/platform",
        "default_dirs": {
            "skills": [{"default": ".agents/skills/", "global": "~/.agents/skills/"}]
        },
        "sources": {
            "catalogs": [
                {
                    "name": "team-core",
                    "source": "https://example.invalid/core",
                    "local_path": str(core),
                    "content_types": ["skills", "workspaces"],
                },
                {
                    "name": "upstream-core",
                    "source": "https://example.invalid/upstream",
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
                    "source": str(workspaces / "engineering.yaml"),
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
    return project, home, upstream / "skills" / "helper" / "SKILL.md"


def _closure(project: Path):
    import importlib

    library = importlib.import_module("library")
    from lib.catalog import load_catalog
    from lib.workspace import resolve_workspace, resolve_workspace_closure

    catalog = load_catalog(project)
    workspace = resolve_workspace(catalog, "team-core:engineering")
    closure = resolve_workspace_closure(
        catalog,
        workspace,
        project,
        "project",
        pin_verifier=library._workspace_pin_verifier(catalog),
    )
    return library, catalog, closure


def test_a_source_edited_after_the_gate_is_invisible_to_the_installer(
    tmp_path: Path,
) -> None:
    """The residual, closed: the installer cannot reach the edited bytes.

    Slice 6 detected this edit after publishing it. There is now nothing to
    detect, because the catalog the installers run against resolves the member to
    the admitted publication and the mutable checkout is never read again.
    """
    project, _home, helper_source = _v2_project(tmp_path)
    library, catalog, closure = _closure(project)
    items, contents = library._workspace_normalized_members(catalog, closure, project)

    admitted_root = tmp_path / "admitted"
    published = publish_admitted_members(admitted_root, items, contents)
    bound = library._workspace_admitted_catalog(
        catalog, closure, items, published, contents
    )

    helper_source.write_text("---\nname: helper\nversion: 1.0.0\n---\n# changed\n")

    _, after_edit = library._workspace_normalized_members(bound, closure, project)
    assert after_edit == contents, (
        "the bound catalog still resolves every member to the admitted bytes "
        "after its source was edited"
    )
    resolved = library._workspace_local_source(
        bound,
        library.lookup_entry(bound, "skill", "helper", fuzzy=False, source_catalog="upstream-core"),
        "skill",
    )
    assert resolved is not None
    assert admitted_root in resolved.parents or resolved == admitted_root / "skill" / "helper"


def test_a_bound_member_that_does_not_resolve_to_the_admitted_bytes_is_refused(
    tmp_path: Path,
) -> None:
    """The binding is verified, not assumed.

    The layout an installer expects is per-primitive, so binding it is a
    derivation and a derivation can be wrong. It is checked against the admitted
    digest before any installer runs, rather than trusted.
    """
    project, _home, _helper_source = _v2_project(tmp_path)
    library, catalog, closure = _closure(project)
    items, contents = library._workspace_normalized_members(catalog, closure, project)

    admitted_root = tmp_path / "admitted"
    published = publish_admitted_members(admitted_root, items, contents)
    (published[items[0].qualified_identity()] / "SKILL.md").write_bytes(b"# tampered\n")

    with pytest.raises(Exception) as refusal:
        library._workspace_admitted_catalog(
            catalog, closure, items, published, contents
        )
    assert "admitted" in str(refusal.value)


def test_the_lock_records_the_catalog_source_and_the_verified_pin(
    tmp_path: Path,
) -> None:
    """Installing from the admitted publication does not rewrite the provenance.

    The bytes came from an admitted snapshot; the *source* is still the catalog
    that was resolved, and the commit is the pin the resolution verified — which
    is a stronger statement than the local HEAD an installer happens to read.
    """
    project, home, _helper_source = _v2_project(tmp_path)
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    installed = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "workspace", "use", "team-core:engineering",
         "--scope", "project", "--json"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    lock = yaml.safe_load((project / ".library.lock").read_text())
    entries = {entry["name"]: entry for entry in lock.get("installed", [])}
    assert {"python-dev", "helper"} <= set(entries)

    manifest = yaml.safe_load((tmp_path / "core" / "workspaces" / "engineering.yaml").read_text())
    pins = {item["alias"]: item["pin"]["value"] for item in manifest["catalogs"]}
    for name, alias in (("python-dev", "core"), ("helper", "upstream")):
        entry = entries[name]
        assert "admitted" not in entry["source"], (
            "the lock records the catalog source, not the publication the "
            "installer consumed"
        )
        assert Path(entry["source"]).exists()
        assert entry["source_commit"] == pins[alias]

    receipts = {receipt["id"]: receipt for receipt in lock.get("receipts", [])}
    for name, alias in (("python-dev", "core"), ("helper", "upstream")):
        receipt = receipts.get(f"skill:{name}")
        assert receipt is not None
        assert receipt["definition_commit"] == pins[alias]
        assert receipt["source_commit"] == pins[alias]

    # The admitted publication is not left behind as a second copy of the content.
    assert not (project / ".library" / "admitted").exists()


def test_the_installed_projection_is_the_admitted_bytes(tmp_path: Path) -> None:
    project, home, _helper_source = _v2_project(tmp_path)
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    installed = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "workspace", "use", "team-core:engineering",
         "--scope", "project", "--json"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert json.loads(installed.stdout)["status"] == "applied"

    for skill in ("python-dev", "helper"):
        projected = project / ".agents" / "skills" / skill / "SKILL.md"
        assert projected.is_file()
        assert f"name: {skill}" in projected.read_text()


# -- wave-1 review findings, held as regression tests ------------------------


def _v2_agent_project(tmp_path: Path) -> tuple[Path, Path]:
    """The wave-1 `CL-st5s-F1` counterexample, as a fixture.

    One catalog, one v2 Workspace, one agent whose entry declares an admitted
    `source` and a different harness-specific `sources.claude`.
    """
    project = tmp_path / "project"
    home = tmp_path / "home"
    core = tmp_path / "core"
    for path in (project, home, core):
        path.mkdir(parents=True)

    agents = core / "agents"
    agents.mkdir()
    (agents / "admitted.md").write_text(
        "---\nname: bypass-agent\ndescription: admitted agent.\nversion: 1.0.0\n---\n"
        "\n--- AGENT PERSONA ---\n\n# ADMITTED PAYLOAD\n"
    )
    (agents / "unadmitted.md").write_text(
        "---\nname: bypass-agent\ndescription: admitted agent.\nversion: 1.0.0\n---\n"
        "\n--- AGENT PERSONA ---\n\n# UNADMITTED PAYLOAD\n"
    )
    prompts = core / "prompts"
    prompts.mkdir()
    (prompts / "control.md").write_text("# control\n")

    subprocess.run(["git", "init", "-q", str(core)], check=True)
    for command in (
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "catalog content"],
    ):
        subprocess.run(command, cwd=core, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=core, capture_output=True, text=True, check=True
    ).stdout.strip()

    manifest = {
        "schema_version": 2,
        "name": "agents",
        "version": "1.0.0",
        "description": "A Workspace containing one harness-specific agent.",
        "status": "experimental",
        "catalogs": [
            {
                "alias": "core",
                "identity": "https://example.invalid/core",
                "pin": {"kind": "commit", "value": head},
            }
        ],
        "roots": [
            {"type": "agent", "name": "bypass-agent", "catalog": "core"},
            {"type": "prompt", "name": "control", "catalog": "core"},
        ],
    }
    workspaces = core / "workspaces"
    workspaces.mkdir()
    (workspaces / "agents.yaml").write_text(yaml.safe_dump(manifest))

    catalog = {
        "catalog_identity": "https://example.invalid/platform",
        "default_dirs": {
            "agents": [
                {"default": ".claude/agents/"},
                {"global": "~/.claude/agents/"},
                {"default_codex": ".codex/agents/"},
                {"global_codex": "~/.codex/agents/"},
            ],
            "prompts": [
                {"default": ".claude/commands/"},
                {"global": "~/.claude/commands/"},
            ],
        },
        "sources": {
            "catalogs": [
                {
                    "name": "team-core",
                    "source": "https://example.invalid/core",
                    "local_path": str(core),
                    "content_types": ["agents", "prompts", "workspaces"],
                }
            ],
            "marketplaces": [],
        },
        "library": {
            "agents": [
                {
                    "name": "bypass-agent",
                    "description": "admitted agent.",
                    "version": "1.0.0",
                    "source": str(agents / "admitted.md"),
                    "sources": {"claude": str(agents / "unadmitted.md")},
                    "metadata": {"library": {"source_catalog": "team-core"}},
                }
            ],
            "prompts": [
                {
                    "name": "control",
                    "description": "control prompt.",
                    "version": "1.0.0",
                    "source": str(prompts / "control.md"),
                    "metadata": {"library": {"source_catalog": "team-core"}},
                }
            ],
            "workspaces": [
                {
                    **manifest,
                    "source": str(workspaces / "agents.yaml"),
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
    return project, home


def test_f1_a_harness_specific_source_cannot_bypass_the_admitted_publication(
    tmp_path: Path,
) -> None:
    """Wave-1 `CL-st5s-F1`, executed end to end.

    The reviewer ran this exact shape against the wave-1 candidate: the gate
    digested and admitted `source`, `_resolve_agent_targets` read
    `sources.claude`, the command returned `applied`, and the installed agent
    contained `UNADMITTED PAYLOAD` while the lock recorded the admitted source
    and the verified pin.

    The gate reads one source, so a member offering the installer a second one is
    refused. That is a real restriction on what a v2 Workspace may contain, and
    it is the fail-closed side of it.
    """
    project, home = _v2_agent_project(tmp_path)
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "workspace", "use", "team-core:agents",
         "--scope", "project", "--json"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "agent:bypass-agent" in combined
    assert "'sources'" in combined

    installed = list((project / ".claude" / "agents").glob("*")) if (
        project / ".claude" / "agents"
    ).exists() else []
    assert installed == [], "nothing is installed for a member that cannot be bound"
    for path in project.rglob("*"):
        if path.is_file():
            assert b"UNADMITTED PAYLOAD" not in path.read_bytes(), (
                f"unadmitted bytes reached {path}"
            )
    assert not (project / ".library" / "admitted").exists()


def test_w2f1_an_entry_with_no_source_resolves_to_nothing(tmp_path: Path) -> None:
    """Wave-2 `CL-st5s-W2-F1`, the mechanism underneath it.

    `Path("")` is `Path(".")`, and it exists. A catalog entry with no `source`
    therefore resolved to the *current directory*, and its "content" was every
    file in the project — which is how a `runtime-config` member, whose schema has
    no `source` at all, appeared to the gate's whole-closure coverage check as a
    member with content.
    """
    import importlib

    library = importlib.import_module("library")

    assert library._workspace_local_source({}, {}, "skill") is None
    assert library._workspace_local_source({}, {"source": ""}, "skill") is None
    assert library._workspace_local_source({}, {"source": "   "}, "skill") is None


def test_w2f1_a_member_field_the_gate_has_not_classified_is_refused(
    tmp_path: Path,
) -> None:
    """Wave-2 `CL-st5s-W2-F1`: the refusal is an allowlist, not a denylist.

    Wave 1 named `sources` on an `agent`; wave 2 answered with `base` on a
    `runtime-config`. Predicting the next spelling is the losing side of this,
    so an entry key nobody has classified as free of installer content refuses
    the member.
    """
    import importlib

    library = importlib.import_module("library")

    inert = {
        "name": "helper",
        "description": "helper skill.",
        "version": "1.0.0",
        "source": "/somewhere/SKILL.md",
        "metadata": {"library": {"source_catalog": "team-core"}},
        "requires": ["skill:other"],
        "tags": ["a"],
    }
    assert library._unadmitted_entry_keys(inert) == []
    assert library._unadmitted_entry_keys({**inert, "base": "/x.yaml"}) == ["base"]
    assert library._unadmitted_entry_keys(
        {**inert, "base": "/x.yaml", "global_overlay": "/y.yaml"}
    ) == ["base", "global_overlay"]
    assert library._unadmitted_entry_keys({**inert, "sources": {"claude": "/z.md"}}) == [
        "sources"
    ]
    assert library._unadmitted_entry_keys({**inert, "handlers": ["h.py"]}) == ["handlers"]
    # A field invented after this bead, which nobody has classified.
    assert library._unadmitted_entry_keys({**inert, "attachments": ["a"]}) == [
        "attachments"
    ]


def test_w2f1_a_runtime_config_member_cannot_install_unadmitted_bytes(
    tmp_path: Path,
) -> None:
    """Wave-2 `CL-st5s-W2-F1`, executed end to end.

    The reviewer's counterexample: a schema-valid `runtime-config` member with no
    `source` and a `base` naming unadmitted bytes. The command returned `applied`
    and wrote `# UNADMITTED RUNTIME CONFIG` to the configured target.
    """
    project, home, base_file = _v2_runtime_config_project(tmp_path)
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "workspace", "use", "team-core:runtime",
         "--scope", "project", "--json"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    unadmitted = base_file.read_bytes()
    assert b"UNADMITTED RUNTIME CONFIG" in unadmitted
    for path in project.rglob("*"):
        if path.is_file():
            assert b"UNADMITTED RUNTIME CONFIG" not in path.read_bytes(), (
                f"unadmitted bytes reached {path}"
            )
    assert not (project / ".library" / "admitted").exists()


def _v2_runtime_config_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """One catalog, one v2 Workspace, one sourceless runtime-config member."""
    project = tmp_path / "project"
    home = tmp_path / "home"
    core = tmp_path / "core"
    for path in (project, home, core):
        path.mkdir(parents=True)

    configs = core / "runtime-configs"
    configs.mkdir()
    base_file = configs / "bypass.yaml"
    base_file.write_text("# UNADMITTED RUNTIME CONFIG\nkey: value\n")
    prompts = core / "prompts"
    prompts.mkdir()
    (prompts / "control.md").write_text("# control\n")

    subprocess.run(["git", "init", "-q", str(core)], check=True)
    for command in (
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "catalog content"],
    ):
        subprocess.run(command, cwd=core, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=core, capture_output=True, text=True, check=True
    ).stdout.strip()

    manifest = {
        "schema_version": 2,
        "name": "runtime",
        "version": "1.0.0",
        "description": "A Workspace containing a sourceless runtime-config.",
        "status": "experimental",
        "catalogs": [
            {
                "alias": "core",
                "identity": "https://example.invalid/core",
                "pin": {"kind": "commit", "value": head},
            }
        ],
        "roots": [
            {"type": "runtime-config", "name": "bypass", "catalog": "core"},
            {"type": "prompt", "name": "control", "catalog": "core"},
        ],
    }
    workspaces = core / "workspaces"
    workspaces.mkdir()
    (workspaces / "runtime.yaml").write_text(yaml.safe_dump(manifest))

    catalog = {
        "catalog_identity": "https://example.invalid/platform",
        "default_dirs": {
            "runtime_configs": [
                {"default": ".agents/"},
                {"global": "~/.agents/"},
            ],
            "prompts": [
                {"default": ".claude/commands/"},
                {"global": "~/.claude/commands/"},
            ],
        },
        "sources": {
            "catalogs": [
                {
                    "name": "team-core",
                    "source": "https://example.invalid/core",
                    "local_path": str(core),
                    "content_types": ["runtime-configs", "prompts", "workspaces"],
                }
            ],
            "marketplaces": [],
        },
        "library": {
            "runtime_configs": [
                {
                    "name": "bypass",
                    "description": "runtime config.",
                    "version": "1.0.0",
                    "base": str(base_file),
                    "metadata": {"library": {"source_catalog": "team-core"}},
                }
            ],
            "prompts": [
                {
                    "name": "control",
                    "description": "control prompt.",
                    "version": "1.0.0",
                    "source": str(prompts / "control.md"),
                    "metadata": {"library": {"source_catalog": "team-core"}},
                }
            ],
            "workspaces": [
                {
                    **manifest,
                    "source": str(workspaces / "runtime.yaml"),
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
    return project, home, base_file
