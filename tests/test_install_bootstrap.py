import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

PLATFORM_SKILLS = {
    "library": REPO_ROOT,
    "skill-forge": REPO_ROOT / "skills" / "skill-forge",
    "agent-forge": REPO_ROOT / "skills" / "agent-forge",
    "standard-forge": REPO_ROOT / "skills" / "standard-forge",
    "script-forge": REPO_ROOT / "skills" / "script-forge",
    "hook-forge": REPO_ROOT / "skills" / "hook-forge",
}


def test_install_sh_links_library_and_platform_forges(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".agents").mkdir()
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    (home / ".opencode").mkdir()

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
