---
name: agentic-primitives
description: Decision-tree standard for choosing the right agentic invocation primitive.
tags:
  - origin:original
  - tier:core
  - category:standard
---

# Agentic Primitives - Decision-Tree Standard

> Scope: All platform forge skills (`skill-forge`, `agent-forge`,
> `hook-forge`, `script-forge`, and `standard-forge`) load this standard via
> `requires_standards:` so primitive-type selection is consistent and
> self-correcting. This is the in-context briefing. For deeper detail, read
> `docs/PRIMITIVES.md` in the library-platform repository.

## The Four Invocation Primitives

| Primitive | One-line definition |
|-----------|---------------------|
| Skill | Context file (`SKILL.md`) the model auto-loads via description matching. No user trigger. |
| Command | Prompt template the user explicitly invokes with `/<name>`. Model does not auto-pick. |
| Agent | Autonomous worker with its own context window, **agent system prompt** (composed by the Library, distinct from the orchestrator's system prompt — subagents do not inherit it), tool grant, and optionally model. |
| Hook | Deterministic enforcement that runs outside the LLM loop at lifecycle events. Model cannot bypass. |

Library-managed dependencies (`Standard`, `MCP-Server`, `Model-Standard`,
`Plugin`, and `Marketplace`) are not invocation primitives. They configure or
distribute the four invocation primitives above.

## Quick Decision Tree

```text
Is the work more than 50 lines of deterministic logic?
  YES -> script (in scripts/), wrapped in a skill if the model must call it
  NO  -> continue

Should the model auto-pick it from context?
  YES -> SKILL
  NO  -> continue

Does the user invoke it explicitly with /name?
  YES -> COMMAND
  NO  -> continue

Does any of C1-C7 below hold?
  YES -> AGENT
  NO  -> continue

Must it fire regardless of model reasoning?
  YES -> HOOK (guardrail)
  NO  -> continue

Cross-cutting factual context that supplements other primitives?
  YES -> STANDARD
  NO  -> reconsider; most cases land in skill or script
```

Use this tree top-down. The first match wins. Walk past a node only if the
answer is no.

## C1-C7 - Agent Justification Criteria

An agent is the right primitive only when at least one of C1-C7 genuinely
holds. If none hold, the capability belongs in a skill, or in a script wrapped
by a skill.

| ID | Criterion | Trigger phrase |
|----|-----------|----------------|
| C1 | Needs a different tool permission set than the parent | "must not have write", "read-only verifier", "tool grant narrower than caller" |
| C2 | Needs its own context budget, roughly 2k+ tokens of work that would pollute the parent | "big report", "long transcript analysis", "would blow up the orchestrator window" |
| C3 | Runs in parallel with sibling agents | "fan out across inputs", "wave dispatch", "concurrent investigations" |
| C4 | Information barrier required | "implementer must not see review notes", "verification cannot share context with implementation" |
| C5 | Needs its own model | "cheap polling", "deep architectural reasoning", "model differs from parent" |
| C6 | Multi-phase stateful orchestration, more than three phases | "phase 1, then phase 2, then phase 3 with checkpoints", "session-close pipeline" |
| C7 | Pre-action gate that decides whether a proposed side effect may execute | "judge", "validator", "authorization check before action" |

Boundary call: a single tool call, grep, or lookup is never C2. Context budget
alone does not justify a fresh window for one read. Combine C2 with at least one
of C1, C3, C4, C5, C6, or C7 for a defensible agent.

## Judge Specialization

A judge is an agent specialization that evaluates a structured Action Proposal
before an actor executes a side effect. C7 holds when the artifact must return
an ALLOW, BLOCK, REVISE, or ESCALATE decision against evidence,
authorization, scope, and policy. The judge itself remains model-reasoned; a
hook or orchestrator may call the judge unconditionally before the
side-effecting action.

## Hook Justification

Hooks are the deterministic safety layer in the agentic stack. Choose a hook
when the constraint is non-negotiable and the model must not be able to opt out:

- Security gates, such as blocking destructive shell commands.
- Audit logging for every matching tool call.
- Session-init context injection that must happen before the model sees user
  input.
- Post-tool side effects that must always happen, such as formatting or cache
  invalidation.

If the model should reason about whether to apply something, that is a skill,
not a hook. If a user must consciously invoke it, that is a command, not a hook.

## Standard Justification

Standards are model context, not model-invoked workflows. Choose a standard
when:

- The content is factual guidance, conventions, lookup tables, or normative
  claims.
- It should be loaded into the model window when relevant triggers fire.
- Multiple skills or agents need the same facts without duplicating them.
- The author of a skill should be able to declare `requires_standards:
  [<name>]` to bind it.

Standards are not imperative workflows. If the draft starts with "Step 1, then
Step 2", it is a skill, not a standard.

## Counter-Examples

| Anti-pattern | Why wrong | Right primitive |
|--------------|-----------|-----------------|
| Spawn an agent to grep one symbol | Single tool call; no C-criterion holds | Direct shell/search call, or skill if recurring |
| Make a hook that asks the user before each commit | Hooks are non-interactive and run outside the LLM loop | Skill or command |
| Write a standard with a step-by-step install workflow | Standards are factual context, not imperative procedure | Skill or command |
| Convert a skill to an agent because it is long | Length alone is not C2; pollution risk is the issue | Keep as skill; extract deterministic logic to a script |
| Build a command for something the model should recognize automatically | User must remember to type it | Skill |
| Use a skill for security enforcement | Model can choose to ignore a skill | Hook |
| Use a hook for `/install-playwright` | Hooks are non-interactive; installs are explicit acts | Command |
| Spawn an agent just to use a stronger model for one prompt | C5 alone is rarely enough | Inline call, or a skill that documents when to switch |

## Forge Self-Correction Pattern

Each platform forge loads this standard and runs an inverse check on its own
primitive type before scaffolding anything:

```text
agent-forge:    Does any of C1-C7 hold? If no, dispatch to skill-forge.
skill-forge:    Is any of C1, C4, C5, C6, or C7 strongly present? If yes, dispatch to agent-forge.
hook-forge:     Must this fire unconditionally? If conditional, dispatch to skill-forge.
standard-forge: Is this imperative workflow? If yes, dispatch to skill-forge.
```

The dispatch is a soft handoff: the forge prints an explicit recommendation and
stops. It does not silently rewrite the user's request as a different primitive.

## Where Detail Lives

This standard is the briefing. Authoritative detail lives in
`docs/PRIMITIVES.md` in the library-platform repository.

Placement detail lives in
`standards/agentic-primitives/primitive-placement.md` and is cataloged as the
`primitive-placement` standard.
