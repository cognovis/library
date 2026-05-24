from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def test_library_skill_documents_consumer_updater() -> None:
    text = read("SKILL.md")

    assert "Consumer Project Updates" in text
    assert "scripts/update-consumers.py" in text
    assert "consumer-projects.yml" in text
    assert "--apply" in text


def test_standard_forge_documents_consumer_update_gate() -> None:
    text = read("skills/standard-forge/SKILL.md")

    assert "Consumer Update Gate" in text
    assert "scripts/update-consumers.py" in text
    assert "consumer-projects.yml" in text
    assert "consumer propagation bead" in text


def test_script_forge_documents_consumer_runtime_gate() -> None:
    text = read("skills/script-forge/SKILL.md")

    assert "Consumer Runtime Gate" in text
    assert "managed_files" in text
    assert "consumer-projects.yml" in text
    assert "scripts/update-consumers.py" in text
