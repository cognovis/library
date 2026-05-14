# Agentic Primitives Glossary

> v0 — source of truth for primitive definitions used across the cognovis-library multi-harness stack.
> Last updated: 2026-05-14
>
> **Claim labeling convention**: Every per-harness behavioral claim is labeled
> **NORMATIVE** (verified against vendor docs / confirmed behavior) or
> **INFERRED** (architectural best-guess, pending validation).

---

## Quick Decision Tree

Use this tree to decide which primitive a new capability belongs in.

```
Is the capability purely deterministic logic (>50 lines)?
 └─ YES → Extract to a script (bash/Python via uv). Wrap the script in a Skill if
           the model needs to call it.
 └─ NO  → Continue below.

Should the model auto-pick this up from context?
 └─ YES → SKILL (model-triggered, no user action needed)
 └─ NO  → Continue below.

Does the user invoke it explicitly by typing a slash command?
 └─ YES → COMMAND (user-only trigger, /name syntax)
 └─ NO  → Continue below.

Does it need an isolated context budget / own tool permissions?
 └─ YES → Is this a pre-action gate (decides whether a proposed side-effect may execute)?
           ├─ YES → JUDGE (specialization of Agent — see §3 Judge Specialization)
           └─ NO  → AGENT (own context window, own system prompt, own tool set)
 └─ NO  → Continue below.

Must it fire regardless of what the model decides?
 └─ YES → GUARDRAIL / HOOK (runs outside the LLM loop)
 └─ NO  → Continue below.

Is it a bundle of multiple primitives above?
 └─ YES → PLUGIN (installable unit containing skills/commands/agents/hooks)
          → Register it in a MARKETPLACE if you want it discoverable
 └─ NO  → Continue below.

Is it project-specific or cross-cutting context supplementing global skills?
 └─ YES → STANDARD (injected into model context, not invokable)
 └─ NO  → Continue below.

Is it an external capability provider accessed via the MCP protocol?
 └─ YES → Does the target harness have shell access?
           ├─ YES (Claude Code / Codex CLI) → Prefer CLI + SKILL over MCP
           └─ NO  (claude.ai web / Claude iOS) → MCP-SERVER is the only path

Does it provide model-specific behavioral guidance for an agent persona?
 └─ YES → MODEL-STANDARD
```

Judge is the pre-action gate: it approves, rejects, or constrains a proposed
side-effect before execution. Reviewer and verification agents are post-action
checks; they inspect results after work has happened and do not authorize the
action itself.

---

## Portability Matrix (TL;DR)

Quick answer to "is primitive X portable between harnesses?"
Jump to the linked section for details, costs, and `NORMATIVE`/`INFERRED` labels.

| # | Primitive | Format portable? | Claude Code | Codex CLI | Codex Cloud | Pi | OpenCode | Details |
|---|-----------|------------------|-------------|-----------|-------------|----|----|---------|
| 1 | [Skill](#1-skill) | **YES** — shared SKILL.md (Open Agent Skills Standard) | full text at session start | name+desc at startup, full on-demand | n/a | n/a | n/a | §1 |
| 2 | [Command](#2-command) | partial — same intent, different formats | `.claude/commands/*.md` (slash) | TBD (CL-qzw) | n/a | n/a | n/a | §2 |
| 3 | [Agent](#3-agent) | **NO** — harness-specific format | `.claude/agents/*.md` (YAML) | `.codex/agents/*.toml` (TOML) | n/a | n/a | n/a | §3 |
| 3a | [Action Boundary](#action-boundary-metadata) | partial — shared keys, primitive-native serialization | YAML frontmatter on skills/agents | YAML for skills, TOML for agents | n/a | unverified | unverified | metadata |
| 4 | [Guardrail/Hook](#4-guardrail-hook) | **NO** — event coverage diverges | 15 events | 3 events (SessionStart/End, Stop) | `approval_policy` only | `tool_call`, `tool_result`, `message`, `session_start` (INFERRED) | `rules` array (INFERRED) | §4 |
| 5 | [Plugin](#5-plugin) | bundle — portability inherits from contents | yes | yes | partial | partial | partial | §5 |
| 6 | [Marketplace](#6-marketplace) | yes — distribution layer | yes | yes | yes | yes | yes | §6 |
| 7 | [Standard](#7-standard) | **YES** — shared markdown, harness-agnostic | inject via hook + `requires_standards:` | `requires_standards:` + AGENTS.md adapter | n/a | n/a | n/a | §7 |
| 8 | [MCP-Server](#8-mcp-server) | yes — protocol-level | yes (also CLI+Skill preferred when shell access) | yes (also CLI+Skill preferred) | n/a | yes (only path) | yes | §8 |
| 9 | Scripts (not a primitive) | yes — plain shell/python | n/a | n/a | n/a | n/a | n/a | §9 |
| 10 | [Model-Standard](#10-model-standard) | partial — concept portable, mechanism per-harness | yes | yes | partial | unverified | unverified | §10 |

**How to read this:**
- **portable** = same source file works in multiple harnesses (no translation needed)
- **harness-specific** = each harness needs its own representation
- **n/a** = primitive does not exist in that harness's mental model
- Cells with `INFERRED` mean pending validation — see the per-primitive section.

For a capability decision ("should this be a skill or an agent?"), use the Quick Decision Tree above.
For implementation details on any cell, jump to its linked section below.

**Action boundary metadata.** `action_boundary` is not a separate primitive.
It is Library metadata declared on any side-effecting skill or agent. NORMATIVE:
the metadata keys are shared across harnesses, but the physical serialization follows
the primitive format (`SKILL.md` YAML frontmatter for skills, YAML or TOML agent
metadata for harness-specific agents).

---

## Primitive Categories

### Category 1: Invocation Primitives

These are the things a model or user can *invoke*. They differ on *who triggers them*
and *what execution context they get*.

---

### 1. Skill

**Definition.** A context file (SKILL.md) that the model loads and applies without
explicit user invocation. The model picks it up autonomously when it recognizes a
matching context.

**Key constitutive feature.** Model-triggered autonomy: the skill's `description`
field is what the model matches against. No user slash command required.

**Trigger semantics.** The harness surfaces available skills to the model. When the
model infers a skill is relevant (via description matching), it applies the skill's
instructions. The mechanics of *how* the SKILL.md text reaches the model differ per
harness — see Cost table below:

- **Claude Code**: full SKILL.md text is loaded into context at session start for
  every installed skill. When the model infers relevance, the content is already
  present; no fresh read occurs.
- **Codex CLI**: only the skill name and description are loaded at startup. When
  the model infers relevance, the harness fetches the full SKILL.md on first use.

In both harnesses, the `description` field is what the model matches against to
decide relevance — only the timing of the full-text load differs.

**Cost (per harness).**

| Harness | Startup cost | Runtime cost |
|---------|-------------|--------------|
| Claude Code | Full SKILL.md text loaded at session start for every installed skill. High static context cost. NORMATIVE — confirmed behavior. | Skill content already in context; no per-invocation fetch. NORMATIVE — direct consequence of session-start loading. |
| Codex CLI | Name, description, and path only loaded at startup (NOT full text). Much lower static cost. INFERRED — consistent with CL-qzw research findings on Codex skill discovery; pending direct vendor confirmation. | Full SKILL.md fetched on first use. Per-invocation fetch cost. INFERRED — consistent with CL-qzw research findings; pending direct vendor confirmation. |

**Format.** SKILL.md — shared format (Open Agent Skills Standard). Install paths
differ: `.agents/skills/<name>/SKILL.md` (canonical, read by Codex natively and by
Claude Code through the `.claude/skills/<name>` bridge symlink)
(Codex). NORMATIVE for both tools.

**When to choose it.** Use a skill when:
- The capability should be available without the user remembering a command.
- The capability is context-sensitive (model should decide when to apply it).
- The skill is reusable across multiple projects and harnesses.

**`always_apply` and `globs` fields.**
Skills support two optional fields that control when the harness injects them:
- `always_apply: true` — forces the skill into context unconditionally (analogous to a guardrail for context injection purposes). Use sparingly: it adds startup context cost for every session. On install, the installer writes an `@<path>` import into `CLAUDE.md` (Claude Code) and `AGENTS.md` (Codex) and a `.cursor/rules/<name>.mdc` with `alwaysApply: true` frontmatter (Cursor).
- `globs: ["*.py", ...]` — suggests the skill when a matching file is present in the edit context. Cursor writes a `.mdc` with `globs:` frontmatter. Claude Code and Codex do not support glob-scoped injection natively; a warning is emitted on install and no harness file is modified for those harnesses.

**`model:` field — FORBIDDEN in skills.** NORMATIVE.
Skills must not include a `model:` frontmatter field. Model selection is the
responsibility of the *agent* that consumes the skill, not the skill itself.

Rationale: `model:` is a Claude Code-specific frontmatter extension. Including it in a
SKILL.md creates harness lock-in — the skill will fail to load or be ignored under
Codex, Cursor, or any harness that does not understand the field. Skills are
harness-agnostic context files. If a skill's *content* implicitly requires a certain
reasoning tier (e.g. "this task needs deep analysis"), document that as a prose note
inside the skill body; do not pin it in frontmatter.

The one-line rule: **skills are context, not configuration — never model-pin them.**

**`action_boundary` frontmatter for side-effecting skills.** NORMATIVE.
Any skill that can cause side effects declares the action boundary it operates
under so a judge layer can request an action proposal before execution.

```yaml
---
name: supplier-payment
description: Draft and submit approved supplier payments.
action_boundary:
  risk_class: external-side-effect
  effect_type: financial
  proposal_schema: standard://judge-layer/proposals/action-proposal.v1
  judge: agent://judge-default
  requires_mandate: true
---
```

Field meanings:
- `risk_class` — the reversibility/escalation class: `read-only`,
  `reversible-write`, `external-side-effect`, or `high-risk`. This axis tells a
  judge how hard to scrutinize the proposal and whether to escalate to a human.
- `effect_type` — the side-effect category, such as `filesystem`, `network`,
  `financial`, `messaging`, `credential`, or `other`. This axis helps route to a
  specialist judge or policy check.
- `proposal_schema` — a `standard://` URI for the Action Proposal Schema the
  actor must satisfy before attempting the side effect.
- `judge` — an `agent://` URI for the judge agent that evaluates the proposal.
- `requires_mandate` — whether execution requires an AP2-style mandate record in
  addition to the proposal.

Skills that only provide context, analysis, or read-only commands omit
`action_boundary`.

**Counter-examples.**
- Do NOT add `model: sonnet` (or any model) to a SKILL.md frontmatter — use an agent if model selection matters.
- Do NOT use `always_apply: true` for something that must block or intercept tool calls — that requires a guardrail/hook, not a skill.
- Do NOT use a skill for a one-off user workflow requiring explicit intent — that is
  a command.

**Worked examples.**

| Skill | Why it is a skill |
|-------|------------------|
| `agent-forge` — "Guide for creating Claude Code agents. Use when creating specialized AI assistants…" | Description triggers auto-load whenever the model detects agent creation context. User does not type `/agent-forge`. |
| `skill-tester` — "Use when testing or installing standalone skills under local development…" | Model auto-invokes when it detects skill development/testing context. |
| `hook-forge` — "Use when creating, configuring, or managing Claude Code hooks…" | Model auto-invokes when hook creation/configuration is in scope. |

**Authoring source-of-truth.** Day-to-day rules for writing a SKILL.md (thin-shell
rule, two-contracts shape, agent-private rule, `disableModelInvocation` guidance)
live in the `skill-forge` skill itself — it is the operational source-of-truth
for skill authoring. This document defines the primitive; `skill-forge` defines
how to write one. Do NOT create parallel policy documents.

---

### 2. Command

**Definition.** A prompt template that a *user* explicitly invokes via a `/name`
slash syntax. The model does not auto-pick commands; the user must type the command.

**Key constitutive feature.** User-only trigger: commands exist because the user
needs explicit control over when a workflow runs, not model discretion.

**Trigger semantics.** User types `/command-name [args]` in the chat interface. The
harness injects the command's template into the conversation. The model then executes
the workflow defined in the template.

**Cost.** Command templates are injected only on explicit invocation — no standing
context cost between invocations.

**Format (Claude Code).** `.claude/commands/<name>.md` with YAML frontmatter. NORMATIVE.

**Format (Codex).** Custom prompts/commands are not supported in Codex. Use skills
instead. NORMATIVE — per CL-qzw research.

**When to choose it.** Use a command when:
- The workflow requires deliberate, explicit user intent (e.g., a destructive operation).
- The workflow is parameterized by user-supplied arguments at invocation time.
- The capability would be confusing or dangerous if auto-triggered by the model.

**Counter-examples.**
- Do NOT use a command for something the model should recognize and apply automatically
  — that is a skill.
- Do NOT use a command in Codex — use a skill with explicit invocation
  guidance in its description.

**Worked examples.**

| Command | Why it is a command |
|---------|-------------------|
| `/compact-reference path/to/file.md` | User explicitly passes a file path. Auto-triggering this would be wrong — the user chooses which file to compact. |
| `/install-playwright` | Destructive system install; user must consciously invoke it. Model should not decide to install Playwright autonomously. |
| `/install-plugin` | Installation is a deliberate act; the user picks the plugin. Auto-triggering would violate user autonomy over system state. |

---

### 3. Agent

**Definition.** An autonomous AI worker with its own context window, system prompt,
tool permissions, and (optionally) model selection. Agents can be spawned by the
orchestrating model to run a subtask in isolation.

**Key constitutive feature.** Isolated context budget: each agent invocation gets a
fresh context window and its own tool grant. The parent model does not share its
context with the subagent.

**Trigger semantics.** The orchestrating model (or a user command) calls
`Agent(subagent_type="<name>")`. The harness launches the agent in a separate context.
The agent runs to completion and returns a result.

**Cost.** Each agent invocation opens a new context window — a significant token cost
for complex tasks. Use agents for tasks that genuinely need isolation, not for simple
lookups.

**Format (Claude Code).** YAML frontmatter in `.claude/agents/<name>.md`. NORMATIVE.

**Format (Codex).** TOML in `.codex/agents/<name>.toml` (or `~/.codex/agents/<name>.toml`
for global). NORMATIVE — Codex has first-class subagents (default/worker/explorer
built-ins plus custom TOML).

**`action_boundary` metadata for side-effecting agents.** NORMATIVE.
Agents that may execute or authorize side effects declare the same boundary fields
as side-effecting skills. Claude agent sources use YAML frontmatter:

```yaml
---
name: payment-runner
description: Execute approved supplier payments.
action_boundary:
  risk_class: external-side-effect
  effect_type: financial
  proposal_schema: standard://judge-layer/proposals/action-proposal.v1
  judge: agent://judge-default
  requires_mandate: true
---
```

Codex agent sources use TOML metadata:

```toml
name = "payment-runner"
description = "Execute approved supplier payments."

[action_boundary]
risk_class = "external-side-effect"
effect_type = "financial"
proposal_schema = "standard://judge-layer/proposals/action-proposal.v1"
judge = "agent://judge-default"
requires_mandate = true
```

**Agent Justification Gate.** NORMATIVE as Library authoring taxonomy.
Agent creation must satisfy at least one C-criterion. Judge agents add C7 and
normally satisfy C1 plus C4, often C5, and sometimes C2.

| Criterion | Justifies an agent when |
|-----------|-------------------------|
| C1: different tool permission set | The work needs a different tool grant than the parent, especially read-only, approval-only, or constrained write access. |
| C2: own context budget | The work needs a fresh context window or must not pollute the parent context. |
| C3: parallel siblings | The work can run independently while the parent or sibling agents continue other work. |
| C4: information barrier | The work needs separation from the actor being checked, or must not see/manipulate the same evidence stream. |
| C5: different model | The work needs a different reasoning tier, latency target, or cost profile. |
| C6: multi-phase orchestration | The work owns a multi-step workflow with durable state, handoffs, or phase gates. |
| C7: pre-action gate | The agent decides whether a proposed side-effect may execute before it happens. |

#### Judge Specialization

**Definition.** A Judge is an Agent specialization that evaluates an Action Proposal
before a side-effecting primitive acts. It returns an allow, deny, request-changes,
or escalate decision, optionally with constraints the actor must follow.

**Key constitutive feature.** Pre-action authorization. A judge sits before the
side effect, not after it. It consumes the proposed action, evidence, expected
consequence, rollback path, and any mandate record, then decides whether the actor
may continue.

**Justification.** A judge must satisfy C7 plus the normal agent gate. In practice
that means C1 (different tool or approval boundary) and C4 (information barrier),
and often C5 (different model). If the check is fully deterministic and does not
require model judgment, use a Guardrail/Hook instead.

**Relationship to reviewers.** Reviewers and verification agents are post-action:
they inspect completed work or generated output. Judges are pre-action: they
authorize, constrain, or reject the action before it executes.

**Distribution status.** This repo defines the taxonomy only. Implementation
artifacts live in the cognovis-core sibling epic (TBD links): default judge agent,
Action Proposal Schema standards, Mandate standards, and forge updates.

**Catalog tags.** Judge-layer artifacts use `judge-layer`; side-effecting actors
that must emit proposals use `requires-proposal`; artifacts that emit AP2-style
mandates use `produces-mandate`. The tag vocabulary is defined in `library.yaml`.

**When to choose it.** Use an agent when:
- The subtask needs a different tool permission set than the parent.
- The subtask is large enough to warrant its own context budget (avoids context
  pollution in the parent).
- The subtask can run in parallel with other agents.
- Security isolation is required (e.g., a read-only verification agent must not
  accidentally write).

**Counter-examples.**
- Do NOT spawn an agent for a single tool call or lookup — that wastes a full context
  window.
- Do NOT create an agent just because the work needs a durable persona, rubric, or
  operating procedure. That is usually a skill or standard unless one of C1-C7 also
  applies.
- Do NOT use an agent when the capability should be reusable across harnesses in a
  portable format — use a skill.

**Worked examples.**

| Agent | Why it is an agent |
|-------|-------------------|
| `beads-workflow:bead-orchestrator` | Orchestrates a multi-step bead workflow with its own system prompt, model, and tool set. Parent model delegates the entire workflow. |
| `beads-workflow:verification-agent` | Isolated, read-only verification context. Tool grant is explicitly limited to Read, Bash, Grep, Glob — isolation prevents accidental writes during verification. |
| `core:session-close` | Orchestrates a multi-phase close pipeline (merge, commit, changelog, push, close bead). Too complex and stateful for inline execution; needs its own context. |

---

### 4. Guardrail (Hook)

**Definition.** A deterministic enforcement mechanism that runs *outside the LLM loop*
at defined lifecycle events. Guardrails fire unconditionally — the model cannot skip or
suppress them.

**Key constitutive feature.** Non-LLM execution: guardrails are not subject to model
reasoning or discretion. They run deterministically as part of the harness machinery.
This is the *only* deterministic safety layer in the agentic stack — everything else
(system prompts, skill instructions, agent restrictions) is best-effort and can be
overridden by the model.

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

**Purpose classes:**
- `pre-tool-veto` — block a tool call before execution. Primary use: security gates.
- `post-tool-reaction` — run side effects after tool completion. Primary use: audit, formatting.
- `session-init` — inject context or setup at session start. Primary use: standards loading.
- `cleanup` — teardown at session end. Primary use: state cleanup, metrics flush.
- `audit-log` — record every tool call. Primary use: compliance logging.

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

### Category 2: Bundle and Distribution

These are not invokable primitives themselves — they are *packaging* units for
distributing collections of invokable primitives.

---

### 5. Plugin

**Definition.** An installable unit that bundles multiple primitives (skills,
commands, agents, hooks) into a single versioned package distributed from
one source. (Scripts are not a primitive — they are an implementation substrate
used inside skills/hooks/agents; see "Design Principle: Scripts" below.)

**Key constitutive feature.** Composite installable: a plugin is defined by its
bundling — it contains multiple primitive types that work together as a coherent
capability. Installing a plugin installs all its parts atomically.

**Trigger semantics.** Plugins are not directly invoked. A user (or CI) runs
`/install-plugin <name>` or equivalent to install the plugin. After installation,
each bundled primitive activates according to its own trigger semantics.

**Cost.** Plugin cost = sum of costs of all bundled primitives. Evaluate each bundled
skill/hook for its standing context or latency cost.

**When to choose it.** Use a plugin when:
- A capability requires multiple cooperating primitives (e.g., a skill + a hook that
  enforces its use).
- You want atomic distribution: if the skill is installed without its companion hook,
  the capability is broken.
- You are publishing to a marketplace for others to discover and install.

**Counter-examples.**
- Do NOT create a plugin for a single skill — that is over-packaging.
- Do NOT treat a plugin as a primitive you can invoke — install it first, then invoke
  its constituent primitives normally.

**Worked examples.**

| Plugin | Why it is a plugin |
|--------|-------------------|
| `reference-file-compactor` | Bundles a skill + a command + hooks into one installable. The skill alone would not work without the companion hooks; atomicity is required. |
| `beads-workflow` | Bundles multiple agents + hooks (with internal scripts as implementation detail of each). The bead orchestration workflow only works when all parts are co-installed. |

---

### 6. Marketplace

**Definition.** A GitHub org or repository that publishes a discoverable collection
of skills, agents, or plugins. The library catalog can reference a marketplace so
users can browse and pull from it.

**Key constitutive feature.** Discovery surface: a marketplace is defined by its role
as a catalog entry point — it publishes primitives for others to find and install, but
does not itself contain installed primitives.

**Trigger semantics.** Marketplaces are not invoked. They are registered via
`library add-marketplace <github-url>`. Users browse or search them and then pull
specific items into their repos.

**Cost.** No runtime cost. Marketplaces are a distribution mechanism only.

**When to choose it.** Register a marketplace when:
- An external GitHub org or repo publishes reusable primitives you want to make
  discoverable to the team.
- You want to centralize discovery without mirroring content.

**Counter-examples.**
- Do NOT mirror third-party content into your own content repos — reference via
  marketplace instead.
- A marketplace is not a primitive you configure in a project — it is a catalog-level
  registration.

**Worked examples.**

| Marketplace | Why it is a marketplace |
|-------------|------------------------|
| `cognovis/samurai-skills` | A GitHub repo that publishes multiple skills for others to pull. Registered in the library catalog; content stays at source. |
| `disler` (GitHub org) | Many public skill repos. Referenced in the library catalog; we do not mirror his content. |
| `anthropics/claude-plugins-official` | Anthropic's curated plugin directory. Third-party; referenced, not mirrored. |

---

### Category 3: Library-Managed Dependencies

These are NOT invocation primitives. They are content types that the Library manages
as dependencies — injected into model context or provisioned as services. The model
does not "call" them the way it calls a skill or agent. NORMATIVE classification
(confirmed from Codex review: standard and mcp-server are not skill-equivalent
invocation primitives).

---

### 7. Standard

**Definition.** A markdown document containing project-specific or cross-cutting
context that supplements skills and agents. Standards are not invoked by the user
or model. They are dependency content loaded only when a consuming primitive
declares `requires_standards:`.

**Key constitutive feature.** Dependency-scoped context: a standard is surfaced
through a consuming skill or agent, not by automatic project-wide injection.

**Delivery semantics — current mechanism (NORMATIVE, Axis 1 lock-in, 2026-05-14):**

**Never auto-injected.** `/library standard use <name>` installs the standard file
at its canonical path and updates `.library.lock`. It does not write to
`AGENTS.md`, `CLAUDE.md`, or any other harness context file. Standards reach the
model only when a consuming primitive declares `requires_standards: [<name>]`.

**Update + remove.** `/library sync` refreshes the vendored standard files under
`.agents/standards/<name>/` or `~/.agents/standards/<name>/` and updates the
lockfile content hash. `/library standard remove <name>` deletes the installed
files and lockfile entry only.

**Standard file paths (cross-harness convention, CL-v56).**

| Priority | Path | Scope |
|----------|------|-------|
| 1 (wins) | `.agents/standards/<name>/<name>.md` | Project-local, folder-form |
| 2 | `~/.agents/standards/<name>/<name>.md` | User-global, folder-form |

**Standard file layout (single-file vs folder-form).**

| Form | When to use | Layout |
|------|-------------|--------|
| Single-file | <600 tokens, single topic | `standards/<name>/<name>.md` (the folder holds only the one entry file) |
| Folder-form | 600-3000 tokens with multiple sub-topics | `standards/<name>/<name>.md` (entry) + sibling `<topic>.md` files in the same folder |

Convention: **entry file = stem matches folder name**. Sibling `.md` files in the
same folder are detail pages reachable via relative links from the entry. The entry
file is what `requires_standards: [<identifier>]` loads; sibling files are pulled
on demand by the model when it follows a link.

For >3000 tokens of disparate content, prefer two separate standards over one
folder with many sibling files.

**Frontmatter convention (domain vs rule).**

A standard's entry file declares either `domain:` or `rule:` in its frontmatter —
one of the two, not both. The choice tells the agent at a glance what kind of
shared knowledge it just opened.

| Field | Use when content is | Example |
|-------|---------------------|---------|
| `domain:` | A body of knowledge about a topic | `domain: python-cli-patterns`, `domain: healthcare-control-areas` |
| `rule:` | A convention or prohibition that applies broadly | `rule: english-only`, `rule: no-emoji`, `rule: adr-location` |

```yaml
# Domain-style standard:
---
domain: python-cli-patterns
description: How to author Python CLIs with argparse, click, and the release flow.
---

# Rule-style standard:
---
rule: english-only
description: All source code is English; user-facing strings may be localized.
---
```

Loader and validator accept either field as the standard's identifier. In
`library.yaml` the catalog entry still uses `name:` — that is catalog-internal and
not user-facing.

The folder name matches the identifier value: `domain: python-cli-patterns` →
`standards/python-cli-patterns/python-cli-patterns.md`.

**Judge-layer standard subtypes.** NORMATIVE as Library taxonomy.
These are standards, not new primitive classes, because they are shared context and
schema contracts consumed by skills, agents, and judges.

| Subtype | Definition | Required shape |
|---------|------------|----------------|
| Action Proposal Schema | A structured object an actor must produce before a side effect. | intended action, evidence, authorization context, expected consequence, rollback path |
| Mandate | An AP2-style authorization-as-evidence record that can be attached to an Action Proposal. | scope, limits, evidence, granted_at, granted_by, expires_at, supersedes |

Action Proposal Schema standards define what a side-effecting actor must submit to
the judge. Mandate standards define durable authorization records: they are evidence
that the actor has permission within a bounded scope, not permission to do anything
outside that scope.

**Optional `scripts/` directory.**

A standard folder may include `scripts/<name>.{sh,py}` alongside its markdown
when parts of the standard can be enforced or automated deterministically.

| Standard kind | Typical script role | Called by |
|---------------|---------------------|-----------|
| `rule:` | Enforcement — e.g. `scripts/check-english.py` scans source files and exits non-zero on violation | Pre-commit hooks, guardrails |
| `domain:` | Tooling — e.g. `scripts/scaffold-cli.py` generates argparse boilerplate | Skills that consume the standard |

Scripts are **not invoked by the standard itself** — the standard's `.md` remains
pure model-context. Scripts are called from outside: by hooks (for rules) or by
skills (for domains). This keeps the standard contract clean (context-only) while
allowing deterministic enforcement to ship in the same package.

Output contract: scripts with multiple failure modes follow the
`execution-result-envelope` JSON shape (`status`, `summary`, `data`, `errors`,
`next_steps`). Pre-commit-style binary enforcement uses a non-zero exit code
with stderr diagnostics.

**Maturity arc (skill reference ↔ standard).**

Markdown files containing factual knowledge can live in two places — inside one
skill as a private reference, or in the catalog as a standard. The structural
difference is ownership and addressability, not content.

| Criterion | Skill-internal reference (`skills/<skill>/references/foo.md`) | Standard (`standards/<name>/<name>.md`) |
|-----------|---------------------------------------------------------------|-----------------------------------------|
| Entry in `library.yaml` | No | Yes (under `library.standards:`) |
| Reachable by other primitives | No — bundled with parent skill | Yes, via `requires_standards: [name]` |
| Versioned with | Parent skill commit | Independent source/commit |
| Reachable when parent skill not loaded | No | Yes |
| Installable standalone | No | Yes (`library standard use <name>`) |

**Operative test:** Would a second primitive (another skill, agent, or project)
want to declare this as a dependency? If yes → standard. If no → skill-internal
reference.

**Mechanical test:** Does the file have a `name:` entry in `library.yaml`? If
yes, it is a standard. If no, it is a skill-internal reference. (Inside the
standard file itself, the identifier appears as `domain:` or `rule:`; the
library.yaml entry maps that to `name:`.)

**Lifecycle:**

```
new idea
   │
   ▼
skill reference         "useful only for this skill"
   │ (promotion: another primitive needs the same content)
   ▼
catalog standard        "shared knowledge with its own lifecycle"
   │ (demotion: only one primitive still uses it)
   ▼
skill reference (back)
```

Promotion mechanics:
1. Move the file: `skills/<skill>/references/<file>.md` → `standards/<name>/<name>.md`
2. Register the entry in `library.yaml` under `library.standards:`
3. Add `requires_standards: [<name>]` to every skill that needs it
4. Remove the original `references/<file>.md` from the source skill
5. Update intra-skill links to rely on `requires_standards` for loading

Demotion is the inverse: fold the standard back into the one skill's `references/`,
drop the catalog entry, remove `requires_standards:` declarations.

**Skills declare dependencies** via `requires_standards` frontmatter:

```yaml
---
name: dolt
description: Dolt version-controlled database skill.
requires_standards: [dolt-server, branch-naming]
---
```

**Runtime loading (skill-script-side):** Individual skill scripts read the cached file
directly from its resolved path (project-local `.agents/standards/<name>/` wins over
user-global `~/.agents/standards/<name>/`):

```bash
STD_PATH=".agents/standards/<name>/<name>.md"
[ -f "$STD_PATH" ] || STD_PATH="${HOME}/.agents/standards/<name>/<name>.md"
STANDARD=$(cat "$STD_PATH")
```

**When to choose it.** Create a standard when:
- A project has coding conventions, architectural decisions, or integration patterns
  that every agent working on the project must know.
- The content is context (factual guidance), not executable workflow (which would be
  a skill).
- The content crosses multiple skills and would need to be duplicated if embedded in
  each skill individually.

**Counter-examples.**
- Do NOT use a standard as an invocable skill — it is not addressable by `/name` or
  by model description-matching.
- Do NOT put imperative workflow steps in a standard — that is a skill or command.

**Metadata note.** Library-owned metadata (e.g., `metadata.library.requires_standards`)
lives in the Library's own namespace. Do NOT pollute standard SKILL.md frontmatter
fields with Library-internal metadata.

**Authoring source-of-truth.** Day-to-day rules for writing a standard
(`rule:` vs `domain:` frontmatter, folder-form vs single-file layout, required
and optional fields, maturity-arc test, promotion mechanics) live in the
`standard-forge` skill itself — it is the operational source-of-truth for
standard authoring. This document defines the primitive; `standard-forge`
defines how to write one. Do NOT create parallel policy documents.

---

### 8. MCP-Server

**Definition.** An external capability provider accessed via the Model Context
Protocol (MCP). MCP servers expose tools, resources, and prompts to any MCP-compatible
client without requiring shell access.

**Key constitutive feature.** Protocol-mediated external capability: MCP servers run
as separate processes (or remote services) and expose a typed tool API over a standard
protocol. They are the primary extensibility mechanism for harnesses that have no
shell access.

**Trigger semantics.** MCP tools appear in the model's tool list alongside native
tools. The model calls them the same way it calls Bash or Read — by generating a
tool-use block. The MCP server responds with a tool result.

**Decision rule (harness-dependent).**

| Harness | Shell access | Recommendation |
|---------|-------------|----------------|
| Claude Code | YES | Prefer CLI + Skill. MCP adds process overhead without benefit when shell is available. INFERRED — architectural principle. |
| Codex CLI | YES | Same as Claude Code: prefer CLI + Skill. INFERRED. |
| claude.ai web | NO | MCP-Server is the only path for external tool access. NORMATIVE. |
| Claude iOS | NO | MCP-Server is the only path for external tool access. NORMATIVE. |

**When to choose it.** Use an MCP server when:
- The target harness has no shell access (web, mobile) and the capability requires
  external data or tool execution.
- An existing MCP server already provides the capability (no need to wrap in a skill).
- The capability must be accessible to both coding and non-coding harnesses and you
  want a single implementation.

**Counter-examples.**
- Do NOT default to MCP for Claude Code / Codex — when you have shell access, a CLI
  tool + skill is simpler, faster, and easier to debug.
- Do NOT build an MCP server to replace a skill that only coding harnesses use.

**Worked examples.**

| MCP Server | Why it is an MCP server |
|-----------|------------------------|
| `executive-circle` MCP | Content library for web/iOS users who have no shell access. The CLI equivalent (`crwl`) exists for coding harnesses. |
| `pencil` MCP | Design tool for non-coding harnesses. `.pen` files are encrypted and must be accessed via MCP tools. |

---

### 9. Design Principle: Scripts (not a primitive)

Scripts are not an agentic primitive — they are the preferred implementation substrate
for deterministic logic inside any primitive.

**The rule:** Maximize deterministic script logic; minimize model decisions.

- Logic that is deterministic, testable, and >50 lines MUST be extracted to a script
  (bash or Python via `uv`). Do not embed it inline in a skill's prompt.
- The model is expensive and non-deterministic. Anything the model decides that a
  script could decide reliably is wasted tokens and added variance.
- Standard runtime: `bash` for simple orchestration; `uv`-managed Python for anything
  requiring libraries or structured data.

**Where scripts live.**

| Context | Script location |
|---------|----------------|
| Skill implementation | `skills/<name>/bin/` alongside SKILL.md |
| Hook implementation | `hooks/<event>/<name>.py` or `.sh` |
| Plugin shared logic | `plugins/<name>/scripts/` |
| Standalone Justfile tasks | `justfile` (tool-agnostic shell) |

**Anti-pattern.** A 200-line shell pipeline embedded in a skill's prompt is a smell.
The model will hallucinate flags, get argument order wrong, and produce non-reproducible
results. Extract to a script and have the skill call it.

---

### 10. Model-Standard

**Definition.** A markdown document containing model-specific behavioral guidance
injected for an agent persona on a given model (e.g., conciseness guidance for
Sonnet, extended thinking budget configuration for Opus). Model-standards are a
sub-type of standards scoped to a particular model's characteristics.

**Key constitutive feature.** Model-scoped behavioral overlay: unlike general
standards (which apply to any model), a model-standard is keyed to a specific model
ID and adjusts the agent's behavior for that model's strengths and limitations.

**Storage.** `.agents/model-standards/<model-name>.md` (project-local) or
`~/.agents/model-standards/<model-name>.md` (user-global).
Example: `.agents/model-standards/claude-sonnet-4-6.md`

**Loading.** Model-standards use project-local > user-global precedence and are
inlined by the Library composer into the effective agent system prompt.

**Path resolution (same precedence rules as Standards):**

| Priority | Path | Scope |
|----------|------|-------|
| 1 (wins) | `.agents/model-standards/<name>.md` | Project-local |
| 2 | `~/.agents/model-standards/<name>.md` | User-global |

**Trigger semantics.** Injected at agent instantiation time when the agent's
frontmatter specifies a `model` field matching this model-standard's filename. The
three-layer composition is applied in order (see Golden Prompt Composition below).

**Agent Golden Prompt Composition.**

When the harness instantiates an agent, the effective system prompt is composed from
three layers in order:

```
Layer 1: Cognovis Base Golden Prompt
  └── Global behavioral rules, safety checks, confirmation gates,
      content isolation, core skill access. Applies to all agents.

Layer 2: Agent Persona
  └── The agent's own system prompt (from .claude/agents/<name>.md
      or .codex/agents/<name>.toml). Defines the agent's specific
      purpose, tool grants, and domain expertise.

Layer 3: Model-Standard (optional)
  └── Model-specific overlays: verbosity tuning, thinking budget,
      output format adjustments, known model quirks to work around.
      Applied only when the agent's `model` field matches a known
      model-standard.
```

**Decision-rule frontmatter fields.**

```yaml
# In an agent's frontmatter (.claude/agents/<name>.md):
golden_prompt_extends: cognovis-base   # which base golden prompt to use
model: claude-sonnet-4-6               # triggers model-standard lookup
model_standards: [conciseness, tool-use-efficiency]  # optional explicit overrides
```

**Composition algorithm (install-time, NOT runtime).**

The Library executes this composition once when the agent is installed or synced.
There is no runtime composition — the harness receives the fully-composed prompt.

Source and target are always SEPARATE paths. The source agent file (library copy) is
never overwritten — the composed prompt is written to the installed copy only.

```
1. Load Layer 1: read .agents/golden-prompts/<golden_prompt_extends>.md
   (skip if golden_prompt_extends=from-scratch or file not found)

2. Load Layer 2: read the SOURCE agent file body (library copy, never the installed copy)
   This reads the original unmodified persona. Repeat installs always read the same source.

3. Load Layer 3:
   a) If model_standards is non-empty: load each name via
         standards-loader.sh --load-model-standard <name>
      Concatenate results in declaration order.
   b) If model_standards is empty AND model is set: attempt alias-based lookup via
         standards-loader.sh --load-model-standard <model>
      (the loader resolves by alias if direct filename lookup fails; silent skip on miss)

4. Compose: Layer1 + "\n---\n" + Layer2 + ("\n---\n" + Layer3 if Layer3 non-empty)

5. Write composed prompt to INSTALLED copy (separate from source):
   - Claude Code: .claude/agents/<name>.md body (keep frontmatter from source)
   - Codex: developer_instructions in .codex/agents/<name>.toml
     (add composition metadata as header comments)
   - OpenCode: .opencode/agents/<name>.md body
   - Pi: export as TypeScript string from the extension module
```

**Tool constraint encoding.** Per-agent tool grants (`tools:`, `disallowedTools:`) are
NOT enforced by all harnesses at the sandbox level (Codex global sandbox semantics
ignore per-agent tool constraints). Therefore, the Library MUST encode the agent's
effective tool grant in the composed system prompt body, not rely on frontmatter alone.
The Cognovis Base Golden Prompt (`Layer 1`) includes a "Tool Constraints" section that
instructs the agent to honor its declared tool list behaviorally even when the harness
would technically allow broader access.

**Canonical source locations (CL-9b1).**

- Golden prompts: `.agents/golden-prompts/<name>.md`
  - Cognovis base: `.agents/golden-prompts/cognovis-base.md`
- Model standards: `.agents/model-standards/<model-name>.md`
  - Sonnet conciseness: `.agents/model-standards/claude-sonnet-4-6.md`
  - Opus thinking budget: `.agents/model-standards/claude-opus-4-7.md`

**When to choose it.** Create a model-standard when:
- A specific model has known behaviors (verbosity, thinking defaults, tool-call
  patterns) that require project-wide adjustment.
- Different agents in the system run on different models and need model-aware
  behavioral tuning without duplicating guidance in every agent file.

**Counter-examples.**
- Do NOT put model-specific guidance in the agent persona file — that locks the
  persona to one model and makes model-swapping harder.
- Do NOT create a model-standard for a behavior that applies to all models — that
  belongs in the base golden prompt or a general standard.
- Do NOT introduce a parallel loader for model-standards — reuse
  `scripts/standards-loader.sh --load-model-standard <name>` (same contract).

---

## Precedence and Name Collision Policy

> Full policy: `docs/policy/name-collision.md` (CL-b4o). This section is a summary
> for primitive-taxonomy consumers. The policy document is authoritative.

### Install path precedence (within a harness)

For every harness, **project-local always overrides global** for the same skill name.

| Harness | Wins (project-local) | Loses (user-global) |
|---------|----------------------|---------------------|
| Claude Code | `.claude/skills/<name>` (bridge -> `.agents/skills/<name>`) | `~/.claude/skills/<name>` |
| Codex CLI | `.agents/skills/<name>` (canonical, read natively) | `~/.agents/skills/<name>` |

### Canonical vs. bridge

Every skill install creates the same three-layer structure:

| Role | Path |
|------|------|
| Layer B (real files, content-addressable) | `~/.local/share/library/skills/<m>/<n>@<tree-sha>/SKILL.md` |
| **Canonical** (Layer C) | `.agents/skills/<name>` real vendored copy by default |
| **Claude bridge** (Layer C) | `.claude/skills/<name>` → `.agents/skills/<name>` (symlink) |
| Codex | reads `.agents/skills/<name>` natively (r1 root, CL-603) — no install path |

The `.agents/skills/<name>` path is always canonical. The `.claude/skills/<name>`
path is always the Claude harness bridge symlink. Codex reaches the same
canonical files directly; no separate `.codex/skills/<name>` install target.
The Layer-B cache remains the resolver source; Layer C is committed content unless
the user explicitly installs with `--symlink` for local development.

### Name uniqueness requirement

Skill names MUST be globally unique within a project. Two real directories at
`.agents/skills/foo` and `.claude/skills/foo` (neither a symlink) are a policy
violation — bug reports from that state will be untriageable.

### Uninstall completeness

`/library remove` MUST remove the Claude bridge AND the canonical install AND
the lockfile entry. The removal sequence: Claude bridge first, then canonical,
then lockfile. The Layer-B cache (`~/.local/share/library/skills/...`) is
garbage-collected separately by `/library prune-cache` once no lockfile entry
references it.

### Admin override

Anthropic's marketplace force-enable operates outside Library's path rules.
Library treats managed skills as read-only and does not override them.

---

## Cross-References

- **ARCHITECTURE.md**: Layer stack, operational workflow, repo split, marketplaces.
  See [ARCHITECTURE.md](ARCHITECTURE.md).
- **Primitive Definitions**: This file (PRIMITIVES.md) is the source of truth for all
  primitive type definitions.
- **Name Collision Policy**: `docs/policy/name-collision.md` (CL-b4o) — authoritative
  policy for collision handling, symlink lifecycle, and uninstall completeness.
- **Audit doc** (`docs/audit/skills-origin.md`, CL-23z): This doc's taxonomy is used to
  classify the intent of every existing artifact. CL-23z inventory uses PRIMITIVES.md
  definitions to classify all 44 agents in scope.
- **Agent Format Mapping** (`docs/research/agents-format-mapping.md`, CL-11p): Field
  mapping for Claude Code ↔ Codex agent translation. Covers new frontmatter fields
  `golden_prompt_extends` and `model_standards` introduced in CL-9b1.
- **Golden Prompts** (CL-9b1): Canonical sources at `.agents/golden-prompts/` and
  `.agents/model-standards/`. See §10 Model-Standard for composition algorithm.
- **Research beads**:
  - `CL-qzw` — Codex Layer 3 (prompts/skills) parity research (source of Codex
    NORMATIVE claims in this doc)
  - `CL-xcm` — Hook distribution across harnesses
  - `CL-11p` — Agent format translation spec (Claude Code ↔ Codex)
  - `CL-7ii` — Marketplace implementation
  - `CL-9b1` — Golden Prompt composition + Model-Standards (§10 implementation)
