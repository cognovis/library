"""Shared core for the standards-loader SessionStart hook.

Reads library.yaml, computes project context, matches triggers against
catalog entries, and returns the matched standards' content.

Used by harness-specific wrappers (claude-code.py, codex-cli.py) which
adapt the result to each harness's hook output protocol.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

LIBRARY_YAML_CANDIDATES = [
    Path.home() / ".claude/skills/library/library.yaml",
    Path.home() / "code/library/meta/library.yaml",
]

INSTALL_ROOTS = [
    Path("./.agents/standards"),
    Path.home() / ".agents/standards",
]

CLAUDE_MD_NAMES = ("CLAUDE.md", "AGENTS.md")
PROJECT_FILE_HINTS = (
    "pyproject.toml", "package.json", "tsconfig.json", "Cargo.toml",
    "go.mod", "Gemfile", "composer.json", "build.gradle", "pom.xml",
    "Dockerfile", "docker-compose.yml", "Makefile", "justfile",
    ".python-version", ".nvmrc", "requirements.txt", "uv.lock",
)


@dataclass
class StandardEntry:
    name: str
    description: str
    source: str
    triggers: list[str]
    is_bundle: bool


def _find_library_yaml() -> Path:
    for p in LIBRARY_YAML_CANDIDATES:
        if p.is_file():
            return p
    sys.stderr.write("standards-loader: library.yaml not found\n")
    sys.exit(0)


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
        return yaml.safe_load(path.read_text())
    except ImportError:
        sys.stderr.write("standards-loader: PyYAML not installed; skipping injection\n")
        sys.exit(0)


def _entries(catalog: dict) -> list[StandardEntry]:
    out = []
    for raw in (catalog.get("library", {}).get("standards", []) or []):
        source = raw.get("source", "")
        out.append(StandardEntry(
            name=raw["name"],
            description=raw.get("description", "").strip(),
            source=source,
            triggers=list(raw.get("triggers", []) or []),
            is_bundle="/tree/" in source,
        ))
    return out


def _project_context(cwd: Path) -> str:
    """Build a single lowercase string scanned for trigger substrings.

    Combines: project basename, listing of top-level filenames,
    contents of CLAUDE.md/AGENTS.md (up to 8 KB each).
    """
    parts: list[str] = [cwd.name.lower()]

    try:
        for entry in cwd.iterdir():
            parts.append(entry.name.lower())
    except OSError:
        pass

    for hint in PROJECT_FILE_HINTS:
        if (cwd / hint).exists():
            parts.append(hint.lower())

    for fname in CLAUDE_MD_NAMES:
        p = cwd / fname
        if p.is_file():
            try:
                parts.append(p.read_text(errors="ignore")[:8192].lower())
            except OSError:
                pass

    return "\n".join(parts)


_WORD_TRIGGER = re.compile(r"^[a-zA-Z]+$")


def _trigger_matches(trig: str, context: str) -> bool:
    if trig == "*":
        return True
    if _WORD_TRIGGER.match(trig):
        # Pure-alphabetic single-word trigger — whole-word match avoids
        # 'python' matching 'pythonic' or 'agent' matching 'agentic'.
        pattern = re.compile(r"\b" + re.escape(trig) + r"\b", re.IGNORECASE)
        return bool(pattern.search(context))
    # Phrases, code constants, paths, extensions, identifiers: substring.
    # These are distinctive enough that substring rarely false-matches.
    return trig.lower() in context


def _match(entry: StandardEntry, context: str) -> bool:
    if not entry.triggers:
        return False
    return any(_trigger_matches(t, context) for t in entry.triggers)


def _read_bundle_triggers(bundle_dir: Path) -> dict | None:
    """Read <bundle_dir>/_triggers.yml. Return None if missing or unreadable.

    Format:
        files:
          style.md: [python, .py, ...]
          ...
    """
    triggers_yml = bundle_dir / "_triggers.yml"
    if not triggers_yml.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(triggers_yml.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    files = data.get("files") or {}
    if not isinstance(files, dict):
        return None
    return files


def _read_entry(entry: StandardEntry, context: str) -> str | None:
    """Read installed content for an entry from the first install root found.

    Bundles: read <root>/<name>/_triggers.yml; for each file listed, evaluate
      its per-file triggers against the project context; include only matching
      files. STRICT MODE: files without an _triggers.yml entry are skipped.
      A bundle with no _triggers.yml contributes nothing.
    Single files: read <root>/<name>.md.
    Project-local roots override global ones (first install root wins per
    bundle); within a bundle the project-local _triggers.yml is authoritative.
    """
    for root in INSTALL_ROOTS:
        if entry.is_bundle:
            bundle_dir = root / entry.name
            if not bundle_dir.is_dir():
                continue
            file_triggers = _read_bundle_triggers(bundle_dir)
            if file_triggers is None:
                # Strict mode: no _triggers.yml -> nothing loads from this bundle
                continue
            pieces = []
            for fname, triggers in file_triggers.items():
                if not triggers:
                    continue
                if not any(_trigger_matches(t, context) for t in triggers):
                    continue
                file_path = bundle_dir / fname
                if not file_path.is_file():
                    continue
                pieces.append(f"### {entry.name}/{fname}\n\n{file_path.read_text(errors='ignore')}")
            if pieces:
                return "\n\n".join(pieces)
            return None
        else:
            single = root / f"{entry.name}.md"
            if single.is_file():
                return f"### {entry.name}\n\n{single.read_text(errors='ignore')}"
    return None


def collect_matched_standards(cwd: Path | None = None) -> str:
    """Public entry point. Returns the assembled markdown text, or empty."""
    if cwd is None:
        cwd = Path.cwd()
    library_yaml = _find_library_yaml()
    catalog = _load_yaml(library_yaml) or {}
    context = _project_context(cwd)

    blocks: list[str] = []
    matched_names: list[str] = []
    file_count = 0
    for entry in _entries(catalog):
        if not _match(entry, context):
            continue
        content = _read_entry(entry, context)
        if not content:
            continue
        blocks.append(content)
        matched_names.append(entry.name)
        # Count only the per-file section markers we inject ("### <bundle>/<name>.md").
        # Other "### " lines inside the standards content are subheadings.
        file_count += len(re.findall(r"^### \S+/\S+\.md", content, re.MULTILINE))

    if not blocks:
        return ""

    header = (
        f"<!-- standards-loader: {file_count} file"
        f"{'' if file_count == 1 else 's'} from "
        f"{len(matched_names)} entr{'y' if len(matched_names) == 1 else 'ies'} "
        f"({', '.join(matched_names)}) -->"
    )
    return header + "\n\n" + "\n\n---\n\n".join(blocks)


if __name__ == "__main__":
    # Dry-run / debug mode
    print(collect_matched_standards())
