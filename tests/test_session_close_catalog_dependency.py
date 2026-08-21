import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.catalog import load_catalog  # noqa: E402
from lib.resolver import resolve_requires  # noqa: E402

def test_session_close_declares_ccore_as_runtime_not_install_dependency() -> None:
    catalog = load_catalog(REPO_ROOT)
    order = resolve_requires(
        catalog,
        "skill",
        "session-close",
        REPO_ROOT,
    )
    entry = next(
        item for item in catalog["library"]["skills"] if item["name"] == "session-close"
    )

    assert ("skill", "cognovis-beads") in order
    assert ("script", "ccore") not in order
    assert entry["runtime_requirements"]["binaries"] == ["ccore"]


def test_ccore_catalog_entry_uses_the_standalone_versioned_repository() -> None:
    catalog = load_catalog(REPO_ROOT)
    entry = next(
        item for item in catalog["library"]["scripts"] if item["name"] == "ccore"
    )

    assert entry["source"] == "https://git.cognovis.de/cognovis/ccore"
    assert entry["version"] == "2026.8.0"
    assert entry["distribution"] == {
        "kind": "uv-tool",
        "package_name": "cognovis-core-tools",
        "executables": ["ccore"],
    }
