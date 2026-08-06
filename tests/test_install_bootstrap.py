import os
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent

PLATFORM_SKILLS = {
    "library": REPO_ROOT,
}


def test_install_sh_links_only_irreducible_library_entrypoint(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".agents").mkdir()
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    (home / ".opencode").mkdir()

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

    installed_cli = home / ".local" / "bin" / "library"
    assert installed_cli.is_symlink()
    assert installed_cli.resolve() == (REPO_ROOT / "bin" / "library").resolve()
    assert os.access(installed_cli, os.X_OK)

    consumer_dir = tmp_path / "consumer"
    consumer_dir.mkdir()

    # A subprocess is required here: this test covers shell PATH lookup, the
    # bootstrap symlink, and the launcher's interpreter/runtime boundary.
    def run_wrapped(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["library", *args],
            cwd=consumer_dir,
            env=env,
            capture_output=True,
            text=True,
        )

    def run_direct(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "uv",
                "run",
                "--script",
                str(REPO_ROOT / "scripts" / "library.py"),
                *args,
            ],
            cwd=consumer_dir,
            env=env,
            capture_output=True,
            text=True,
        )

    wrapped = run_wrapped("skill", "list", "--json")
    direct = run_direct("skill", "list", "--json")

    assert wrapped.returncode == direct.returncode == 0
    assert wrapped.stdout == direct.stdout

    wrapped_top_level = run_wrapped("audit", "--help")
    direct_top_level = run_direct("audit", "--help")

    assert wrapped_top_level.returncode == direct_top_level.returncode == 0
    assert wrapped_top_level.stdout == direct_top_level.stdout

    wrapped_failure = run_wrapped(
        "skill", "use", "zzz-does-not-exist", "--dry-run"
    )
    direct_failure = run_direct(
        "skill", "use", "zzz-does-not-exist", "--dry-run"
    )

    assert wrapped_failure.returncode == direct_failure.returncode == 2
    assert wrapped_failure.stdout == direct_failure.stdout

    help_result = run_wrapped("--help")
    version_result = run_wrapped("--version")

    assert help_result.returncode == 0
    assert help_result.stdout.startswith("usage: library ")
    assert "Canonical grammar: library <primitive> <verb>" in help_result.stdout
    assert "uv run --script" not in help_result.stdout
    assert version_result.stdout.startswith("library ")

    documented_shapes = (
        ("workspace", "status", "--all", "--scope", "project", "--help"),
        ("workspace", "sync", "--all", "--scope", "project", "--help"),
        ("skill", "list", "--help"),
        ("audit", "--help"),
    )
    for args in documented_shapes:
        parsed = run_wrapped(*args)
        assert parsed.returncode == 0, parsed.stderr

    for skill_root in (
        home / ".agents" / "skills",
        home / ".claude" / "skills",
        home / ".codex" / "skills",
        home / ".opencode" / "skills",
    ):
        for name, expected_target in PLATFORM_SKILLS.items():
            installed = skill_root / name
            assert installed.is_symlink(), f"{installed} was not created as a symlink"
            assert installed.resolve() == expected_target.resolve()
        for forge in (
            "skill-forge",
            "agent-forge",
            "standard-forge",
            "script-forge",
            "hook-forge",
        ):
            assert not (skill_root / forge).exists()

    lock = yaml.safe_load((home / ".config" / "library" / "global.lock").read_text())
    assert [root["id"] for root in lock["requested_roots"]] == ["skill:library"]
    assert lock["receipts"][0]["bootstrap_owned"] is True


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

    assert "library workspace status --all --scope project" in readme
    assert "library workspace sync --all --scope project" in readme
    assert "library skill list" in readme
    assert "library audit" in readme
    assert "target interface until" not in readme
    assert "does not currently ship a standalone `bin/library`" not in bootstrap_docs
    assert "uv run --script <LIBRARY_SKILL_DIR>/scripts/library.py" not in skill
    assert "uv run --script scripts/library.py" not in bootstrap_docs
    assert "uv run --script <LIBRARY_SKILL_DIR>/scripts/library.py" not in bootstrap_docs
    assert "library --help" in skill
    assert "library --help" in install_cookbook
    assert "library <primitive> use <name> --dry-run --json" in add_cookbook
    assert "irreducible global bootstrap" in normalized_readme
    assert "dialog-oriented" in readme
    assert "dialog-oriented" in install_cookbook


def test_install_sh_adopts_exact_historical_forge_link_without_recreating_others(
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
    assert f"{home / '.local' / 'bin'} is not in $PATH" in result.stdout
    lock = yaml.safe_load((home / ".config" / "library" / "global.lock").read_text())
    assert {root["id"] for root in lock["requested_roots"]} == {
        "skill:library",
        "skill:skill-forge",
    }
    assert historical.is_symlink()
    assert not (skill_root / "agent-forge").exists()
