import os
import importlib.util
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent

PLATFORM_SKILLS = {
    "library": REPO_ROOT,
}


def _load_bootstrap_receipts_module():
    script = REPO_ROOT / "scripts" / "register-bootstrap-receipts.py"
    spec = importlib.util.spec_from_file_location("bootstrap_receipts", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_receipts_ignore_retired_harness_skill_links(tmp_path: Path) -> None:
    """Only supported harness skill links become bootstrap receipt targets."""
    module = _load_bootstrap_receipts_module()
    source = tmp_path / "source"
    source.mkdir()
    home = tmp_path / "home"
    for relative in (".agents/skills", ".claude/skills", ".codex/skills", ".opencode/skills"):
        target_dir = home / relative
        target_dir.mkdir(parents=True)
        (target_dir / "example").symlink_to(source)

    links = module.matching_links(home, "example", source)

    assert links == [
        home / ".agents" / "skills" / "example",
        home / ".claude" / "skills" / "example",
        home / ".codex" / "skills" / "example",
    ]


def test_install_sh_links_only_irreducible_library_entrypoint(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".agents").mkdir()
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg-data")
    env["PATH"] = f"{home / '.local' / 'bin'}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "install.sh")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    assert "Installing the Library control plane with uv" in result.stdout
    assert not (home / ".agents" / "skills" / "library").exists()
    assert not (home / ".claude" / "skills" / "library").exists()
    assert not (home / ".codex" / "skills" / "library").exists()


def test_bootstrap_documents_the_installed_cli_contract() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    skill = (REPO_ROOT / "SKILL.md").read_text()
    cookbooks = {
        path.name: path.read_text()
        for path in sorted((REPO_ROOT / "cookbook").glob("*.md"))
    }
    install_cookbook = cookbooks["install.md"]
    add_cookbook = cookbooks["add.md"]
    normalized_readme = " ".join(readme.split())
    bootstrap_docs = "\n".join((readme, skill, *cookbooks.values()))

    assert "library workspace status --all" in readme
    assert "library workspace sync --all" in readme
    assert "library skill list" in readme
    assert "library audit" in readme
    assert "target interface until" not in readme
    assert "does not currently ship a standalone `bin/library`" not in bootstrap_docs
    assert "uv run --script <LIBRARY_SKILL_DIR>/scripts/library.py" not in skill
    assert "uv run --script scripts/library.py" not in bootstrap_docs
    assert "uv run --script <LIBRARY_SKILL_DIR>/scripts/library.py" not in bootstrap_docs
    assert "library --help" in install_cookbook
    assert "library <primitive> use <name> --dry-run --json" in add_cookbook
    assert "irreducible global bootstrap" in normalized_readme
    assert "dialog-oriented" in readme
    assert "dialog-oriented" in install_cookbook


def test_install_sh_leaves_historical_forge_link_outside_bootstrap_scope(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    skill_root = home / ".agents" / "skills"
    skill_root.mkdir(parents=True)
    historical = skill_root / "skill-forge"
    historical.symlink_to(REPO_ROOT / "skills" / "skill-forge")
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg-data")

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "install.sh")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Installing the Library control plane with uv" in result.stdout
    assert historical.is_symlink()
    assert not (skill_root / "agent-forge").exists()


def test_packaged_launcher_copies_remain_identical_to_compatibility_copies() -> None:
    for relative in ("cld", "cdx", "lib/orchestrator-config-sync.zsh"):
        assert (REPO_ROOT / "bin" / relative).read_bytes() == (
            REPO_ROOT / "scripts" / "bin" / relative
        ).read_bytes()


def test_changelog_documents_solo_and_executive_pack_launcher_contract() -> None:
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "CL-zw39" in changelog
    assert "-sb`/`--solo-bead" in changelog
    assert "-ep`/`--executive-pack" in changelog
    assert "natural-language role" in changelog
    assert "-b` compatibility alias" in changelog


def test_install_script_is_executable() -> None:
    assert os.access(REPO_ROOT / "install.sh", os.X_OK)
