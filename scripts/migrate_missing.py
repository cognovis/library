#!/usr/bin/env python3
"""
migrate_missing.py — CL-8vb: Migrate ~40 missing artefacts to cognovis/library-core.

Groups:
  A: beads-workflow plugin (15 skills, 10 agents, 5 hooks)
  B: 3 codex .toml bridges
  C: 5 plugin standards + 4 personal standards required by migrated skills
  D: 4 misc items (vision-review, infra-principles, nbj-audit, people-query)

Usage:
    python3 scripts/migrate_missing.py \
        --library-core /tmp/cognovis-library-core \
        --source /Users/malte/code/claude-code-plugins
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


# ---------------------------------------------------------------------------
# Artefact definitions
# ---------------------------------------------------------------------------

BEADS_WORKFLOW_SKILLS = [
    "bd-release-notes", "bead-metrics", "compound", "create", "epic-init",
    "factory-check", "impl", "intake", "plan", "refactor-note", "retro",
    "review-conventions", "wave-orchestrator", "wave-reviewer", "workplan",
]

BEADS_WORKFLOW_AGENTS = [
    "bead-orchestrator.md", "changelog-updater.md", "doc-changelog-updater.md",
    "feature-doc-updater.md", "plan-reviewer.md", "quick-fix.md",
    "review-agent.md", "verification-agent.md", "wave-monitor.md", "wave-orchestrator.md",
]

BEADS_WORKFLOW_HOOKS = [
    "bd-cache-invalidator.py", "feature-scenario-reminder.py",
    "pre-compact-state.py", "session-context.py", "session-end.py",
]

CODEX_TOML_BRIDGES = [
    "bead-orchestrator.toml", "session-close.toml", "wave-orchestrator.toml",
]

# (source_relative_to_claude_code_plugins, destination_filename_in_agents_standards)
STANDARDS = [
    (".claude/standards/workflow/adr-location.md", "adr-location.md"),
    (".claude/standards/dev-tools/execution-result-envelope.md", "execution-result-envelope.md"),
    (".claude/standards/integrations/open-brain-http-client.md", "open-brain-http-client.md"),
    (".claude/standards/dev-tools/python-default-bash-exception.md", "python-default-bash-exception.md"),
    (".claude/standards/dev-tools/script-first-rule.md", "script-first-rule.md"),
]

# Personal standards required by migrated skills (referenced via requires_standards: in SKILL.md).
# These live under ~/.claude/standards/, not under claude-code-plugins.
# Format: (absolute_source_path, destination_filename_in_agents_standards)
PERSONAL_STANDARDS = [
    ("/Users/malte/.claude/standards/workflow/english-only.md", "english-only.md"),
    ("/Users/malte/.claude/standards/dev-tools/tool-standards.md", "tool-standards.md"),
    ("/Users/malte/.claude/standards/workflow/no-emoji.md", "no-emoji.md"),
    ("/Users/malte/.claude/standards/healthcare/control-areas.md", "healthcare-control-areas.md"),
]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def copy_dir(src: Path, dst: Path, label: str = "") -> None:
    """Copy a directory recursively, removing dst first if it exists.

    Python bytecode artefacts (__pycache__, *.pyc, *.pyo) are never copied
    into library-core — they are machine-specific and must not be committed.
    """
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {src}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    print(f"  [dir]  {label or dst.name}: {src} -> {dst}")


def copy_file(src: Path, dst: Path, label: str = "") -> None:
    """Copy a single file, creating parent dirs as needed."""
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  [file] {label or dst.name}: {src} -> {dst}")


def make_symlink(link: Path, target_rel: str) -> None:
    """Create a relative symlink, removing existing link if needed."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(target_rel)
    print(f"  [symlink] {link} -> {target_rel}")


# ---------------------------------------------------------------------------
# Group A: beads-workflow plugin
# ---------------------------------------------------------------------------

def migrate_group_a(source: Path, library_core: Path) -> None:
    print("\n=== Group A: beads-workflow plugin ===")
    bw_src = source / "beads-workflow"
    bw_dst = library_core / "plugins" / "beads-workflow"
    bw_dst.mkdir(parents=True, exist_ok=True)

    # Skills
    skills_dst = bw_dst / "skills"
    skills_dst.mkdir(parents=True, exist_ok=True)
    for skill_name in BEADS_WORKFLOW_SKILLS:
        src = bw_src / "skills" / skill_name
        dst = skills_dst / skill_name
        copy_dir(src, dst, f"skill:{skill_name}")

    # Agents — plugin canonical + bridge copies
    agents_dst = bw_dst / "agents"
    agents_dst.mkdir(parents=True, exist_ok=True)
    claude_agents_dst = library_core / ".claude" / "agents"
    codex_agents_dst = library_core / ".codex" / "agents"
    claude_agents_dst.mkdir(parents=True, exist_ok=True)
    codex_agents_dst.mkdir(parents=True, exist_ok=True)

    for agent_name in BEADS_WORKFLOW_AGENTS:
        src = bw_src / "agents" / agent_name
        # plugin canonical
        copy_file(src, agents_dst / agent_name, f"plugin agent:{agent_name}")
        # bridge: .claude/agents/
        copy_file(src, claude_agents_dst / agent_name, f"  bridge .claude/agents:{agent_name}")
        # bridge: .codex/agents/
        copy_file(src, codex_agents_dst / agent_name, f"  bridge .codex/agents:{agent_name}")

    # Hooks + hooks.json
    hooks_dst = bw_dst / "hooks"
    hooks_dst.mkdir(parents=True, exist_ok=True)
    for hook_name in BEADS_WORKFLOW_HOOKS:
        src = bw_src / "hooks" / hook_name
        copy_file(src, hooks_dst / hook_name, f"hook:{hook_name}")
    # hooks.json
    copy_file(bw_src / "hooks" / "hooks.json", hooks_dst / "hooks.json", "hooks.json")


# ---------------------------------------------------------------------------
# Group B: codex .toml bridges
# ---------------------------------------------------------------------------

def migrate_group_b(source: Path, library_core: Path) -> None:
    print("\n=== Group B: codex .toml bridges ===")
    toml_src_dir = source / "dev-tools" / "codex-agents"
    codex_agents_dst = library_core / ".codex" / "agents"
    codex_agents_dst.mkdir(parents=True, exist_ok=True)

    for toml_name in CODEX_TOML_BRIDGES:
        src = toml_src_dir / toml_name
        copy_file(src, codex_agents_dst / toml_name, f"toml bridge:{toml_name}")


# ---------------------------------------------------------------------------
# Group C: 5 standards
# ---------------------------------------------------------------------------

def migrate_group_c(source: Path, library_core: Path) -> None:
    print("\n=== Group C: standards ===")
    standards_dst = library_core / ".agents" / "standards"
    standards_dst.mkdir(parents=True, exist_ok=True)

    for src_rel, dst_name in STANDARDS:
        src = source / src_rel
        copy_file(src, standards_dst / dst_name, f"standard:{dst_name}")

    # Personal standards required by migrated skills
    for src_abs, dst_name in PERSONAL_STANDARDS:
        copy_file(Path(src_abs), standards_dst / dst_name, f"personal-standard:{dst_name}")


# ---------------------------------------------------------------------------
# Group D: misc items
# ---------------------------------------------------------------------------

def migrate_group_d(source: Path, library_core: Path) -> None:
    print("\n=== Group D: misc items ===")

    # 1. vision-review skill -> architecture-trinity plugin
    vision_src = source / "meta" / "skills" / "vision-review"
    vision_dst = library_core / "plugins" / "architecture-trinity" / "skills" / "vision-review"
    copy_dir(vision_src, vision_dst, "vision-review")

    # 2. infra-principles skill
    infra_src = source / "infra" / "skills" / "infra-principles"
    infra_dst = library_core / ".claude" / "skills" / "infra-principles"
    copy_dir(infra_src, infra_dst, "infra-principles")
    # bridge symlink: .agents/skills/infra-principles -> ../../.claude/skills/infra-principles
    make_symlink(
        library_core / ".agents" / "skills" / "infra-principles",
        "../../.claude/skills/infra-principles",
    )

    # 3. nbj-audit skill
    nbj_src = source / "meta" / "skills" / "nbj-audit"
    nbj_dst = library_core / ".claude" / "skills" / "nbj-audit"
    copy_dir(nbj_src, nbj_dst, "nbj-audit")
    # bridge symlink: .agents/skills/nbj-audit -> ../../.claude/skills/nbj-audit
    make_symlink(
        library_core / ".agents" / "skills" / "nbj-audit",
        "../../.claude/skills/nbj-audit",
    )

    # 4. people-query skill
    people_query_src = Path("/Users/malte/.claude/skills/open-brain/people-query")
    people_query_dst = library_core / ".claude" / "skills" / "people-query"
    copy_dir(people_query_src, people_query_dst, "people-query")
    # bridge symlink: .agents/skills/people-query -> ../../.claude/skills/people-query
    make_symlink(
        library_core / ".agents" / "skills" / "people-query",
        "../../.claude/skills/people-query",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate ~40 missing artefacts to library-core (CL-8vb)")
    parser.add_argument("--library-core", default="/tmp/cognovis-library-core", type=Path)
    parser.add_argument("--source", default="/Users/malte/code/claude-code-plugins", type=Path)
    args = parser.parse_args()

    library_core: Path = args.library_core.resolve()
    source: Path = args.source.resolve()

    if not library_core.exists():
        raise SystemExit(f"ERROR: library-core not found at {library_core}")
    if not source.exists():
        raise SystemExit(f"ERROR: source plugins not found at {source}")

    print(f"Library-core: {library_core}")
    print(f"Source:       {source}")

    migrate_group_a(source, library_core)
    migrate_group_b(source, library_core)
    migrate_group_c(source, library_core)
    migrate_group_d(source, library_core)

    print("\nDone. All artefacts migrated.")


if __name__ == "__main__":
    main()
