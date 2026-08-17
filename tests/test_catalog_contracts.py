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


def test_platform_forge_descriptions_match_checked_in_frontmatter() -> None:
    catalog = load_catalog()["library"]
    platform_skills = {
        entry["name"]: entry
        for entry in catalog["skills"]
        if ((entry.get("metadata") or {}).get("library") or {}).get("source_catalog")
        == "library-platform"
        and (REPO_ROOT / "skills" / entry["name"] / "SKILL.md").is_file()
    }
    for name, entry in platform_skills.items():
        frontmatter = yaml.safe_load(
            (REPO_ROOT / "skills" / name / "SKILL.md").read_text().split("---", 2)[1]
        )
        assert entry["description"] == frontmatter["description"]


def test_catalog_sources_match_declared_source_ownership() -> None:
    catalog = load_catalog()
    source_urls = {
        source["name"]: source["source"].rstrip("/")
        for source_group in ("catalogs", "marketplaces")
        for source in catalog["sources"][source_group]
        if str(source.get("source", "")).startswith(("http://", "https://"))
    }
    mismatches: list[str] = []

    for (primitive_name, _), entries in catalog_entries(catalog).items():
        for entry in entries:
            metadata = (entry.get("metadata") or {}).get("library") or {}
            source_catalog = metadata.get("source_catalog")
            source = entry.get("source")
            if not isinstance(source, str) or not source.startswith(("http://", "https://")):
                continue
            if not source_catalog:
                matching_owners = [
                    name
                    for name, owner_url in source_urls.items()
                    if source == owner_url or source.startswith(f"{owner_url}/")
                ]
                if primitive_name != "mcp" or len(matching_owners) != 1:
                    mismatches.append(
                        f"{entry['name']}: missing source_catalog for {source}"
                    )
                continue
            if source_catalog not in source_urls:
                mismatches.append(
                    f"{entry['name']}: undeclared source_catalog {source_catalog}"
                )
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


def test_catalog_type_and_name_pairs_are_unique() -> None:
    duplicates = {
        key: candidates
        for key, candidates in catalog_entries(load_catalog()).items()
        if len(candidates) != 1
    }

    assert not duplicates, "\n".join(
        f"duplicate {primitive_type}:{name} ({len(candidates)} entries)"
        for (primitive_type, name), candidates in duplicates.items()
    )


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


def test_workspace_roots_and_dependency_closures_resolve() -> None:
    catalog = load_catalog()
    entries = catalog_entries(catalog)
    unresolved: list[str] = []

    def visit(owner: str, key: tuple[str, str], seen: set[tuple[str, str]]) -> None:
        if key in seen:
            return
        seen.add(key)
        candidates = entries.get(key, [])
        if len(candidates) != 1:
            unresolved.append(f"{owner} resolves {key[0]}:{key[1]} to {len(candidates)} entries")
            return
        for dependency in candidates[0].get("requires") or []:
            dependency_type, dependency_name = dependency.split(":", 1)
            visit(owner, (dependency_type, dependency_name), seen)

    for workspace in catalog["library"]["workspaces"]:
        seen: set[tuple[str, str]] = set()
        for root in workspace["roots"]:
            visit(workspace["name"], (root["type"], root["name"]), seen)

    assert not unresolved, "\n".join(unresolved)


def test_only_the_intrinsically_machine_wide_script_declares_a_global_default_scope() -> None:
    """ADR-0012: catalog metadata cannot nominate a second desired state.

    `script:ccore` is a uv tool on PATH, so its marker states an intrinsic
    property of the artifact rather than a Library scope selection. Every other
    entry carrying one was claiming a desired state the platform does not have.
    """
    catalog = load_catalog()
    entries = catalog_entries(catalog)

    marked = sorted(
        f"{key[0]}:{key[1]}"
        for key, candidates in entries.items()
        for entry in candidates
        if entry.get("default_scope") == "global"
    )

    assert marked == ["script:ccore"]
