"""Current catalog coverage contracts after the repository cleanup."""

from pathlib import Path
import sys
from urllib.parse import urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.primitives import (  # noqa: E402
    all_primitive_names,
    get_primitive,
    resolve_yaml_section,
)


def load_catalog() -> dict:
    return yaml.safe_load((REPO_ROOT / "library.yaml").read_text())


def catalog_entries(catalog: dict) -> dict[tuple[str, str], list[dict]]:
    entries: dict[tuple[str, str], list[dict]] = {}
    for primitive_name in all_primitive_names():
        primitive = get_primitive(primitive_name)
        assert primitive is not None
        for entry in resolve_yaml_section(catalog, primitive):
            entries.setdefault((primitive_name, entry["name"]), []).append(entry)
    return entries


def test_command_prompts_remain_registered_as_prompts() -> None:
    prompts = load_catalog()["library"]["prompts"]

    assert {entry["name"] for entry in prompts} == {
        "compact-reference",
        "executive-pack",
        "install-plugin",
        "topic",
    }
    assert all("category:command" in entry.get("tags", []) for entry in prompts)


def test_catalog_sources_match_declared_source_ownership() -> None:
    catalog = load_catalog()
    source_urls = {
        source["name"]: source["source"].rstrip("/")
        for source in catalog["sources"]["catalogs"]
    }
    mismatches: list[str] = []

    for entries in catalog_entries(catalog).values():
        for entry in entries:
            metadata = (entry.get("metadata") or {}).get("library") or {}
            source_catalog = metadata.get("source_catalog")
            source = entry.get("source")
            if not source_catalog or source_catalog not in source_urls:
                continue
            if not isinstance(source, str) or not source.startswith(("http://", "https://")):
                continue
            declared = urlsplit(source_urls[source_catalog])
            actual = urlsplit(source)
            declared_repo = declared.path.rstrip("/")
            if actual.netloc != declared.netloc or not (
                actual.path == declared_repo
                or actual.path.startswith(f"{declared_repo}/")
            ):
                mismatches.append(
                    f"{entry['name']}: {source_catalog} does not own {source}"
                )

    assert not mismatches, "\n".join(mismatches)


def test_typed_dependencies_resolve_to_catalog_entries() -> None:
    catalog = load_catalog()
    entries = catalog_entries(catalog)
    unresolved: list[str] = []

    for (primitive_name, name), candidates in entries.items():
        for entry in candidates:
            for dependency in entry.get("requires") or []:
                assert isinstance(dependency, str) and ":" in dependency
                dependency_type, dependency_name = dependency.split(":", 1)
                if (dependency_type, dependency_name) not in entries:
                    unresolved.append(
                        f"{primitive_name}:{name} requires missing {dependency}"
                    )

    assert not unresolved, "\n".join(unresolved)
