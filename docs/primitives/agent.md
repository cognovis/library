# Agent

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** An autonomous AI worker with its own context window, **agent
system prompt**, tool permissions, and (optionally) model selection. Agents
can be spawned by the orchestrating model to run a subtask in isolation.

> **Two prompts, not one.** "System prompt" is ambiguous in this stack. The
> agent's system prompt (this primitive) is the composed body of the agent's
> definition file — see [Golden-Prompt](golden-prompt.md) + [Model-Standard](model-standard.md)
> for how Layer 1/2/3 are stitched together. It is distinct from the
> [orchestrator system prompt](system-prompt.md) of the top-level `cld` / `cdx`
> session. Subagents do **not** inherit the orchestrator's system prompt
> (`code.claude.com/docs/en/sub-agents`: *"Subagents receive only this system
> prompt … not the full Claude Code system prompt."*).

**Key constitutive feature.** Isolated context budget: each agent invocation
gets a fresh context window and its own tool grant. The parent model does not
share its context with the subagent, and the subagent does not see the
orchestrator's system prompt.

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
| `beads-workflow:bead-orchestrator` | Orchestrates a multi-step bead workflow with its own agent system prompt, model, and tool set. Parent model delegates the entire workflow. |
| `beads-workflow:verification-agent` | Isolated, read-only verification context. Tool grant is explicitly limited to Read, Bash, Grep, Glob — isolation prevents accidental writes during verification. |
| `core:session-close` | Orchestrates a multi-phase close pipeline (merge, commit, changelog, push, close bead). Too complex and stateful for inline execution; needs its own context. |

---
