# Guardrail / Hook

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** A deterministic enforcement mechanism that runs *outside the LLM loop*
at defined lifecycle events. Guardrails fire unconditionally — the model cannot skip or
suppress them.

**Key constitutive feature.** Non-LLM execution: guardrails are not subject to model
reasoning or discretion. They run deterministically as part of the harness machinery.
This is the *only* deterministic safety layer in the agentic stack — everything else
(system prompts, skill instructions, agent restrictions) is best-effort and can be
overridden by the model.

Not every hook is a pre-tool veto. Catalog entries MUST declare `enforcement` so
installers and reviewers can distinguish true blocking guardrails from prompt
mutators and information hooks:

| Enforcement | Meaning | Example |
|-------------|---------|---------|
| `veto` | Blocks a tool/action at the tool boundary. | `gitleaks-guard` blocks unsafe `git push`. |
| `session-block` | Blocks session startup before model work proceeds. | Version gates that fail SessionStart. |
| `mutate` | Rewrites or supplements a harness payload without blocking. | Agent prompt standards injection. |
| `inform` | Emits context, logs, or summaries only. | Session catch-up summaries. |

Consumers MUST filter by `enforcement` rather than assuming every cataloged
guardrail has veto semantics.

**Trigger semantics.** The harness fires guardrails at predefined lifecycle events. The
mechanism differs per harness: hooks run as external processes (Claude Code, Codex CLI),
TypeScript extension handlers execute in-process (Pi), or static policies gate tool
calls before execution (Codex Cloud, OpenCode).

**Cross-harness capability matrix (NORMATIVE unless noted).**

| Harness | Mechanism | Config file | Handler format | Pre-tool veto | Post-tool | Session-init |
|---------|-----------|-------------|----------------|:-------------:|:---------:|:------------:|
| Claude Code | hooks | `settings.json` | Any executable | YES (exit 2) | YES | YES |
| Codex CLI | hooks (limited) | `hooks.json` | Node ESM `.mjs` | WORKAROUND | NO | YES |
| Codex Cloud | `approval_policy` | `config.toml` | static TOML | BLUNT (all tools) | NO | NO |
| Pi | TypeScript extensions | `.pi/extensions/*.ts` | TypeScript | YES | YES | PARTIAL |
| OpenCode | permission rules | `opencode.json` | JSON rules | YES | NO | NO |

Key:
- **YES** — full native support.
- **WORKAROUND** — implemented via a less-capable event (advisory only, not hard-blocking).
- **BLUNT** — mechanism exists but applies to all tool calls, not just matched patterns.
- **PARTIAL** — supported for some scenarios only.
- **NO** — not supported; skip this harness for this purpose.

**Claude Code hook events — three-cadence taxonomy:**

| Cadence | Events |
|---------|--------|
| Per session | SessionStart, SessionEnd |
| Per turn | UserPromptSubmit, UserPromptExpansion, Stop, StopFailure |
| Per tool call | PreToolUse, PostToolUse, PostToolUseFailure |
| Per permission | PermissionRequest, PermissionDenied |
| Per subagent | SubagentStart, SubagentStop |
| Other | PreCompact, Notification |

**Per-harness event coverage:**

| Harness | Events | Notes |
|---------|--------|-------|
| Claude Code | 15 events: SessionStart, SessionEnd, UserPromptSubmit, UserPromptExpansion, PreToolUse, PostToolUse, PostToolUseFailure, PermissionRequest, PermissionDenied, Notification, SubagentStart, SubagentStop, Stop, StopFailure, PreCompact | NORMATIVE. See [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks). |
| Codex CLI | 3 events: SessionStart, SessionEnd, Stop | NORMATIVE — per CL-qzw research. No PreToolUse equivalent. |
| Codex Cloud | Pre-tool call via `approval_policy` | NORMATIVE. Static policy only; no event scripting. |
| Pi | `tool_call`, `tool_result`, `message`, `session_start` | INFERRED — pending vendor doc validation. |
| OpenCode | Pre-tool-call via `rules` array | INFERRED — pending vendor doc validation. |

Full event-to-harness mapping: see `docs/research/guardrails-mapping.md`. Official Claude Code hook reference: [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks).

**Capability mismatch warnings.** The `/library use-guardrail` cookbook automatically
detects when a target harness does not support the guardrail's declared purpose and
emits a warning with options (install with workaround / skip / cancel). See
`cookbook/use-guardrail.md` Step 4 for the full decision table.

`codex_status` is mandatory for Codex routing decisions:
- `supported` — a `sources.codex_cli` implementation exists, or the entry is a
  manifest with a Codex source.
- `not-supported` — Codex install requests are refused for `--harness codex`
  and `--harness all`.
- `planned` — the gap is known, but installers must still refuse Codex until a
  Codex source exists.

`runtime_requirements.binaries` lists external commands that must be present
before enabling a guardrail. Installers refuse non-dry-run installs when a
required binary is missing; runtime hooks should fail closed when the missing
binary would weaken enforcement.

**Purpose classes:**
- `pre-tool-veto` — block a tool call before execution. Primary use: security gates.
- `post-tool-reaction` — run side effects after tool completion. Primary use: audit, formatting.
- `session-init` — inject context or setup at session start. Primary use: standards loading.
- `cleanup` — teardown at session end. Primary use: state cleanup, metrics flush.
- `audit-log` — record every tool call. Primary use: compliance logging.

**Tier and default scope semantics:**
- `tier: core` — broadly applicable fleet safety such as destructive-command
  blocking. Default scope is usually `global` or `ask`.
- `tier: domain` — applies to a class of projects such as healthcare, finance,
  or infrastructure. Default scope is usually `ask`.
- `tier: project` — assumes project-local conventions, binaries, bead workflow,
  or domain files. Default scope is usually `project`.
- `default_scope: global` — install globally without prompting only when the
  guardrail is broadly safe and has no project assumptions.
- `default_scope: project` — install into the target project when project-local
  state, policy, or auditability matters.
- `default_scope: ask` — require an explicit choice when either scope is plausible.

**Cost.** Hooks run as external processes — low LLM token cost, but each hook adds
latency to the event it intercepts. Keep hook scripts fast (<100 ms) for
PreToolUse/PostToolUse hooks.

**When to choose it.** Use a guardrail when:
- A behavior must be enforced regardless of model decisions (security, logging,
  formatting).
- Context must be injected at session start before the model processes any prompts.
- A side effect must always happen after a tool use (auto-format, audit log).
- The constraint is non-negotiable — the model must not be able to opt out.

**Counter-examples.**
- Do NOT use a guardrail for capabilities the model should reason about — that is a skill.
- Do NOT use a guardrail for interactive workflows — guardrails run non-interactively and
  cannot prompt the user mid-execution.

**Worked examples.**

| Guardrail | Why it is a guardrail |
|-----------|----------------------|
| `block-destructive-bash` (PreToolUse) | Blocks irreversible commands (recursive deletes, force-pushes, DROP TABLE). Must fire on every Bash tool call regardless of model reasoning. Model cannot bypass. Compiles to 4 harnesses: Claude Code (hook), Codex CLI (advisory), Codex Cloud (approval_policy), OpenCode (permission rules). |
| `auto-capture.py` (PostToolUse) | Captures tool calls for audit. Must fire on every tool use regardless of what the model decides. Model cannot opt out. |
| `bd-cache-invalidator.py` (PreToolUse) | Invalidates beads cache. Must run before specific tool types unconditionally to keep cache consistent. |
| SessionStart context-loader hooks | Inject standards and skill context before the model sees any user input. Must run before model reasoning begins — model cannot be trusted to load its own context reliably. |

---
