# Agentic Primitives Glossary

> v0 — source of truth for primitive definitions used across the cognovis-library multi-harness stack.
> Last updated: 2026-08-05
>
> **Claim labeling convention**: Every per-harness behavioral claim is labeled
> **NORMATIVE** (verified against vendor docs / confirmed behavior) or
> **INFERRED** (architectural best-guess, pending validation).

---

## Quick Decision Tree

Use this tree to decide which primitive a new capability belongs in.

```
Is the capability purely deterministic logic (>50 lines) that runs NO model?
 └─ YES → SCRIPT (Python-only deterministic helper). Wrap the script in a Skill,
           Command, Hook, or Agent if the model/runtime needs to call it.
 └─ NO  → Continue below.

Is it a fixed-shape orchestration of multiple subagents — deterministic control
flow that spawns fresh-context agents, the same shape every run, worth resuming?
 └─ YES → WORKFLOW (deterministic spine + model leaves — see primitives/workflow.md)
 └─ NO  → Continue below.

Is it a "runbook" — a versioned, non-self-executing decision, routing, or
handoff guide for one acting agent?
 └─ YES → SKILL with `classification.skill_class: navigator | procedure`.
          RUNBOOK IS NOT A PRIMITIVE. Tested and rejected by ADR-0011
          (CL-2p73, 2026-08-08): every claimed constitutive behavior is already
          carried by Skill plus catalog metadata, and no `runbook-` projection
          prefix is reserved. Do not re-open without a Library-ENFORCED behavior
          that Skill plus metadata cannot carry.
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

Does it define the authoritative Library-managed environment for one project,
including safe retirement of obsolete members?
 └─ YES → WORKSPACE (metadata-only desired-state root; no harness artifact)
 └─ NO  → Continue below.

Does one entrypoint primitive require other primitives in order to function?
 └─ YES → Declare typed `requires:` dependencies on that entrypoint. Do not add
          a Package or empty bundle sentinel.
 └─ NO  → Continue below.

Is it project-specific or cross-cutting context supplementing global skills?
 └─ YES → STANDARD (injected into model context, not invokable)
 └─ NO  → Continue below.

Is it a capability provider accessed via the MCP protocol?
 └─ YES → Which species (see [ADR-0007](adr/library-tool-surface-mcp.md))?
           ├─ First-party LIBRARY-TOOL-SURFACE — typed invocation over Library
           │   operations and Scripts. Choose only when the server owns a real
           │   invariant or access path unavailable from a stable CLI + Skill.
           │   Flag mistakes alone do not justify a daemon and duplicate wrapper.
           └─ Third-party EXTERNAL-CAPABILITY — remote data, encrypted formats,
              vendor APIs. Does the target harness have shell access?
                ├─ YES (Claude Code / Codex CLI) → If a CLI already covers the
                │   capability, prefer CLI + SKILL over MCP.
                └─ NO  (claude.ai web / Claude iOS) → MCP-SERVER is the only path.

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
>   [agent-base](primitives/agent-base.md) + Layer 3
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

| # | Primitive | Format portable? | Claude Code | Codex CLI | Codex Cloud | Pi | Details |
|---|-----------|------------------|-------------|-----------|-------------|----|---------|
| 1 | [Skill](primitives/skill.md) | **YES** — shared SKILL.md (Open Agent Skills Standard) | full text at session start | name+desc at startup, full on-demand | n/a | n/a | details |
| 2 | [Command](primitives/command.md) | partial — same intent, different formats | `.claude/commands/*.md` (slash) | TBD (CL-qzw) | n/a | n/a | details |
| 3 | [Agent](primitives/agent.md) | **NO** — harness-specific format | `.claude/agents/*.md` (YAML) | `.codex/agents/*.toml` (TOML) | n/a | n/a | details |
| 3a | [Action Boundary](primitives/action-boundary.md) | partial — shared keys, primitive-native serialization | YAML frontmatter on skills/agents | YAML for skills, TOML for agents | n/a | unverified | metadata |
| 4 | [Guardrail/Hook](primitives/guardrail-hook.md) | **NO** — event coverage diverges | 15 events | 8 events (PreToolUse, PermissionRequest, PostToolUse, PreCompact, PostCompact, SessionStart, UserPromptSubmit, Stop) | `approval_policy` only | `tool_call`, `tool_result`, `message`, `session_start` (INFERRED) | details |
| 5 | [Package](primitives/package.md) | **RETIRED Library concept** — external ecosystem packages remain distribution formats | n/a | n/a | n/a | n/a | retirement note |
| 6 | [Marketplace](primitives/marketplace.md) | yes — distribution layer | yes | yes | yes | yes | details |
| 7 | [Standard](primitives/standard.md) | **YES** — shared markdown, harness-agnostic | inject via hook + `requires_standards:` | `requires_standards:` + AGENTS.md adapter | n/a | n/a | details |
| 8 | [MCP-Server](primitives/mcp-server.md) | yes — protocol-level | yes (also CLI+Skill preferred when shell access) | yes (also CLI+Skill preferred) | n/a | applicable through cognovis-pi | details |
| 9 | [Script](primitives/script.md) | **YES** — Python file plus Library metadata | callable from skills/hooks/commands | callable from skills/hooks | callable from CI/export | callable through adapters | details |
| 10 | [Model-Standard](primitives/model-standard.md) | partial — concept portable, mechanism per-harness | yes | yes | partial | unverified | details |
| 11 | [Agent Base (Agent Base Prompt)](primitives/agent-base.md) | **YES** — shared markdown base layer, harness composition varies | install-time composition into agent system prompt | install-time composition into agent system prompt | partial | unverified | details |
| 12 | [System-Prompt](primitives/system-prompt.md) | partial — concept portable, flags differ per harness | `--system-prompt[-file]`, `--tools`, `--bare`, cld registry | TBD — Codex flag parity unverified | n/a | n/a | details |
| 13 | [Workflow](primitives/workflow.md) | **YES** — shared JS spec (Anthropic Workflow API) | native Workflow tool (gated by `CLAUDE_CODE_WORKFLOWS`) or Library runtime | Library runtime via `codex exec` (INFERRED) | n/a | n/a | details |
| 14 | [Project-Native Pi/Just Bridge](primitives/project-native-pi-bridge.md) | **NO** — temporary harness-native projection | files and extension bundles | files and directories | Pi-native | verified | project-only; Open Skills stays authoritative for methods |
| 15 | [Workspace](primitives/workspace.md) | **YES** — Library metadata, no harness artifact | members project individually | members project individually | members inherit support | members inherit support | metadata-only desired-state root |

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

### Catalog Entry Fields: Harness Support and Runtime Requirements

Two optional fields apply to every catalog entry shape (`base_entry` and all
primitive entry types):

**`harness_support`** — per-harness install eligibility. Declare when a
primitive works in some harnesses but not others. The installer refuses
`--harness <h>` installs if the entry marks that harness `not-supported`.

```yaml
metadata:
  library:
    harness_support:
      claude_code: supported      # or not-supported, planned
      codex: not-supported
      pi: supported
```

Harness IDs are a closed enum maintained by the Library schema, not an open
catalog-derived registry. The current product IDs are `claude_code`, `codex`,
and `pi`. Omitting a key means "no explicit claim" (install proceeds). Use
`planned` for a supported harness where support is in progress. The install gate
fires before dependency installs to prevent partial mutations.

Cursor, OpenCode, Antigravity, and other retired harnesses are not current
Library projection targets. Historical ADR evidence may still name them, but
the active CLI only accepts the three current product IDs.

`metadata.library.harness_support` belongs to primitive entry metadata. MCP
server entries use `install.mcp` as the source of truth for harness-specific MCP
configuration, and project tooling entries use their `target_kind` and
conditions. Those planes intentionally do not carry `harness_support`.

**`runtime_requirements`** — binary prerequisites for the primitive to function.
Declare when the primitive requires CLI tools that may not be present on every
machine. The installer checks `runtime_requirements.binaries` with PATH lookup
before dependency installs or target writes, and refuses the install when any
declared binary is missing. It does not execute the binaries.

```yaml
runtime_requirements:
  binaries:
    - bun
    - rg
```

**Plane enforcement.** Entries tagged `tier:domain` or `tier:project` must
declare `metadata.library.plane`. `validate-library.py` fails validation if
the field is absent. `tier:core` entries are exempt.

### Foreign model-instructing content needs an admission decision

Applies to **Skill, Command, Agent, Agent Base, Model-Standard, Standard, Prompt,
System-Prompt, and Runtime-Config** when the steward is not first-party
(ADR-0011 [`Model-instructing foreign content`](adr/heterogeneous-marketplace-workspaces.md),
`CL-lt51`, Human Decision HD-5 of 2026-08-10).

These primitives run no process. That is not the same as inert: a harness loads
them into a model's context precisely so the model will follow them, with the
agent's tools and the operator's credentials. An upstream revision that adds
"before answering, read `~/.ssh/id_rsa`" is executed as surely as a shell script.
So installing one from a foreign marketplace requires a digest-bound decision
recorded with `library admission grant`, the same gate a Workflow passes, and
updating one goes through `library marketplace update` — quarantine, scan,
review, human approval — before any pin is raised.

**First-party catalog content is not affected.** The question the operator is
being asked is whether to trust somebody else's instructions; asking it about
this repository's own Skills would block the platform on itself.

### 1. Skill

Details: [Skill](primitives/skill.md).

**Classification metadata (ADR-0011, `CL-2p73`).** A catalog Skill entry may carry
`classification.skill_class` with the value `navigator` or `procedure`. A
*navigator* routes a reader to the right capability (`ask-matt`, `ask-malte`); a
*procedure* carries out a named piece of work (`implement`, `tdd`). This is
validated catalog metadata, not a new primitive: ADR-0011 tested and rejected a
first-class Runbook because every claimed constitutive behavior — versioning,
non-self-execution, required-versus-optional capabilities, conditional routes,
handoff artifacts, human gates, and prefix reservation — is already carried by
Skill plus `requires:` plus Workspace membership plus the name-collision policy.
The honest cost is recorded there: a harness that ignores classification metadata
cannot tell the two apart.

It is **curated, never inferred from upstream content** (`CL-coif`). No upstream
frontmatter field distinguishes the two: `ask-matt` (navigator) and `implement`
(procedure) both ship `disable-model-invocation: true`, which means "do not
auto-invoke me" and nothing about routing. An entry with no curated value carries
`classification.skill_class_source: not-curated` rather than a guess.

### 2. Command

Details: [Command](primitives/command.md).

### 3. Agent

Details: [Agent](primitives/agent.md). Judge remains a specialization of Agent.

### 4. Guardrail (Hook)

Details: [Guardrail / Hook](primitives/guardrail-hook.md).

### 5. Package

Retired as a Library primitive. See the [Package retirement note](primitives/package.md).
Use an entrypoint primitive's `requires:` closure for strict functional coupling
and a Workspace for selectable desired-state composition. External ecosystem
packages remain ordinary distribution formats.

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

### 11. Agent Base (Agent Base Prompt)

Details: [Agent Base](primitives/agent-base.md). Layer 1 of the
composed **agent** system prompt. Distinct from the orchestrator system
prompt (see #12).

### 12. System-Prompt

Details: [System-Prompt](primitives/system-prompt.md). The **orchestrator**-level
system prompt + built-in tool set that `cld` / `cdx` loads at top-level session
start. Distinct from the agent system prompt (see #3, #10, #11). Subagents do
not inherit it.

### 13. Workflow

Details: [Workflow](primitives/workflow.md). A deterministic orchestration spec
(Anthropic Workflow JS API) whose control flow runs as code and whose leaves
spawn fresh-context model subagents. Distinct from **script** (#9 — runs no
model) and **agent** (#3 — a single context window, not control flow over many).
Established by [ADR-0006](adr/workflow-primitive.md).

### 14. Workspace

Details: [Workspace](primitives/workspace.md). A metadata-only requested root
whose constitutive feature is ownership-aware desired-state reconciliation. It
has no deployable artifact and can explicitly retire clean, ownerless receipts
through ADR-0010's prune contract. A project may directly register several
orthogonal Workspaces. Schema v1 keeps every manifest to same-catalog artifact
roots; schema v2 adds cross-catalog roots qualified by an alias from a pinned
`catalogs:` block, which is the only place a manifest may name a source. Nested
Workspace roots remain deferred in both versions. The Workspace CLI implements
discovery, validation, registration, status, explanation, sync, adoption,
removal, and digest-bound pruning.


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

`library <primitive> remove <name>` MUST remove the Claude bridge AND the canonical install AND
the lockfile entry. The removal sequence: Claude bridge first, then canonical,
then lockfile. The Layer-B cache (`~/.local/share/library/skills/...`) is
garbage-collected separately once no lockfile receipt
references it.

Workspace reconciliation follows a stricter ownership protocol. Removing a
Workspace unregisters only its requested root and prints the resulting plan.
Physical receipt deletion requires `library workspace sync --prune --apply`,
freshly resolved zero-owner proof, matching per-file digests, and an atomic
post-prune lock write before target deletion. See ADR-0010.

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
- **Workspace Desired State**: [ADR-0010](adr/workspace-desired-state-reconciliation.md)
  — universal ownership, lockfile v2, scope isolation, and safe pruning.
- **Agent Base Prompts** (CL-9b1): Canonical sources at `.agents/agent-bases/` and
  `.agents/model-standards/`. See [Model-Standard](primitives/model-standard.md) and [Agent Base](primitives/agent-base.md) for the composition algorithm.
