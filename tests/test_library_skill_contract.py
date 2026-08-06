from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "SKILL.md"


def read_skill() -> str:
    return SKILL_PATH.read_text()


def read_frontmatter() -> dict[str, object]:
    _, frontmatter, _ = read_skill().split("---", 2)
    return yaml.safe_load(frontmatter)


def test_library_skill_requires_explicit_user_invocation() -> None:
    frontmatter = read_frontmatter()

    assert frontmatter["disable-model-invocation"] is True
    assert frontmatter["argument-hint"] == (
        "<primitive|search|installed|status|audit|sync|catalog> "
        "[verb] [name-or-query] [options]"
    )


def test_bare_library_invocation_derives_non_mutating_cli_help() -> None:
    text = read_skill()
    normalized = text.lower()

    assert "## Invocation Guidance" in text
    assert "When invoked without arguments" in text
    assert "library --help" in text
    assert "globally installed `library` command" in text
    assert "uv run --script <LIBRARY_SKILL_DIR>/scripts/library.py" not in text
    assert "derive the available values from that output" in normalized
    assert "primitive names" in text
    assert "primitive verbs" in text
    assert "global commands" in text
    assert "common options" in text
    assert "representative examples" in text
    assert "Do not mutate state" in text


def test_partial_and_complete_invocations_have_distinct_routing() -> None:
    text = read_skill()

    assert "When the invocation is incomplete" in text
    assert "next missing required value" in text
    assert "show only the valid choices" in text
    assert "When the invocation is complete" in text
    assert "delegate it to the canonical CLI" in text
