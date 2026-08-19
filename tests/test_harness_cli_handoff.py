"""The supported install hands cld, cdx, and cra to harness-cli."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]

RETIRED_LAUNCHER_PATHS = (
    "bin/cld",
    "bin/cdx",
    "scripts/bin/cld",
    "scripts/bin/cdx",
    "bin/lib/bead-loop-authority.zsh",
    "scripts/bin/lib/bead-loop-authority.zsh",
    "scripts/launchers.py",
)

REMOVED_LAUNCHER_ONLY_HELPERS = (
    "bin/lib/orchestrator-config-sync.zsh",
    "scripts/bin/lib/orchestrator-config-sync.zsh",
    "scripts/compact-bead-context.py",
    "scripts/filter-codex-jsonl.py",
    "scripts/worktree-overlays.py",
    "scripts/cdx-bead-workflow.py",
)

RETAINED_HELPERS = (
    "scripts/coordinator_callback.py",
)

LIVE_REFERENCE_ROOTS = (
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "SKILL.md",
    REPO_ROOT / "install.sh",
    REPO_ROOT / "pyproject.toml",
    REPO_ROOT / "cookbook",
    REPO_ROOT / "docs" / "ARCHITECTURE.md",
    REPO_ROOT / "docs" / "harness-baseline.md",
    REPO_ROOT / "docs" / "primitives" / "system-prompt.md",
    REPO_ROOT / "scripts",
    REPO_ROOT / "tests",
)

FORBIDDEN_LIVE_REFERENCES = (
    "scripts/bin/cld",
    "scripts/bin/cdx",
    "bin/cld",
    "bin/cdx",
    "scripts.launchers",
    "bead-loop-authority.zsh",
    "orchestrator-config-sync.zsh",
    "compact-bead-context.py",
    "filter-codex-jsonl.py",
    "worktree-overlays.py",
    "cdx-bead-workflow.py",
)


def _install_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "UV_TOOL_DIR": str(tmp_path / "tools"),
            "UV_TOOL_BIN_DIR": str(bin_dir),
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        }
    )
    return env


def test_library_package_does_not_ship_harness_short_commands(tmp_path: Path) -> None:
    env = _install_env(tmp_path)
    bin_dir = Path(env["UV_TOOL_BIN_DIR"])
    install = subprocess.run(
        ["uv", "tool", "install", str(REPO_ROOT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert install.returncode == 0, install.stderr
    assert (bin_dir / "library").is_file()
    for command in ("cld", "cdx", "cra"):
        assert not (bin_dir / command).exists()


def test_supported_install_exposes_harness_cli_adapters(
    tmp_path: Path, harness_cli_source: Path
) -> None:
    env = _install_env(tmp_path)
    bin_dir = Path(env["UV_TOOL_BIN_DIR"])
    tool_dir = Path(env["UV_TOOL_DIR"])
    harness_cli = harness_cli_source

    installed = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "install.sh"),
            "--harness-cli-source",
            str(harness_cli),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr or installed.stdout
    assert (bin_dir / "library").is_file()
    library_root = (tool_dir / "library").resolve()
    harness_root = (tool_dir / "cognovis-harness-cli").resolve()
    assert harness_root.is_dir()

    for command in ("cld", "cdx", "cra"):
        executable = bin_dir / command
        assert executable.is_file()
        resolved = executable.resolve()
        assert resolved.is_relative_to(harness_root)
        assert not resolved.is_relative_to(library_root)
        source = resolved.read_text(encoding="utf-8")
        assert "harness_cli.cli" in source
        assert f"from harness_cli.cli import {command}" in source

    smokes = {
        "cld": subprocess.run(
            [str(bin_dir / "cld"), "--dry-run"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        ),
        "cdx": subprocess.run(
            [str(bin_dir / "cdx"), "--dry-run"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        ),
        "cra": subprocess.run(
            [str(bin_dir / "cra"), "--dry-run"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        ),
    }
    expected_programs = {"cld": "claude", "cdx": "codex", "cra": "agent"}
    for command, result in smokes.items():
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout)
        program = str(payload["program"])
        assert expected_programs[command] in program


def test_legacy_launcher_paths_and_launcher_only_helpers_are_absent() -> None:
    for relative in RETIRED_LAUNCHER_PATHS + REMOVED_LAUNCHER_ONLY_HELPERS:
        assert not (REPO_ROOT / relative).exists()
    for relative in RETAINED_HELPERS:
        assert (REPO_ROOT / relative).is_file()


def test_live_runtime_and_packaging_have_no_retired_launcher_paths() -> None:
    hits: list[str] = []
    for root in LIVE_REFERENCE_ROOTS:
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix not in {".md", ".py", ".toml", ".sh", ""} and path.name != "install.sh":
                continue
            if path.name.startswith("test_harness_cli_handoff"):
                continue
            text = path.read_text(encoding="utf-8")
            for needle in FORBIDDEN_LIVE_REFERENCES:
                if needle in text:
                    hits.append(f"{path.relative_to(REPO_ROOT)}:{needle}")
    assert hits == []
