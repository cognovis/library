"""Regression tests for cld launcher permission defaults.

Role-scope audit for launcher-dispatched bead roles:
- cld/cdx -b and -bq are orchestrator entry points that keep broad workflow
  permissions while constraining implementer execution to bead worktrees.
- cld/cdx -br are reviewer entry points and must default to read-only review
  scope at the launcher boundary.
- No cld/cdx/cra verifier launcher entry point exists today; verification is
  dispatched through scoped subagents/adapters outside this launcher surface.
- cra has no bead-role dispatch surface.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


CLD_BIN = Path(__file__).resolve().parents[1] / "bin" / "cld"
UNTRUSTED_MARKER = "ZZZ_UNTRUSTED_BEAD_FIELD_MARKER_ZZZ"


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
        "prompt = sys.argv[-1] if len(sys.argv) > 1 else ''\n"
        "pathlib.Path(os.environ['CLAUDE_PROMPT_FILE']).write_text(prompt, encoding='utf-8')\n",
    )
    return claude_mock, argv_file, prompt_file, called_file


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
        "if args[:2] == ['dolt', 'pull']:\n"
        "    raise SystemExit(0)\n"
        "if len(args) >= 2 and args[0] == 'show':\n"
        "    bead_id = args[1]\n"
        "    if '--children' in args:\n"
        "        print(json.dumps({bead_id: []}))\n"
        "    else:\n"
        "        print(json.dumps([{\n"
        "            'id': bead_id,\n"
        "            'status': os.environ.get('BD_STATUS', 'open'),\n"
        f"            'title': 'title {UNTRUSTED_MARKER}',\n"
        f"            'description': 'description {UNTRUSTED_MARKER}',\n"
        f"            'notes': 'notes {UNTRUSTED_MARKER}',\n"
        f"            'acceptance_criteria': 'acceptance {UNTRUSTED_MARKER}',\n"
        "        }]))\n"
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


def _run_cld(tmp_path: Path, args: list[str]) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path, Path]:
    claude_mock, argv_file, prompt_file, called_file = _write_claude_capture(tmp_path)
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
    env["BD_BIN"] = str(bd_mock)
    env["BD_ARGV_LOG"] = str(bd_log)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(CLD_BIN), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env=env,
    )
    return result, argv_file, prompt_file, called_file, bd_log


def _argv_has_permission_mode(argv: list[str], mode: str) -> bool:
    return any(left == "--permission-mode" and right == mode for left, right in zip(argv, argv[1:]))


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


def _argv_has_flag(argv: list[str], flag: str) -> bool:
    """True if `flag` appears bare, as "--flag=value", or as "--flag" "value"."""
    prefix = f"{flag}="
    return any(token == flag or token.startswith(prefix) for token in argv)


# Deterministic narrow review tool profile for cld -br (CL-9knh). General
# Bash is NOT granted: Bash can mutate files/bead state regardless of
# Edit/Write/NotebookEdit being disallowed (e.g. `uv run python -c
# "os.remove(...)"` or arbitrary shell one-liners), so "read-only by
# convention" is not an enforceable boundary. The ONLY Bash grant -br ever
# makes is a single exact-match entry for the coordinator callback's
# terminal-state signal (see BEAD_REVIEW_ALLOWED_TOOLS_WITH_CALLBACK below),
# added only when both --coordinator-workspace/--coordinator-surface are
# present.
BEAD_REVIEW_ALLOWED_TOOLS = (
    "Read,Grep,Glob,"
    "mcp__cognovis-tools__bead_show,mcp__cognovis-tools__bead_search,"
    "mcp__cognovis-tools__bead_list,mcp__cognovis-tools__bead_repos,"
    "mcp__cognovis-tools__bead_ready,mcp__cognovis-tools__bead_review_write"
)


def bead_review_allowed_tools_with_callback(surface: str) -> str:
    """The -br allowedTools value when a coordinator callback is present:
    BEAD_REVIEW_ALLOWED_TOOLS plus exactly one EXACT-match (no trailing "*")
    Bash grant scoped to the single cmux trigger-flash invocation for the
    given validated surface value.
    """
    return f"{BEAD_REVIEW_ALLOWED_TOOLS},Bash(cmux trigger-flash --surface {surface})"


BEAD_REVIEW_DISALLOWED_TOOLS = (
    "Edit,Write,NotebookEdit,"
    "mcp__cognovis-tools__bead_create,mcp__cognovis-tools__bead_claim,"
    "mcp__cognovis-tools__bead_update,mcp__cognovis-tools__bead_update_notes,"
    "mcp__cognovis-tools__bead_close,mcp__cognovis-tools__bead_dep_add,"
    "mcp__cognovis-tools__bead_dep_remove,mcp__cognovis-tools__bead_dolt_sync"
)


def test_cld_bead_review_allowed_tools_include_all_required_read_tools(tmp_path: Path) -> None:
    """AK4 negative matrix: reject missing read tools in the -br profile."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    allowed = _argv_flag_value(argv, "--allowedTools")
    assert allowed is not None, "missing --allowedTools flag: no read tools would be granted under plan mode"
    allowed_set = set(allowed.split(","))
    required_read_tools = {
        "Read",
        "Grep",
        "Glob",
        "mcp__cognovis-tools__bead_show",
        "mcp__cognovis-tools__bead_search",
        "mcp__cognovis-tools__bead_list",
        "mcp__cognovis-tools__bead_repos",
        "mcp__cognovis-tools__bead_ready",
        "mcp__cognovis-tools__bead_review_write",
    }
    missing = required_read_tools - allowed_set
    assert not missing, f"missing required read tools in --allowedTools: {missing}"
    assert allowed == BEAD_REVIEW_ALLOWED_TOOLS


def test_cld_bead_review_allowed_tools_exclude_bash_without_callback(tmp_path: Path) -> None:
    """Finding 1/3: Bash must be entirely absent from --allowedTools when no
    coordinator callback flags are passed — not even a narrowed pattern."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    allowed = _argv_flag_value(argv, "--allowedTools")
    assert allowed is not None
    allowed_set = set(allowed.split(","))
    assert "Bash" not in allowed_set
    assert not any(tool.startswith("Bash(") for tool in allowed_set)
    assert "Bash" not in allowed


def test_cld_bead_review_disallowed_tools_block_all_general_mutations(tmp_path: Path) -> None:
    """AK4 negative matrix: reject leaked general bead mutations in the -br profile."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    disallowed = _argv_flag_value(argv, "--disallowedTools")
    assert disallowed is not None, "missing --disallowedTools flag: no defense-in-depth against mutation leakage"
    disallowed_set = set(disallowed.split(","))
    forbidden_mutations = {
        "Edit",
        "Write",
        "NotebookEdit",
        "mcp__cognovis-tools__bead_create",
        "mcp__cognovis-tools__bead_claim",
        "mcp__cognovis-tools__bead_update",
        "mcp__cognovis-tools__bead_update_notes",
        "mcp__cognovis-tools__bead_close",
        "mcp__cognovis-tools__bead_dep_add",
        "mcp__cognovis-tools__bead_dep_remove",
        "mcp__cognovis-tools__bead_dolt_sync",
    }
    missing = forbidden_mutations - disallowed_set
    assert not missing, f"leaked general mutation tools not blocked by --disallowedTools: {missing}"
    assert disallowed == BEAD_REVIEW_DISALLOWED_TOOLS
    # bead_review_write is the ONE allowed mutation exception — it must never
    # be blocked, or the reviewer could not write metadata.review.
    assert "mcp__cognovis-tools__bead_review_write" not in disallowed_set


def test_cld_bead_review_allowed_and_disallowed_tools_do_not_overlap(tmp_path: Path) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    allowed_value = _argv_flag_value(argv, "--allowedTools")
    disallowed_value = _argv_flag_value(argv, "--disallowedTools")
    assert allowed_value is not None
    assert disallowed_value is not None
    allowed_set = set(allowed_value.split(","))
    disallowed_set = set(disallowed_value.split(","))
    assert not (allowed_set & disallowed_set), "a tool cannot be both allowed and disallowed"


def test_cld_bead_review_still_uses_plan_mode_with_tool_profile(tmp_path: Path) -> None:
    """AK4 negative matrix: reject non-plan-mode regression once the tool profile is added."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_has_permission_mode(argv, "plan")
    assert not _argv_has_permission_mode(argv, "auto")
    assert not _argv_has_permission_mode(argv, "acceptEdits")
    assert not _argv_has_permission_mode(argv, "bypassPermissions")
    assert "--dangerously-skip-permissions" not in argv


def test_cld_bead_review_callback_contract_unaffected_by_tool_profile(tmp_path: Path) -> None:
    """AK4 negative matrix: reject callback regression once the tool profile is added."""
    result, argv_file, prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [
            "-br",
            "CL-safe",
            "--coordinator-workspace",
            "workspace:15",
            "--coordinator-surface",
            "surface:33",
        ],
    )

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    prompt = prompt_file.read_text(encoding="utf-8")
    assert _argv_flag_value(argv, "--allowedTools") == bead_review_allowed_tools_with_callback("surface:33")
    assert _argv_flag_value(argv, "--disallowedTools") == BEAD_REVIEW_DISALLOWED_TOOLS
    assert "Coordinator callback" in prompt
    assert "cmux trigger-flash --surface surface:33" in prompt
    # The review prompt must remain the last positional claude argument even
    # with the new variadic-flag values inserted ahead of it.
    assert argv[-1] == prompt


def test_cld_bead_review_callback_grant_is_structurally_pure(tmp_path: Path) -> None:
    """Finding 3.2: the cmux callback exception must be exactly one narrow
    Bash grant and must not be widenable into a general shell escape.

    Asserts the generated --allowedTools value contains the entry
    `Bash(cmux trigger-flash --surface surface:33)` VERBATIM with no
    trailing "*", and that the full --allowedTools string contains none of
    "*", ";", "&&", "|", "$(" anywhere.
    """
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [
            "-br",
            "CL-safe",
            "--coordinator-workspace",
            "workspace:15",
            "--coordinator-surface",
            "surface:33",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    allowed = _argv_flag_value(argv, "--allowedTools")
    assert allowed is not None
    assert "Bash(cmux trigger-flash --surface surface:33)" in allowed
    assert "Bash(cmux trigger-flash --surface surface:33)*" not in allowed
    for forbidden in ("*", ";", "&&", "|", "$("):
        assert forbidden not in allowed, f"forbidden shell-escape substring {forbidden!r} found in --allowedTools"
    # Exactly one Bash entry — the exact-match cmux grant — no other Bash
    # pattern of any kind.
    allowed_tools = allowed.split(",")
    bash_entries = [tool for tool in allowed_tools if tool == "Bash" or tool.startswith("Bash(")]
    assert bash_entries == ["Bash(cmux trigger-flash --surface surface:33)"]


def test_cld_bead_review_model_override_preserves_tool_profile(tmp_path: Path) -> None:
    """AK4 negative matrix: reject model-override regression once the tool profile is added."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path, ["-br", "CL-safe", "--model", "sonnet"]
    )

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_flag_value(argv, "--model") == "sonnet"
    assert "opus" not in argv
    assert _argv_flag_value(argv, "--allowedTools") == BEAD_REVIEW_ALLOWED_TOOLS
    assert _argv_flag_value(argv, "--disallowedTools") == BEAD_REVIEW_DISALLOWED_TOOLS


@pytest.mark.parametrize("args", [["-b", "CL-safe"], ["-bq", "CL-safe"]])
def test_cld_bead_review_tool_profile_does_not_leak_into_implementer_modes(
    tmp_path: Path,
    args: list[str],
) -> None:
    """The narrow -br-only tool profile must never reach -b/-bq (implementer) dispatch."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert not _argv_has_flag(argv, "--allowedTools")
    assert not _argv_has_flag(argv, "--disallowedTools")


@pytest.mark.parametrize(
    "args",
    [
        ["Plain passthrough prompt"],
        ["-b", "CL-safe"],
        ["-bq", "CL-safe"],
    ],
)
def test_cld_defaults_to_permission_auto_without_dangerous_skip(
    tmp_path: Path,
    args: list[str],
) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--dangerously-skip-permissions" not in argv
    assert _argv_has_permission_mode(argv, "auto")


def test_cld_bead_review_defaults_to_plan_mode_without_dangerous_skip(tmp_path: Path) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--dangerously-skip-permissions" not in argv
    assert not _argv_has_permission_mode(argv, "auto")
    assert _argv_has_permission_mode(argv, "plan")


@pytest.mark.parametrize(
    "args",
    [
        ["--skip-perms", "Plain passthrough prompt"],
        ["--skip-perms", "-b", "CL-safe"],
        ["--skip-perms", "-bq", "CL-safe"],
        ["--skip-perms", "-br", "CL-safe"],
    ],
)
def test_cld_skip_perms_explicitly_uses_dangerous_skip_and_warns(
    tmp_path: Path,
    args: list[str],
) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--dangerously-skip-permissions" in argv
    assert not _argv_has_permission_mode(argv, "auto")
    assert not _argv_has_permission_mode(argv, "plan")
    stderr = result.stderr.lower()
    assert "warning" in stderr
    assert "dangerously-skip-permissions" in stderr


@pytest.mark.parametrize(
    ("args", "expected_worktree", "expected_agent"),
    [
        (["-b", "CL-safe"], "bead-CL-safe", "bead-orchestrator"),
        (["-bq", "CL-safe"], "bead-CL-safe", "quick-fix"),
    ],
)
def test_cld_implementer_modes_use_bead_worktree_scope(
    tmp_path: Path,
    args: list[str],
    expected_worktree: str,
    expected_agent: str,
) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    worktree_index = argv.index("--worktree")
    assert argv[worktree_index + 1] == expected_worktree
    agent_index = argv.index("--agent")
    assert argv[agent_index + 1] == expected_agent


def test_cld_bead_review_does_not_use_implementation_worktree(tmp_path: Path) -> None:
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--worktree" not in argv


def test_cld_help_has_no_verifier_launcher_entry_point(tmp_path: Path) -> None:
    result, _argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["--help"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    assert "-bv" not in result.stdout
    assert "--bead-verify" not in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["-b", "CL-safe", "--route-profile", "cld-composer", "--force-tier", "infra"],
        ["-bq", "CL-safe", "--route-profile", "cld-composer", "--force-tier", "infra"],
    ],
)
def test_cld_bead_prompt_does_not_embed_raw_bead_fields(
    tmp_path: Path,
    args: list[str],
) -> None:
    result, _argv_file, prompt_file, called_file, bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    bd_calls = [json.loads(line) for line in bd_log.read_text(encoding="utf-8").splitlines()]
    assert any(call[:2] == ["show", "CL-safe"] for call in bd_calls)
    prompt = prompt_file.read_text(encoding="utf-8")
    assert "Bead ID: CL-safe" in prompt
    assert "Portless namespace: CL-safe" in prompt
    assert UNTRUSTED_MARKER not in prompt
