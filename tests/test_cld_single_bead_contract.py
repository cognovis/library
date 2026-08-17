"""Regression tests for cld's single-bead-only contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


CLD_BIN = Path(__file__).resolve().parents[1] / "bin" / "cld"
SYSTEM_GIT = shutil.which("git")


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _write_core_authority(tmp_path: Path) -> Path:
    assert SYSTEM_GIT is not None
    root = tmp_path / "cognovis-core-authority"
    for relative in (
        "skills/executive-pack/SKILL.md",
        "skills/bead-execution-loop/SKILL.md",
        "agents/bead-implementer.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"current authority: {relative}\n", encoding="utf-8")
    subprocess.run([SYSTEM_GIT, "init", "-q", root], check=True)
    subprocess.run([SYSTEM_GIT, "-C", root, "add", "."], check=True)
    subprocess.run(
        [
            SYSTEM_GIT,
            "-C",
            root,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "test authority",
        ],
        check=True,
    )
    return root


def _write_claude_capture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    claude_mock = tmp_path / "claude-capture"
    argv_file = tmp_path / "claude-argv.json"
    prompt_file = tmp_path / "claude-prompt.txt"
    called_file = tmp_path / "claude-called.txt"
    _write_executable(
        claude_mock,
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "sync_log = os.environ.get('SYNC_LOG', '')\n"
        "if sync_log:\n"
        "    with pathlib.Path(sync_log).open('a', encoding='utf-8') as f:\n"
        "        f.write('claude launch\\n')\n"
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
        "sync_log = os.environ.get('SYNC_LOG', '')\n"
        "if sync_log:\n"
        "    with pathlib.Path(sync_log).open('a', encoding='utf-8') as f:\n"
        "        f.write('bd ' + ' '.join(args) + '\\n')\n"
        "log = pathlib.Path(os.environ['BD_ARGV_LOG'])\n"
        "with log.open('a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(args) + '\\n')\n"
        "if args[:3] == ['config', 'get', 'issue_prefix']:\n"
        "    print('CL')\n"
        "    raise SystemExit(0)\n"
        "if len(args) >= 2 and args[0] == 'show':\n"
        "    bead_id = args[1]\n"
        "    if bead_id in os.environ.get('BD_MISSING_IDS', '').split(','):\n"
        "        raise SystemExit(1)\n"
        "    if '--children' in args:\n"
        "        count = int(os.environ.get('BD_CHILD_COUNT', '0'))\n"
        "        print(json.dumps({bead_id: [{'id': f'{bead_id}.{index + 1}'} for index in range(count)]}))\n"
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
        # GIT_REPO_ROOT and GIT_TRACKED stay unset for the default mock, so cld
        # behaves exactly as it did before worktree-overlay resolution existed.
        "#!/bin/sh\n"
        "if test -n \"${SYNC_LOG:-}\"; then printf 'git %s\\n' \"$*\" >> \"$SYNC_LOG\"; fi\n"
        "if [ \"$1\" = \"rev-parse\" ] && [ \"$2\" = \"--show-toplevel\" ]; then\n"
        "  [ -n \"${GIT_REPO_ROOT:-}\" ] && printf '%s\\n' \"$GIT_REPO_ROOT\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"ls-files\" ] || [ \"$3\" = \"ls-files\" ]; then\n"
        "  [ -n \"${GIT_TRACKED:-}\" ] && printf '%b\\n' \"$GIT_TRACKED\"\n"
        "  exit 0\n"
        "fi\n"
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
    stale_skill = home / ".agents" / "skills" / "executive-pack" / "SKILL.md"
    stale_skill.parent.mkdir(parents=True)
    stale_skill.write_text("stale home projection\n", encoding="utf-8")
    authority_root = _write_core_authority(tmp_path)

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
    env["COGNOVIS_CORE_AUTHORITY_ROOT"] = str(authority_root)
    env["BEAD_LOOP_AUTHORITY_GIT_BIN"] = str(SYSTEM_GIT)
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
    assert "retired implicit multi-Bead mode" in result.stderr
    assert "--executive-pack" in result.stderr
    assert "explicit ordered same-repository Pack" in result.stderr


def test_cld_contains_no_wave_dispatch_prompt_or_help_entry() -> None:
    source = CLD_BIN.read_text(encoding="utf-8")

    assert "Wave orchestration request" not in source
    assert "Dispatch wave-orchestrator" not in source
    assert "cld -bw ${bead_id}" not in source
    assert "retired implicit multi-Bead mode" in source
    assert "explicit ordered same-repository Pack" in source


def test_cld_help_exposes_canonical_solo_and_executive_pack_modes(
    tmp_path: Path,
) -> None:
    result, _argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        ["--help"],
    )

    assert result.returncode == 0
    assert called_file.exists()
    assert "-sb, --solo-bead ID" in result.stdout
    assert "canonical single-Bead mode" in result.stdout
    assert "-ep, --executive-pack ID,ID" in result.stdout
    assert "explicit ordered same-repository" in result.stdout
    assert "-b,  --bead ID" in result.stdout
    assert "compatibility alias for --solo-bead" in result.stdout
    assert "-- [PROMPT]" in result.stdout
    assert "Separate caller prose from harness flags" in result.stdout


@pytest.mark.parametrize("flag", ["-sb", "--solo-bead", "-b", "--bead"])
def test_cld_solo_mode_emits_claude_family_role_contract_and_caller_override(
    tmp_path: Path,
    flag: str,
) -> None:
    caller_prompt = "Use Sonnet for implementation if Opus is unavailable."
    result, argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [flag, "CL-smoke", "--", caller_prompt],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    prompt = prompt_file.read_text(encoding="utf-8")
    assert "Solo Bead delivery" in prompt
    assert "execution_mode=auto" in prompt
    assert "Bead: CL-smoke" in prompt
    assert f"Repository: {tmp_path}" in prompt
    assert "distinct Opus implementation sub-agent" in prompt
    assert "Reviewer 1 is a fresh GPT-5.6-sol perspective with high reasoning" in prompt
    assert "Reviewer 2 is a fresh Kimi perspective" in prompt
    assert "fresh Opus fallback" in prompt
    assert "installed executive-pack and cognovis-beads skills" in prompt
    assert caller_prompt in prompt
    assert "Explicit caller role instructions override these defaults" in prompt
    assert "role separation" in prompt
    assert "Reviewer 1 and Reviewer 2 family diversity" in prompt
    assert "route_profile" not in prompt
    assert "cdx-bead-workflow.py" not in prompt
    assert argv.count(prompt) == 1
    assert caller_prompt not in argv[:-1]
    assert "Managed worktree label: bead-CL-smoke" in prompt


@pytest.mark.parametrize("flag", ["-ep", "--executive-pack"])
def test_cld_executive_pack_preserves_order_and_uses_one_session(
    tmp_path: Path,
    flag: str,
) -> None:
    caller_prompt = "Reviewer 2 may use DeepSeek when Kimi is unavailable."
    result, argv_file, prompt_file, called_file, bd_log = _run_cld(
        tmp_path,
        [flag, "CL-first,CL-second", "--", caller_prompt],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    prompt = prompt_file.read_text(encoding="utf-8")
    assert "Executive Pack delivery" in prompt
    assert "Ordered Beads: CL-first, CL-second" in prompt
    assert "installed executive-pack and cognovis-beads skills" in prompt
    assert caller_prompt in prompt
    assert caller_prompt not in argv[:-1]
    assert _argv_flag_value(argv, "--worktree") == "bead-pack-CL-first-CL-second"
    assert "Managed worktree label: bead-pack-CL-first-CL-second" in prompt
    calls = [json.loads(line) for line in bd_log.read_text(encoding="utf-8").splitlines()]
    assert ["show", "CL-first", "--json"] in calls
    assert ["show", "CL-second", "--json"] in calls


@pytest.mark.parametrize(
    ("args", "message", "env_overrides"),
    [
        (["-sb", "smoke"], "not an exact Bead ID", {}),
        (["-sb", "CL-one,CL-two"], "accepts exactly one", {}),
        (["-ep", "CL-one"], "at least two", {}),
        (["-ep", "CL-one,CL-one"], "duplicate Bead ID", {}),
        (["-sb", "CL-parent"], "executable leaf", {"BD_CHILD_COUNT": "1"}),
        (["-sb", "CL-closed"], "open, unclaimed", {"BD_STATUS": "closed"}),
        (["-sb", "CL-missing"], "not found in this repository", {"BD_MISSING_IDS": "CL-missing"}),
    ],
)
def test_cld_delivery_modes_reject_invalid_inputs_before_harness(
    tmp_path: Path,
    args: list[str],
    message: str,
    env_overrides: dict[str, str],
) -> None:
    result, _argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        args,
        env_overrides=env_overrides,
    )

    assert result.returncode == 2
    assert message in result.stderr
    assert not called_file.exists()


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


@pytest.mark.parametrize(
    ("flag", "execution_mode"),
    [("-bq", "quick")],
)
def test_regression_cld_bead_modes_use_current_core_authority(
    tmp_path: Path,
    flag: str,
    execution_mode: str,
) -> None:
    result, argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [flag, "CL-smoke"],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    prompt = prompt_file.read_text(encoding="utf-8")
    expected_revision = subprocess.run(
        [SYSTEM_GIT, "-C", tmp_path / "cognovis-core-authority", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert f"Git revision {expected_revision}" in prompt
    assert _argv_flag_value(argv, "--agent") is None
    assert "executive-pack" in prompt
    assert f"execution_mode={execution_mode}" in prompt
    assert "caller route `claude-manual`" in prompt
    assert "cognovis-core-authority" in prompt
    assert "skills/bead-execution-loop/SKILL.md" in prompt
    assert "agents/bead-implementer.md" in prompt
    assert "revision-bound source files supersede same-named home-scoped projections" in prompt
    assert "stale home projection" not in prompt
    assert "installed bead-implementation-loop" not in prompt
    if execution_mode == "quick":
        assert "unconditional explicit Quick" in prompt
        # CL-3gdz: -bq forces the quick tier unconditionally, bypassing the
        # size/effort eligibility gate.
        assert "force_tier=quick" in prompt


def test_cld_active_bead_entrypoint_has_no_legacy_policy_authority() -> None:
    source = CLD_BIN.read_text(encoding="utf-8")

    # CL-3gdz: force_tier is no longer banned — -bq now forces the quick tier
    # (force_tier=quick) to bypass the size/effort eligibility gate. It is a tier
    # declaration, not orchestrator routing authority, so it stays out of this
    # ban list while phase0/route_profile/adapter routing remain forbidden.
    for banned in (
        "phase0-claim.py",
        "requested_workflow",
        "route_profile",
        'claude_args+=("--agent" "bead-orchestrator")',
        "codex-impl",
        "codex-exec",
    ):
        assert banned not in source

    delivery_source = source.split("_launch_repository_delivery()", 1)[1].split(
        "_claude_args_have_model()", 1
    )[0]
    for banned in (
        "_resolve_bead_loop_authority",
        "cdx-bead-workflow.py",
        "--implementer",
        "--reviewer-1",
        "--reviewer-2",
        "json.dumps",
    ):
        assert banned not in delivery_source
    assert 'bead_id=""' not in source.splitlines()
    assert 'if [[ -n "$bead_id" ]]' not in source


def test_cld_delivery_mode_preserves_harness_flags_after_mode_and_uses_prompt_boundary(
    tmp_path: Path,
) -> None:
    caller_prompt = "Use Sonnet for implementation -- exactly as written."
    result, argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [
            "-sb",
            "CL-smoke",
            "--model",
            "opus",
            "--",
            caller_prompt,
        ],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    prompt = prompt_file.read_text(encoding="utf-8")
    assert _argv_flag_value(argv, "--model") == "opus"
    assert caller_prompt not in argv
    assert prompt.count(caller_prompt) == 1


def test_cld_delivery_preserves_unlisted_harness_flag_values_before_prompt(
    tmp_path: Path,
) -> None:
    caller_prompt = "Keep this caller prose unchanged."
    result, argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [
            "-sb",
            "CL-smoke",
            "--agent",
            "my-agent",
            "--append-system-prompt",
            "extra rules",
            "--",
            caller_prompt,
        ],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    prompt = prompt_file.read_text(encoding="utf-8")
    assert _argv_flag_value(argv, "--agent") == "my-agent"
    assert _argv_flag_value(argv, "--append-system-prompt") == "extra rules"
    assert argv[-2:] == ["--", prompt]
    assert prompt.count(caller_prompt) == 1


def test_cld_delivery_keeps_launcher_owned_flags_effectively_last(
    tmp_path: Path,
) -> None:
    result, argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [
            "-sb",
            "CL-smoke",
            "--worktree",
            "caller-label",
            "--agent",
            "my-agent",
            "--setting-sources",
            "user",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    prompt = prompt_file.read_text(encoding="utf-8")
    worktree_values = [
        argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "--worktree"
    ]
    setting_source_values = [
        argv[index + 1]
        for index, value in enumerate(argv[:-1])
        if value == "--setting-sources"
    ]
    assert worktree_values[-1] == "bead-CL-smoke"
    assert setting_source_values[-1] == "user,project,local"
    assert _argv_flag_value(argv, "--agent") == "my-agent"
    assert argv[-2:] == ["--", prompt]


def test_cld_plain_mode_forwards_double_dash_and_following_tokens(tmp_path: Path) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        ["--", "hello", "world"],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    assert json.loads(argv_file.read_text(encoding="utf-8"))[-3:] == [
        "--",
        "hello",
        "world",
    ]


@pytest.mark.parametrize(
    "args",
    [
        ["-sb", "CL-smoke"],
        ["-ep", "CL-first,CL-second"],
    ],
)
def test_cld_delivery_syncs_before_native_worktree_launch(
    tmp_path: Path,
    args: list[str],
) -> None:
    sync_log = tmp_path / "sync.log"
    result, _argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        args,
        env_overrides={"SYNC_LOG": str(sync_log)},
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    events = sync_log.read_text(encoding="utf-8").splitlines()
    fetch_index = events.index("git fetch origin")
    pull_index = events.index("git pull --no-rebase")
    dolt_index = events.index("bd dolt pull")
    launch_index = events.index("claude launch")
    assert fetch_index < pull_index < dolt_index < launch_index


@pytest.mark.parametrize("flag", ["-b", "-bq"])
def test_cld_bead_modes_reject_parent_before_git_or_harness(
    tmp_path: Path,
    flag: str,
) -> None:
    git_called = tmp_path / "git-called"
    _write_executable(
        tmp_path / "git",
        "#!/bin/sh\n"
        "touch \"$GIT_CALLED_FILE\"\n"
        "exit 0\n",
    )

    result, _argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [flag, "CL-parent"],
        env_overrides={
            "BD_CHILD_COUNT": "1",
            "GIT_CALLED_FILE": str(git_called),
        },
    )

    assert result.returncode == 2
    assert "has 1 children" in result.stderr
    assert not git_called.exists()
    assert not called_file.exists()


@pytest.mark.parametrize("flag", ["-sb", "-b", "-bq"])
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
    assert "Session Close" in prompt
    assert "Normal progress updates are NOT intervention events and must NOT trigger the callback." in prompt
    assert "If cmux is unavailable, skip the flash (best-effort)" in prompt


def test_cld_executive_pack_with_callback_preserves_session_close_contract(
    tmp_path: Path,
) -> None:
    result, argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [
            "-ep",
            "CL-first,CL-second",
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
    assert "workspace:15 / surface:33" in prompt
    assert "cmux trigger-flash --surface surface:33" in prompt
    assert "Session Close" in prompt


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


def test_cld_bead_review_dispatches_through_acpx_runner(tmp_path: Path) -> None:
    """ADR-0009: -br owns no dispatch client; the session routes the reviewer."""
    result, argv_file, _prompt_file, called_file, bd_log = _run_cld(
        tmp_path, ["-br", "CL-smoke"]
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    assert "CLD_BEAD_LINE=cld" in result.stdout
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    prompt = argv[-1]
    assert "CL-smoke" in prompt
    assert "acpx-runner" in prompt
    assert "LEAD_FAMILY=claude" in prompt
    assert "CONTRACT=review_gate_v1" in prompt
    # The reviewer model comes from the routing standard, not the launcher.
    assert "--model" not in argv
    assert "--provider" not in argv
    assert "--adapter" not in argv
    assert "--worktree" not in argv
    assert "--agent" not in argv
    bd_calls = [json.loads(line) for line in bd_log.read_text(encoding="utf-8").splitlines()]
    assert not any(call[:1] == ["dolt"] for call in bd_calls)


def test_cld_bead_review_rejects_explicit_model_override(tmp_path: Path) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        ["-br", "CL-smoke", "--model", "sonnet"],
    )

    assert result.returncode == 2
    assert not called_file.exists()
    assert "resolves its reviewer from capabilities" in result.stderr


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
    assert "LEAD_FAMILY=claude" in argv[-1]


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


def _seed_main_checkout_overlays(tmp_path: Path) -> Path:
    """Create the gitignored overlay content a real main checkout carries."""
    main = tmp_path / "main"
    (main / ".agents" / "skills" / "session-close").mkdir(parents=True)
    (main / ".agents" / "pi").mkdir(parents=True)
    (main / ".claude" / "skills" / "beads").mkdir(parents=True)
    (main / ".env").write_text("TOKEN=value\n", encoding="utf-8")
    return main


@pytest.mark.parametrize("flag", ["-b", "-bq"])
def test_cld_bead_modes_configure_worktree_overlay_symlinks(
    tmp_path: Path,
    flag: str,
) -> None:
    """AC2: cld hands the overlay set to Claude Code's native worktree symlinks.

    Claude Code creates the worktree itself, so the wrapper cannot symlink into
    it. It resolves the overlay set from the main checkout's index instead and
    passes it as worktree.symlinkDirectories.
    """
    main = _seed_main_checkout_overlays(tmp_path)

    result, argv_file, _prompt_file, _called_file, _bd_log = _run_cld(
        tmp_path,
        [flag, "CL-smoke"],
        env_overrides={"GIT_REPO_ROOT": str(main), "GIT_TRACKED": ".agents/pi/cli.ts"},
    )

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--worktree" in argv
    settings = json.loads(_argv_flag_value(argv, "--settings") or "{}")
    # .agents is partly tracked, so only its missing child is linked; .env is a
    # file and symlinkDirectories takes directories only.
    assert settings == {
        "worktree": {"symlinkDirectories": [".agents/skills", ".claude/skills"]}
    }


def test_cld_bead_mode_omits_overlay_settings_outside_a_repository(
    tmp_path: Path,
) -> None:
    result, argv_file, _prompt_file, _called_file, _bd_log = _run_cld(
        tmp_path,
        ["-b", "CL-smoke"],
    )

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_flag_value(argv, "--settings") is None


def test_cld_worktree_overlay_settings_can_be_disabled(tmp_path: Path) -> None:
    main = _seed_main_checkout_overlays(tmp_path)

    result, argv_file, _prompt_file, _called_file, _bd_log = _run_cld(
        tmp_path,
        ["-b", "CL-smoke"],
        env_overrides={"GIT_REPO_ROOT": str(main), "CLD_WORKTREE_OVERLAYS": ""},
    )

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_flag_value(argv, "--settings") is None


def test_cld_worktree_overlay_settings_honor_an_explicit_overlay_list(
    tmp_path: Path,
) -> None:
    main = _seed_main_checkout_overlays(tmp_path)

    result, argv_file, _prompt_file, _called_file, _bd_log = _run_cld(
        tmp_path,
        ["-b", "CL-smoke"],
        env_overrides={
            "GIT_REPO_ROOT": str(main),
            "CLD_WORKTREE_OVERLAYS": ".claude/skills",
        },
    )

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    settings = json.loads(_argv_flag_value(argv, "--settings") or "{}")
    assert settings == {"worktree": {"symlinkDirectories": [".claude/skills"]}}


def test_cld_preserves_a_caller_supplied_settings_argument(tmp_path: Path) -> None:
    """A caller's own --settings must win; claude takes the last one."""
    main = _seed_main_checkout_overlays(tmp_path)
    caller_settings = str(tmp_path / "caller-settings.json")

    result, argv_file, _prompt_file, _called_file, _bd_log = _run_cld(
        tmp_path,
        ["-b", "CL-smoke", "--settings", caller_settings],
        env_overrides={"GIT_REPO_ROOT": str(main)},
    )

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert argv.count("--settings") == 1
    assert _argv_flag_value(argv, "--settings") == caller_settings
