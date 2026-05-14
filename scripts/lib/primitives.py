"""
primitives.py — Primitive registry and metadata.

Defines the canonical set of supported primitives, their library.yaml section
mappings, and associated metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PrimitiveInfo:
    """Metadata for a supported library primitive."""

    name: str
    """Canonical primitive name (e.g. 'skill', 'model-standard')."""

    yaml_section: str
    """Top-level or nested key in library.yaml (e.g. 'library.skills', 'guardrails')."""

    yaml_key: str
    """The actual dict key chain to look up in the loaded YAML.

    For nested sections (library.X): 'library/<X>'
    For top-level sections: '<key>'
    """

    description: str
    """Human-readable description of this primitive type."""

    aliases: list[str] = field(default_factory=list)
    """Alternative names accepted on the CLI."""

    install_subdir: Optional[str] = None
    """Default subdirectory name under default_dirs entry for this primitive."""


# Registry of all supported primitives in canonical order.
PRIMITIVES: list[PrimitiveInfo] = [
    PrimitiveInfo(
        name="skill",
        yaml_section="library.skills",
        yaml_key="library/skills",
        description="Chat skills loaded from ~/.claude/skills/ or .claude/skills/",
        install_subdir="skills",
    ),
    PrimitiveInfo(
        name="agent",
        yaml_section="library.agents",
        yaml_key="library/agents",
        description="Subagent definitions deployed to ~/.claude/agents/",
        install_subdir="agents",
    ),
    PrimitiveInfo(
        name="prompt",
        yaml_section="library.prompts",
        yaml_key="library/prompts",
        description="Slash commands deployed to ~/.claude/commands/",
        install_subdir="prompts",
    ),
    PrimitiveInfo(
        name="script",
        yaml_section="library.scripts",
        yaml_key="library/scripts",
        description="First-class Python helper scripts deployed to .agents/scripts/",
        install_subdir="scripts",
    ),
    PrimitiveInfo(
        name="standard",
        yaml_section="library.standards",
        yaml_key="library/standards",
        description="Standards documents injected into AGENTS.md",
        install_subdir="standards",
    ),
    PrimitiveInfo(
        name="guardrail",
        yaml_section="guardrails",
        yaml_key="guardrails",
        description="Pre/PostToolUse hooks and permission rules",
        install_subdir="guardrails",
    ),
    PrimitiveInfo(
        name="mcp",
        yaml_section="mcp_servers",
        yaml_key="mcp_servers",
        description="MCP server configurations for Claude/Codex/OpenCode",
        install_subdir=None,  # handled by install-mcp.py
    ),
    PrimitiveInfo(
        name="model-standard",
        yaml_section="model_standards",
        yaml_key="model_standards",
        description="Model-specific behavioral standards (Layer 3 composition)",
        aliases=["model_standard"],
        install_subdir="model-standards",
    ),
    PrimitiveInfo(
        name="golden-prompt",
        yaml_section="golden_prompts",
        yaml_key="golden_prompts",
        description="Golden prompt base layers for agent composition (Layer 1)",
        aliases=["golden_prompt"],
        install_subdir="golden-prompts",
    ),
]

# Lookup tables
_BY_NAME: dict[str, PrimitiveInfo] = {p.name: p for p in PRIMITIVES}
_BY_ALIAS: dict[str, PrimitiveInfo] = {}
for _p in PRIMITIVES:
    for _alias in _p.aliases:
        _BY_ALIAS[_alias] = _p


def get_primitive(name: str) -> Optional[PrimitiveInfo]:
    """Return primitive info by name or alias. Returns None if not found."""
    return _BY_NAME.get(name) or _BY_ALIAS.get(name)


def all_primitive_names() -> list[str]:
    """Return all canonical primitive names."""
    return [p.name for p in PRIMITIVES]


def resolve_yaml_section(data: dict, primitive: PrimitiveInfo) -> list[dict]:
    """Extract the list of entries for this primitive from parsed library.yaml data.

    Returns an empty list if the section is absent or empty.
    """
    key = primitive.yaml_key
    if "/" in key:
        # Nested: e.g. 'library/skills' -> data['library']['skills']
        parts = key.split("/", 1)
        section = data.get(parts[0], {}) or {}
        entries = section.get(parts[1], []) or []
    else:
        # Top-level: e.g. 'guardrails' -> data['guardrails']
        entries = data.get(key, []) or []

    return entries if isinstance(entries, list) else []
