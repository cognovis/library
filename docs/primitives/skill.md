# Skill

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

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
- **Cursor**: skills are projected through `.cursor/skills/<name>/` as a symlink
  to the canonical `.agents/skills/<name>/` project install. Global installs use
  `~/.cursor/skills/<name>/` pointing to `~/.agents/skills/<name>/`.

In both harnesses, the `description` field is what the model matches against to
decide relevance — only the timing of the full-text load differs.

**Cost (per harness).**

| Harness | Startup cost | Runtime cost |
|---------|-------------|--------------|
| Claude Code | Full SKILL.md text loaded at session start for every installed skill. High static context cost. NORMATIVE — confirmed behavior. | Skill content already in context; no per-invocation fetch. NORMATIVE — direct consequence of session-start loading. |
| Codex CLI | Name, description, and path only loaded at startup (NOT full text). Much lower static cost. INFERRED — consistent with CL-qzw research findings on Codex skill discovery; pending direct vendor confirmation. | Full SKILL.md fetched on first use. Per-invocation fetch cost. INFERRED — consistent with CL-qzw research findings; pending direct vendor confirmation. |

**Format.** SKILL.md — shared format (Open Agent Skills Standard). Install paths
differ: `.agents/skills/<name>/SKILL.md` (canonical, read by Codex natively and by
Claude Code through the `.claude/skills/<name>` bridge symlink and by Cursor
through the `.cursor/skills/<name>` bridge symlink). NORMATIVE for these tools.

**Cursor projection.** Project-scope Cursor installs use
`.cursor/skills/<name>/` as a symlink to `.agents/skills/<name>/`. Global-scope
Cursor installs use `~/.cursor/skills/<name>/` as a symlink to
`~/.agents/skills/<name>/`. Cursor rules generated from `always_apply` or
`globs` are written to `.cursor/rules/<name>.mdc` by the harness materializer.
Agent, MCP, and guardrail installs are not supported for Cursor by the library
installer; those primitive requests fail with a compatibility message instead
of writing `.cursor/agents/`, MCP config, or guardrail hooks.

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
- Do NOT teach CLI flag syntax in skill prose when a typed MCP tool is the
  canonical, independently justified boundary for the same intent. When a `library-tool-surface` MCP server
  ([mcp-server #species-2](mcp-server.md#species-2-library-tool-surface),
  established by [ADR-0007](../adr/library-tool-surface-mcp.md)) covers an
  intent (`git.merge_from_main`, ...), the skill MUST route
  to the typed tool by name. This rule does not justify creating that tool in
  the first place. For a stable public CLI such as `bd`, concise command
  examples plus deterministic helper scripts are preferred when an MCP wrapper
  would add no trust boundary beyond calling the same CLI.

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
