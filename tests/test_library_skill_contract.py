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
        "<init|status|primitive> "
        "[verb] [name-or-query] [options]"
    )


def test_library_skill_defines_project_local_inspection_and_recommendation() -> None:
    text = read_skill()

    assert "## Inspect and recommend" in text
    assert "library status --offline --json" in text
    assert "library workspace list --json" in text
    assert "ask the user to confirm it" in text
    assert "historical machine-wide lock" in text.lower()
    assert "never install before confirmation" in text.lower()


def test_library_skill_defines_confirmed_project_local_installation() -> None:
    text = read_skill()

    assert "library init" in text
    assert "library workspace use cognovis-library-core:python-cli" in text
    assert "library skill use <name>" in text
    assert "`library init` takes no Workspace selector." in text
    assert "No\ncommand takes a scope selector" in text
