#!/usr/bin/env python3
"""
test_compose_agent.py — Unit tests for scripts/compose-agent.py

Bead: CL-08n
Tests:
  1. Compose agent with agent_base: auto — Layer1+Layer2 in output
  2. Compose agent with model_standards: [claude-sonnet-4-6] — Layer3 appended
  3. from-scratch → no Layer 1 in output
  4. empty model_standards: [] and no model: field → no Layer 3
  5. --harness=codex produces TOML-safe output (no raw triple-quotes breaking TOML)
  6. Composer exits non-zero when agent_base base is missing
  7. Layer separators are present in composed output

Run with:
    python3 -m pytest tests/compose/test_compose_agent.py -v
  or:
    python3 tests/compose/test_compose_agent.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COMPOSE_SCRIPT = REPO_ROOT / "scripts" / "compose-agent.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def run_compose(
    agent_file: Path,
    base_dir: Path | None,
    model_standard_dir: Path | None = None,
    harness: str | None = None,
    expect_success: bool = True,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run compose-agent.py against agent_file with given base dirs.

    Returns (returncode, stdout, stderr).
    """
    env = os.environ.copy()
    if base_dir is not None:
        env["AGENT_BASES_DIR"] = str(base_dir)
    else:
        env.pop("AGENT_BASES_DIR", None)
    if model_standard_dir:
        env["MODEL_STANDARDS_DIR"] = str(model_standard_dir)
    if extra_env:
        env.update(extra_env)

    cmd = [sys.executable, str(COMPOSE_SCRIPT), str(agent_file)]
    if harness:
        cmd.append(f"--harness={harness}")

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def make_base_dir(tmp_path: Path) -> Path:
    """Create a temp agent-bases dir with the test fixture base."""
    base_dir = tmp_path / "agent-bases"
    base_dir.mkdir()
    fixture_base = FIXTURES_DIR / "base-cognovis-base.md"
    (base_dir / "cognovis-base.md").write_text(fixture_base.read_text())
    return base_dir


def make_per_harness_base_dir(tmp_path: Path) -> Path:
    """Create a temp agent-bases dir with per-harness test fixture bases."""
    base_dir = tmp_path / "agent-bases"
    base_dir.mkdir()
    fixtures = {
        "claude-agent-base.md": FIXTURES_DIR / "base-claude-agent-base.md",
        "codex-agent-base.md": FIXTURES_DIR / "base-codex-agent-base.md",
    }
    for filename, fixture in fixtures.items():
        (base_dir / filename).write_text(fixture.read_text())
    return base_dir


def make_model_standard_dir(tmp_path: Path) -> Path:
    """Create a temp model-standards dir with the test fixture standard."""
    std_dir = tmp_path / "model-standards"
    std_dir.mkdir()
    fixture_std = FIXTURES_DIR / "model-standard-claude-sonnet-4-6.md"
    (std_dir / "claude-sonnet-4-6.md").write_text(fixture_std.read_text())
    return std_dir


def make_agent_with_runtime_frontmatter(tmp_path: Path) -> Path:
    """Create an agent fixture that includes runtime and composer frontmatter."""
    agent_file = tmp_path / "agent-with-runtime-frontmatter.md"
    agent_file.write_text(
        """---
name: frontmatter-agent
description: Agent with runtime frontmatter
tools: [Read, Bash]
model: claude-sonnet-4-6
mcpServers:
  open-brain:
    command: ob
permissionMode: acceptEdits
agent_base: auto
model_standards: [claude-sonnet-4-6]
cache_control: ephemeral
requires:
  - private-field
---

# Frontmatter Agent

This agent verifies runtime frontmatter emission.
"""
    )
    return agent_file


def make_agent_with_legacy_frontmatter(tmp_path: Path) -> Path:
    """Create an agent fixture that uses the one-release frontmatter alias."""
    agent_file = tmp_path / "agent-with-legacy-frontmatter.md"
    agent_file.write_text(
        """---
name: legacy-frontmatter-agent
description: Agent with legacy composer frontmatter
golden_prompt_extends: cognovis-base
model_standards: []
---

# Legacy Frontmatter Agent

This agent verifies the legacy frontmatter alias.
"""
    )
    return agent_file


def make_agent_with_legacy_agent_base_extends(tmp_path: Path) -> Path:
    """Create an agent fixture that uses the legacy agent_base_extends field."""
    agent_file = tmp_path / "agent-with-legacy-agent-base-extends.md"
    agent_file.write_text(
        """---
name: legacy-agent-base-agent
description: Agent with legacy agent base frontmatter
agent_base_extends: cognovis-base
model_standards: []
---

# Legacy Agent Base Agent

This agent verifies the legacy agent_base_extends field.
"""
    )
    return agent_file


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_compose_with_base_contains_layer1(tmp_path):
    """Composing an agent that extends cognovis-base includes Layer 1 marker."""
    base_dir = make_base_dir(tmp_path)
    agent_file = FIXTURES_DIR / "agent-with-base.md"

    rc, stdout, stderr = run_compose(agent_file, base_dir)
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert "COGNOVIS_BASE_LAYER1_MARKER" in stdout, (
        f"Layer 1 marker not found in output.\nstdout: {stdout}\nstderr: {stderr}"
    )
    print("PASS test_compose_with_base_contains_layer1")


def test_compose_accepts_legacy_frontmatter_alias(tmp_path):
    """golden_prompt_extends remains accepted as a one-release frontmatter alias."""
    base_dir = make_base_dir(tmp_path)
    agent_file = make_agent_with_legacy_frontmatter(tmp_path)

    rc, stdout, stderr = run_compose(agent_file, base_dir)
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert "COGNOVIS_BASE_LAYER1_MARKER" in stdout, (
        f"Layer 1 marker not found for legacy alias.\nstdout: {stdout}\nstderr: {stderr}"
    )
    assert "Legacy Frontmatter Agent" in stdout, (
        f"Layer 2 body not found for legacy alias.\nstdout: {stdout}\nstderr: {stderr}"
    )
    assert (
        "DeprecationWarning: golden_prompt_extends is deprecated; "
        "use agent_base."
    ) in stderr
    print("PASS test_compose_accepts_legacy_frontmatter_alias")


def test_compose_accepts_legacy_agent_base_extends(tmp_path):
    """agent_base_extends remains accepted as a compatibility alias."""
    base_dir = make_base_dir(tmp_path)
    agent_file = make_agent_with_legacy_agent_base_extends(tmp_path)

    rc, stdout, stderr = run_compose(agent_file, base_dir)
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert "COGNOVIS_BASE_LAYER1_MARKER" in stdout
    assert "Legacy Agent Base Agent" in stdout
    print("PASS test_compose_accepts_legacy_agent_base_extends")


def test_compose_finds_legacy_global_agent_base_dir(tmp_path):
    """Composer finds a Layer 1 base when only ~/.agents/golden-prompts exists."""
    home = tmp_path / "home"
    legacy_dir = home / ".agents" / "golden-prompts"
    legacy_dir.mkdir(parents=True)
    fixture_base = FIXTURES_DIR / "base-cognovis-base.md"
    (legacy_dir / "cognovis-base.md").write_text(fixture_base.read_text())
    agent_file = FIXTURES_DIR / "agent-with-base.md"

    rc, stdout, stderr = run_compose(
        agent_file,
        None,
        extra_env={"HOME": str(home)},
    )
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert "COGNOVIS_BASE_LAYER1_MARKER" in stdout, (
        f"Layer 1 marker not found from legacy global dir.\nstdout: {stdout}\nstderr: {stderr}"
    )
    assert (
        "DeprecationWarning: agent_base 'auto' resolved "
        "from legacy golden-prompts directory"
    ) in stderr
    print("PASS test_compose_finds_legacy_global_agent_base_dir")


def test_compose_dispatches_cognovis_base_alias_by_harness(tmp_path):
    """cognovis-base resolves to distinct per-harness Layer 1 base files."""
    base_dir = make_per_harness_base_dir(tmp_path)
    agent_file = FIXTURES_DIR / "agent-with-base.md"

    claude_rc, claude_stdout, claude_stderr = run_compose(
        agent_file,
        base_dir,
        harness="claude",
    )
    codex_rc, codex_stdout, codex_stderr = run_compose(
        agent_file,
        base_dir,
        harness="codex",
    )

    assert claude_rc == 0, f"compose-agent.py exited {claude_rc}: {claude_stderr}"
    assert codex_rc == 0, f"compose-agent.py exited {codex_rc}: {codex_stderr}"
    assert "CLAUDE_AGENT_BASE_LAYER1_MARKER" in claude_stdout
    assert "CODEX_AGENT_BASE_LAYER1_MARKER" not in claude_stdout
    assert "CODEX_AGENT_BASE_LAYER1_MARKER" in codex_stdout
    assert "CLAUDE_AGENT_BASE_LAYER1_MARKER" not in codex_stdout
    print("PASS test_compose_dispatches_cognovis_base_alias_by_harness")


def test_compose_with_base_contains_layer2(tmp_path):
    """Composed output includes Layer 2 (agent persona body)."""
    base_dir = make_base_dir(tmp_path)
    agent_file = FIXTURES_DIR / "agent-with-base.md"

    rc, stdout, stderr = run_compose(agent_file, base_dir)
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert "Test Agent" in stdout, (
        f"Layer 2 body not found in output.\nstdout: {stdout}\nstderr: {stderr}"
    )
    print("PASS test_compose_with_base_contains_layer2")


def test_compose_layer_order(tmp_path):
    """Layer 1 must appear before Layer 2 in composed output."""
    base_dir = make_base_dir(tmp_path)
    agent_file = FIXTURES_DIR / "agent-with-base.md"

    rc, stdout, stderr = run_compose(agent_file, base_dir)
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    l1_pos = stdout.find("COGNOVIS_BASE_LAYER1_MARKER")
    l2_pos = stdout.find("Test Agent")
    assert l1_pos < l2_pos, (
        f"Layer 1 should appear before Layer 2. L1 pos={l1_pos}, L2 pos={l2_pos}"
    )
    print("PASS test_compose_layer_order")


def test_compose_with_model_standard_contains_layer3(tmp_path):
    """Composing an agent with model_standards: [claude-sonnet-4-6] includes Layer 3."""
    base_dir = make_base_dir(tmp_path)
    std_dir = make_model_standard_dir(tmp_path)
    agent_file = FIXTURES_DIR / "agent-with-explicit-standard.md"

    rc, stdout, stderr = run_compose(agent_file, base_dir, std_dir)
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert "SONNET_LAYER3_MARKER" in stdout, (
        f"Layer 3 marker not found in output.\nstdout: {stdout}\nstderr: {stderr}"
    )
    print("PASS test_compose_with_model_standard_contains_layer3")


def test_from_scratch_no_layer1(tmp_path):
    """from-scratch agent_base produces no Layer 1 content."""
    base_dir = make_base_dir(tmp_path)
    agent_file = FIXTURES_DIR / "agent-from-scratch.md"

    rc, stdout, stderr = run_compose(agent_file, base_dir)
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert "COGNOVIS_BASE_LAYER1_MARKER" not in stdout, (
        f"Layer 1 marker should NOT appear in from-scratch output.\nstdout: {stdout}"
    )
    assert "Test Agent (from-scratch)" in stdout, (
        f"Layer 2 body missing from from-scratch output.\nstdout: {stdout}"
    )
    print("PASS test_from_scratch_no_layer1")


def test_empty_model_standards_no_layer3(tmp_path):
    """Empty model_standards: [] and no model: field → no Layer 3."""
    base_dir = make_base_dir(tmp_path)
    std_dir = make_model_standard_dir(tmp_path)
    agent_file = FIXTURES_DIR / "agent-no-model.md"

    rc, stdout, stderr = run_compose(agent_file, base_dir, std_dir)
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert "SONNET_LAYER3_MARKER" not in stdout, (
        f"Layer 3 marker should NOT appear when model_standards is empty.\nstdout: {stdout}"
    )
    print("PASS test_empty_model_standards_no_layer3")


def test_codex_harness_toml_safe(tmp_path):
    """--harness=codex output is TOML-safe: no raw triple-quotes that break TOML."""
    base_dir = make_base_dir(tmp_path)
    agent_file = FIXTURES_DIR / "agent-with-base.md"

    rc, stdout, stderr = run_compose(agent_file, base_dir, harness="codex")
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    # TOML triple-quoted strings would break if output contains unescaped '''
    assert "'''" not in stdout, (
        f"Output contains unescaped TOML triple-quotes '''.\nstdout: {stdout}"
    )
    print("PASS test_codex_harness_toml_safe")


def test_claude_harness_emits_runtime_frontmatter(tmp_path):
    """--harness=claude preserves runtime frontmatter and strips composer fields."""
    base_dir = make_base_dir(tmp_path)
    std_dir = make_model_standard_dir(tmp_path)
    agent_file = make_agent_with_runtime_frontmatter(tmp_path)

    rc, stdout, stderr = run_compose(agent_file, base_dir, std_dir, harness="claude")
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert stdout.startswith("---\n"), f"Claude output must start with frontmatter.\nstdout: {stdout}"

    _, frontmatter, body = stdout.split("---\n", 2)
    for field in ("name:", "description:", "tools:", "model:"):
        assert field in frontmatter, f"Missing {field} in frontmatter:\n{frontmatter}"
    assert "mcpServers:" in frontmatter, f"Missing mcpServers in frontmatter:\n{frontmatter}"
    assert "permissionMode:" in frontmatter, (
        f"Missing permissionMode in frontmatter:\n{frontmatter}"
    )
    for field in ("agent_base:", "agent_base_extends:", "model_standards:", "cache_control:", "requires:"):
        assert field not in frontmatter, f"Composer field leaked into frontmatter:\n{frontmatter}"
    assert body.lstrip("\n").startswith("# Cognovis Base Agent Base Prompt"), (
        f"Composed body should follow Claude frontmatter.\nbody: {body}"
    )
    assert "SONNET_LAYER3_MARKER" in body, (
        f"Model standard body should still be composed.\nbody: {body}"
    )
    print("PASS test_claude_harness_emits_runtime_frontmatter")


def test_codex_harness_does_not_emit_frontmatter(tmp_path):
    """--harness=codex keeps the previous body-only TOML-safe output."""
    base_dir = make_base_dir(tmp_path)
    agent_file = FIXTURES_DIR / "agent-with-base.md"

    rc, stdout, stderr = run_compose(agent_file, base_dir, harness="codex")
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert stdout.startswith("# Cognovis Base Agent Base Prompt"), (
        f"Codex output should remain body-only.\nstdout: {stdout}"
    )
    assert not stdout.startswith("---\n"), f"Codex output should not emit frontmatter.\nstdout: {stdout}"
    assert "description: Test agent fixture for compose tests" not in stdout, (
        f"Codex output should not include source frontmatter.\nstdout: {stdout}"
    )
    print("PASS test_codex_harness_does_not_emit_frontmatter")


def test_layer_separators_present(tmp_path):
    """Composed output contains the layer separator markers."""
    base_dir = make_base_dir(tmp_path)
    agent_file = FIXTURES_DIR / "agent-with-base.md"

    rc, stdout, stderr = run_compose(agent_file, base_dir)
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert "--- AGENT PERSONA ---" in stdout, (
        f"AGENT PERSONA separator not found.\nstdout: {stdout}"
    )
    print("PASS test_layer_separators_present")


def test_layer3_separator_present(tmp_path):
    """Composed output contains MODEL STANDARD separator when Layer 3 is included."""
    base_dir = make_base_dir(tmp_path)
    std_dir = make_model_standard_dir(tmp_path)
    agent_file = FIXTURES_DIR / "agent-with-explicit-standard.md"

    rc, stdout, stderr = run_compose(agent_file, base_dir, std_dir)
    assert rc == 0, f"compose-agent.py exited {rc}: {stderr}"
    assert "--- MODEL STANDARD ---" in stdout, (
        f"MODEL STANDARD separator not found.\nstdout: {stdout}"
    )
    print("PASS test_layer3_separator_present")


def test_missing_base_exits_nonzero(tmp_path):
    """Composer exits non-zero when the required agent_base base is missing."""
    empty_base_dir = tmp_path / "empty-agent-bases"
    empty_base_dir.mkdir()
    agent_file = FIXTURES_DIR / "agent-with-base.md"

    rc, stdout, stderr = run_compose(agent_file, empty_base_dir, expect_success=False)
    assert rc != 0, (
        f"Expected non-zero exit when base is missing, got rc={rc}.\nstdout: {stdout}\nstderr: {stderr}"
    )
    print("PASS test_missing_base_exits_nonzero")


# ---------------------------------------------------------------------------
# Main runner (no pytest required)
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_compose_with_base_contains_layer1,
    test_compose_accepts_legacy_frontmatter_alias,
    test_compose_accepts_legacy_agent_base_extends,
    test_compose_finds_legacy_global_agent_base_dir,
    test_compose_dispatches_cognovis_base_alias_by_harness,
    test_compose_with_base_contains_layer2,
    test_compose_layer_order,
    test_compose_with_model_standard_contains_layer3,
    test_from_scratch_no_layer1,
    test_empty_model_standards_no_layer3,
    test_codex_harness_toml_safe,
    test_claude_harness_emits_runtime_frontmatter,
    test_codex_harness_does_not_emit_frontmatter,
    test_layer_separators_present,
    test_layer3_separator_present,
    test_missing_base_exits_nonzero,
]


def main() -> int:
    import tempfile as _tempfile

    pass_count = 0
    fail_count = 0
    for test_fn in ALL_TESTS:
        with _tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            try:
                test_fn(tmp_path)
                pass_count += 1
            except AssertionError as e:
                print(f"FAIL {test_fn.__name__}: {e}")
                fail_count += 1
            except Exception as e:
                print(f"ERROR {test_fn.__name__}: {type(e).__name__}: {e}")
                fail_count += 1

    print(f"\n{pass_count} passed, {fail_count} failed")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
