# Agentic Primitives Glossary

> v0 — source of truth for primitive definitions used across the cognovis-library multi-harness stack.
> Last updated: 2026-04-30
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
 └─ YES → AGENT (own context window, own system prompt, own tool set)
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
model infers a skill is relevant (via description matching), it reads the full SKILL.md
and follows its instructions.

**Cost (per harness).**

| Harness | Startup cost | Runtime cost |
|---------|-------------|--------------|
| Claude Code | Full SKILL.md text loaded at session start for every installed skill. High static context cost. NORMATIVE — confirmed behavior. | Skill content already in context; no per-invocation fetch. |
| Codex CLI | Name, description, and path only loaded at startup (NOT full text). Much lower static cost. NORMATIVE — from CL-qzw research. | Full SKILL.md fetched on first use. Per-invocation fetch cost. |

**Format.** SKILL.md — shared format (Open Agent Skills Standard). Install paths
differ: `.claude/skills/<n>/SKILL.md` (Claude Code) vs `.agents/skills/<n>/SKILL.md`
(Codex). NORMATIVE for both tools.

**When to choose it.** Use a skill when:
- The capability should be available without the user remembering a command.
- The capability is context-sensitive (model should decide when to apply it).
- The skill is reusable across multiple projects and harnesses.

**Counter-examples.**
- Do NOT use a skill for something that must fire unconditionally — that is a
  guardrail/hook.
- Do NOT use a skill for a one-off user workflow requiring explicit intent — that is
  a command.

**Worked examples.**

| Skill | Why it is a skill |
|-------|------------------|
| `agent-forge` — "Guide for creating Claude Code agents. Use when creating specialized AI assistants…" | Description triggers auto-load whenever the model detects agent creation context. User does not type `/agent-forge`. |
| `skill-tester` — "Use when testing or installing standalone skills under local development…" | Model auto-invokes when it detects skill development/testing context. |
| `hook-creator` — "Use when creating, configuring, or managing Claude Code hooks…" | Model auto-invokes when hook creation/configuration is in scope. |

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

**Format (Claude Code).** `.claude/commands/<n>.md` with YAML frontmatter. NORMATIVE.

**Format (Codex).** Custom prompts/commands are DEPRECATED in Codex. Use skills
instead. NORMATIVE — per CL-qzw research.

**When to choose it.** Use a command when:
- The workflow requires deliberate, explicit user intent (e.g., a destructive operation).
- The workflow is parameterized by user-supplied arguments at invocation time.
- The capability would be confusing or dangerous if auto-triggered by the model.

**Counter-examples.**
- Do NOT use a command for something the model should recognize and apply automatically
  — that is a skill.
- Do NOT use a command in Codex (deprecated) — use a skill with explicit invocation
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

**Format (Claude Code).** YAML frontmatter in `.claude/agents/<n>.md`. NORMATIVE.

**Format (Codex).** TOML in `.codex/agents/<n>.toml` (or `~/.codex/agents/<n>.toml`
for global). NORMATIVE — Codex has first-class subagents (default/worker/explorer
built-ins plus custom TOML).

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

**Definition.** A deterministic script that runs *outside the LLM loop* at defined
lifecycle events. Guardrails fire unconditionally — the model cannot skip or suppress
them.

**Key constitutive feature.** Non-LLM execution: hooks are not subject to model
reasoning or discretion. They run deterministically as part of the harness machinery.

**Trigger semantics.** The harness fires hooks at predefined events. The hook script
runs synchronously (PreToolUse/PostToolUse) or asynchronously (PostToolUseFailure,
Notification). Hooks can block tool execution (PreToolUse returning exit code 2) or
observe silently.

**Hook events (per harness).**

| Harness | Available events |
|---------|----------------|
| Claude Code | 13 events: SessionStart, SessionEnd, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, PermissionRequest, Notification, SubagentStart, SubagentStop, Stop, PreCompact, Setup. NORMATIVE. |
| Codex CLI | 3 events only: SessionStart, SessionEnd, Stop. NORMATIVE — per CL-qzw research. |

**Cost.** Hooks run as external processes — low LLM token cost, but each hook adds
latency to the event they intercept. Keep hook scripts fast (<100 ms) for
PreToolUse/PostToolUse hooks.

**When to choose it.** Use a guardrail/hook when:
- A behavior must be enforced regardless of model decisions (security, logging,
  formatting).
- Context must be injected at session start before the model processes any prompts.
- A side effect must always happen after a tool use (auto-format, audit log).

**Counter-examples.**
- Do NOT use a hook for capabilities the model should reason about — that is a skill.
- Do NOT use a hook for interactive workflows — hooks run non-interactively and cannot
  prompt the user mid-execution.

**Worked examples.**

| Hook | Why it is a hook |
|------|-----------------|
| `auto-capture.py` (PreToolUse) | Captures tool calls for audit. Must fire on every tool use regardless of what the model decides. Model cannot opt out. |
| `bd-cache-invalidator.py` (PreToolUse) | Invalidates beads cache. Must run before specific tool types unconditionally to keep cache consistent. |
| SessionStart context-loader hooks | Inject standards and skill context before the model sees any user input. Must run before model reasoning begins — model cannot be trusted to load its own context reliably. |

---

### Category 2: Bundle and Distribution

These are not invokable primitives themselves — they are *packaging* units for
distributing collections of invokable primitives.

---

### 5. Plugin

**Definition.** An installable unit that bundles multiple primitives (skills,
commands, agents, hooks, scripts) into a single versioned package distributed from
one source.

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
| `beads-workflow` | Bundles multiple agents + scripts + hooks. The bead orchestration workflow only works when all parts are co-installed. |

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
context that supplements global skills. Standards are injected into the model's
context by the harness (not invoked by the model or user), providing durable
behavioral guidance scoped to a project or domain.

**Key constitutive feature.** Harness-injected context (not model-invoked): a
standard is surfaced to the model by the harness at session start or on demand via
the standards injection mechanism — the model does not autonomously "call" a standard.

**Trigger semantics.** Injected via SessionStart hook (Claude Code today — NORMATIVE).
Future migration target: file-convention at `.agents/standards/<name>.md` readable by
any harness. Discovery is via `standards/index.yml` which maps trigger conditions to
standard files.

**Current examples (from `~/.claude/standards/index.yml`).**

| Standard | Domain |
|----------|--------|
| `python/style` | Python coding style rules |
| `python/python314-patterns` | Python 3.14 pattern guidance |
| `dev-tools/script-first-rule` | Maximize script logic, minimize model decisions |
| `dev-tools/execution-result-envelope` | Structured tool result format |
| `dev-tools/python-default-bash-exception` | Python exception handling in bash contexts |
| `integrations/open-brain-http-client` | HTTP client patterns for open-brain |

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

### Design Principle: Scripts (not a primitive)

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
| Skill implementation | `skills/<n>/bin/` alongside SKILL.md |
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

**Storage.** `.agents/model-standards/<model-name>.md`
Example: `.agents/model-standards/claude-sonnet-4-6.md`

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
  └── The agent's own system prompt (from .claude/agents/<n>.md
      or .codex/agents/<n>.toml). Defines the agent's specific
      purpose, tool grants, and domain expertise.

Layer 3: Model-Standard (optional)
  └── Model-specific overlays: verbosity tuning, thinking budget,
      output format adjustments, known model quirks to work around.
      Applied only when the agent's `model` field matches a known
      model-standard.
```

**Decision-rule frontmatter fields.**

```yaml
# In an agent's frontmatter (.claude/agents/<n>.md):
golden_prompt_extends: cognovis-base   # which base golden prompt to use
model: claude-sonnet-4-6               # triggers model-standard lookup
model_standards: [conciseness, tool-use-efficiency]  # optional explicit overrides
```

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

---

## Cross-References

- **ARCHITECTURE.md**: Layer stack, operational workflow, repo split, marketplaces.
  See [ARCHITECTURE.md](ARCHITECTURE.md).
- **Primitive Definitions**: This file (PRIMITIVES.md) is the source of truth for all
  primitive type definitions.
- **Audit doc**: Per-harness behavior claims in this document are labeled NORMATIVE
  or INFERRED to support future validation.
- **Research beads**:
  - `CL-qzw` — Codex Layer 3 (prompts/skills) parity research (source of Codex
    NORMATIVE claims in this doc)
  - `CL-xcm` — Hook distribution across harnesses
  - `CL-11p` — Agent format translation spec (Claude Code ↔ Codex)
  - `CL-7ii` — Marketplace implementation
