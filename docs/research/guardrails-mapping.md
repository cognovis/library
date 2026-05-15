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
| Codex CLI | NATIVE | NATIVE | NATIVE | PARTIAL |
| Codex Cloud | BLUNT | NO | NO | NO |
| Pi | NATIVE | NATIVE | PARTIAL | NO |
| OpenCode | NATIVE | NO | NO | NO |

Legend:
- **NATIVE** — Full support for this lifecycle class; preferred install path.
- **BLUNT** — Mechanism exists but is coarser than requested (affects all tools, not just targeted ones).
- **PARTIAL** — Supported for some events or scenarios only.
- **NO** — Not supported; skip this harness for this purpose class.

---

## Harness Reference Table

| Harness | Mechanism | Config file | Handler format | Native events |
|---------|-----------|-------------|----------------|---------------|
| **Claude Code** | hooks | `settings.json` (project or global) | Any executable (bash, python, etc.) | 15 events — see below |
| **Codex CLI** | hooks (limited) | `hooks.json` | command hook | PreToolUse, PermissionRequest, PostToolUse, PreCompact, PostCompact, SessionStart, UserPromptSubmit, Stop |
| **Codex Cloud** | `sandbox_mode` + `approval_policy` | `config.toml` | static TOML policy | Pre-tool only via approval gate (always/unless-allow-listed) |
| **Pi** | TypeScript Extensions | `.pi/extensions/*.ts` | TypeScript code | Tool-call events; `pi.on("event", handler)` |
| **OpenCode** | permission rules | `opencode.json` | JSON rules array | Pre-tool-call gates only |

### NORMATIVE claim sources
- Claude Code: https://code.claude.com/docs/en/hooks (confirmed 15 events)
- Codex CLI: local Codex CLI 0.130.0 plus `scripts/install-hook.py`
  `CODEX_SUPPORTED_EVENTS` — see also `codex-prompts.md`
- Codex Cloud: https://github.com/openai/codex (config.toml docs)
- Pi: https://pi.dev/docs/extensions (INFERRED — not yet fully validated)
- OpenCode: https://opencode.ai/docs/permissions (INFERRED — not yet fully validated)

---

## Event Coverage Per Harness

### Claude Code Events (15 events, NORMATIVE)

Source: https://code.claude.com/docs/en/hooks

| Event | Cadence | Can block? | Use for |
|-------|---------|------------|---------|
| `SessionStart` | Per session | No | Context injection, state setup |
| `SessionEnd` | Per session | No | Cleanup, final logging |
| `UserPromptSubmit` | Per turn | No | Prompt sanitization, logging |
| `UserPromptExpansion` | Per turn | No | Prompt expansion observation |
| `Stop` | Per turn | No | Cleanup before Claude stops |
| `StopFailure` | Per turn | No | Error handling on stop failure |
| `PreToolUse` | Per tool call | YES (exit 2) | Tool veto, parameter validation |
| `PostToolUse` | Per tool call | No | Side effects, audit logging |
| `PostToolUseFailure` | Per tool call | No | Error recovery, alerting |
| `PermissionRequest` | Per permission | YES | Custom permission logic |
| `PermissionDenied` | Per permission | No | Audit denied permissions |
| `SubagentStart` | Per subagent | No | Subagent context injection |
| `SubagentStop` | Per subagent | No | Metrics, result post-processing |
| `PreCompact` | Other | No | State preservation before compaction |
| `Notification` | Other | No | Monitoring |

### Codex CLI Events (8 events, NORMATIVE for 0.130.0)

| Event | Timing | Can block? | Use for |
|-------|--------|------------|---------|
| `PreToolUse` | Before tool execution | YES | Tool veto, parameter validation |
| `PermissionRequest` | Permission gate | YES | Custom permission logic |
| `PostToolUse` | After tool completion | No | Side effects, audit logging |
| `PreCompact` | Before compaction | No | State preservation before compaction |
| `PostCompact` | After compaction | No | State restoration or cleanup after compaction |
| `SessionStart` | Session initialization | No | Context injection, setup |
| `UserPromptSubmit` | Before prompt processing | UNKNOWN | Prompt observation or policy checks; blocking semantics not relied on here |
| `Stop` | Before session stops | No | Final cleanup |

**Key gap:** Codex CLI has fewer lifecycle events than Claude Code and does not
currently expose Claude-only events such as `SessionEnd`, `SubagentStart`,
`SubagentStop`, `StopFailure`, `Notification`, `PermissionDenied`, or
`PostToolUseFailure`. Unsupported events are filtered by `scripts/install-hook.py`
with a mismatch warning.

### Codex Cloud (static policy, NORMATIVE)

Codex Cloud uses a declarative policy model, not event hooks:
- `approval_policy = "always"` — require human approval for every tool call
- `approval_policy = "unless-allow-listed"` — Codex decides what to approve
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
| Codex CLI | NATIVE | `PreToolUse` hook in `hooks.json` | Hard block for matched tool calls |
| Codex Cloud | BLUNT | `approval_policy = "always"` in config.toml | Hard gate — but applies to ALL tool calls |
| Pi | NATIVE | TypeScript extension `tool_call` handler | Hard block |
| OpenCode | NATIVE | JSON `rules` with `action: "deny"` | Hard block for matched patterns |

**Mismatch warning triggers:**
- Codex Cloud: emit warning, offer approval_policy=always or skip

### `post-tool-reaction`

Goal: run code after a tool call completes (side effects, audit, notification).

| Harness | Support | Installation | Notes |
|---------|---------|--------------|-------|
| Claude Code | NATIVE | `PostToolUse` or `PostToolUseFailure` hook | Full support |
| Codex CLI | NATIVE | `PostToolUse` hook in `hooks.json` | Supported; no Codex `PostToolUseFailure` event is listed in 0.130.0 |
| Codex Cloud | NO | — | No hook system; skip |
| Pi | NATIVE | `tool_result` extension | Full support |
| OpenCode | NO | — | No post-tool hooks; skip |

**Mismatch warning:** Codex CLI should warn only for unsupported event names in a
manifest, not for the `post-tool-reaction` purpose class itself.

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
| Codex CLI | PARTIAL | `Stop`, `PreCompact`, or `PostCompact` hook | No `SessionEnd` event in 0.130.0 |
| Codex Cloud | NO | — | No hook system; skip |
| Pi | NO | — | No equivalent; skip |
| OpenCode | NO | — | No cleanup hooks; skip |

### `audit-log`

Goal: log every tool call for security/compliance audit.

| Harness | Support | Installation | Notes |
|---------|---------|--------------|-------|
| Claude Code | NATIVE | `PostToolUse` hook | Full support |
| Codex CLI | PARTIAL | `PostToolUse` hook | Supported for completed tool calls; failure-specific event not listed in 0.130.0 |
| Codex Cloud | NO | — | No hook system; skip |
| Pi | NATIVE | `tool_result` extension | Full support |
| OpenCode | NO | — | No post-tool hooks; skip |

---

## Mismatch Warning Decision Table

The `use-guardrail` cookbook emits mismatch warnings based on this table:

| Guardrail purpose | Target harness | Warning type | Default action |
|-------------------|----------------|--------------|----------------|
| `pre-tool-veto` | `codex_cloud` | BLUNT — install as approval_policy=always? | Skip |
| `post-tool-reaction` | `codex_cloud` | NOT SUPPORTED — skip? | Skip |
| `post-tool-reaction` | `opencode` | NOT SUPPORTED — skip? | Skip |
| `session-init` | `codex_cloud` | NOT SUPPORTED — skip? | Skip |
| `session-init` | `opencode` | NOT SUPPORTED — skip? | Skip |
| `cleanup` requiring `SessionEnd` | `codex_cli` | PARTIAL — install supported cleanup events only? | Continue with event-level warning |
| `cleanup` | `codex_cloud` | NOT SUPPORTED — skip? | Skip |
| `cleanup` | `pi` | NOT SUPPORTED — skip? | Skip |
| `cleanup` | `opencode` | NOT SUPPORTED — skip? | Skip |
| `audit-log` | `codex_cloud` | NOT SUPPORTED — skip? | Skip |
| `audit-log` | `opencode` | NOT SUPPORTED — skip? | Skip |
| Unsupported event in manifest | `codex_cli` | EVENT UNSUPPORTED — skip event and emit `mismatch_warning` | Continue with supported events |
| Any | harness NOT in `capability` map | UNSUPPORTED — no implementation exists | Skip |

---

## Worked Example: block-destructive-bash

This guardrail has `purpose: pre-tool-veto` and targets destructive Bash commands.

**Harness summary:**

| Harness | Installed as | Effectiveness | Config changed |
|---------|-------------|---------------|----------------|
| Claude Code | `PreToolUse` hook (bash script) | Hard block — exit 2 | `settings.json` hooks section |
| Codex CLI | `PreToolUse` command hook | Hard block for matched Bash calls | `hooks.json` PreToolUse |
| Codex Cloud | `approval_policy = "always"` | Hard gate (all tools) | `config.toml` |
| OpenCode | JSON permission rules | Hard block (matched patterns) | `opencode.json` rules array |
| Pi | Not implemented yet | — | — |

**Mismatch warnings emitted during install:**
1. `codex_cloud`: Requested `pre-tool-veto` but Codex Cloud only has `approval_policy`.
   Installs as `approval_policy = "always"` (blunt — affects ALL tool calls).
2. `codex_cli`: No warning for `PreToolUse` itself in Codex CLI 0.130.0. Warnings
   apply only if the manifest also contains unsupported Claude-only events.

---

## Follow-up Items

- Validate Pi extension API against `pi.dev` docs (current claims are INFERRED)
- Validate OpenCode JSON rules format against `opencode.ai` docs
- Add Pi source file to `block-destructive-bash` once Pi API confirmed
- Research whether Codex Cloud `sandbox_permissions` can scope blocking to specific
  patterns (would upgrade from BLUNT to NATIVE for some use cases)
- Keep this document synchronized with `scripts/install-hook.py`
  `CODEX_SUPPORTED_EVENTS` when Codex CLI upgrades.
