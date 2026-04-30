# Guardrails: Cross-Harness Capability Mapping

> **Bead:** CL-xcm | **Epic:** CL-36o (Multi-Harness Library) | **Date:** 2026-04-30
>
> **Status:** NORMATIVE — this document is the source of truth for per-harness guardrail
> capability mapping used by `/library use-guardrail`, `/library add-guardrail`, and the
> guardrail `capability` section in `library.yaml`.
>
> **Claim labeling:** NORMATIVE (verified against vendor docs / confirmed behavior) or
> INFERRED (architectural best-guess, pending validation).

---

## Executive Summary

Every harness in the multi-harness library stack has *some* form of deterministic
guardrail mechanism. They differ significantly in expressiveness:

| Harness | Pre-tool veto | Post-tool reaction | Session init | Cleanup |
|---------|:-------------:|:------------------:|:------------:|:-------:|
| Claude Code | NATIVE | NATIVE | NATIVE | NATIVE |
| Codex CLI | WORKAROUND | NO | NATIVE | PARTIAL |
| Codex Cloud | BLUNT | NO | NO | NO |
| Pi | NATIVE | NATIVE | PARTIAL | NO |
| OpenCode | NATIVE | NO | NO | NO |

Legend:
- **NATIVE** — Full support for this lifecycle class; preferred install path.
- **WORKAROUND** — Supported but with reduced effectiveness; requires mismatch warning.
- **BLUNT** — Mechanism exists but is coarser than requested (affects all tools, not just targeted ones).
- **PARTIAL** — Supported for some events or scenarios only.
- **NO** — Not supported; skip this harness for this purpose class.

---

## Harness Reference Table

| Harness | Mechanism | Config file | Handler format | Native events |
|---------|-----------|-------------|----------------|---------------|
| **Claude Code** | hooks | `settings.json` (project or global) | Any executable (bash, python, etc.) | 13+ events — see below |
| **Codex CLI** | hooks (limited) | `hooks.json` | Node ESM `.mjs` | 3 events only: SessionStart, SessionEnd, Stop |
| **Codex Cloud** | `sandbox_mode` + `approval_policy` | `config.toml` | static TOML policy | Pre-tool only via approval gate (all/auto) |
| **Pi** | TypeScript Extensions | `.pi/extensions/*.ts` | TypeScript code | Tool-call events; `pi.on("event", handler)` |
| **OpenCode** | permission rules | `opencode.json` | JSON rules array | Pre-tool-call gates only |

### NORMATIVE claim sources
- Claude Code: https://docs.anthropic.com/claude-code/hooks (confirmed 13 events)
- Codex CLI: CL-qzw research session (2026-04-16) — see `codex-prompts.md`
- Codex Cloud: https://github.com/openai/codex (config.toml docs)
- Pi: https://pi.dev/docs/extensions (INFERRED — not yet fully validated)
- OpenCode: https://opencode.ai/docs/permissions (INFERRED — not yet fully validated)

---

## Event Coverage Per Harness

### Claude Code Events (13 events, NORMATIVE)

| Event | Timing | Can block? | Use for |
|-------|--------|------------|---------|
| `SessionStart` | Session initialization | No | Context injection, state setup |
| `SessionEnd` | Session teardown | No | Cleanup, final logging |
| `UserPromptSubmit` | Before model processes prompt | No | Prompt sanitization, logging |
| `PreToolUse` | Before each tool call | YES (exit 2) | Tool veto, parameter validation |
| `PostToolUse` | After each tool call | No | Side effects, audit logging |
| `PostToolUseFailure` | After a tool call fails | No | Error recovery, alerting |
| `PermissionRequest` | When model requests permission | YES | Custom permission logic |
| `Notification` | System notifications | No | Monitoring |
| `SubagentStart` | Before spawning a subagent | No | Subagent context injection |
| `SubagentStop` | After a subagent returns | No | Metrics, result post-processing |
| `Stop` | Before Claude stops responding | No | Cleanup |
| `PreCompact` | Before context compaction | No | State preservation |
| `Setup` | First-time setup | No | Environment initialization |

### Codex CLI Events (3 events, NORMATIVE)

| Event | Timing | Can block? | Use for |
|-------|--------|------------|---------|
| `SessionStart` | Session initialization | No | Advisory injection, context setup |
| `SessionEnd` | Session teardown | No | Cleanup |
| `Stop` | Before session stops | No | Final cleanup |

**Key gap:** No `PreToolUse` equivalent. Pre-tool veto is not possible; advisory
injection via `SessionStart` is the nearest workaround.

### Codex Cloud (static policy, NORMATIVE)

Codex Cloud uses a declarative policy model, not event hooks:
- `approval_policy = "all"` — require human approval for every tool call
- `approval_policy = "auto"` — Codex decides what to approve
- `sandbox_mode` — restrict which filesystem paths and network access are available

There is no per-tool-call hook; policy applies globally to all tool calls.

### Pi Events (INFERRED — pending validation)

Pi TypeScript Extensions expose `pi.on(event, handler)`:
- `tool_call` — fires before tool execution (veto possible)
- `tool_result` — fires after tool execution
- `message` — fires on message events
- `session_start` — fires at session start (partial equivalent of SessionStart)

### OpenCode Rules (INFERRED — pending validation)

OpenCode evaluates JSON permission rules from `opencode.json` before each tool call:
- Each rule has: `tool`, `pattern` (regex), `action` (deny/ask), `message`
- Rules are applied per-tool-call before the model can proceed
- No post-tool hooks

---

## Purpose Class Mapping

### `pre-tool-veto`

Goal: block a tool call before it executes.

| Harness | Support | Installation | Effectiveness |
|---------|---------|--------------|---------------|
| Claude Code | NATIVE | `PreToolUse` hook (exit 2 to block) | Hard block — model cannot proceed |
| Codex CLI | WORKAROUND | `SessionStart` advisory injection | Advisory only — model is warned, not blocked |
| Codex Cloud | BLUNT | `approval_policy = "all"` in config.toml | Hard gate — but applies to ALL tool calls |
| Pi | NATIVE | TypeScript extension `tool_call` handler | Hard block |
| OpenCode | NATIVE | JSON `rules` with `action: "deny"` | Hard block for matched patterns |

**Mismatch warning triggers:**
- Codex CLI: emit warning, offer SessionStart workaround or skip
- Codex Cloud: emit warning, offer approval_policy=all or skip

### `post-tool-reaction`

Goal: run code after a tool call completes (side effects, audit, notification).

| Harness | Support | Installation | Notes |
|---------|---------|--------------|-------|
| Claude Code | NATIVE | `PostToolUse` or `PostToolUseFailure` hook | Full support |
| Codex CLI | NO | — | No PostToolUse equivalent; skip |
| Codex Cloud | NO | — | No hook system; skip |
| Pi | NATIVE | `tool_result` extension | Full support |
| OpenCode | NO | — | No post-tool hooks; skip |

**Mismatch warning:** All harnesses except Claude Code and Pi should be skipped.

### `session-init`

Goal: inject context or run setup code at the start of a session.

| Harness | Support | Installation | Notes |
|---------|---------|--------------|-------|
| Claude Code | NATIVE | `SessionStart` hook | Full support |
| Codex CLI | NATIVE | `SessionStart` hook (`.mjs`) | Full support |
| Codex Cloud | NO | — | No session hook; skip |
| Pi | PARTIAL | `session_start` event | INFERRED — confirm Pi implementation |
| OpenCode | NO | — | No session hooks; skip |

### `cleanup`

Goal: run teardown code at the end of a session.

| Harness | Support | Installation | Notes |
|---------|---------|--------------|-------|
| Claude Code | NATIVE | `Stop` or `PreCompact` hook | Full support |
| Codex CLI | PARTIAL | `Stop` hook only | No `PreCompact` equivalent |
| Codex Cloud | NO | — | No hook system; skip |
| Pi | NO | — | No equivalent; skip |
| OpenCode | NO | — | No cleanup hooks; skip |

### `audit-log`

Goal: log every tool call for security/compliance audit.

| Harness | Support | Installation | Notes |
|---------|---------|--------------|-------|
| Claude Code | NATIVE | `PostToolUse` hook | Full support |
| Codex CLI | NO | — | No PostToolUse; use SessionStart to log session metadata only |
| Codex Cloud | NO | — | No hook system; skip |
| Pi | NATIVE | `tool_result` extension | Full support |
| OpenCode | NO | — | No post-tool hooks; skip |

---

## Mismatch Warning Decision Table

The `use-guardrail` cookbook emits mismatch warnings based on this table:

| Guardrail purpose | Target harness | Warning type | Default action |
|-------------------|----------------|--------------|----------------|
| `pre-tool-veto` | `codex_cli` | WORKAROUND — install as SessionStart advisory? | Skip |
| `pre-tool-veto` | `codex_cloud` | BLUNT — install as approval_policy=all? | Skip |
| `post-tool-reaction` | `codex_cli` | NOT SUPPORTED — skip? | Skip |
| `post-tool-reaction` | `codex_cloud` | NOT SUPPORTED — skip? | Skip |
| `post-tool-reaction` | `opencode` | NOT SUPPORTED — skip? | Skip |
| `session-init` | `codex_cloud` | NOT SUPPORTED — skip? | Skip |
| `session-init` | `opencode` | NOT SUPPORTED — skip? | Skip |
| `cleanup` | `codex_cloud` | NOT SUPPORTED — skip? | Skip |
| `cleanup` | `pi` | NOT SUPPORTED — skip? | Skip |
| `cleanup` | `opencode` | NOT SUPPORTED — skip? | Skip |
| `audit-log` | `codex_cli` | NOT SUPPORTED — skip? | Skip |
| `audit-log` | `codex_cloud` | NOT SUPPORTED — skip? | Skip |
| `audit-log` | `opencode` | NOT SUPPORTED — skip? | Skip |
| Any | harness NOT in `capability` map | UNSUPPORTED — no implementation exists | Skip |

---

## Worked Example: block-destructive-bash

This guardrail has `purpose: pre-tool-veto` and targets destructive Bash commands.

**Harness summary:**

| Harness | Installed as | Effectiveness | Config changed |
|---------|-------------|---------------|----------------|
| Claude Code | `PreToolUse` hook (bash script) | Hard block — exit 2 | `settings.json` hooks section |
| Codex CLI | `SessionStart` advisory hook | Advisory only | `hooks.json` SessionStart |
| Codex Cloud | `approval_policy = "all"` | Hard gate (all tools) | `config.toml` |
| OpenCode | JSON permission rules | Hard block (matched patterns) | `opencode.json` rules array |
| Pi | Not implemented yet | — | — |

**Mismatch warnings emitted during install:**
1. `codex_cli`: Requested `pre-tool-veto` but Codex CLI only supports `SessionStart`.
   Installs as advisory injection (reduced effectiveness).
2. `codex_cloud`: Requested `pre-tool-veto` but Codex Cloud only has `approval_policy`.
   Installs as `approval_policy = "all"` (blunt — affects ALL tool calls).

---

## Follow-up Items

- Validate Pi extension API against `pi.dev` docs (current claims are INFERRED)
- Validate OpenCode JSON rules format against `opencode.ai` docs
- Add Pi source file to `block-destructive-bash` once Pi API confirmed
- Research whether Codex Cloud `sandbox_permissions` can scope blocking to specific
  patterns (would upgrade from BLUNT to NATIVE for some use cases)
