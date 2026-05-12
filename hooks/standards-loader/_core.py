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
CONTEXT_DOTFILE_NAMES = {
    ".env",
    ".env.example",
    ".python-version",
    ".nvmrc",
    ".node-version",
}
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


@dataclass
class MatchedStandardFile:
    entry_name: str
    relative_name: str
    path: Path


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

    Combines project basename and top-level filenames. Instruction files
    (CLAUDE.md/AGENTS.md) are intentionally not scanned by default: they contain
    generic words such as "agent", "git", "test", and "view", which otherwise
    trigger broad standards bundles for nearly every project.
    """
    parts: list[str] = [cwd.name.lower()]

    try:
        for entry in cwd.iterdir():
            if entry.name.startswith(".") and entry.name not in CONTEXT_DOTFILE_NAMES:
                continue
            parts.append(entry.name.lower())
    except OSError:
        pass

    for hint in PROJECT_FILE_HINTS:
        if (cwd / hint).exists():
            parts.append(hint.lower())

    if os.environ.get("STANDARDS_LOADER_SCAN_INSTRUCTIONS") == "1":
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


def _matched_files_for_entry(entry: StandardEntry, context: str) -> list[MatchedStandardFile]:
    """Return installed files for a matched entry from the first install root found.

    Bundles: read <root>/<name>/_triggers.yml; for each file listed, evaluate
      its per-file triggers against the project context; include only matching
      files. STRICT MODE: files without an _triggers.yml entry are skipped.
      A bundle with no _triggers.yml contributes nothing.
    Single files: return <root>/<name>.md.
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
            matches: list[MatchedStandardFile] = []
            for fname, triggers in file_triggers.items():
                if not triggers:
                    continue
                if not any(_trigger_matches(t, context) for t in triggers):
                    continue
                file_path = bundle_dir / fname
                if not file_path.is_file():
                    continue
                matches.append(MatchedStandardFile(entry.name, fname, file_path))
            return matches
        else:
            single = root / f"{entry.name}.md"
            if single.is_file():
                return [MatchedStandardFile(entry.name, f"{entry.name}.md", single)]
    return []


def _matched_standard_files(cwd: Path) -> list[MatchedStandardFile]:
    library_yaml = _find_library_yaml()
    catalog = _load_yaml(library_yaml) or {}
    context = _project_context(cwd)

    files: list[MatchedStandardFile] = []
    for entry in _entries(catalog):
        if not _match(entry, context):
            continue
        files.extend(_matched_files_for_entry(entry, context))
    return files


def collect_matched_standards(cwd: Path | None = None) -> str:
    """Public entry point. Returns the assembled markdown text, or empty."""
    if cwd is None:
        cwd = Path.cwd()
    files = _matched_standard_files(cwd)
    if not files:
        return ""

    blocks = [
        f"### {match.entry_name}/{match.relative_name}\n\n{match.path.read_text(errors='ignore')}"
        for match in files
    ]
    matched_names = sorted({match.entry_name for match in files})
    file_count = len(files)

    if not blocks:
        return ""

    header = (
        f"<!-- standards-loader: {file_count} file"
        f"{'' if file_count == 1 else 's'} from "
        f"{len(matched_names)} entr{'y' if len(matched_names) == 1 else 'ies'} "
        f"({', '.join(matched_names)}) -->"
    )
    return header + "\n\n" + "\n\n---\n\n".join(blocks)


def collect_matched_standards_index(cwd: Path | None = None) -> str:
    """Return a compact index of matched standards without injecting full content."""
    if cwd is None:
        cwd = Path.cwd()
    files = _matched_standard_files(cwd)
    if not files:
        return ""

    matched_names = sorted({match.entry_name for match in files})
    lines = [
        f"<!-- standards-loader: {len(files)} matched file"
        f"{'' if len(files) == 1 else 's'} from "
        f"{len(matched_names)} entr{'y' if len(matched_names) == 1 else 'ies'} "
        f"({', '.join(matched_names)}); full content not auto-injected -->",
        "",
        "Relevant standards are available on disk. Load only the specific file that directly applies to the current task:",
    ]
    for match in files:
        lines.append(f"- {match.entry_name}/{match.relative_name}: {match.path}")
    lines.append("")
    lines.append("Set STANDARDS_LOADER_MODE=full to inject full matched standard content.")
    return "\n".join(lines)


if __name__ == "__main__":
    # Dry-run / debug mode
    print(collect_matched_standards())
