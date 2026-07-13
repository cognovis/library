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
import time

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


def _write_cld_path_mocks(tmp_path: Path, cmux_log: Path | None = None) -> None:
    _write_executable(
        tmp_path / "git",
        "#!/bin/sh\n"
        "exit 0\n",
    )
    if cmux_log is None:
        _write_executable(
            tmp_path / "cmux",
            "#!/bin/sh\n"
            "exit 1\n",
        )
    else:
        _write_executable(
            tmp_path / "cmux",
            f"#!{sys.executable}\n"
            "import json, os, pathlib, sys\n"
            f"log = pathlib.Path({str(cmux_log)!r})\n"
            "with log.open('a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "raise SystemExit(0)\n",
        )


def _run_cld(
    tmp_path: Path,
    args: list[str],
    cmux_log: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path, Path]:
    claude_mock, argv_file, prompt_file, called_file = _write_claude_capture(tmp_path)
    bd_mock, bd_log = _write_bd_mock(tmp_path)
    _write_cld_path_mocks(tmp_path, cmux_log=cmux_log)
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


# Deterministic narrow review tool profile for cld -br (CL-9knh, fix-cycle 2).
# Bash is HARD-EXCLUDED via --tools (the built-in tool-set flag), not merely
# left ungranted in --allowedTools: empirical testing showed Claude Code's
# plan-mode classifier can silently auto-approve Bash invocations that "look
# safe" (e.g. `git status`) regardless of --allowedTools/--disallowedTools
# content, as long as Bash is registered as an available tool at all — even
# when --allowedTools only contains one exact-match Bash(...) entry for a
# completely different command. Only removing Bash from the --tools built-in
# set (not just the allow/deny lists) makes it genuinely unavailable. This
# profile is therefore a SINGLE fixed string — no callback-conditional Bash
# grant exists anymore. See BEAD_REVIEW_TOOLS below for the --tools value
# that performs the actual hard exclusion.
BEAD_REVIEW_ALLOWED_TOOLS = (
    "Read,Grep,Glob,"
    "mcp__cognovis-tools__bead_show,mcp__cognovis-tools__bead_search,"
    "mcp__cognovis-tools__bead_list,mcp__cognovis-tools__bead_repos,"
    "mcp__cognovis-tools__bead_ready,mcp__cognovis-tools__bead_review_write"
)


# --tools value that hard-excludes Bash from the built-in tool set for -br
# (unconditionally, callback or not). This is what genuinely makes Bash
# unavailable — --allowedTools/--disallowedTools alone only govern
# approval-without-prompting for tools that ARE registered.
BEAD_REVIEW_TOOLS = "Read,Grep,Glob"


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


@pytest.mark.parametrize(
    "args",
    [
        ["-br", "CL-safe"],
        [
            "-br",
            "CL-safe",
            "--coordinator-workspace",
            "workspace:15",
            "--coordinator-surface",
            "surface:33",
        ],
    ],
    ids=["no-callback", "with-callback"],
)
def test_cld_bead_review_allowed_tools_exclude_bash_always(tmp_path: Path, args: list[str]) -> None:
    """Fix-cycle 2: Bash must be entirely absent from --allowedTools in BOTH
    the callback and no-callback cases — not even a narrowed exact-match
    pattern. The old design granted a single exact-match Bash(...) entry for
    the coordinator callback; that design is abandoned because Claude Code's
    plan-mode classifier can auto-approve unrelated Bash commands once Bash
    is registered as available at all, regardless of --allowedTools content.
    Bash exclusion is now enforced via --tools (see
    test_cld_bead_review_tools_flag_hard_excludes_bash_always)."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    allowed = _argv_flag_value(argv, "--allowedTools")
    assert allowed is not None
    allowed_set = set(allowed.split(","))
    assert "Bash" not in allowed_set
    assert not any(tool.startswith("Bash(") for tool in allowed_set)
    assert "Bash" not in allowed
    assert allowed == BEAD_REVIEW_ALLOWED_TOOLS


@pytest.mark.parametrize(
    "args",
    [
        ["-br", "CL-safe"],
        [
            "-br",
            "CL-safe",
            "--coordinator-workspace",
            "workspace:15",
            "--coordinator-surface",
            "surface:33",
        ],
    ],
    ids=["no-callback", "with-callback"],
)
def test_cld_bead_review_tools_flag_hard_excludes_bash_always(tmp_path: Path, args: list[str]) -> None:
    """Fix 1 (CL-9knh fix-cycle 2): --tools=Read,Grep,Glob must be present in
    argv for EVERY -br invocation, callback or not — this is what actually
    removes Bash from the built-in tool set (--allowedTools/--disallowedTools
    alone only govern approval-without-prompting for tools that ARE
    registered, which was empirically shown to be insufficient)."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_flag_value(argv, "--tools") == BEAD_REVIEW_TOOLS


@pytest.mark.parametrize("args", [["-b", "CL-safe"], ["-bq", "CL-safe"]])
def test_cld_bead_review_tools_flag_does_not_leak_into_implementer_modes(
    tmp_path: Path,
    args: list[str],
) -> None:
    """The -br-only --tools hard exclusion must never reach -b/-bq
    (implementer) dispatch — those modes need full Bash access."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert not _argv_has_flag(argv, "--tools")


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


def test_cld_bead_review_uses_dontask_mode_with_tool_profile(tmp_path: Path) -> None:
    """AK4 negative matrix, updated for CL-9knh iteration 3: -br must use
    `dontAsk`, not `plan` or any other mode. `--permission-mode plan` was
    found (via independent live probes — see bead CL-9knh notes) to
    categorically block MCP tool execution even for tools explicitly present
    in --allowedTools, which defeats the whole point of the -br tool
    profile. `dontAsk` was verified via a live `claude --print
    --permission-mode dontAsk ...` dry-run to allow allowlisted tools while
    still honoring --disallowedTools."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_has_permission_mode(argv, "dontAsk")
    assert not _argv_has_permission_mode(argv, "auto")
    assert not _argv_has_permission_mode(argv, "acceptEdits")
    assert not _argv_has_permission_mode(argv, "bypassPermissions")
    assert not _argv_has_permission_mode(argv, "plan")
    assert not _argv_has_permission_mode(argv, "manual")
    assert "--dangerously-skip-permissions" not in argv


def test_cld_bead_review_dontask_mode_grants_full_allowed_tools_together(tmp_path: Path) -> None:
    """CL-9knh iteration 3 positive-case coverage: prove the ARGV-level
    contract that --permission-mode dontAsk and the full expected
    --allowedTools profile are emitted TOGETHER for the same -br invocation.

    This repo's launcher test harness mocks the `claude` binary (it only
    captures argv/prompt — see _write_claude_capture) and this suite has no
    precedent for live-binary tests that exercise real Claude Code
    permission/tool-execution behavior (tests/smoke/ only checks filesystem
    install paths, never invokes a live Claude Code session — see
    tests/smoke/README.md "Known Limitations"). Introducing a live,
    API-key-dependent test here would break this suite's fast/hermetic
    design (~15-20s via subprocess mocks). The actual runtime claim this
    fix depends on — "an allowlisted MCP tool call succeeds under dontAsk,
    where it was denied under plan" — is therefore proven by the live AK5
    smoke run against an uncached bead (coordinator-run, outside this
    suite), not by a unit test. This test only guards the argv shape that
    makes that runtime behavior possible.
    """
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_flag_value(argv, "--permission-mode") == "dontAsk"
    assert _argv_flag_value(argv, "--allowedTools") == BEAD_REVIEW_ALLOWED_TOOLS


def test_cld_bead_review_dontask_mode_still_blocks_all_mutations(tmp_path: Path) -> None:
    """CL-9knh iteration 3 negative-case coverage: switching -br's
    permission mode from `plan` to `dontAsk` must not widen the tool
    profile. --tools stays hard-limited to Read,Grep,Glob (Bash excluded),
    and --disallowedTools still carries the full mutation blocklist with
    Edit/Write/NotebookEdit absent from --allowedTools."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_flag_value(argv, "--permission-mode") == "dontAsk"
    assert _argv_flag_value(argv, "--tools") == BEAD_REVIEW_TOOLS
    assert _argv_flag_value(argv, "--disallowedTools") == BEAD_REVIEW_DISALLOWED_TOOLS
    allowed_set = set(_argv_flag_value(argv, "--allowedTools").split(","))
    assert "Bash" not in allowed_set
    assert "Edit" not in allowed_set
    assert "Write" not in allowed_set
    assert "NotebookEdit" not in allowed_set


def test_cld_bead_review_callback_contract_unaffected_by_tool_profile(tmp_path: Path) -> None:
    """Fix-cycle 2: the -br callback contract still fires (prompt text +
    --tools/--allowedTools/--disallowedTools profile), but the reviewer no
    longer has Bash to run cmux trigger-flash itself — the launcher runs it
    post-exit instead (see launcher-side flash coverage below)."""
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
    assert _argv_flag_value(argv, "--tools") == BEAD_REVIEW_TOOLS
    assert _argv_flag_value(argv, "--allowedTools") == BEAD_REVIEW_ALLOWED_TOOLS
    assert _argv_flag_value(argv, "--disallowedTools") == BEAD_REVIEW_DISALLOWED_TOOLS
    assert "Coordinator callback" in prompt
    assert "no Bash access" in prompt
    assert "cmux trigger-flash --surface surface:33" in prompt
    assert "you do not need to, and cannot, run it yourself" in prompt
    # The review prompt must remain the last positional claude argument even
    # with the new variadic-flag values inserted ahead of it.
    assert argv[-1] == prompt


def test_cld_bead_review_callback_no_longer_grants_any_bash_permission_string(tmp_path: Path) -> None:
    """Fix-cycle 2: the OLD exact-match `Bash(cmux trigger-flash --surface
    ...)` --allowedTools grant is fully removed, not just narrowed further.
    No argv token for -br (with a coordinator callback present) may contain
    the substring "Bash(" or the bare string "Bash" anywhere — confirming
    the coordinator-surface value is no longer interpolated into any Bash
    permission string at all. Bash exclusion now happens exclusively via
    --tools (see test_cld_bead_review_tools_flag_hard_excludes_bash_always).
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
    for token in argv:
        assert "Bash(" not in token, f"unexpected Bash(...) permission string in argv: {token!r}"
        assert token != "Bash"
    assert _argv_flag_value(argv, "--tools") == BEAD_REVIEW_TOOLS


def test_cld_bead_review_model_override_preserves_tool_profile(tmp_path: Path) -> None:
    """AK4 negative matrix: reject model-override regression once the tool profile is added."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path, ["-br", "CL-safe", "--model", "sonnet"]
    )

    assert result.returncode == 0, result.stderr
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_flag_value(argv, "--model") == "sonnet"
    assert "opus" not in argv
    assert _argv_flag_value(argv, "--tools") == BEAD_REVIEW_TOOLS
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
    assert not _argv_has_flag(argv, "--tools")


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


def test_cld_bead_review_defaults_to_dontask_mode_without_dangerous_skip(tmp_path: Path) -> None:
    """CL-9knh iteration 3: -br defaults to `dontAsk` (not `plan` or
    `auto`) without --skip-perms."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--dangerously-skip-permissions" not in argv
    assert not _argv_has_permission_mode(argv, "auto")
    assert not _argv_has_permission_mode(argv, "plan")
    assert _argv_has_permission_mode(argv, "dontAsk")


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
    assert not _argv_has_permission_mode(argv, "dontAsk")
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


# ── Launcher-side cmux flash (Fix 2, CL-9knh fix-cycle 2) ─────────────────
# With Bash hard-excluded from -br's tool set, the reviewer session can no
# longer run `cmux trigger-flash` itself. bin/cld now runs the claude
# subprocess as a foreground child for -br (instead of `exec`-replacing
# itself), captures its exit code, and — only when a coordinator callback is
# present — invokes `cmux trigger-flash --surface ${coordinator_surface}`
# from the launcher's OWN process after the subprocess exits, then exits
# with the captured code. These tests extend the mock `cmux` binary to log
# its invocations so the flash's origin (launcher vs. claude subprocess) is
# provable by construction, not by timing.


def _cmux_trigger_flash_calls(cmux_log: Path) -> list[list[str]]:
    """Extract only the `trigger-flash` invocations from a cmux call log.

    The launcher's `_cmux_rename` helper unconditionally calls
    `cmux identify --json` (for pane-tab renaming) in every bead mode, so a
    raw non-empty log does not by itself indicate a flash occurred — these
    tests must filter to `trigger-flash` calls specifically.
    """
    if not cmux_log.exists():
        return []
    calls = [json.loads(line) for line in cmux_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [call for call in calls if call and call[0] == "trigger-flash"]


def test_cld_bead_review_launcher_flashes_cmux_after_exit_with_callback(tmp_path: Path) -> None:
    """The mock `claude` binary used here (see _write_claude_capture) is a
    pure Python script that only writes argv/prompt files — it never itself
    invokes cmux — so a logged trigger-flash call proves the flash
    genuinely originates from the launcher process, not from anything the
    claude mock does."""
    cmux_log = tmp_path / "cmux-argv.jsonl"
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
        cmux_log=cmux_log,
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_flag_value(argv, "--tools") == BEAD_REVIEW_TOOLS
    # No Bash tool-permission entry anywhere (the review prompt's prose may
    # legitimately mention "Bash" while explaining why it has no access —
    # check the tool-profile flag values specifically, not the whole argv).
    assert _argv_flag_value(argv, "--allowedTools") == BEAD_REVIEW_ALLOWED_TOOLS
    assert "Bash" not in _argv_flag_value(argv, "--allowedTools")
    assert "Bash" not in _argv_flag_value(argv, "--tools")

    flash_calls = _cmux_trigger_flash_calls(cmux_log)
    assert flash_calls == [
        ["trigger-flash", "--surface", "surface:33"]
    ], f"expected exactly one trigger-flash call, got: {flash_calls}"


def test_cld_bead_review_launcher_does_not_flash_cmux_without_callback(tmp_path: Path) -> None:
    """Without coordinator callback flags, the launcher must never invoke
    cmux trigger-flash at all — _has_coordinator_callback gates the
    post-exit flash exactly as it gated the old in-session callback
    contract. (cmux identify --json from _cmux_rename may still be logged;
    only trigger-flash calls are asserted here.)"""
    cmux_log = tmp_path / "cmux-argv.jsonl"
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        ["-br", "CL-safe"],
        cmux_log=cmux_log,
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_flag_value(argv, "--tools") == BEAD_REVIEW_TOOLS

    assert _cmux_trigger_flash_calls(cmux_log) == [], (
        "launcher invoked cmux trigger-flash without a coordinator callback present"
    )


@pytest.mark.parametrize("args", [["-b", "CL-safe"], ["-bq", "CL-safe"]])
def test_cld_implementer_modes_still_use_exec_and_do_not_flash_cmux(
    tmp_path: Path,
    args: list[str],
) -> None:
    """-b/-bq must keep the original `exec` behavior (no post-exit launcher
    code runs for them) and must never trigger the -br-only launcher-side
    cmux flash, even when coordinator callback flags are present — those
    modes signal the coordinator from inside their own (unrestricted) Bash
    session, per _coordinator_callback_contract's impl branch. (cmux
    identify --json from _cmux_rename may still be logged; only
    trigger-flash calls are asserted here.)"""
    cmux_log = tmp_path / "cmux-argv.jsonl"
    result, _argv_file, _prompt_file, called_file, _bd_log = _run_cld(
        tmp_path,
        [
            *args,
            "--coordinator-workspace",
            "workspace:15",
            "--coordinator-surface",
            "surface:33",
        ],
        cmux_log=cmux_log,
    )

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    assert _cmux_trigger_flash_calls(cmux_log) == [], (
        "launcher invoked cmux trigger-flash for an implementer (-b/-bq) mode; "
        "only -br's post-exit flash should ever fire"
    )


# ── Headless (non-interactive) exit via --print (CL-9knh, iteration 4) ────
# A live smoke against an uncached bead confirmed the review itself works
# end-to-end, but exposed a structural bug: bin/cld's -br path launched
# claude WITHOUT --print, i.e. as a genuinely interactive session. Without
# --print, "the model finished its turn" is not the same as "the process
# exits" -- Claude Code stays alive at an interactive prompt waiting for
# more input, so the launcher's foreground `"${CLAUDE_BIN}"
# "${claude_args[@]}"` call (see the post-exit cmux flash block) never
# returns on its own, and the post-exit flash never fires autonomously.
# Interactive Claude also restores its alternate terminal screen buffer on
# exit, wiping the verdict text from the pane's visible scrollback even
# once the session IS terminated. --print fixes both: it runs the prompt
# non-interactively, prints the response as plain text (default
# --output-format, no alternate-screen TUI), and exits automatically once
# the turn completes. -br only -- -b/-bq/plain passthrough must keep their
# current exec-based, fully interactive behavior since they run long
# multi-phase orchestrations that legitimately need to stay interactive.


def test_cld_bead_review_claude_args_include_print_for_headless_exit(tmp_path: Path) -> None:
    """-br must add --print to claude_args so the subprocess runs
    non-interactively and exits automatically once its turn completes."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, ["-br", "CL-safe"])

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--print" in argv, "-br must launch claude with --print for headless (non-interactive) exit"


@pytest.mark.parametrize(
    "args",
    [
        ["Plain passthrough prompt"],
        ["-b", "CL-safe"],
        ["-bq", "CL-safe"],
    ],
)
def test_cld_bead_review_print_flag_does_not_leak_into_other_modes(
    tmp_path: Path,
    args: list[str],
) -> None:
    """--print is -br-only: -b/-bq/plain-passthrough must keep their current
    (non-`--print`, `exec`-based) fully interactive behavior -- those modes
    run long multi-phase orchestrations that legitimately need to stay
    interactive and are unaffected by this bead."""
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld(tmp_path, args)

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--print" not in argv


def test_cld_bead_review_launcher_regains_control_and_flashes_promptly_after_claude_exits(
    tmp_path: Path,
) -> None:
    """CL-9knh iteration 4: prove the launcher regains control PROMPTLY once
    the (now --print-aware) claude subprocess exits -- bounded wall-clock
    time, not "eventually" or dependent on the process being externally
    killed. The mock `claude` binary (see _write_claude_capture) already
    exits immediately by construction -- it is a short Python script, not a
    long-running process -- so this test's job is to make that prompt-exit
    property an explicit, load-bearing assertion (elapsed time, not just
    "the flash eventually happened") rather than an implicit side effect of
    the mock. There is no sleep/timeout/retry anywhere in this launcher
    path; a slow result here would indicate the launcher is relying on
    something other than the subprocess exiting on its own (e.g. still
    using `exec`, or waiting on an external kill)."""
    cmux_log = tmp_path / "cmux-argv.jsonl"

    start = time.monotonic()
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
        cmux_log=cmux_log,
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0, result.stderr
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert "--print" in argv, "-br must launch claude with --print for headless (non-interactive) exit"

    flash_calls = _cmux_trigger_flash_calls(cmux_log)
    assert flash_calls == [
        ["trigger-flash", "--surface", "surface:33"]
    ], f"expected exactly one prompt trigger-flash call, got: {flash_calls}"

    # Bounded, not "eventual": the entire launcher invocation (subprocess
    # launch -> claude exit -> post-exit cmux flash -> launcher exit) must
    # complete well within a few seconds.
    assert elapsed < 5.0, (
        f"launcher took {elapsed:.2f}s to regain control and flash cmux after "
        "claude exited; expected prompt (bounded) completion, not an eventual/hung result"
    )


# ── Non-zero exit propagation (CL-9knh, Fix6, Opus cold-review advisory) ──
# The -br post-exit block (see above) captures claude's exit code via
# `_claude_exit=$?` immediately after the foreground call -- before the
# cmux flash runs -- and the flash's own failure is swallowed by `|| true`,
# so it cannot clobber the propagated code. That is correct by code
# inspection, but every existing test above uses a mock `claude` that
# always exits 0, so only the success path was ever exercised. These two
# helpers build a variant mock that exits with a caller-chosen non-zero
# code so the failure path gets real coverage.


def _write_claude_capture_with_exit_code(
    tmp_path: Path, exit_code: int
) -> tuple[Path, Path, Path, Path]:
    """Like _write_claude_capture, but the mock exits with a specific
    non-zero code instead of always succeeding with 0."""
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
        "pathlib.Path(os.environ['CLAUDE_PROMPT_FILE']).write_text(prompt, encoding='utf-8')\n"
        f"sys.exit({exit_code})\n",
    )
    return claude_mock, argv_file, prompt_file, called_file


def _run_cld_with_claude_exit_code(
    tmp_path: Path,
    args: list[str],
    exit_code: int,
    cmux_log: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path, Path]:
    """Same wiring as _run_cld, but the mock `claude` binary exits with
    `exit_code` instead of always succeeding."""
    claude_mock, argv_file, prompt_file, called_file = _write_claude_capture_with_exit_code(
        tmp_path, exit_code
    )
    bd_mock, bd_log = _write_bd_mock(tmp_path)
    _write_cld_path_mocks(tmp_path, cmux_log=cmux_log)
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


def test_cld_bead_review_launcher_propagates_nonzero_exit_code_and_still_flashes(
    tmp_path: Path,
) -> None:
    """CL-9knh Fix6 (Opus cold-review advisory): the -br post-exit block
    captures claude's exit code via `_claude_exit=$?` immediately after the
    foreground call, before the cmux flash runs, and the flash's own
    failure is swallowed by `|| true` so it cannot clobber the propagated
    code. This test exercises the previously-uncovered non-zero-exit path
    with a distinctive code (17, not 1, to avoid confusion with a generic
    failure) and asserts BOTH halves of the contract together: the
    launcher's own process exit code is exactly the code claude exited
    with (not 0, not some other transformed value), AND the cmux flash
    still fires exactly once even though claude failed -- confirming the
    flash fires regardless of why/how the session ended, not only on a
    clean exit (the original Fix 2 design intent)."""
    cmux_log = tmp_path / "cmux-argv.jsonl"
    result, argv_file, _prompt_file, called_file, _bd_log = _run_cld_with_claude_exit_code(
        tmp_path,
        [
            "-br",
            "CL-safe",
            "--coordinator-workspace",
            "workspace:15",
            "--coordinator-surface",
            "surface:33",
        ],
        exit_code=17,
        cmux_log=cmux_log,
    )

    assert result.returncode == 17, (
        "expected the launcher to propagate claude's exit code (17) verbatim, "
        f"got {result.returncode}: {result.stderr}"
    )
    assert called_file.exists()
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert _argv_flag_value(argv, "--tools") == BEAD_REVIEW_TOOLS

    flash_calls = _cmux_trigger_flash_calls(cmux_log)
    assert flash_calls == [
        ["trigger-flash", "--surface", "surface:33"]
    ], f"expected exactly one trigger-flash call on non-zero exit, got: {flash_calls}"
