import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.catalog import load_catalog  # noqa: E402
from lib.resolver import resolve_requires  # noqa: E402

LIBRARY_SPEC = importlib.util.spec_from_file_location(
    "library_scope_test_cli", REPO_ROOT / "scripts" / "library.py"
)
assert LIBRARY_SPEC is not None and LIBRARY_SPEC.loader is not None
LIBRARY_MODULE = importlib.util.module_from_spec(LIBRARY_SPEC)
LIBRARY_SPEC.loader.exec_module(LIBRARY_MODULE)


def test_session_close_resolves_ccore_before_install() -> None:
    order = resolve_requires(
        load_catalog(REPO_ROOT),
        "skill",
        "session-close",
        REPO_ROOT,
    )

    assert ("skill", "cognovis-beads") in order
    assert ("script", "ccore") in order
    assert order.index(("script", "ccore")) < order.index(("skill", "session-close"))


def test_ccore_catalog_entry_uses_the_standalone_versioned_repository() -> None:
    catalog = load_catalog(REPO_ROOT)
    entry = next(
        item for item in catalog["library"]["scripts"] if item["name"] == "ccore"
    )

    assert entry["source"] == "https://github.com/cognovis/ccore"
    assert entry["version"] == "2026.8.0"
    assert entry["distribution"] == {
        "kind": "uv-tool",
        "package_name": "cognovis-core-tools",
        "executables": ["ccore"],
    }


def test_project_skill_installs_global_uv_tool_dependency_in_its_own_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = {
        "library": {
            "skills": [
                {
                    "name": "project-skill",
                    "description": "Project-scoped test skill.",
                    "source": str(tmp_path / "SKILL.md"),
                    "requires": ["script:ccore"],
                }
            ],
            "scripts": [
                {
                    "name": "ccore",
                    "description": "Global CLI.",
                    "source": str(tmp_path / "ccore"),
                    "default_scope": "global",
                    "distribution": {
                        "kind": "uv-tool",
                        "package_name": "cognovis-core-tools",
                        "executables": ["ccore"],
                    },
                }
            ],
        }
    }
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr("lib.resolver.is_already_installed", lambda *_: False)
    monkeypatch.setattr(
        LIBRARY_MODULE,
        "_dispatch_use",
        lambda _args, _repo, _catalog, primitive, name, scope, *_rest: (
            calls.append((primitive, name, scope)) or 0
        ),
    )

    result = LIBRARY_MODULE._install_with_deps(
        SimpleNamespace(symlink=False),
        tmp_path,
        catalog,
        "skill",
        "project-skill",
        "project",
        "all",
        False,
    )

    assert result == 0
    assert calls == [
        ("script", "ccore", "global"),
        ("skill", "project-skill", "project"),
    ]
