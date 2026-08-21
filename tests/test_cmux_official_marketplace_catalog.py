"""Catalog contract for the official CMUX Marketplace rollout."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import yaml
import pytest


ROOT = Path(__file__).resolve().parents[1]
CMUX_PIN = "a4c2ce93a461cf784dd3bd1bcc03e2a7cd2420ee"
CMUX_WORKSPACE_SOURCE_COMMIT = "8576dcb10d4256a1aae68b2b9ebb55397a4a9c4e"
CORE_SOURCE_COMMIT = "eea6dabedf995925f416f74c41f36bf5c26a37d7"
OFFICIAL_SKILLS = frozenset(
    {
        "cmux",
        "cmux-workspace",
        "cmux-settings",
        "cmux-customization",
        "cmux-diagnostics",
        "cmux-browser",
        "cmux-markdown",
    }
)
OFFICIAL_DESCRIPTIONS = {
    "cmux": (
        "End-user control of cmux topology and routing (windows, workspaces, "
        "panes/surfaces, focus, moves, reorder, identify, trigger flash). Use "
        "when automation needs deterministic placement and navigation in a "
        "multi-pane cmux layout."
    ),
    "cmux-workspace": (
        "Work inside the current cmux workspace and terminal. Use for cmux "
        "workspace, current workspace, caller surface, panes, surfaces, socket "
        "targeting, and non-interfering cmux automation."
    ),
    "cmux-settings": (
        "View and edit cmux settings in ~/.config/cmux/cmux.json. Use when the "
        "user wants to change cmux preferences (appearance, sidebar, "
        "notifications, automation, browser, shortcuts), set a value by JSON "
        "path, validate the file, open it in an editor, or look up which keys "
        "cmux recognizes. Triggers on '/cmux-settings', 'change cmux setting', "
        "'set <something> in cmux', 'cmux config', 'cmux.json', or 'rebind a "
        "cmux shortcut'."
    ),
    "cmux-customization": (
        "Customize cmux for an end user. Use when changing cmux.json actions, "
        "custom commands, workspace layouts, plus-button behavior, surface tab "
        "bar buttons, Command Palette entries, Dock controls, sidebar and app "
        "settings, shortcuts, notifications, browser routing, examples-library "
        "presets, or Ghostty-backed terminal preferences."
    ),
    "cmux-diagnostics": (
        "Run end-user cmux diagnostics. Use when cmux hooks, notifications, "
        "session restore, settings, browser automation, socket access, CLI "
        "control, or agent resume behavior is not working, or when the user asks "
        "for a cmux health check, doctor report, or support-safe debug summary."
    ),
    "cmux-browser": (
        "End-user browser automation with cmux. Use when you need to open sites, "
        "interact with pages, wait for state changes, and extract data from cmux "
        "browser surfaces."
    ),
    "cmux-markdown": (
        "Open markdown files in a formatted viewer panel with live reload. Use "
        "when you need to display plans, documentation, or notes alongside the "
        "terminal with rich rendering (headings, code blocks, tables, lists)."
    ),
}
DISPATCH_CLOSURE_MEMBERS = (
    ("skills", "cmux"),
    ("skills", "cmux-workspace"),
    ("skills", "cognovis-beads"),
    ("standards", "judge-layer"),
    ("agents", "judge-default"),
    ("skills", "cmux-bead-dispatch"),
)


def _catalog() -> dict:
    return yaml.safe_load((ROOT / "library.yaml").read_text(encoding="utf-8"))


def _entry(catalog: dict, kind: str, name: str) -> dict:
    return next(entry for entry in catalog["library"][kind] if entry["name"] == name)


def _core_root() -> Path:
    """Locate the checked-out Core catalog without binding tests to one operator."""
    candidates = []
    configured = os.environ.get("COGNOVIS_CORE")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        (
            ROOT.parent / "cognovis-core",
            ROOT.parents[1] / "cognovis-core",
            ROOT.parents[2] / "library" / "cognovis-core",
        )
    )
    for candidate in candidates:
        if (candidate / "workspaces" / "cognovis-cmux.yaml").is_file():
            return candidate
    raise AssertionError(f"cognovis-core checkout not found in {candidates}")


def _library_cli_root() -> Path | None:
    """Return the separately shipped Library runtime when the checkout is present."""
    candidates = []
    configured = os.environ.get("LIBRARY_CLI_ROOT")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        (
            ROOT.parent / "library-cli",
            ROOT.parents[1] / "library-cli",
            ROOT.parents[2] / "library" / "library-cli",
        )
    )
    return next(
        (
            candidate
            for candidate in candidates
            if (candidate / "pyproject.toml").is_file()
            and (candidate / "scripts" / "library.py").is_file()
        ),
        None,
    )


def test_cmux_official_is_one_remote_git_marketplace_with_gpl_evidence() -> None:
    catalog = _catalog()
    matches = [
        entry
        for entry in catalog["sources"]["marketplaces"]
        if entry["name"] == "cmux-official"
    ]

    assert len(matches) == 1
    marketplace = matches[0]
    assert marketplace["source"] == "https://github.com/manaflow-ai/cmux"
    assert marketplace["type"] == "git"
    assert marketplace["provider_kind"] == "git-repo"
    assert marketplace["local_path"] is None
    assert marketplace["writable"] is False
    assert marketplace["content_types"] == ["skills"]
    assert marketplace["rights"] == {
        "fetch_authorization": "granted",
        "install_rights": "granted",
        "redistribution_rights": "granted",
        "derivative_rights": "granted",
        "evidence_source": (
            "upstream LICENSE (GPL-3.0-or-later), reviewed at "
            "a4c2ce93a461cf784dd3bd1bcc03e2a7cd2420ee on 2026-08-21"
        ),
    }


def test_official_cmux_skills_have_foreign_pinned_provenance_without_local_copies() -> None:
    catalog = _catalog()
    skills = {
        entry["name"]: entry
        for entry in catalog["library"]["skills"]
        if entry["name"] in OFFICIAL_SKILLS
    }

    assert set(skills) == OFFICIAL_SKILLS
    assert set(OFFICIAL_DESCRIPTIONS) == OFFICIAL_SKILLS
    for name, entry in skills.items():
        assert entry["description"] == OFFICIAL_DESCRIPTIONS[name]
        assert entry["source"] == (
            "https://github.com/manaflow-ai/cmux/blob/"
            f"{CMUX_PIN}/skills/{name}/SKILL.md"
        )
        assert entry["from_marketplace"] == "cmux-official"
        assert entry["repo"] == "cmux"
        assert entry["path"] == f"skills/{name}"
        assert entry["branch"] == CMUX_PIN
        assert entry["metadata"]["library"] == {
            "source_catalog": "cmux-official",
            "inventory": "marketplace",
            "plane": "dev",
            "steward": "manaflow-ai",
        }
        assert "origin:third-party" in entry["tags"]
        assert not any(
            "cognovis/library-core/blob/main/skills/cmux" in value
            for value in entry.values()
            if isinstance(value, str)
        )


def test_dispatch_remains_cognovis_owned_but_depends_on_official_cmux_skills() -> None:
    catalog = _catalog()
    dispatch = _entry(catalog, "skills", "cmux-bead-dispatch")

    assert dispatch["metadata"]["library"]["source_catalog"] == "cognovis-library-core"
    assert {"skill:cmux", "skill:cmux-workspace"} <= set(dispatch["requires"])


def test_dispatch_closure_sources_have_safe_nonempty_repository_paths() -> None:
    """Pinned Workspace reads must not receive an empty tree-path segment."""
    catalog = _catalog()

    for kind, name in DISPATCH_CLOSURE_MEMBERS:
        source = str(_entry(catalog, kind, name)["source"])
        parsed = urlsplit(source)
        segments = tuple(segment for segment in parsed.path.split("/") if segment)

        assert parsed.scheme == "https"
        assert source.endswith("/") is False
        assert segments
        assert segments[-1] not in {".", ".."}
        assert ".." not in segments


def test_cognovis_core_uses_its_canonical_forgejo_identity() -> None:
    catalog = _catalog()
    core = next(
        entry
        for entry in catalog["sources"]["catalogs"]
        if entry["name"] == "cognovis-library-core"
    )

    assert core["source"] == "https://git.cognovis.de/cognovis/library-core"
    workspace = _entry(catalog, "workspaces", "cognovis-cmux-dispatch")
    assert workspace["catalogs"][0]["identity"] == core["source"]


def test_cmux_workspaces_are_published_from_core_with_their_exact_manifests() -> None:
    catalog = _catalog()
    core_root = _core_root()

    for name in ("cognovis-cmux", "cognovis-cmux-dispatch"):
        manifest = yaml.safe_load(
            (core_root / "workspaces" / f"{name}.yaml").read_text(encoding="utf-8")
        )
        entry = _entry(catalog, "workspaces", name)
        for key, value in manifest.items():
            if key == "metadata":
                continue
            assert entry[key] == value
        expected_metadata = dict(manifest.get("metadata") or {})
        expected_metadata["library"] = {
            "source_catalog": "cognovis-library-core",
            "inventory": "manual",
            "source_commit": (
                CORE_SOURCE_COMMIT
                if name == "cognovis-cmux-dispatch"
                else CMUX_WORKSPACE_SOURCE_COMMIT
            ),
        }
        assert entry["metadata"] == expected_metadata

        if name == "cognovis-cmux-dispatch":
            assert entry["source"] == (
                "https://git.cognovis.de/cognovis/library-core/raw/commit/"
                f"{CORE_SOURCE_COMMIT}/workspaces/cognovis-cmux-dispatch.yaml"
            )
        else:
            assert entry["source"] == (
                "https://git.cognovis.de/cognovis/library-core/raw/commit/"
                f"{CMUX_WORKSPACE_SOURCE_COMMIT}/workspaces/cognovis-cmux.yaml"
            )


def test_external_library_cli_validates_both_cmux_workspaces() -> None:
    """The active Library runtime, not archived catalog code, owns Workspace validation."""
    cli_root = _library_cli_root()
    if cli_root is None:
        pytest.skip("separately shipped library-cli checkout is unavailable")

    for workspace in ("cognovis-cmux", "cognovis-cmux-dispatch"):
        result = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(cli_root),
                "library",
                "--catalog",
                str(ROOT / "library.yaml"),
                "workspace",
                "validate",
                f"cognovis-library-core:{workspace}",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        assert json.loads(result.stdout) == {
            "operation": "validate",
            "status": "valid",
            "reference": f"cognovis-library-core:{workspace}",
        }


def test_external_library_cli_attributes_all_declared_catalog_sources(
    tmp_path: Path,
) -> None:
    """Every declared source must cover its Core and Marketplace entry origins."""
    cli_root = _library_cli_root()
    if cli_root is None:
        pytest.skip("separately shipped library-cli checkout is unavailable")

    catalog = _catalog()
    registry_dir = tmp_path / "config" / "library"
    registry_dir.mkdir(parents=True)
    declared_sources = [
        *catalog["sources"].get("catalogs", []),
        *catalog["sources"].get("marketplaces", []),
    ]
    registry_sources = []
    for source in declared_sources:
        checkout = tmp_path / "checkouts" / source["name"]
        checkout.mkdir(parents=True)
        registry_sources.append(
            {"identity": source["source"], "checkout": str(checkout)}
        )
    registry_dir.joinpath("catalog-sources.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "catalogs": registry_sources,
            }
        ),
        encoding="utf-8",
    )

    environment = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "config")}
    environment.pop("VIRTUAL_ENV", None)
    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(cli_root),
            "library",
            "--catalog",
            str(ROOT / "library.yaml"),
            "catalog",
            "sources",
            "--json",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["unattributed"] == []
    assert payload["unregistered"] == []
