"""Regression tests for cld's single-bead-only contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


CLD_BIN = Path(__file__).resolve().parents[1] / "bin" / "cld"


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _write_claude_capture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    claude_mock = tmp_path / "claude-capture"
    argv_file = tmp_path / "claude-argv.json"
    prompt_file = tmp_path / "claude-prompt.txt"
    called_file = tmp_path / "claude-called.txt"
    _write_executable(
        claude_mock,
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['CLAUDE_CALLED_FILE']).write_text('called', encoding='utf-8')\n"
        "pathlib.Path(os.environ['CLAUDE_ARGV_FILE']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        "if len(sys.argv) > 1:\n"
        "    pathlib.Path(os.environ['CLAUDE_PROMPT_FILE']).write_text(sys.argv[-1], encoding='utf-8')\n"
        "print(f\"CLD_BEAD_LINE={os.environ.get('CLD_BEAD_LINE', '')}\")\n"
        "print(f\"CLD_ROUTE_PROFILE={os.environ.get('CLD_ROUTE_PROFILE', '')}\")\n",
    )
    return claude_mock, argv_file, prompt_file, called_file


def _write_review_client_capture(tmp_path: Path) -> Path:
    return _write_executable(
        tmp_path / "review-client",
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['CLAUDE_CALLED_FILE']).write_text('called', encoding='utf-8')\n"
        "pathlib.Path(os.environ['CLAUDE_ARGV_FILE']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        "print(f\"CLD_BEAD_LINE={os.environ.get('CLD_BEAD_LINE', '')}\")\n",
    )


def _write_bd_mock(tmp_path: Path) -> tuple[Path, Path]:
    bd_mock = tmp_path / "bd-mock"
    bd_log = tmp_path / "bd-argv.jsonl"
    _write_executable(
        bd_mock,
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "log = pathlib.Path(os.environ['BD_ARGV_LOG'])\n"
        "with log.open('a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(args) + '\\n')\n"
        "if args[:3] == ['config', 'get', 'issue_prefix']:\n"
        "    print('CL')\n"
        "    raise SystemExit(0)\n"
        "if len(args) >= 2 and args[0] == 'show':\n"
        "    bead_id = args[1]\n"
        "    if '--children' in args:\n"
        "        print(json.dumps({bead_id: []}))\n"
        "    else:\n"
        "        print(json.dumps([{'id': bead_id, 'status': os.environ.get('BD_STATUS', 'open')}]))\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['dolt', 'pull']:\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(0)\n",
    )
    return bd_mock, bd_log


def _write_cld_path_mocks(tmp_path: Path) -> None:
    _write_executable(
        tmp_path / "git",
        "#!/bin/sh\n"
        "exit 0\n",
    )
    _write_executable(
        tmp_path / "cmux",
        "#!/bin/sh\n"
        "exit 1\n",
    )


def _argv_flag_value(argv: list[str], flag: str) -> str | None:
    """Look up a flag's value, supporting both "--flag value" (two argv
    tokens) and "--flag=value" (one argv token) forms. The -br tool-profile
    flags use the "=" form specifically: claude's --allowedTools/
    --disallowedTools are variadic (`<tools...>`) and greedily collect every
    subsequent non-flag argv element when passed as a separate token,
    swallowing the trailing review prompt — see bin/cld for the full
    explanation. "--flag=value" binds the value to the flag as one token so
    there is nothing left for the variadic collection to swallow.
    """
    prefix = f"{flag}="
    for token in argv:
        if token.startswith(prefix):
            return token[len(prefix):]
    for left, right in zip(argv, argv[1:]):
        if left == flag:
            return right
    return None


# Deterministic narrow review tool profile for cld -br (CL-9knh, fix-cycle 2).
# Kept in sync with the identical constants in test_launcher_permission_modes.py
# and with the production implementation in bin/cld. Bash is HARD-EXCLUDED via
# --tools (BEAD_REVIEW_TOOLS below), not merely left out of --allowedTools —
# see test_launcher_permission_modes.py's constant docstring for the full
# rationale (plan-mode classifier auto-approval of unrelated Bash commands
# once Bash is registered as available at all). This profile is a SINGLE
# fixed string now — no callback-conditional Bash grant exists anymore.
BEAD_REVIEW_ALLOWED_TOOLS = (
    "Read,Grep,Glob,"
    "mcp__cognovis-tools__bead_show,mcp__cognovis-tools__bead_search,"
    "mcp__cognovis-tools__bead_list,mcp__cognovis-tools__bead_repos,"
    "mcp__cognovis-tools__bead_ready,mcp__cognovis-tools__bead_review_write"
)


# --tools value that hard-excludes Bash from the built-in tool set for -br
# (unconditionally, callback or not).
BEAD_REVIEW_TOOLS = "Read,Grep,Glob"


BEAD_REVIEW_DISALLOWED_TOOLS = (
    "Edit,Write,NotebookEdit,"
    "mcp__cognovis-tools__bead_create,mcp__cognovis-tools__bead_effort_classify,"
    "mcp__cognovis-tools__bead_claim_prepare,mcp__cognovis-tools__bead_claim_commit,"
    "mcp__cognovis-tools__bead_claim,"
    "mcp__cognovis-tools__bead_update,mcp__cognovis-tools__bead_update_notes,"
    "mcp__cognovis-tools__bead_close,mcp__cognovis-tools__bead_dep_add,"
    "mcp__cognovis-tools__bead_dep_remove,mcp__cognovis-tools__bead_dolt_sync"
)


def _run_cld(
    tmp_path: Path,
    args: list[str],
    env_overrides: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path, Path]:
    claude_mock, argv_file, prompt_file, called_file = _write_claude_capture(tmp_path)
    review_client = _write_review_client_capture(tmp_path)
    bd_mock, bd_log = _write_bd_mock(tmp_path)
    _write_cld_path_mocks(tmp_path)
    home = tmp_path / "home"
    home.mkdir()

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_BIN"] = str(claude_mock)
    env["CLAUDE_ARGV_FILE"] = str(argv_file)
    env["CLAUDE_PROMPT_FILE"] = str(prompt_file)
    env["CLAUDE_CALLED_FILE"] = str(called_file)
    env["CLD_BEAD_REVIEW_CLIENT"] = str(review_client)
    env["BD_BIN"] = str(bd_mock)
    env["BD_ARGV_LOG"] = str(bd_log)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(
        [str(CLD_BIN), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env=env,
    )
    return result, argv_file, prompt_file, called_file, bd_log


@pytest.mark.parametrize(
    "flag",
    ["-bw", "--bead-wave", "-bl", "--bead-label", "-bi", "--bead-ids"],
)
def test_cld_rejects_multi_bead_dispatch_flags(tmp_path: Path, flag: str) -> None:
    called = tmp_path / "claude-called"
    claude_mock = tmp_path / "claude-mock"
    claude_mock.write_text(
        "#!/bin/sh\n"
        "touch \"$CALLED_FILE\"\n",
        encoding="utf-8",
    )
    claude_mock.chmod(0o755)

    env = dict(os.environ)
    env["CLAUDE_BIN"] = str(claude_mock)
    env["CALLED_FILE"] = str(called)

    result = subprocess.run(
        [str(CLD_BIN), flag, "CL-parent"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert not called.exists()
    assert "cld does not dispatch multi-bead waves" in result.stderr
    assert "wave skills with cmux panes" in result.stderr
    assert "cld -b <bead-id>" in result.stderr


def test_cld_contains_no_wave_dispatch_prompt_or_help_entry() -> None:
    source = CLD_BIN.read_text(encoding="utf-8")

    assert "Wave orchestration request" not in source
    assert "Dispatch wave-orchestrator" not in source
    assert "cld -bw ${bead_id}" not in source
    assert "Waves must be started manually using the wave skills with cmux panes" in source


@pytest.mark.parametrize("flag", ["-b", "-bq"])
def test_cld_bead_modes_without_callback_do_not_inject_callback_contract(
    tmp_path: Path,
    flag: str,
) -> None:
    result, argv_file, prompt_file, called_file, _bd_log = _run_cld(tmp_path, [flag, "CL-smoke"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    prompt = prompt_file.read_text(encoding="utf-8")
    assert argv[-1] == prompt
    assert "Coordinator callback" not in prompt
    assert "trigger-flash" not in prompt


# Guards CL-sl3j: both launcher modes must enter the one canonical orchestrator,
# while the prompt preserves the strict auto/quick Bead Claim distinction.
@pytest.mark.parametrize(
    ("flag", "requested_workflow"),
    [("-b", "auto"), ("-bq", "quick")],
)
def test_regression_cld_bead_modes_forward_requested_workflow(
    tmp_path: Path,
    flag: str,
    requested_workflow: str,
) -> None:
    result, argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [flag, "CL-smoke"],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    prompt = prompt_file.read_text(encoding="utf-8")
    assert _argv_flag_value(argv, "--agent") == "bead-orchestrator"
    assert f"requested_workflow={requested_workflow}" in prompt
    if requested_workflow == "quick":
        assert "requested_workflow=auto" not in prompt
        assert "do not fall back to full" in prompt


# Guards CL-1n24: force-tier must use the typed claim contract symmetrically;
# neither launcher mode may send the orchestrator back to legacy Phase 0.
@pytest.mark.parametrize("flag", ["-b", "-bq"])
def test_regression_cld_bead_modes_forward_force_tier_to_claim_prepare(
    tmp_path: Path,
    flag: str,
) -> None:
    result, _argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [flag, "CL-smoke", "--force-tier", "mcp"],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    prompt = prompt_file.read_text(encoding="utf-8")
    assert "force_tier=mcp" in prompt
    assert "bead_claim_prepare" in prompt
    assert "phase0-claim.py" not in prompt
    assert "takes precedence over requested_workflow" in prompt


def test_regression_cld_help_distinguishes_forced_quick_from_strict_bq(
    tmp_path: Path,
) -> None:
    result, _argv_file, _prompt_file, _called_file, _bd_log = _run_cld(
        tmp_path,
        ["--help"],
    )

    assert result.returncode == 0, result.stderr
    assert "quick, gsd, paul, mcp" in result.stdout
    assert "solo" not in result.stdout
    assert "quick is an eligibility override, unlike strict -bq" in result.stdout


@pytest.mark.parametrize("force_tier", ["solo", "infra"])
def test_regression_cld_rejects_unsupported_force_tier_before_launch(
    tmp_path: Path,
    force_tier: str,
) -> None:
    result, _argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        ["-b", "CL-smoke", "--force-tier", force_tier],
    )

    assert result.returncode == 2
    assert f"invalid force tier '{force_tier}'" in result.stderr
    assert not called_file.exists()


@pytest.mark.parametrize("flag", ["-b", "-bq"])
def test_cld_bead_modes_default_route_profile_is_parameter_only_with_ambient_env(
    tmp_path: Path,
    flag: str,
) -> None:
    result, _argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [flag, "CL-smoke"],
        env_overrides={"CLD_ROUTE_PROFILE": "evil-profile"},
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    assert "CLD_ROUTE_PROFILE=\n" in result.stdout
    assert "CLD_ROUTE_PROFILE=evil-profile" not in result.stdout
    prompt = prompt_file.read_text(encoding="utf-8")
    assert "Route profile: cld-default" in prompt
    assert "route_profile=cld-default" in prompt
    assert "bead_claim_prepare" in prompt
    assert "evil-profile" not in prompt


@pytest.mark.parametrize("flag", ["-b", "-bq"])
def test_cld_bead_modes_explicit_route_profile_is_parameter_only_with_ambient_env(
    tmp_path: Path,
    flag: str,
) -> None:
    result, _argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [flag, "CL-smoke", "--route-profile", "custom-profile"],
        env_overrides={"CLD_ROUTE_PROFILE": "evil-profile"},
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    assert "CLD_ROUTE_PROFILE=\n" in result.stdout
    assert "CLD_ROUTE_PROFILE=evil-profile" not in result.stdout
    prompt = prompt_file.read_text(encoding="utf-8")
    assert "Route profile: custom-profile" in prompt
    assert "route_profile=custom-profile" in prompt
    assert "bead_claim_prepare" in prompt
    assert "evil-profile" not in prompt


@pytest.mark.parametrize("flag", ["-b", "-bq"])
def test_cld_bead_modes_with_callback_inject_contract_and_consume_flags(
    tmp_path: Path,
    flag: str,
) -> None:
    result, argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [
            flag,
            "CL-smoke",
            "--coordinator-workspace",
            "workspace:15",
            "--coordinator-surface",
            "surface:33",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    prompt = prompt_file.read_text(encoding="utf-8")
    assert "--coordinator-workspace" not in argv
    assert "--coordinator-surface" not in argv
    assert "Coordinator callback: this session runs under a coordinator that owns cmux" in prompt
    assert "workspace:15 / surface:33" in prompt
    assert "cmux trigger-flash --surface surface:33" in prompt
    assert "blocking question" in prompt
    assert "terminal state" in prompt
    assert "Phase 16" in prompt
    assert "Normal progress updates are NOT intervention events and must NOT trigger the callback." in prompt
    assert "If cmux is unavailable, skip the flash (best-effort)" in prompt


@pytest.mark.parametrize(
    "args, message",
    [
        (["-b", "CL-smoke", "--coordinator-workspace"], "--coordinator-workspace requires an argument"),
        (["-b", "CL-smoke", "--coordinator-workspace", "workspace:15"], "coordinator callback requires both"),
        (
            [
                "-b",
                "CL-smoke",
                "--coordinator-workspace",
                "workspace:x",
                "--coordinator-surface",
                "surface:33",
            ],
            "invalid coordinator workspace",
        ),
        (
            [
                "-b",
                "CL-smoke",
                "--coordinator-workspace",
                "workspace:15",
                "--coordinator-surface",
                "surface:x",
            ],
            "invalid coordinator surface",
        ),
        (["-br", "CL-smoke", "-b", "CL-other"], "mutually exclusive"),
        # Finding 3.1: shell-metacharacter coordinator-surface values must
        # still be rejected by the existing ^surface:[0-9]+$ validation
        # BEFORE any --allowedTools string is ever constructed for -br's
        # tool profile (which interpolates the validated surface value into
        # a Bash(...) permission entry — see Finding 2).
        (
            [
                "-br",
                "CL-smoke",
                "--coordinator-workspace",
                "workspace:15",
                "--coordinator-surface",
                "surface:33; rm -rf /",
            ],
            "invalid coordinator surface",
        ),
        (
            [
                "-br",
                "CL-smoke",
                "--coordinator-workspace",
                "workspace:15",
                "--coordinator-surface",
                "surface:33 && evil",
            ],
            "invalid coordinator surface",
        ),
        (
            [
                "-br",
                "CL-smoke",
                "--coordinator-workspace",
                "workspace:15",
                "--coordinator-surface",
                "surface:33 | evil",
            ],
            "invalid coordinator surface",
        ),
        (
            [
                "-br",
                "CL-smoke",
                "--coordinator-workspace",
                "workspace:15",
                "--coordinator-surface",
                "surface:33$(evil)",
            ],
            "invalid coordinator surface",
        ),
        (
            [
                "-br",
                "CL-smoke",
                "--coordinator-workspace",
                "workspace:15",
                "--coordinator-surface",
                "surface:33`evil`",
            ],
            "invalid coordinator surface",
        ),
    ],
)
def test_cld_invalid_callback_or_review_arguments_fail_before_harness(
    tmp_path: Path,
    args: list[str],
    message: str,
) -> None:
    result, _argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 2
    assert not called_file.exists()
    assert message in result.stderr


def test_cld_bead_review_defaults_to_opus_and_shared_client(tmp_path: Path) -> None:
    result, argv_file, _prompt_file, called_file, bd_log = _run_cld(
        tmp_path, ["-br", "CL-smoke"]
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    assert "CLD_BEAD_LINE=cld" in result.stdout
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_flag_value(argv, "--provider") == "claude"
    assert _argv_flag_value(argv, "--adapter") == "claude-agent"
    assert _argv_flag_value(argv, "--bead-id") == "CL-smoke"
    assert _argv_flag_value(argv, "--model") == "opus"
    assert "--worktree" not in argv
    assert "--agent" not in argv
    bd_calls = [json.loads(line) for line in bd_log.read_text(encoding="utf-8").splitlines()]
    assert not any(call[:1] == ["dolt"] for call in bd_calls)


def test_cld_bead_review_honors_explicit_model_override(tmp_path: Path) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        ["-br", "CL-smoke", "--model", "sonnet"],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--model" in argv
    assert "sonnet" in argv
    assert "opus" not in argv


def test_cld_bead_review_callback_uses_review_terminal_contract(tmp_path: Path) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [
            "-br",
            "CL-smoke",
            "--coordinator-workspace",
            "workspace:15",
            "--coordinator-surface",
            "surface:33",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--coordinator-workspace" not in argv
    assert "--coordinator-surface" not in argv
    assert _argv_flag_value(argv, "--provider") == "claude"


def test_cld_resume_flag_continues_to_forward_to_claude(tmp_path: Path) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-r"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "-r" in argv
    assert "-br" not in argv


def test_cld_help_documents_review_and_callback_flags(tmp_path: Path) -> None:
    result, _argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["--help"])

    assert result.returncode == 0
    assert called_file.exists()
    assert "-br, --bead-review ID" in result.stdout
    assert "--coordinator-workspace workspace:<n>" in result.stdout
    assert "--coordinator-surface surface:<n>" in result.stdout


def test_cld_has_no_callback_environment_variable_interface() -> None:
    source = CLD_BIN.read_text(encoding="utf-8")

    assert "WAVE_COORDINATOR" not in source
    assert "CLD_COORDINATOR" not in source
    assert "COORDINATOR_WORKSPACE" not in source
    assert "COORDINATOR_SURFACE" not in source
