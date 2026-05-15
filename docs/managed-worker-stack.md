# Managed Worker Stack — slot model and library mapping

> Cross-cutting reference for how the cognovis library implements Nate Jones's
> "managed worker" model. Reading order: this file → ADR-0003 in cognovis-core
> → the five judge-layer standards. Last updated 2026-05-14.

## The Five-Slot Model

A production agent is not a chatbot. It is a managed worker, and like any worker
it needs five distinct supporting systems. Each slot has its own failure modes
and its own primitives. Conflating them produces brittle agents that work in
demos and fail in production.

| Slot | What it does | Failure mode if missing |
|------|--------------|-------------------------|
| **Orchestration** | Who does the work; how phases of a task are sequenced and assigned | Tasks stall mid-flight; no recovery; no parallelism |
| **Coordination** | How work moves between actors; durable handoffs across sessions and machines | Lost context; ambiguous ownership; nothing survives the session |
| **Judgment** | Whether work is allowed; pre-action authorization decisions | Confident wrong actions in production; the agent "doing the thing you trained it to do, but past where it had permission" |
| **Continuity** | What is remembered; durable, provenance-labeled context across runs | Every run rediscovers the same context; agent-generated guesses silently become future instruction |
| **Human review** | Escalation, correction, accountability for cases the system cannot resolve | Either every action requires human approval (workflow dies) or no action does (incidents happen) |

This vocabulary comes from Nate Jones's newsletter series in April-May 2026 (see
"Source Material" in `cognovis-core/docs/adr/ADR-0003-judge-layer-architecture.md`).
He names the orchestration layer as the one nobody owns yet — the Kubernetes
moment for agents hasn't happened — and names judgment as the discipline most
agent products are missing.

## Library Mapping

| Slot | Target shape | Current library state | Direction |
|------|--------------|------------------------|-----------|
| **Orchestration** | Archon, GasCity, or Pi (runtime-agnostic adapter) | `bead-orchestrator` + cmux panes (throwaway, working) | Migrate, don't extend. The catalog is the durable asset; the runtime is rented. |
| **Coordination** | beads / bd | `bd` — already correct | Keep. Validates against Nate's five structural tests (persistent state, defined verbs, ownership, permissions, history). |
| **Judgment** | Generic judge + specialist judges, structured proposals, mandate-shaped authorization, paired evals | **Fully built** in cognovis-core/clc-oxg (2026-05-14): five judge-layer standards, `judge-default` agent, 24-case eval suite, Phase 4.5 orchestrator gate, deterministic+reasoned hybrid architecture. First consumer in `open-brain` (Memory-Write Judge). | Extend with specialist judges when prompt complexity justifies splitting (authorization, privacy, reversibility, quality, security). |
| **Continuity** | OpenBrain with structured judgment on writes and retrieval contract on reads | OpenBrain at `~/code/open-brain`; Memory-Write Judge live; provenance-labeled metadata on every save. Read-time retrieval contract pending (`open-brain-ekn.4`). | Extend. The seven-question Retrieval Contract is the next durable shape. |
| **Human review** | Confirmation Gates + ESCALATE outcomes routed to human queues | Confirmation Gates table in `~/.claude/CLAUDE.md`; ESCALATE outcomes append to bead notes | Keep. Nate doesn't name a winner for this slot; current shape is adequate. |

## Primitive Mapping (Library Taxonomy)

Each slot maps to specific primitive types in
`meta/docs/PRIMITIVES.md`. No new top-level primitives were created for the
judgment slot — judges are Agent specializations, Action Proposals and Mandates
are Standard sub-types, and `action_boundary` is frontmatter metadata.

| Slot | Primary primitives |
|------|--------------------|
| Orchestration | Agent (bead-orchestrator), Skill (wave-orchestrator), Plugin |
| Coordination | External system (beads/bd) — outside Library primitive taxonomy |
| Judgment | Agent → **Judge specialization** (C7 + C1 + C4); Standard → **Action Proposal Schema** sub-type; Standard → **Mandate** sub-type; Skill (judge-eval); Hook/Guardrail (deterministic gates) |
| Continuity | External system (OpenBrain) + Skill (open-brain integrations) + typed runtime contracts in `python/src/open_brain/` |
| Human review | Hook/Guardrail (Confirmation Gates) + Agent (review-agent, verification-agent for post-action) |

The action_boundary frontmatter block — declared on any side-effecting Skill or
Agent — is what wires a primitive into the Judgment slot. See PRIMITIVES.md §1
(Skill) and §3 (Agent) for the shape and `meta/skills/skill-forge/
references/action-boundary.md` for the gate-question reference.

## Runtime-Portability Thesis

The slot model lives above any specific runtime. The typed-primitive catalog
(skills, agents, standards, judges, proposals, mandates) is expressed as plain
markdown plus Python types. None of it is coupled to bead-orchestrator's phase
numbering or cmux's pane model.

This is deliberate. The orchestration slot is the one Nate names as unowned,
which means it will churn: Archon, GasCity, OpenClaw, Hermes, Pi, and whichever
runtime emerges as the Kubernetes-equivalent will compete on shape. Our bet is
that the catalog survives whichever runtime wins. The bead-orchestrator is the
current implementation, not the destination.

**Migration discipline:** when an orchestrator candidate stabilizes (currently
Archon as the open-source frontrunner, GasCity as Nate's named candidate, Pi as
the lightweight fallback), the adapter pattern is:

```
library/runtimes/<adapter-name>/
  primitives/    # translate Skill/Agent/Judge/Proposal/Mandate to adapter primitives
  phases/        # map orchestrator phases (esp. Phase 4.5 pre-action gate)
  tests/         # one pilot bead (open-brain memory-write judge) running on the adapter
```

Build one adapter at a time, throwaway quality, with the same pilot. Pick the
adapter that fights you least. Sunset bead-orchestrator only after the winning
adapter is production-proven for 30+ days.

See `cognovis-core/docs/research/gascity-migration-plan.md` and
`cognovis-core/docs/research/gascity-vs-archon-orchestration-comparison.md` for
the current adapter-evaluation work.

## Reading Order for Newcomers

1. **This file** — the slot model and what each slot does
2. **`cognovis-core/docs/adr/ADR-0003-judge-layer-architecture.md`** — the
   decisions that closed the Judgment slot (12 architectural choices with
   rationale, alternatives, consequences)
3. **`cognovis-core/standards/judge-layer/README.md`** — the contracts the
   judgment slot ships and how they relate to each other
4. **`cognovis-core/standards/judge-layer/{action-proposal,judge-outcomes,
   provenance-labels,mandate-schema,judge-eval-suite}.md`** — the five canonical
   contracts
5. **`open-brain/docs/features/memory-write-judge.md`** — how a real consumer
   implements the contracts (typed dataclasses, deterministic-first gate,
   integration with save_memory)
6. **`cognovis-core/docs/research/judge-layer-thread-2026-05-14.md`** — the
   research note: which Nate articles fed which decisions, the implementation
   thread, quality trajectory across the review cycles

## Open Questions

- **Which orchestrator wins?** Archon, GasCity, Pi, or something later. Adapter
  pattern is the hedge. Decision deferred.
- **Reasoned-gate hooks in OpenBrain.** The hybrid architecture supports a
  `reasoned_gate` callback that runs after deterministic ALLOW. No reasoned gate
  ships today; v1 is purely deterministic. The hook is documented but unwired.
- **Cross-slot proposal correlation.** A skill that both sends an email and
  writes a memory needs two proposals (Action Proposal for the send, Memory
  Write Proposal for the write). The relationship between the two proposal
  shapes is documented in `open-brain/docs/features/memory-write-judge.md` but
  the orchestrator doesn't yet correlate them.
- **policy_version back-port.** OpenBrain's Memory-Write Judge adds
  `policy_version` as a required outcome field. The generic
  `judge-outcomes.md` standard should support it as an optional field for any
  judge that wants to version its rules. Pending.
- **Specialist judges.** Generic `judge-default` is the v1 implementation.
  Split into specialists (authorization, privacy, reversibility, quality,
  security) when prompt complexity justifies it. Trigger condition not yet met.
