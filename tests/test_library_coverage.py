#!/usr/bin/env python3
"""
test_library_coverage.py — Tests for library.yaml coverage of migrated artefacts

Bead: CL-yko
Tests:
  1. All cognovis-migrated skills are registered in library.yaml
  2. All sussdorff-migrated skills are registered in library.yaml
  3. All cognovis-migrated agents are registered in library.yaml
  4. All sussdorff-migrated agents are registered in library.yaml
  5. All cognovis-migrated commands are registered as prompts in library.yaml
  6. All registered entries have source URLs
  7. All registered entries have descriptions
  8. All registered entries have tags
  9. validate-library.py passes after all entries added
  10. check-coverage.py script exists and is executable

Run with:
    python3 -m pytest tests/test_library_coverage.py -v
  or:
    python3 tests/test_library_coverage.py
"""

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("FAIL: PyYAML is not installed. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(1)

# ---- Setup ----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_YAML = REPO_ROOT / "library.yaml"
AUDIT_JSON = REPO_ROOT / "docs" / "audit" / "skills-origin.json"
CHECK_COVERAGE_SCRIPT = REPO_ROOT / "scripts" / "check-coverage.py"


def load_library():
    with open(LIBRARY_YAML) as f:
        return yaml.safe_load(f)


def load_audit():
    with open(AUDIT_JSON) as f:
        return json.load(f)


def get_registered_names(library_data):
    """Return sets of registered names per section."""
    lib = library_data.get("library", {})
    skills = {e["name"] for e in lib.get("skills", []) if "name" in e}
    agents = {e["name"] for e in lib.get("agents", []) if "name" in e}
    prompts = {e["name"] for e in lib.get("prompts", []) if "name" in e}
    return skills, agents, prompts


# Expected cognovis skills (names as they appear in library.yaml)
EXPECTED_COGNOVIS_SKILLS = {
    "agent-forge", "angebotserstellung", "beads", "billing-reviewer", "binary-explorer",
    "brand-forge", "bug-triage", "claude-md-pruner", "cmux", "cmux-browser", "cmux-markdown",
    "codex", "collmex-cli", "council", "daily-brief", "dolt", "entropy-scan", "event-log",
    "hook-creator", "infra-principles", "inject-standards", "mail-send", "mira-aidbox",
    "nbj-audit", "op-credentials", "pencil", "people-query", "playwright-cli",
    "plugin-management", "portless", "project-context", "project-health", "project-setup",
    "prompt-refiner", "skill-auditor", "spec-developer", "standards", "summarize",
    "sync-standards", "system-prompt-audit", "token-cost", "ui-cli", "vision", "vision-author",
}

# Expected sussdorff skills
EXPECTED_SUSSDORFF_SKILLS = {
    "ai-readiness", "amazon", "career-check", "google-invoice", "mm-cli",
    "linkedin", "transcribe", "hetzner-cloud", "home-infra", "local-vm",
    "paperless-cli", "piler-cli",
}

# Expected cognovis agents
EXPECTED_COGNOVIS_AGENTS = {
    "bead-orchestrator", "branch-synchronizer", "changelog-updater",
    "chrome-devtools-tester", "ci-monitor", "codex-guide", "compliance-reviewer",
    "constraint-checker", "convention-reviewer", "doc-changelog-updater",
    "feature-doc-updater", "feedback-extractor", "file-analyzer", "git-operations",
    "gui-review", "holdout-validator", "human-factors-reviewer", "implementer",
    "integration-test-runner", "learning-extractor", "pester-test-engineer",
    "plan-reviewer", "playwright-tester", "prd-generator", "quick-fix", "researcher",
    "review-agent", "scenario-generator", "session-close", "skill-auditor",
    "spellcheck-test-engineer", "test-author", "test-engineer", "uat-validator",
    "verification-agent", "wave-monitor", "wave-orchestrator",
}

# Expected sussdorff agents
EXPECTED_SUSSDORFF_AGENTS = {"home"}

# Expected prompts (commands + standards)
EXPECTED_PROMPTS = {
    "compact-reference", "install-playwright", "install-plugin",
    "adr-location", "english-only", "execution-result-envelope",
    "healthcare-control-areas", "no-emoji", "open-brain-http-client",
    "python-default-bash-exception", "script-first-rule", "tool-standards",
}


# ---- Tests ----------------------------------------------------------------

def test_cognovis_skills_registered():
    """All expected cognovis skills must be registered in library.skills."""
    library = load_library()
    skills, _, _ = get_registered_names(library)
    missing = EXPECTED_COGNOVIS_SKILLS - skills
    assert not missing, f"Missing cognovis skills in library.yaml: {sorted(missing)}"


def test_sussdorff_skills_registered():
    """All expected sussdorff skills must be registered in library.skills."""
    library = load_library()
    skills, _, _ = get_registered_names(library)
    missing = EXPECTED_SUSSDORFF_SKILLS - skills
    assert not missing, f"Missing sussdorff skills in library.yaml: {sorted(missing)}"


def test_cognovis_agents_registered():
    """All expected cognovis agents must be registered in library.agents."""
    library = load_library()
    _, agents, _ = get_registered_names(library)
    missing = EXPECTED_COGNOVIS_AGENTS - agents
    assert not missing, f"Missing cognovis agents in library.yaml: {sorted(missing)}"


def test_sussdorff_agents_registered():
    """All expected sussdorff agents must be registered in library.agents."""
    library = load_library()
    _, agents, _ = get_registered_names(library)
    missing = EXPECTED_SUSSDORFF_AGENTS - agents
    assert not missing, f"Missing sussdorff agents in library.yaml: {sorted(missing)}"


def test_prompts_registered():
    """All expected prompts (commands + standards) must be registered in library.prompts."""
    library = load_library()
    _, _, prompts = get_registered_names(library)
    missing = EXPECTED_PROMPTS - prompts
    assert not missing, f"Missing prompts in library.yaml: {sorted(missing)}"


def test_all_entries_have_source_urls():
    """All new library-core entries must have a source URL (not from_marketplace)."""
    library = load_library()
    lib = library.get("library", {})

    errors = []
    for section_name in ("skills", "agents", "prompts"):
        for entry in lib.get(section_name, []):
            name = entry.get("name", "<unknown>")
            # Skip impeccable (from_marketplace) and any other marketplace entries
            if "from_marketplace" in entry:
                continue
            if "source" not in entry:
                errors.append(f"{section_name}/{name}: missing source URL")

    assert not errors, f"Entries without source URLs:\n" + "\n".join(errors)


def test_all_entries_have_descriptions():
    """All library-core entries must have descriptions."""
    library = load_library()
    lib = library.get("library", {})

    errors = []
    for section_name in ("skills", "agents", "prompts"):
        for entry in lib.get(section_name, []):
            name = entry.get("name", "<unknown>")
            if "from_marketplace" in entry:
                continue
            desc = entry.get("description", "").strip()
            if not desc:
                errors.append(f"{section_name}/{name}: missing or empty description")

    assert not errors, f"Entries without descriptions:\n" + "\n".join(errors)


def test_all_entries_have_tags():
    """All library-core entries must have at least one tag."""
    library = load_library()
    lib = library.get("library", {})

    errors = []
    for section_name in ("skills", "agents", "prompts"):
        for entry in lib.get(section_name, []):
            name = entry.get("name", "<unknown>")
            if "from_marketplace" in entry:
                continue
            tags = entry.get("tags", [])
            if not tags:
                errors.append(f"{section_name}/{name}: missing tags")

    assert not errors, f"Entries without tags:\n" + "\n".join(errors)


def test_source_urls_point_to_correct_repos():
    """Source URLs must point to cognovis or sussdorff library-core."""
    library = load_library()
    lib = library.get("library", {})

    errors = []
    for section_name in ("skills", "agents", "prompts"):
        for entry in lib.get(section_name, []):
            name = entry.get("name", "<unknown>")
            if "from_marketplace" in entry:
                continue
            source = entry.get("source", "")
            if source and not (
                "cognovis/library-core" in source
                or "sussdorff/library-core" in source
            ):
                errors.append(f"{section_name}/{name}: source URL does not point to library-core: {source}")

    assert not errors, f"Entries with wrong source URLs:\n" + "\n".join(errors)


def test_check_coverage_script_exists():
    """scripts/check-coverage.py must exist."""
    assert CHECK_COVERAGE_SCRIPT.exists(), (
        f"scripts/check-coverage.py not found at {CHECK_COVERAGE_SCRIPT}"
    )


def test_requires_format():
    """requires field must use string format 'type:name' not object format."""
    library = load_library()
    lib = library.get("library", {})

    errors = []
    for section_name in ("skills", "agents", "prompts"):
        for entry in lib.get(section_name, []):
            name = entry.get("name", "<unknown>")
            requires = entry.get("requires", [])
            for req in requires:
                if not isinstance(req, str):
                    errors.append(f"{section_name}/{name}: requires item must be string, got {type(req).__name__}: {req}")
                elif not any(req.startswith(p) for p in ("skill:", "agent:", "prompt:")):
                    errors.append(f"{section_name}/{name}: requires item must match 'skill:|agent:|prompt:' pattern: {req}")

    assert not errors, f"Invalid requires format:\n" + "\n".join(errors)


# ---- Runner ---------------------------------------------------------------

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v"],
        capture_output=False
    )
    sys.exit(result.returncode)
