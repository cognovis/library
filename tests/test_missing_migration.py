"""
test_missing_migration.py — Tests for CL-8vb: ~40 missing artefacts.
RED until migrate_missing.py is run.
"""
import os
from pathlib import Path
import pytest

LIBRARY_CORE = Path(os.environ.get("LIBRARY_CORE", "/tmp/cognovis-library-core"))
SOURCE = Path(os.environ.get("SOURCE_PLUGINS", "/Users/malte/code/claude-code-plugins"))
PEOPLE_QUERY_SOURCE = Path("/Users/malte/.claude/skills/open-brain/people-query")

BEADS_WORKFLOW_SKILLS = [
    "bd-release-notes", "bead-metrics", "compound", "create", "epic-init",
    "factory-check", "impl", "intake", "plan", "refactor-note", "retro",
    "review-conventions", "wave-orchestrator", "workplan"
]

BEADS_WORKFLOW_AGENTS = [
    "bead-orchestrator.md", "changelog-updater.md", "doc-changelog-updater.md",
    "feature-doc-updater.md", "plan-reviewer.md", "quick-fix.md",
    "review-agent.md", "verification-agent.md", "wave-monitor.md", "wave-orchestrator.md"
]

BEADS_WORKFLOW_HOOKS = [
    "bd-cache-invalidator.py", "feature-scenario-reminder.py",
    "pre-compact-state.py", "session-context.py", "session-end.py"
]

CODEX_TOML_BRIDGES = [
    "bead-orchestrator.toml", "session-close.toml", "wave-orchestrator.toml"
]

STANDARDS = [
    "adr-location.md", "execution-result-envelope.md", "open-brain-http-client.md",
    "python-default-bash-exception.md", "script-first-rule.md"
]


# ---------------------------------------------------------------------------
# Group A: beads-workflow plugin
# ---------------------------------------------------------------------------

class TestBeadsWorkflowPlugin:
    """Group A: beads-workflow plugin skills, agents, hooks."""

    def test_plugin_directory_exists(self):
        assert (LIBRARY_CORE / "plugins" / "beads-workflow").is_dir()

    @pytest.mark.parametrize("skill_name", BEADS_WORKFLOW_SKILLS)
    def test_skill_in_plugin(self, skill_name):
        skill_dir = LIBRARY_CORE / "plugins" / "beads-workflow" / "skills" / skill_name
        assert skill_dir.is_dir(), f"Missing skill dir: {skill_dir}"
        assert (skill_dir / "SKILL.md").exists(), f"Missing SKILL.md in: {skill_dir}"

    @pytest.mark.parametrize("agent_name", BEADS_WORKFLOW_AGENTS)
    def test_agent_in_plugin(self, agent_name):
        agent_path = LIBRARY_CORE / "plugins" / "beads-workflow" / "agents" / agent_name
        assert agent_path.exists(), f"Missing agent in plugin: {agent_path}"

    @pytest.mark.parametrize("agent_name", BEADS_WORKFLOW_AGENTS)
    def test_agent_in_claude_agents(self, agent_name):
        agent_path = LIBRARY_CORE / ".claude" / "agents" / agent_name
        assert agent_path.exists(), f"Missing bridge agent in .claude/agents/: {agent_path}"

    @pytest.mark.parametrize("agent_name", BEADS_WORKFLOW_AGENTS)
    def test_agent_in_codex_agents(self, agent_name):
        agent_path = LIBRARY_CORE / ".codex" / "agents" / agent_name
        assert agent_path.exists(), f"Missing bridge agent in .codex/agents/: {agent_path}"

    @pytest.mark.parametrize("hook_name", BEADS_WORKFLOW_HOOKS)
    def test_hook_in_plugin(self, hook_name):
        hook_path = LIBRARY_CORE / "plugins" / "beads-workflow" / "hooks" / hook_name
        assert hook_path.exists(), f"Missing hook: {hook_path}"

    def test_hooks_json_in_plugin(self):
        hooks_json = LIBRARY_CORE / "plugins" / "beads-workflow" / "hooks" / "hooks.json"
        assert hooks_json.exists(), f"Missing hooks.json: {hooks_json}"


# ---------------------------------------------------------------------------
# Group B: codex .toml bridges
# ---------------------------------------------------------------------------

class TestCodexTomlBridges:
    """Group B: 3 codex .toml bridges."""

    @pytest.mark.parametrize("toml_name", CODEX_TOML_BRIDGES)
    def test_toml_bridge_in_codex(self, toml_name):
        toml_path = LIBRARY_CORE / ".codex" / "agents" / toml_name
        assert toml_path.exists(), f"Missing .toml bridge: {toml_path}"


# ---------------------------------------------------------------------------
# Group C: 5 standards
# ---------------------------------------------------------------------------

class TestStandards:
    """Group C: 5 standards migrated to .agents/standards/."""

    def test_standards_directory_exists(self):
        assert (LIBRARY_CORE / ".agents" / "standards").is_dir()

    @pytest.mark.parametrize("std_name", STANDARDS)
    def test_standard_file(self, std_name):
        std_path = LIBRARY_CORE / ".agents" / "standards" / std_name
        assert std_path.exists(), f"Missing standard: {std_path}"


# ---------------------------------------------------------------------------
# Group D: misc items
# ---------------------------------------------------------------------------

class TestMiscItems:
    """Group D: 4 misc items."""

    def test_vision_review_skill_in_architecture_trinity(self):
        skill_dir = LIBRARY_CORE / "plugins" / "architecture-trinity" / "skills" / "vision-review"
        assert skill_dir.is_dir(), f"Missing vision-review dir: {skill_dir}"
        assert (skill_dir / "SKILL.md").exists(), f"Missing SKILL.md in vision-review"

    def test_infra_principles_skill_in_claude_skills(self):
        skill_dir = LIBRARY_CORE / ".claude" / "skills" / "infra-principles"
        assert skill_dir.is_dir(), f"Missing infra-principles dir: {skill_dir}"
        assert (skill_dir / "SKILL.md").exists(), f"Missing SKILL.md in infra-principles"

    def test_infra_principles_bridge_symlink(self):
        bridge = LIBRARY_CORE / ".agents" / "skills" / "infra-principles"
        assert bridge.exists(), f"Missing infra-principles bridge: {bridge}"

    def test_nbj_audit_skill_in_claude_skills(self):
        skill_dir = LIBRARY_CORE / ".claude" / "skills" / "nbj-audit"
        assert skill_dir.is_dir(), f"Missing nbj-audit dir: {skill_dir}"
        assert (skill_dir / "SKILL.md").exists(), f"Missing SKILL.md in nbj-audit"

    def test_nbj_audit_bridge_symlink(self):
        bridge = LIBRARY_CORE / ".agents" / "skills" / "nbj-audit"
        assert bridge.exists(), f"Missing nbj-audit bridge: {bridge}"

    def test_people_query_skill_in_claude_skills(self):
        skill_dir = LIBRARY_CORE / ".claude" / "skills" / "people-query"
        assert skill_dir.is_dir(), f"Missing people-query dir: {skill_dir}"
        assert (skill_dir / "SKILL.md").exists(), f"Missing SKILL.md in people-query"

    def test_people_query_bridge_symlink(self):
        bridge = LIBRARY_CORE / ".agents" / "skills" / "people-query"
        assert bridge.exists(), f"Missing people-query bridge: {bridge}"


# ---------------------------------------------------------------------------
# Frontmatter / description checks (AK2)
# ---------------------------------------------------------------------------

class TestFrontmatter:
    """AK2: All SKILL.md files have a description: line."""

    def _get_all_skill_mds(self):
        paths = []
        # beads-workflow skills
        for skill_name in BEADS_WORKFLOW_SKILLS:
            p = LIBRARY_CORE / "plugins" / "beads-workflow" / "skills" / skill_name / "SKILL.md"
            if p.exists():
                paths.append(p)
        # vision-review
        p = LIBRARY_CORE / "plugins" / "architecture-trinity" / "skills" / "vision-review" / "SKILL.md"
        if p.exists():
            paths.append(p)
        # infra-principles, nbj-audit, people-query
        for name in ["infra-principles", "nbj-audit", "people-query"]:
            p = LIBRARY_CORE / ".claude" / "skills" / name / "SKILL.md"
            if p.exists():
                paths.append(p)
        return paths

    def test_all_skill_mds_have_description(self):
        skill_mds = self._get_all_skill_mds()
        missing = []
        for p in skill_mds:
            content = p.read_text()
            if "description:" not in content:
                missing.append(str(p))
        assert not missing, f"Missing 'description:' in:\n" + "\n".join(missing)
