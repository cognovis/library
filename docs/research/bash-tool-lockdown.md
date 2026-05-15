# Bash Tool Lockdown Research

> **Bead:** CL-4eg | **Date:** 2026-05-15 | **Status:** Research note
>
> **Scope:** Findings from `https://github.com/disler/bash-damage-from-within`,
> local Claude Code/Codex behavior, and how the existing `dcg` hook fits into a
> phased hardening path. This is not a migration plan to remove Bash by default.

## Executive Summary

The practical hardening ladder is:

1. prompt guidance,
2. system/developer guidance,
3. blacklist guardrail for dangerous Bash,
4. default-deny Bash whitelist, and
5. remove Bash entirely and expose narrow purpose-built tools.

The repository's current posture is closest to **L3**: both Claude Code and Codex
run `/Users/malte/.local/bin/dcg` as a `PreToolUse` Bash hook. That is a useful
floor for high-blast-radius commands, but it is not equivalent to removing Bash.

The most portable **future** L5 design is a small local MCP server that exposes
specific tools such as `run_tests`, `git_status`, or `list_target`, while the
harness disables the general shell/Bash tool. The same MCP server can be
registered for Claude Code and Codex, but the server must be safe by construction:
fixed commands, scoped paths, bounded output, and no arbitrary command execution.

Recommendation: keep L3 as the default for now, document L4/L5 as optional
profiles, and avoid switching everyday sessions to L5 until the tool inventory
and launcher ergonomics are clear.

## Source Material

- `disler/bash-damage-from-within` demonstrates the five-level ladder with
  Claude Code examples and a Pi extension example.
- Local Claude Code version observed: `2.1.142`.
- Local Codex CLI version observed: `0.130.0`.
- Local Codex feature flags observed: `shell_tool` and `unified_exec` are stable
  and enabled by default.
- Local Codex help exposes `--disable <FEATURE>` and `--enable <FEATURE>`.

## Ladder Mapping

| Level | Mechanism | Claude Code | Codex CLI | Notes |
|---|---|---|---|---|
| L1 | Prompt/skill instruction | Skill or user prompt says not to use unsafe Bash | `AGENTS.md`, skill, or user prompt says the same | Advisory only. Easy to bypass accidentally or through prompt pressure. |
| L2 | System/developer instruction | Project or global instructions restrict Bash use | `AGENTS.md` and launcher-injected rules restrict Bash use | Stronger than L1, still advisory. |
| L3 | Bash blacklist | `PreToolUse` hook blocks known-dangerous Bash patterns | `PreToolUse` hook in `~/.codex/hooks.json` can run the same validator | Current `dcg` layer. Blocks obvious destructive operations, not all bypasses. |
| L4 | Bash default-deny whitelist | `PreToolUse` hook permits only anchored safe patterns | Same concept via Codex hooks, but treat this as policy validation that needs test coverage | Safer than blacklist, but still leaves a shell surface. |
| L5 | No Bash, narrow tools only | Deny `Bash`; allow specific MCP tools | `codex --disable shell_tool` plus specific MCP tools | Strongest model. Requires local tool server design and per-session ergonomics. |

## Claude Code Findings

Claude Code has direct tool scoping in settings and agents. The example L5
configuration from `bash-damage-from-within` denies `Bash`, `WebFetch`,
`WebSearch`, and sensitive target paths, then allows normal file tools plus
specific MCP tools:

- `mcp__safe-tools__run_tests`
- `mcp__safe-tools__git_status`
- `mcp__safe-tools__list_target`

The corresponding `.mcp.json` launches a local stdio MCP server. The server code
uses fixed subprocess invocations and does not expose a general command runner.

This is the important security property: the model cannot ask for arbitrary Bash,
and the custom MCP tools do not accept arbitrary shell fragments.

## Codex Findings

Codex does not appear to have a Claude-style `--tools Bash,Edit,Read` built-in
tool allowlist. The closest built-in switch is feature disabling:

```bash
codex --disable shell_tool
```

Local behavior was tested with `codex exec`:

- Default Codex could run `pwd` through the shell.
- `codex exec --disable shell_tool ...` made the model report that no shell tool
  was available.
- `codex exec --disable shell_tool --disable unified_exec ...` behaved the same
  in that test.

`unified_exec` remained listed as an enabled stable feature when only
`shell_tool` was disabled, but the model still could not execute shell commands.
For high-assurance experiments, disable both until Codex's feature/tool boundary
is documented more tightly:

```bash
codex --disable shell_tool --disable unified_exec
```

Codex MCP support is independent of the shell feature. `codex mcp` manages
external MCP servers, and `~/.codex/config.toml` can register a local stdio MCP
server. That means an L5 Codex profile can remove the general shell while leaving
purpose-built MCP tools available.

## MCP Server Implications

Yes, the L5 pattern means providing an MCP server for the allowed operations.
For local development, that server normally runs locally as a stdio process
started by the harness.

This is portable across Claude Code and Codex because MCP is the shared tool
protocol. The same server can serve both harnesses if each harness has its own
registration and tool allow/disable configuration.

Design constraints for a safe local MCP server:

- expose task-specific verbs, not `run_command`;
- use argument validation with typed inputs;
- resolve all paths against an explicit workspace root;
- avoid `shell=True`;
- call fixed executable argv lists;
- set timeouts and output limits;
- return structured results;
- avoid tools that pass through arbitrary interpreter snippets;
- test both allowed and rejected inputs.

Parameterized tools are acceptable only when the parameter is a domain value,
not a shell fragment. For example, `run_pytest(test_path)` can be made safe if
`test_path` is validated as a path inside the workspace. `run(command)` is just
Bash with a different name.

## Role Of `dcg`

`dcg` is the current shared Bash safety layer:

- Claude Code: `~/.claude/settings.json` registers `/Users/malte/.local/bin/dcg`
  under `hooks.PreToolUse` with matcher `Bash`.
- Codex: `~/.codex/hooks.json` registers the same command under
  `hooks.PreToolUse` with matcher `Bash`.
- `bin/cdx` runs Codex in full-auto mode by default and explicitly delegates
  safeguarding to `dcg` via `~/.codex/hooks.json`.

So `dcg` is best understood as the current L3 guardrail. It is valuable because
it catches known destructive shell commands before execution, especially in
full-auto sessions. It should remain enabled even if L4 profiles are introduced.

Its limits are also clear:

- it only sees tool calls that go through the Bash/shell tool path;
- it cannot inspect subprocesses launched inside an MCP server unless that server
  explicitly calls shared validation logic;
- blacklist logic can miss encoded scripts, renamed binaries, indirect
  interpreter calls, or unsafe operations hidden behind otherwise allowed
  commands;
- it does not reduce the shell surface area, it only vetoes matched calls.

In an L5 session, `dcg` mostly becomes a backstop rather than the primary
control, because the general shell tool is disabled. The MCP tools themselves
must carry the safety boundary.

## Phased Path

Short term:

- keep `dcg` as the default Bash safety floor;
- document that it is L3, not a no-shell guarantee;
- avoid changing `cld`/`cdx` defaults while other moving parts are active.

Medium term:

- prototype a `safe-tools` MCP server with two or three high-value tools;
- register it in both Claude Code and Codex;
- add tests for command construction, path validation, timeouts, and output
  limits.

Optional hardening profiles:

- `cld-safe`: deny Bash and enable only the safe-tools MCP server;
- `cdx-safe`: launch with `--disable shell_tool` and the same safe-tools MCP
  server;
- a separate L4 profile can keep Bash but apply a default-deny whitelist for
  common development commands.

Open questions before moving to L5 by default:

- Which everyday commands need first-class MCP tools?
- Which workflows still truly need an interactive shell?
- Should safe-tools live in the platform repo, a private catalog, or as a
  standalone package?
- Should `dcg` expose reusable validation functions for MCP tools, or should MCP
  tools avoid shell-like parameters entirely?

## Non-Goals

- No immediate migration to L5.
- No removal of Bash from default `cld` or `cdx` launchers.
- No replacement of `dcg`.
- No broad default-deny whitelist until the allowed command inventory is clear.
