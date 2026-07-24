"""
catalog_inventory.py - Source catalog matching and convention-scan inventory.

This module keeps promotion-routing logic in source catalog metadata instead of
hard-coding repository names in callers.
"""

from __future__ import annotations

import io
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML

from .catalog import get_catalogs, get_marketplaces
from .errors import CatalogError
from .primitives import get_primitive, resolve_yaml_section


PRIMITIVE_CONTENT_TYPES: dict[str, set[str]] = {
    "skill": {"skill", "skills"},
    "agent": {"agent", "agents"},
    "prompt": {"prompt", "prompts", "command", "commands"},
    "script": {"script", "scripts"},
    "standard": {"standard", "standards"},
    "guardrail": {"guardrail", "guardrails", "hook", "hooks"},
    "mcp": {"mcp", "mcp_server", "mcp_servers"},
    "model-standard": {
        "model-standard",
        "model_standard",
        "model-standards",
        "model_standards",
    },
    "agent-base": {
        "agent-base",
        "agent_base",
        "agent-bases",
        "agent_bases",
    },
    "workflow": {"workflow", "workflows"},
}

CONTENT_TYPE_PRIMITIVES: dict[str, str] = {
    alias: primitive
    for primitive, aliases in PRIMITIVE_CONTENT_TYPES.items()
    for alias in aliases
}

SCAN_PRIMITIVES = {
    "skill",
    "agent",
    "prompt",
    "standard",
    "model-standard",
    "agent-base",
    "workflow",
}

IGNORED_PATH_PARTS = {
    ".beads",
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}

IGNORED_MARKDOWN_FILENAMES = {
    "CHANGELOG.md",
    "README.md",
}


def normalize_topics(raw_topics: str | list[Any] | tuple[Any, ...] | None) -> list[str]:
    """Return stable lowercase topic tokens from CSV text or a sequence."""
    if raw_topics is None:
        return []
    if isinstance(raw_topics, str):
        values = raw_topics.split(",")
    else:
        values = [str(value) for value in raw_topics]
    return sorted(
        {
            value.strip().lower()
            for value in values
            if value is not None and value.strip()
        }
    )


def match_catalogs(
    catalog_data: dict[str, Any],
    primitive_type: str,
    topics: str | list[str] | None = None,
    *,
    writable_only: bool = False,
) -> dict[str, Any]:
    """Rank source catalogs and marketplaces for a primitive and topic set."""
    primitive = get_primitive(primitive_type)
    if primitive is None:
        raise CatalogError(f"Unknown primitive type: {primitive_type}")

    requested_topics = normalize_topics(topics)
    requested_set = set(requested_topics)
    matches: list[dict[str, Any]] = []

    for registry_name, entry in iter_source_entries(catalog_data):
        if writable_only and not bool(entry.get("writable", False)):
            continue
        if not source_accepts_primitive(entry, primitive.name):
            continue

        scope = entry.get("scope") if isinstance(entry.get("scope"), dict) else {}
        source_topics = normalize_topics(scope.get("topics"))
        excludes = normalize_topics(scope.get("excludes"))
        excluded_topics = sorted(requested_set.intersection(excludes))
        if excluded_topics:
            continue

        matched_topics = sorted(requested_set.intersection(source_topics))
        score = len(matched_topics)
        denominator = max(len(requested_topics), 1)
        confidence = score / denominator if requested_topics else 0.0
        matches.append(
            {
                "name": entry.get("name", ""),
                "registry": registry_name,
                "source": entry.get("source", ""),
                "local_path": entry.get("local_path"),
                "writable": bool(entry.get("writable", False)),
                "content_types": list(entry.get("content_types") or []),
                "scope": {
                    "topics": source_topics,
                    "excludes": excludes,
                },
                "matched_topics": matched_topics,
                "score": score,
                "confidence": round(confidence, 3),
            }
        )

    matches.sort(
        key=lambda item: (
            -item["score"],
            -int(item["writable"]),
            item["registry"],
            item["name"],
        )
    )

    top_score = matches[0]["score"] if matches else 0
    selected = (
        [match for match in matches if match["score"] == top_score] if matches else []
    )
    selection_kind = "none"
    if len(selected) == 1:
        selection_kind = "top"
    elif len(selected) > 1:
        selection_kind = "tie"

    for match in matches:
        if match in selected:
            match["selection"] = selection_kind
        else:
            match["selection"] = "candidate"

    return {
        "status": "ok",
        "query": {
            "primitive_type": primitive.name,
            "topics": requested_topics,
            "writable_only": writable_only,
        },
        "matches": matches,
        "selected": selected,
        "selection": selection_kind,
    }


def iter_source_entries(
    catalog_data: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Return all registered source providers with their registry name."""
    entries: list[tuple[str, dict[str, Any]]] = []
    entries.extend(("catalogs", entry) for entry in get_catalogs(catalog_data))
    entries.extend(("marketplaces", entry) for entry in get_marketplaces(catalog_data))
    return entries


def source_accepts_primitive(entry: dict[str, Any], primitive_type: str) -> bool:
    """Return True when a source entry declares it can carry a primitive."""
    aliases = PRIMITIVE_CONTENT_TYPES.get(primitive_type)
    if aliases is None:
        primitive = get_primitive(primitive_type)
        if primitive is None:
            raise CatalogError(f"Unknown primitive type: {primitive_type}")
        aliases = PRIMITIVE_CONTENT_TYPES[primitive.name]

    declared = {
        str(content_type).strip().lower()
        for content_type in (entry.get("content_types") or [])
        if str(content_type).strip()
    }
    return bool(declared.intersection(aliases))


def catalog_sync_plan(
    catalog_data: dict[str, Any],
    *,
    source_names: list[str] | None = None,
    primitive_type: str | None = None,
) -> dict[str, Any]:
    """Build a convention-scan inventory refresh plan."""
    primitive_filter = None
    if primitive_type:
        primitive = get_primitive(primitive_type)
        if primitive is None:
            raise CatalogError(f"Unknown primitive type: {primitive_type}")
        primitive_filter = primitive.name

    selected_names = set(source_names or [])
    source_results: list[dict[str, Any]] = []
    generated_by_primitive: dict[str, list[dict[str, Any]]] = {}

    for registry_name, source_entry in iter_source_entries(catalog_data):
        source_name = str(source_entry.get("name") or "")
        if selected_names and source_name not in selected_names:
            continue

        source_result = scan_source_inventory(
            registry_name,
            source_entry,
            primitive_type=primitive_filter,
        )
        source_results.append(source_result)
        for primitive_name, entries in source_result.get(
            "entries_by_primitive", {}
        ).items():
            generated_by_primitive.setdefault(primitive_name, []).extend(entries)

    missing_sources = sorted(
        selected_names - {result["name"] for result in source_results}
    )
    if missing_sources:
        raise CatalogError(f"Unknown source catalog(s): {', '.join(missing_sources)}")

    generated_counts = {
        primitive_name: len(entries)
        for primitive_name, entries in sorted(generated_by_primitive.items())
    }
    flat_entries = [
        {
            "primitive": primitive_name,
            **entry,
        }
        for primitive_name, entries in sorted(generated_by_primitive.items())
        for entry in entries
    ]

    return {
        "status": "dry-run",
        "strategy": "convention-scan",
        "sources": source_results,
        "generated": generated_counts,
        "total_generated": len(flat_entries),
        "entries": flat_entries,
    }


def sync_catalog_inventory(
    catalog_data: dict[str, Any],
    catalog_root: Path,
    *,
    source_names: list[str] | None = None,
    primitive_type: str | None = None,
    write: bool = False,
) -> dict[str, Any]:
    """Refresh catalog entries from local source checkouts."""
    plan = catalog_sync_plan(
        catalog_data,
        source_names=source_names,
        primitive_type=primitive_type,
    )
    if not write:
        return plan

    yaml_path = catalog_root / "library.yaml"

    # Round-trip via ruamel.yaml so top-level documentation comments
    # (e.g. the default_dirs.skills cross-harness header) survive the
    # regeneration. Mid-file section dividers nested INSIDE library
    # entry lists are still lost because apply_inventory_plan replaces
    # those lists wholesale — that part is acceptable since the
    # dividers can be reconstructed from source-group conventions.
    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 4096
    yaml_rt.representer.add_representer(type(None), represent_null)
    # Match the existing library.yaml style: list items indented under their
    # parent mapping ("    - foo" not "  - foo").
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    with yaml_path.open(encoding="utf-8") as f:
        rt_data = yaml_rt.load(f)

    updated = apply_inventory_plan(rt_data, plan)

    buf = io.StringIO()
    yaml_rt.dump(updated, buf)
    yaml_path.write_text(buf.getvalue(), encoding="utf-8")

    result = deepcopy(plan)
    result["status"] = "ok"
    result["written"] = str(yaml_path)
    return result


def represent_null(representer: Any, data: None) -> Any:
    """Render null explicitly so catalog diffs stay stable."""
    return representer.represent_scalar("tag:yaml.org,2002:null", "null")


def apply_inventory_plan(
    catalog_data: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    """Return catalog data with generated entries replacing matching source entries."""
    updated = deepcopy(catalog_data)
    updated.setdefault("library", {})

    source_entries_by_primitive: dict[str, list[dict[str, Any]]] = {}
    for source_result in plan.get("sources", []):
        source_entry = source_result.get("source_entry", {})
        if not source_entry:
            continue
        for primitive_name in source_result.get("entries_by_primitive", {}):
            source_entries_by_primitive.setdefault(primitive_name, []).append(
                source_entry
            )

    generated: dict[str, list[dict[str, Any]]] = {}
    for entry in plan.get("entries", []):
        primitive_name = entry.get("primitive")
        if not primitive_name:
            continue
        entry_copy = {key: value for key, value in entry.items() if key != "primitive"}
        generated.setdefault(str(primitive_name), []).append(entry_copy)

    for primitive_name, generated_entries in generated.items():
        primitive = get_primitive(primitive_name)
        if primitive is None:
            continue
        section_key = primitive.yaml_key.split("/", 1)[1]
        existing_entries = resolve_yaml_section(updated, primitive)
        source_entries = source_entries_by_primitive.get(primitive_name, [])
        source_names = {str(source.get("name") or "") for source in source_entries}
        merged_generated_entries, matched_existing_ids = merge_generated_entries(
            existing_entries,
            generated_entries,
            source_entries,
            source_names,
        )
        kept_entries = [
            entry
            for entry in existing_entries
            if id(entry) not in matched_existing_ids
            and (
                not entry_belongs_to_sources(entry, source_entries, source_names)
                or not entry_is_inventory_generated(entry)
            )
        ]
        kept_names = {str(entry.get("name") or "") for entry in kept_entries}
        non_colliding_generated_entries = [
            entry
            for entry in merged_generated_entries
            if str(entry.get("name") or "") not in kept_names
        ]
        updated["library"][section_key] = kept_entries + sorted(
            non_colliding_generated_entries,
            key=lambda entry: str(entry.get("name", "")),
        )

    return updated


def merge_generated_entries(
    existing_entries: list[dict[str, Any]],
    generated_entries: list[dict[str, Any]],
    source_entries: list[dict[str, Any]],
    source_names: set[str],
) -> tuple[list[dict[str, Any]], set[int]]:
    """Merge generated entries with matching curated catalog rows.

    Convention scan should update scanner-owned rows, but it must not erase
    unrelated manual metadata such as tags, tier/default scope, or Gas City
    annotations from rows that already point at the same source artifact.
    """
    existing_by_source: dict[str, dict[str, Any]] = {}
    existing_by_name: dict[str, dict[str, Any]] = {}
    for entry in existing_entries:
        if not entry_belongs_to_sources(entry, source_entries, source_names):
            continue
        source = normalize_source_ref(str(entry.get("source") or ""))
        if source:
            existing_by_source[source] = entry
        name = str(entry.get("name") or "")
        if name:
            existing_by_name[name] = entry

    matched_existing_ids: set[int] = set()
    merged_entries: list[dict[str, Any]] = []
    for generated_entry in generated_entries:
        source = normalize_source_ref(str(generated_entry.get("source") or ""))
        name = str(generated_entry.get("name") or "")
        existing_entry = existing_by_source.get(source) or existing_by_name.get(name)
        if existing_entry is not None:
            matched_existing_ids.add(id(existing_entry))
            merged_entries.append(merge_catalog_entry(existing_entry, generated_entry))
        else:
            merged_entries.append(generated_entry)

    return merged_entries, matched_existing_ids


def merge_catalog_entry(
    existing_entry: dict[str, Any], generated_entry: dict[str, Any]
) -> dict[str, Any]:
    """Return a refreshed catalog row while preserving curated metadata."""
    merged = deepcopy(existing_entry)
    for key, value in generated_entry.items():
        merged[key] = value

    if "tags" in existing_entry:
        merged["tags"] = deepcopy(existing_entry["tags"])
    if entry_is_inventory_generated(existing_entry):
        if "requires" not in generated_entry:
            merged.pop("requires", None)
    elif "requires" in existing_entry:
        merged["requires"] = deepcopy(existing_entry["requires"])

    existing_metadata = existing_entry.get("metadata")
    generated_metadata = generated_entry.get("metadata")
    if isinstance(existing_metadata, dict) or isinstance(generated_metadata, dict):
        metadata: dict[str, Any] = {}
        if isinstance(existing_metadata, dict):
            metadata = deepcopy(existing_metadata)
        if isinstance(generated_metadata, dict):
            metadata = deep_merge(metadata, generated_metadata)
        merged["metadata"] = metadata

    return merged


def deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dictionaries, with update values taking precedence."""
    result = deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def entry_is_inventory_generated(entry: dict[str, Any]) -> bool:
    """Return True for rows previously written by convention-scan."""
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    library_meta = (
        metadata.get("library") if isinstance(metadata.get("library"), dict) else {}
    )
    return str(library_meta.get("inventory") or "") == "convention-scan"


def normalize_source_ref(source: str) -> str:
    """Normalize source refs for matching file and tree URLs."""
    return source.rstrip("/")


def scan_source_inventory(
    registry_name: str,
    source_entry: dict[str, Any],
    *,
    primitive_type: str | None = None,
) -> dict[str, Any]:
    """Scan one source checkout using the repository layout convention."""
    source_name = str(source_entry.get("name") or "")
    local_path_value = source_entry.get("local_path")
    result: dict[str, Any] = {
        "name": source_name,
        "registry": registry_name,
        "local_path": local_path_value,
        "status": "skipped",
        "source_entry": source_entry,
        "entries_by_primitive": {},
        "counts": {},
    }

    if not local_path_value:
        result["reason"] = "remote-only"
        return result

    root = Path(str(local_path_value)).expanduser()
    if not root.exists():
        result["reason"] = "local_path missing"
        return result

    primitive_names = declared_scan_primitives(source_entry)
    if primitive_type:
        primitive_names = [name for name in primitive_names if name == primitive_type]

    entries_by_primitive: dict[str, list[dict[str, Any]]] = {}
    for primitive_name in primitive_names:
        entries = scan_primitive(root, source_entry, primitive_name)
        if entries:
            entries_by_primitive[primitive_name] = entries

    result["status"] = "scanned"
    result["entries_by_primitive"] = entries_by_primitive
    result["counts"] = {
        primitive_name: len(entries)
        for primitive_name, entries in sorted(entries_by_primitive.items())
    }
    return result


def declared_scan_primitives(source_entry: dict[str, Any]) -> list[str]:
    """Return scan-supported primitives declared by a source entry."""
    primitives = {
        CONTENT_TYPE_PRIMITIVES[content_type]
        for content_type in {
            str(value).strip().lower()
            for value in (source_entry.get("content_types") or [])
        }
        if content_type in CONTENT_TYPE_PRIMITIVES
    }
    return sorted(primitives.intersection(SCAN_PRIMITIVES))


def scan_primitive(
    root: Path,
    source_entry: dict[str, Any],
    primitive_name: str,
) -> list[dict[str, Any]]:
    """Scan one primitive kind under a local source checkout."""
    if primitive_name == "skill":
        files = sorted(
            skill_file
            for skill_dir in (root / "skills").glob("*")
            if skill_dir.is_dir()
            for skill_file in [find_skill_file(skill_dir)]
            if skill_file is not None
        )
    elif primitive_name == "agent":
        # Private handler directories may contain README files and tests. Agent
        # profiles are the top-level Markdown files in the canonical agents
        # directory; recursively scanning would publish handler documentation as
        # an invalid agent entry.
        files = sorted((root / "agents").glob("*.md"))
    elif primitive_name == "prompt":
        files = sorted((root / "prompts").glob("**/*.md"))
    elif primitive_name == "standard":
        files = scan_standard_artifacts(root / "standards")
    elif primitive_name == "model-standard":
        files = sorted((root / "model-standards").glob("**/*.md"))
    elif primitive_name == "agent-base":
        files = sorted((root / "agent-bases").glob("**/*.md"))
        if not files:
            files = sorted((root / "golden-prompts").glob("**/*.md"))
    elif primitive_name == "workflow":
        files = sorted((root / ".claude" / "workflows").glob("**/*.js"))
    else:
        files = []

    entries = []
    for path in files:
        if any(part in IGNORED_PATH_PARTS for part in path.parts):
            continue
        entries.append(artifact_entry(root, source_entry, primitive_name, path))
    return entries


def find_skill_file(skill_dir: Path) -> Path | None:
    """Return the canonical skill file in a top-level skill directory."""
    files_by_name = {path.name: path for path in skill_dir.iterdir() if path.is_file()}
    for filename in ("SKILL.md", "skill.md"):
        if filename in files_by_name:
            return files_by_name[filename]
    return None


def scan_standard_artifacts(standards_root: Path) -> list[Path]:
    """Return standards artifacts using bundle-aware conventions."""
    if not standards_root.exists():
        return []

    artifacts: list[Path] = []
    artifacts.extend(
        path
        for path in sorted(standards_root.glob("*.md"))
        if path.name not in IGNORED_MARKDOWN_FILENAMES
    )

    for child in sorted(standards_root.iterdir()):
        if not child.is_dir() or any(
            part in IGNORED_PATH_PARTS for part in child.parts
        ):
            continue
        if (child / "_triggers.yml").exists():
            artifacts.append(child)
            continue
        artifacts.extend(
            path
            for path in sorted(child.glob("*.md"))
            if path.name not in IGNORED_MARKDOWN_FILENAMES
        )

    return artifacts


def artifact_entry(
    root: Path,
    source_entry: dict[str, Any],
    primitive_name: str,
    path: Path,
) -> dict[str, Any]:
    """Build a library.yaml entry from a scanned artifact."""
    frontmatter, heading = read_markdown_metadata(path)
    name = str(catalog_artifact_name(primitive_name, path, frontmatter))
    description = str(
        frontmatter.get("description")
        or heading
        or f"{primitive_name} from {source_entry.get('name', 'source')}: {name}"
    )
    relative_path = path.relative_to(root).as_posix()
    is_directory = path.is_dir()
    if is_directory and not relative_path.endswith("/"):
        relative_path = f"{relative_path}/"

    library_metadata = {
        "source_catalog": source_entry.get("name", ""),
        "inventory": "convention-scan",
    }
    if primitive_name in {"skill", "agent", "standard"}:
        library_metadata["plane"] = "dev"

    entry: dict[str, Any] = {
        "name": name,
        "description": collapse_description(description),
        "source": source_url(
            source_entry, relative_path, root, is_directory=is_directory
        ),
        "metadata": {"library": library_metadata},
    }

    tags = frontmatter.get("tags")
    if isinstance(tags, list):
        entry["tags"] = [str(tag) for tag in tags]
    else:
        entry["tags"] = default_artifact_tags(source_entry, primitive_name, path)

    requires = frontmatter.get("requires")
    if isinstance(requires, list):
        typed_requires = [
            str(item) for item in requires if isinstance(item, str) and ":" in item
        ]
    else:
        typed_requires = []

    if primitive_name == "agent":
        required_standards = frontmatter.get("requires_standards")
        if isinstance(required_standards, list):
            typed_requires.extend(
                f"standard:{name}"
                for item in required_standards
                if (name := str(item).strip())
            )

        handler_dir = path.parent / f"{path.stem}-handlers"
        if handler_dir.is_dir():
            entry["handlers"] = [handler_dir.relative_to(root).as_posix()]

    if typed_requires:
        entry["requires"] = sorted(set(typed_requires))

    version = frontmatter.get("version")
    if version is not None:
        entry["version"] = str(version)

    return entry


def default_artifact_tags(
    source_entry: dict[str, Any], primitive_name: str, path: Path
) -> list[str]:
    """Return conservative tags for convention-scanned entries without tags."""
    tags: list[str] = []
    if str(source_entry.get("owner") or "") == "cognovis":
        tags.append("origin:original")
    if primitive_name in {"skill", "agent", "standard"}:
        tags.append("tier:domain")
    if primitive_name == "standard":
        tags.append(
            "category:standard-bundle" if path.is_dir() else "category:standard"
        )
    return tags or ["inventory:convention-scan"]


def read_markdown_metadata(path: Path) -> tuple[dict[str, Any], str]:
    """Read YAML frontmatter and the first Markdown heading from a file."""
    if path.is_dir():
        candidates = [
            path / f"{path.name}.md",
            path / "README.md",
            *sorted(path.glob("*.md")),
        ]
        for candidate in candidates:
            if candidate.exists():
                return read_markdown_metadata(candidate)
        return {}, ""

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(errors="replace")

    frontmatter: dict[str, Any] = {}
    heading = ""
    if text.startswith("---\n"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                parsed = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                parsed = {}
            if isinstance(parsed, dict):
                frontmatter = parsed

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            heading = stripped[2:].strip()
            break
    return frontmatter, heading


def catalog_artifact_name(
    primitive_name: str, path: Path, frontmatter: dict[str, Any]
) -> str:
    """Return the catalog name for a scanned artifact."""
    if primitive_name == "agent":
        return path.stem
    return str(frontmatter.get("name") or default_artifact_name(primitive_name, path))


def default_artifact_name(primitive_name: str, path: Path) -> str:
    """Derive a catalog name from an artifact path."""
    if path.is_dir():
        return path.name
    if primitive_name == "skill" and path.name.lower() == "skill.md":
        return path.parent.name
    return path.stem


def collapse_description(description: str) -> str:
    """Convert YAML multiline descriptions to a compact one-line value."""
    return " ".join(str(description).split())


def source_url(
    source_entry: dict[str, Any],
    relative_path: str,
    root: Path,
    *,
    is_directory: bool = False,
) -> str:
    """Build a source reference for a scanned artifact."""
    base = str(source_entry.get("source") or "").rstrip("/")
    if is_github_repo_url(base):
        mode = "tree" if is_directory else "blob"
        return f"{base}/{mode}/main/{relative_path}"
    return str(root / relative_path)


def is_github_repo_url(source: str) -> bool:
    """Return True for GitHub repository URLs, false for org-only URLs."""
    if not source.startswith("https://github.com/"):
        return False
    parts = source.removeprefix("https://github.com/").strip("/").split("/")
    return len(parts) >= 2 and bool(parts[0]) and bool(parts[1])


def entry_belongs_to_sources(
    entry: dict[str, Any],
    source_entries: list[dict[str, Any]],
    source_names: set[str],
) -> bool:
    """Return True if an existing catalog entry is owned by selected sources."""
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    library_meta = (
        metadata.get("library") if isinstance(metadata.get("library"), dict) else {}
    )
    if str(library_meta.get("source_catalog") or "") in source_names:
        return True

    if str(entry.get("from_marketplace") or "") in source_names:
        return True

    entry_source = str(entry.get("source") or "")
    for source_entry in source_entries:
        remote = str(source_entry.get("source") or "").rstrip("/")
        local = str(source_entry.get("local_path") or "").rstrip("/")
        if remote and entry_source.startswith(f"{remote}/"):
            return True
        if local and entry_source.startswith(f"{local}/"):
            return True
    return False
