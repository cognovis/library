"""Regression tests for stale dependency closures during root installation.

A root install resolves its full `requires:` closure. Members that are already
installed must be compared against the ACTIVE catalog contract (declared
version / declared source), not only against upstream git state. Otherwise an
older direct install of a dependency survives the root install and the root
loads against a runtime-incompatible member (bead CL-2i17).
"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.lockfile import (  # noqa: E402
    find_lockfile,
    load_lockfile,
    make_entry,
    save_lockfile,
    upsert_entry,
)

LIBRARY_SPEC = importlib.util.spec_from_file_location(
    "library_stale_closure_test_cli", REPO_ROOT / "scripts" / "library.py"
)
assert LIBRARY_SPEC is not None and LIBRARY_SPEC.loader is not None
LIBRARY_MODULE = importlib.util.module_from_spec(LIBRARY_SPEC)
LIBRARY_SPEC.loader.exec_module(LIBRARY_MODULE)


def _install_lockfile_entry(
    repo_root: Path,
    name: str,
    *,
    source: str,
    version: str | None,
) -> None:
    """Record `name` as an installed project-scoped skill and materialize it.

    `checksum_sha256` is deliberately empty so `_has_local_tamper` short-circuits
    to False; these tests isolate catalog-contract drift from local tamper.
    """
    install_target = repo_root / "deployed" / name
    install_target.mkdir(parents=True, exist_ok=True)
    (install_target / "SKILL.md").write_text(f"# {name}\n")

    lockfile_path = find_lockfile(repo_root, global_scope=False)
    data = load_lockfile(lockfile_path)
    upsert_entry(
        data,
        make_entry(
            name=name,
            primitive_type="skill",
            marketplace="test-marketplace",
            source=source,
            source_commit="local",
            cache_path=str(repo_root / "cache" / name),
            install_target=f"{install_target}/",
            checksum_sha256="",
            checksum_type="directory",
            scope="project",
            version=version,
        ),
    )
    save_lockfile(lockfile_path, data)


def _skill_entry(
    tmp_path: Path,
    name: str,
    *,
    version: str | None = None,
    requires: list[str] | None = None,
    source: str | None = "<default>",
) -> dict:
    """Build a minimal catalog skill entry."""
    entry: dict = {"name": name, "description": f"Test skill {name}."}
    if source == "<default>":
        entry["source"] = str(tmp_path / "sources" / name)
    elif source is not None:
        entry["source"] = source
    if version is not None:
        entry["version"] = version
    if requires:
        entry["requires"] = requires
    return entry


def _record_dispatches(
    monkeypatch: pytest.MonkeyPatch,
    upstream_status: str = "current",
) -> list[tuple[str, str, str]]:
    """Capture `_dispatch_use` calls and pin upstream status to `current`."""
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        LIBRARY_MODULE,
        "_check_upstream_status_for_entry",
        lambda *_args, **_kwargs: upstream_status,
    )
    monkeypatch.setattr(
        LIBRARY_MODULE,
        "_dispatch_use",
        lambda _args, _repo, _catalog, primitive, name, scope, *_rest: (
            calls.append((primitive, name, scope)) or 0
        ),
    )
    return calls


def _run(tmp_path: Path, catalog: dict, name: str) -> int:
    return LIBRARY_MODULE._install_with_deps(
        SimpleNamespace(symlink=False),
        tmp_path,
        catalog,
        "skill",
        name,
        "project",
        "all",
        False,
    )


def test_stale_catalog_version_dependency_is_refreshed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog bumped the dependency version — the old install must refresh."""
    dep_source = str(tmp_path / "sources" / "stale-dep")
    _install_lockfile_entry(tmp_path, "stale-dep", source=dep_source, version="1.0.0")
    catalog = {
        "library": {
            "skills": [
                _skill_entry(tmp_path, "stale-dep", version="2.0.0"),
                _skill_entry(tmp_path, "root-skill", requires=["skill:stale-dep"]),
            ]
        }
    }
    calls = _record_dispatches(monkeypatch)

    assert _run(tmp_path, catalog, "root-skill") == 0
    assert calls == [
        ("skill", "stale-dep", "project"),
        ("skill", "root-skill", "project"),
    ]


def test_dependency_source_moved_in_catalog_is_refreshed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catalog moved the dependency to a new source — refresh the old install."""
    _install_lockfile_entry(
        tmp_path,
        "moved-dep",
        source="https://github.com/old-owner/old-repo/tree/main/skills/moved-dep",
        version=None,
    )
    catalog = {
        "library": {
            "skills": [
                _skill_entry(
                    tmp_path,
                    "moved-dep",
                    source="https://github.com/new-owner/new-repo/tree/main/skills/moved-dep",
                ),
                _skill_entry(tmp_path, "root-skill", requires=["skill:moved-dep"]),
            ]
        }
    }
    calls = _record_dispatches(monkeypatch)

    assert _run(tmp_path, catalog, "root-skill") == 0
    assert calls == [
        ("skill", "moved-dep", "project"),
        ("skill", "root-skill", "project"),
    ]


def test_mixed_old_and_new_closure_refreshes_only_the_stale_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mixed old/new closure: refresh the stale member, leave the current one."""
    _install_lockfile_entry(
        tmp_path,
        "current-dep",
        source=str(tmp_path / "sources" / "current-dep"),
        version="2.0.0",
    )
    _install_lockfile_entry(
        tmp_path,
        "stale-dep",
        source=str(tmp_path / "sources" / "stale-dep"),
        version="1.0.0",
    )
    catalog = {
        "library": {
            "skills": [
                _skill_entry(tmp_path, "current-dep", version="2.0.0"),
                _skill_entry(tmp_path, "stale-dep", version="2.0.0"),
                _skill_entry(
                    tmp_path,
                    "root-skill",
                    requires=["skill:current-dep", "skill:stale-dep"],
                ),
            ]
        }
    }
    calls = _record_dispatches(monkeypatch)

    assert _run(tmp_path, catalog, "root-skill") == 0
    assert calls == [
        ("skill", "stale-dep", "project"),
        ("skill", "root-skill", "project"),
    ]


def test_unresolvable_stale_dependency_fails_before_root_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stale member with no installable catalog source must block the whole graph."""
    _install_lockfile_entry(
        tmp_path,
        "broken-dep",
        source=str(tmp_path / "sources" / "broken-dep"),
        version="1.0.0",
    )
    catalog = {
        "library": {
            "skills": [
                _skill_entry(tmp_path, "broken-dep", version="2.0.0", source=None),
                _skill_entry(tmp_path, "root-skill", requires=["skill:broken-dep"]),
            ]
        }
    }
    calls = _record_dispatches(monkeypatch)

    assert _run(tmp_path, catalog, "root-skill") != 0
    message = capsys.readouterr().err
    assert "broken-dep" in message
    assert "library skill sync broken-dep" in message
    assert calls == []


def test_contract_current_dependency_is_still_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No churn: a member matching the catalog contract exactly is still skipped."""
    _install_lockfile_entry(
        tmp_path,
        "current-dep",
        source=str(tmp_path / "sources" / "current-dep"),
        version="2.0.0",
    )
    catalog = {
        "library": {
            "skills": [
                _skill_entry(tmp_path, "current-dep", version="2.0.0"),
                _skill_entry(tmp_path, "root-skill", requires=["skill:current-dep"]),
            ]
        }
    }
    calls = _record_dispatches(monkeypatch)

    assert _run(tmp_path, catalog, "root-skill") == 0
    assert calls == [("skill", "root-skill", "project")]
    assert "[skip] skill:current-dep already installed" in capsys.readouterr().err


def test_multi_harness_and_marketplace_sources_are_not_reported_as_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sources-map and from_marketplace entries must not be false-positive refreshes."""
    _install_lockfile_entry(
        tmp_path,
        "codex-dep",
        source="https://github.com/acme/acme-skills/tree/main/skills/codex-dep/",
        version=None,
    )
    _install_lockfile_entry(
        tmp_path,
        "marketplace-dep",
        source="https://github.com/acme/acme-skills/tree/main/skills/marketplace-dep",
        version=None,
    )
    catalog = {
        "marketplaces": [
            {"id": "acme", "source": "https://github.com/acme/acme-skills"}
        ],
        "library": {
            "skills": [
                {
                    "name": "codex-dep",
                    "description": "Multi-harness skill.",
                    "sources": {
                        "claude": "https://github.com/acme/acme-skills/tree/main/skills/codex-dep-claude",
                        "codex": "https://github.com/acme/acme-skills/tree/main/skills/codex-dep",
                    },
                },
                {
                    "name": "marketplace-dep",
                    "description": "Marketplace skill.",
                    "from_marketplace": "acme",
                    "path": "skills/marketplace-dep",
                },
                _skill_entry(
                    tmp_path,
                    "root-skill",
                    requires=["skill:codex-dep", "skill:marketplace-dep"],
                ),
            ]
        },
    }
    calls = _record_dispatches(monkeypatch)

    assert _run(tmp_path, catalog, "root-skill") == 0
    assert calls == [("skill", "root-skill", "project")]


def test_unresolvable_marketplace_source_fails_before_root_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-git marketplace is schema-valid but unresolvable for a direct install.

    The installed member can then be neither verified against nor refreshed from
    the active catalog, so the closure must fail before the root is installed
    instead of silently skipping the stale member.
    """
    _install_lockfile_entry(
        tmp_path,
        "moved-dep",
        source="https://github.com/old-owner/old-repo/tree/main/skills/moved-dep",
        version=None,
    )
    catalog = {
        "marketplaces": [
            {
                "id": "skills-sh",
                "source": "https://github.com/acme/acme-skills",
                "type": "skills-sh",
            }
        ],
        "library": {
            "skills": [
                {
                    "name": "moved-dep",
                    "description": "Moved to a non-git marketplace.",
                    "from_marketplace": "skills-sh",
                    "path": "skills/moved-dep",
                },
                _skill_entry(tmp_path, "root-skill", requires=["skill:moved-dep"]),
            ]
        },
    }
    calls = _record_dispatches(monkeypatch)

    assert _run(tmp_path, catalog, "root-skill") != 0
    message = capsys.readouterr().err
    assert "moved-dep" in message
    assert "library skill sync moved-dep" in message
    assert calls == []


def test_unknown_marketplace_reference_fails_before_root_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An entry pointing at a marketplace the catalog no longer defines fails closed."""
    _install_lockfile_entry(
        tmp_path,
        "orphan-dep",
        source="https://github.com/acme/acme-skills/tree/main/skills/orphan-dep",
        version=None,
    )
    catalog = {
        "marketplaces": [
            {"id": "acme", "source": "https://github.com/acme/acme-skills"}
        ],
        "library": {
            "skills": [
                {
                    "name": "orphan-dep",
                    "description": "References a marketplace that was removed.",
                    "from_marketplace": "retired-marketplace",
                    "path": "skills/orphan-dep",
                },
                _skill_entry(tmp_path, "root-skill", requires=["skill:orphan-dep"]),
            ]
        },
    }
    calls = _record_dispatches(monkeypatch)

    assert _run(tmp_path, catalog, "root-skill") != 0
    message = capsys.readouterr().err
    assert "orphan-dep" in message
    assert "library skill sync orphan-dep" in message
    assert calls == []
