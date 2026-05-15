#!/usr/bin/env python3
"""
compose-agent.py — Compose a three-layer agent prompt at install time.

Implements layered agent prompt composition (Part C of bead CL-08n).

Algorithm:
  1. Parse YAML frontmatter from the agent file.
  2. Resolve Layer 1 (golden_prompt_extends):
       - "cognovis-base" (or any name): load from golden-prompts dir; extract body.
       - "from-scratch": skip Layer 1.
  3. Read agent body (Layer 2): everything after the closing --- in the agent file.
  4. Resolve Layer 3 (model_standards list + model: field alias lookup):
       - Load each named standard from model-standards dir; extract body.
       - Concatenate in declared order.
  5. Concatenate layers with section separator markers.
  6. For --harness=codex: escape result for TOML triple-quoted string embedding.
  7. Emit composed body on stdout.
  8. Exit non-zero if a required layer is missing.

Usage:
  compose-agent.py <agent-file> [--harness=claude|codex|opencode]

Environment variables (for testing / overrides):
  GOLDEN_PROMPTS_DIR   — Override the golden-prompts search directory.
  MODEL_STANDARDS_DIR  — Override the model-standards search directory.

Exit codes:
  0 — Composition succeeded; composed body on stdout.
  1 — Missing required layer (Layer 1 base not found when golden_prompt_extends
      is not from-scratch); error details on stderr.
  2 — Invalid arguments or unreadable agent file.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(2)

# ---------------------------------------------------------------------------
# Separator strings (deterministic — do NOT change without updating tests)
# ---------------------------------------------------------------------------
SEP_PERSONA = "--- AGENT PERSONA ---"
SEP_MODEL_STANDARD = "--- MODEL STANDARD ---"
CLAUDE_FRONTMATTER_EXCLUDE = {
    "cache_control",
    "golden_prompt_extends",
    "model_standards",
    "requires",
}


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter delimited by '---' lines.

    Returns (frontmatter_dict, body_text).
    Body is everything after the closing --- delimiter.
    If no frontmatter is found, returns ({}, text).
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    # Find closing ---
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            fm_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1:])
            fm = yaml.safe_load(fm_text) or {}
            return fm, body.lstrip("\n")

    # No closing --- found — treat whole file as body
    return {}, text


def extract_body(file_path: Path) -> str:
    """Read a file and return just the body (after frontmatter)."""
    text = file_path.read_text(encoding="utf-8")
    _, body = parse_frontmatter(text)
    return body.strip()


def format_claude_frontmatter(frontmatter: dict[str, Any]) -> str:
    """Serialize runtime frontmatter for Claude agent files."""
    runtime_frontmatter = {
        key: value
        for key, value in frontmatter.items()
        if key not in CLAUDE_FRONTMATTER_EXCLUDE
    }
    if not runtime_frontmatter:
        return ""

    serialized = yaml.safe_dump(
        runtime_frontmatter,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{serialized}\n---\n\n"


# ---------------------------------------------------------------------------
# Layer resolution
# ---------------------------------------------------------------------------

def _find_in_dir(name: str, search_dir: Path) -> Path | None:
    """Look for <name>.md in search_dir; also check aliases via frontmatter scan."""
    # Exact filename match
    exact = search_dir / f"{name}.md"
    if exact.exists():
        return exact

    # Alias scan: check all .md files for model_aliases frontmatter
    if search_dir.is_dir():
        for candidate in search_dir.glob("*.md"):
            try:
                text = candidate.read_text(encoding="utf-8")
                fm, _ = parse_frontmatter(text)
                aliases = fm.get("model_aliases", [])
                if isinstance(aliases, list) and name in aliases:
                    return candidate
            except (OSError, yaml.YAMLError):
                continue
    return None


def resolve_layer1(name: str, proj_root: Path, override_dir: str | None = None) -> Path | None:
    """Resolve golden-prompt Layer 1 file.

    Search order (when no override_dir):
      1. <proj_root>/.agents/golden-prompts/<name>.md
      2. ~/.agents/golden-prompts/<name>.md

    When override_dir is provided (e.g. via GOLDEN_PROMPTS_DIR env var),
    ONLY that directory is searched — no fallback. This enables test isolation.
    """
    if override_dir:
        result = _find_in_dir(name, Path(override_dir).expanduser())
        return result

    search_dirs: list[Path] = [
        proj_root / ".agents" / "golden-prompts",
        Path.home() / ".agents" / "golden-prompts",
    ]
    for d in search_dirs:
        result = _find_in_dir(name, d)
        if result:
            return result
    return None


def resolve_layer3(name: str, proj_root: Path, override_dir: str | None = None) -> Path | None:
    """Resolve model-standard Layer 3 file.

    Search order (when no override_dir):
      1. <proj_root>/.agents/model-standards/<name>.md (+ alias scan)
      2. ~/.agents/model-standards/<name>.md (+ alias scan)

    When override_dir is provided (e.g. via MODEL_STANDARDS_DIR env var),
    ONLY that directory is searched — no fallback. This enables test isolation.
    """
    if override_dir:
        result = _find_in_dir(name, Path(override_dir).expanduser())
        return result

    search_dirs: list[Path] = [
        proj_root / ".agents" / "model-standards",
        Path.home() / ".agents" / "model-standards",
    ]
    for d in search_dirs:
        result = _find_in_dir(name, d)
        if result:
            return result
    return None


# ---------------------------------------------------------------------------
# TOML escaping
# ---------------------------------------------------------------------------

def escape_for_toml(text: str) -> str:
    """Escape a string for safe embedding inside a TOML literal (triple-quoted) string.

    TOML basic strings use double quotes; triple-quoted basic strings are delimited
    by '''. We escape any sequence of three or more single-quotes by inserting a
    zero-width no-break space (U+FEFF) — but since we cannot inject invisible chars
    into a terminal, we instead break the triple-quote sequence by escaping with
    backslash continuation: ''' -> \\''' is not valid TOML; the safest approach is
    to replace ''' with '' + ' (split across multiple literal string chunks).

    For practical purposes in TOML developer_instructions fields, we:
      1. Replace literal ''' (three single-quotes) with '\\'''  which is not valid.
      Instead we replace ''' -> '' + single-quote which is just ''' but that's the
      same problem.

    The actual safe approach: TOML multi-line BASIC strings use triple double-quotes
    (\"\"\"...\"\"\"). For developer_instructions we escape backslashes and double-quotes.
    """
    # Escape backslashes first (must be first to avoid double-escaping)
    text = text.replace("\\", "\\\\")
    # Escape double quotes
    text = text.replace('"', '\\"')
    # Break any triple-double-quote sequences that could terminate the string
    text = text.replace('\\"\\"\\"', '\\"\\"\\" \\"\\"')
    # Also handle raw triple single-quotes (TOML literal strings)
    # Replace ''' with '' + \' — not standard but prevents literal TOML breakage
    text = text.replace("'''", "''\\''")
    return text


# ---------------------------------------------------------------------------
# Main composition logic
# ---------------------------------------------------------------------------

def compose(
    agent_file: Path,
    harness: str = "claude",
    golden_prompts_dir: str | None = None,
    model_standards_dir: str | None = None,
) -> str:
    """Compose the three-layer agent prompt.

    Returns the composed body as a string.
    Raises SystemExit(1) if a required layer cannot be resolved.
    """
    if not agent_file.exists():
        print(f"ERROR: Agent file not found: {agent_file}", file=sys.stderr)
        sys.exit(2)

    agent_text = agent_file.read_text(encoding="utf-8")
    fm, layer2_body = parse_frontmatter(agent_text)
    layer2_body = layer2_body.strip()

    # Determine proj_root for layer resolution (directory containing the agent file,
    # or climb to find a directory containing .agents/)
    proj_root = _find_proj_root(agent_file)

    # ---------------------------------------------------------------------------
    # Layer 1: golden_prompt_extends
    # ---------------------------------------------------------------------------
    golden_prompt_extends = fm.get("golden_prompt_extends", "")
    layer1_body: str | None = None

    if golden_prompt_extends and golden_prompt_extends != "from-scratch":
        layer1_path = resolve_layer1(
            golden_prompt_extends,
            proj_root,
            override_dir=golden_prompts_dir or os.environ.get("GOLDEN_PROMPTS_DIR"),
        )
        if layer1_path is None:
            print(
                f"ERROR: golden_prompt '{golden_prompt_extends}' not found.\n"
                f"  Searched: {proj_root / '.agents' / 'golden-prompts'} and "
                f"{Path.home() / '.agents' / 'golden-prompts'}\n"
                f"  Install it first: /library use {golden_prompt_extends}",
                file=sys.stderr,
            )
            sys.exit(1)
        layer1_body = extract_body(layer1_path)

    # ---------------------------------------------------------------------------
    # Layer 3: model_standards + model: alias
    # ---------------------------------------------------------------------------
    model_standards_names: list[str] = []

    # Explicit model_standards list
    explicit_standards = fm.get("model_standards", [])
    if isinstance(explicit_standards, list):
        model_standards_names.extend(explicit_standards)

    # Auto-lookup from model: field (only if not already in the explicit list)
    model_field = fm.get("model", "")
    if model_field and model_field not in model_standards_names:
        # Check if the model field resolves to a known standard
        override = model_standards_dir or os.environ.get("MODEL_STANDARDS_DIR")
        resolved = resolve_layer3(model_field, proj_root, override_dir=override)
        if resolved:
            # Prepend the model: field standard (it's the primary model standard)
            model_standards_names.insert(0, model_field)

    layer3_bodies: list[str] = []
    for std_name in model_standards_names:
        override = model_standards_dir or os.environ.get("MODEL_STANDARDS_DIR")
        std_path = resolve_layer3(std_name, proj_root, override_dir=override)
        if std_path:
            body = extract_body(std_path)
            if body:
                layer3_bodies.append(body)
        # Missing model standards are silently skipped (warn-and-continue per loader contract)

    # ---------------------------------------------------------------------------
    # Concatenation
    # ---------------------------------------------------------------------------
    parts: list[str] = []

    if layer1_body:
        parts.append(layer1_body)

    parts.append(f"{SEP_PERSONA}\n\n{layer2_body}")

    if layer3_bodies:
        layer3_combined = "\n\n".join(layer3_bodies)
        parts.append(f"{SEP_MODEL_STANDARD}\n\n{layer3_combined}")

    composed = "\n\n".join(parts)

    # ---------------------------------------------------------------------------
    # Harness-specific output transformation
    # ---------------------------------------------------------------------------
    if harness == "codex":
        composed = escape_for_toml(composed)
    elif harness == "claude":
        composed = f"{format_claude_frontmatter(fm)}{composed}"

    return composed


def _find_proj_root(agent_file: Path) -> Path:
    """Walk up from agent_file to find a directory containing .agents/.

    Falls back to the agent file's directory if not found.
    """
    current = agent_file.parent
    while current != current.parent:
        if (current / ".agents").is_dir():
            return current
        current = current.parent
    return agent_file.parent


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compose a three-layer agent prompt (Layer 1 + Layer 2 + Layer 3).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("agent_file", type=Path, help="Path to the agent .md file.")
    parser.add_argument(
        "--harness",
        choices=["claude", "codex", "opencode"],
        default="claude",
        help="Target harness (default: claude). 'codex' escapes output for TOML embedding.",
    )
    parser.add_argument(
        "--golden-prompts-dir",
        default=None,
        help="Override the golden-prompts search directory.",
    )
    parser.add_argument(
        "--model-standards-dir",
        default=None,
        help="Override the model-standards search directory.",
    )

    args = parser.parse_args()

    composed = compose(
        agent_file=args.agent_file,
        harness=args.harness,
        golden_prompts_dir=args.golden_prompts_dir,
        model_standards_dir=args.model_standards_dir,
    )
    print(composed, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
