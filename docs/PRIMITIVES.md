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
 └─ YES → SCRIPT (Python-only deterministic helper). Wrap the script in a Skill,
           Command, Hook, Agent, or Gas City pack surface if the model/runtime
           needs to call it.
 └─ NO  → Continue below.

Should the model auto-pick this up from context?
 └─ YES → SKILL (model-triggered, no user action needed)
 └─ NO  → Continue below.

Does the user invoke it explicitly by typing a slash command?
 └─ YES → COMMAND (user-only trigger, /name syntax)
 └─ NO  → Continue below.

Does it need an isolated context budget / own tool permissions?
 └─ YES → Is this a pre-action gate (decides whether a proposed side-effect may execute)?
           ├─ YES → JUDGE (specialization of Agent — see [Agent](primitives/agent.md#judge-specialization))
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
 └─ NO  → Continue below.

Does it provide a shared base prompt layer for multiple agents (Layer 1
of the composed agent system prompt)?
 └─ YES → GOLDEN-PROMPT (a.k.a. "agent base prompt")
 └─ NO  → Continue below.

Does it replace or extend the ORCHESTRATOR's system prompt or tool set
(the prompt loaded by `cld` / `cdx` at session start, NOT an agent's prompt)?
 └─ YES → SYSTEM-PROMPT
```

> **Two distinct "system prompts" in this stack.** The decision tree
> distinguishes them because they live in different contexts:
>
> - **Orchestrator system prompt** ([system-prompt](primitives/system-prompt.md))
>   — top-level `cld` / `cdx` session. Default = vendor prompt; override via
>   CLI flags or the `system-prompts/registry.yml` mechanism.
> - **Agent system prompt** ([agent](primitives/agent.md) + Layer 1
>   [golden-prompt](primitives/golden-prompt.md) + Layer 3
>   [model-standard](primitives/model-standard.md)) — each spawned subagent.
>   Composed at install time by the Library.
>
> Subagents do **not** inherit the orchestrator's system prompt. Setting one
> does not affect the other.

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
| 1 | [Skill](primitives/skill.md) | **YES** — shared SKILL.md (Open Agent Skills Standard) | full text at session start | name+desc at startup, full on-demand | n/a | n/a | n/a | details |
| 2 | [Command](primitives/command.md) | partial — same intent, different formats | `.claude/commands/*.md` (slash) | TBD (CL-qzw) | n/a | n/a | n/a | details |
| 3 | [Agent](primitives/agent.md) | **NO** — harness-specific format | `.claude/agents/*.md` (YAML) | `.codex/agents/*.toml` (TOML) | n/a | n/a | n/a | details |
| 3a | [Action Boundary](primitives/action-boundary.md) | partial — shared keys, primitive-native serialization | YAML frontmatter on skills/agents | YAML for skills, TOML for agents | n/a | unverified | unverified | metadata |
| 4 | [Guardrail/Hook](primitives/guardrail-hook.md) | **NO** — event coverage diverges | 15 events | 8 events (PreToolUse, PermissionRequest, PostToolUse, PreCompact, PostCompact, SessionStart, UserPromptSubmit, Stop) | `approval_policy` only | `tool_call`, `tool_result`, `message`, `session_start` (INFERRED) | `rules` array (INFERRED) | details |
| 5 | [Plugin](primitives/plugin.md) | bundle — portability inherits from contents | yes | yes | partial | partial | partial | details |
| 6 | [Marketplace](primitives/marketplace.md) | yes — distribution layer | yes | yes | yes | yes | yes | details |
| 7 | [Standard](primitives/standard.md) | **YES** — shared markdown, harness-agnostic | inject via hook + `requires_standards:` | `requires_standards:` + AGENTS.md adapter | n/a | n/a | n/a | details |
| 8 | [MCP-Server](primitives/mcp-server.md) | yes — protocol-level | yes (also CLI+Skill preferred when shell access) | yes (also CLI+Skill preferred) | n/a | yes (only path) | yes | details |
| 9 | [Script](primitives/script.md) | **YES** — Python file plus Library metadata | callable from skills/hooks/commands | callable from skills/hooks | callable from CI/export | callable through adapters | callable through adapters | details |
| 10 | [Model-Standard](primitives/model-standard.md) | partial — concept portable, mechanism per-harness | yes | yes | partial | unverified | unverified | details |
| 11 | [Golden-Prompt (Agent Base Prompt)](primitives/golden-prompt.md) | **YES** — shared markdown base layer, harness composition varies | install-time composition into agent system prompt | install-time composition into agent system prompt | partial | unverified | unverified | details |
| 12 | [System-Prompt](primitives/system-prompt.md) | partial — concept portable, flags differ per harness | `--system-prompt[-file]`, `--tools`, `--bare`, cld registry | TBD — Codex flag parity unverified | n/a | n/a | n/a | details |

**How to read this:**
- **portable** = same source file works in multiple harnesses (no translation needed)
- **harness-specific** = each harness needs its own representation
- **n/a** = primitive does not exist in that harness's mental model
- Cells with `INFERRED` mean pending validation — see the per-primitive section.

For a capability decision ("should this be a skill or an agent?"), use the Quick Decision Tree above.
For implementation details on any cell, jump to its linked section below.

## Primitive Reference

Detailed definitions now live in focused pages. The headings below preserve the old
anchors used by existing docs and external references.

### Action Boundary Metadata

Details: [Action Boundary Metadata](primitives/action-boundary.md).

### Plane And Projection Vocabulary

Details: [Plane And Projection Vocabulary](primitives/plane-vocabulary.md).

### 1. Skill

Details: [Skill](primitives/skill.md).

### 2. Command

Details: [Command](primitives/command.md).

### 3. Agent

Details: [Agent](primitives/agent.md). Judge remains a specialization of Agent.

### 4. Guardrail (Hook)

Details: [Guardrail / Hook](primitives/guardrail-hook.md).

### 5. Plugin

Details: [Plugin](primitives/plugin.md).

### 6. Marketplace

Details: [Marketplace](primitives/marketplace.md).

### 7. Standard

Details: [Standard](primitives/standard.md).

### 8. MCP-Server

Details: [MCP-Server](primitives/mcp-server.md).

### 9. Script

Details: [Script](primitives/script.md).

### 10. Model-Standard

Details: [Model-Standard](primitives/model-standard.md).

### 11. Golden-Prompt (Agent Base Prompt)

Details: [Golden-Prompt](primitives/golden-prompt.md). Layer 1 of the
composed **agent** system prompt. Distinct from the orchestrator system
prompt (see #12).

### 12. System-Prompt

Details: [System-Prompt](primitives/system-prompt.md). The **orchestrator**-level
system prompt + built-in tool set that `cld` / `cdx` loads at top-level session
start. Distinct from the agent system prompt (see #3, #10, #11). Subagents do
not inherit it.


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
- **Primitive Definitions**: The focused pages under `docs/primitives/` are the
  source of truth for individual primitive type definitions; this file is the
  navigation entrypoint and compatibility anchor map.
- **Name Collision Policy**: `docs/policy/name-collision.md` (CL-b4o) — authoritative
  policy for collision handling, symlink lifecycle, and uninstall completeness.
- **Audit doc** (`docs/audit/skills-origin.md`, CL-23z): This doc's taxonomy is used to
  classify the intent of every existing artifact. CL-23z inventory uses PRIMITIVES.md
  definitions to classify all 44 agents in scope.
- **Agent Format Mapping** (`docs/research/agents-format-mapping.md`, CL-11p): Field
  mapping for Claude Code ↔ Codex agent translation. Covers new frontmatter fields
  `golden_prompt_extends` and `model_standards` introduced in CL-9b1.
- **Golden Prompts** (CL-9b1): Canonical sources at `.agents/golden-prompts/` and
  `.agents/model-standards/`. See [Model-Standard](primitives/model-standard.md) and [Golden-Prompt](primitives/golden-prompt.md) for the composition algorithm.
- **Research beads**:
  - `CL-qzw` — Codex Layer 3 (prompts/skills) parity research (source of Codex
    NORMATIVE claims in this doc)
  - `CL-xcm` — Hook distribution across harnesses
  - `CL-11p` — Agent format translation spec (Claude Code ↔ Codex)
  - `CL-7ii` — Marketplace implementation
  - `CL-9b1` — Golden Prompt composition + Model-Standards implementation
