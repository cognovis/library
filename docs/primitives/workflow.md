# Workflow

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).
> Established by [ADR-0006](../adr/workflow-primitive.md).

**Definition.** A deterministic orchestration spec whose control flow runs as
code and whose leaves spawn fresh-context model subagents. The loops,
conditionals, fan-out, and gates are plain JavaScript that spend zero model
tokens; only the leaf `agent()` calls cost context, each in its own clean window.

**Key constitutive feature.** The **spine/leaf split**. The spine — control flow —
is deterministic code that holds no model and burns no tokens; the leaves are
`agent(prompt, opts)` calls, each a fresh-context subagent that returns text or a
JSON-Schema-validated object. Every leaf call is journaled by a hash of
`(prompt, opts)`, so a re-run with the same spec and args is a 100% cache hit and
a crashed run resumes from where it died.

**Why it is its own primitive.** It fits no existing type:

- not a **script** — a script is Python-only and runs no model ([script](script.md));
  a workflow's defining trait is that it spawns model leaves;
- not an **agent** — an agent is a single context window with one system prompt,
  not control flow over many ([agent](agent.md));
- not a **plugin** — a plugin is a container of other primitives, not a spec
  ([plugin](plugin.md)).

**Spec format.** A workflow is authored to the Claude Code Workflow tool's JS API
(established as canonical in ADR-0006 Decision 2): a first-statement
`export const meta = {…}` pure literal, then an async body using the injected
globals `agent`, `pipeline`, `parallel`, `phase`, `budget`, `args`, and
`workflow` (one level of nesting). Structured leaf output is requested with a
JSON-Schema `schema` option on `agent()`. The `workflow-creator` skill is the
authoring front-end; it is not itself the primitive.

```js
export const meta = {
  name: 'review-and-verify',
  description: 'Review each dimension, verify each finding as it lands',
  phases: [{ title: 'Review' }, { title: 'Verify' }],
}

const results = await pipeline(
  DIMENSIONS,
  d => agent(d.prompt, { phase: 'Review', schema: FINDINGS }),
  review => parallel((review?.findings ?? []).map(f => () =>
    agent(`Adversarially verify: ${f.title}`, { phase: 'Verify', schema: VERDICT }))),
)
return { confirmed: results.flat().filter(Boolean).filter(f => f.isReal) }
```

**Execution model.** One spec runs under three interchangeable backends; only the
implementation of `agent()` differs (ADR-0006 Decision 3). The spine is
harness-neutral JavaScript and never changes between them.

| Backend | `agent()` provided by | Availability |
|---------|------------------------|--------------|
| Native Workflow tool | the Claude Code binary, in-process (gated by `CLAUDE_CODE_WORKFLOWS`) | when Anthropic ships it |
| Library runtime | our runner, shelling each leaf to `claude -p --output-format json` | open implementation (ADR-0006 D5) |
| Codex | the same runner, shelling each leaf to `codex exec` | open implementation (ADR-0006 D5) |

This pluggable executor is what makes a workflow cross-harness. INFERRED for the
Library-runtime and Codex backends — pending the runtime spike.

**Security posture (NORMATIVE).** Two properties are requirements, not benefits
(ADR-0006 Decision 4):

- **The spine is inert** — no filesystem, no shell, no network. It is pure
  control flow over `agent()` calls. The native tool's determinism sandbox
  enforces this; the Library runtime MUST enforce the same.
- **Leaves are scoped** — each `agent()` declares the least privilege its job
  needs, per `agentType` (reviewer read-only; verifier read-only + tests;
  implementer write + shell inside its own worktree).

Together these let orchestration stop running with blanket
`--dangerously-skip-permissions`: the layer that decides cannot act, and the
layer that acts cannot decide. The native `workflow-subagent` ships with
`tools: ["*"]`, so least-privilege scoping is engineered by the Library via
per-`agentType` permission sets — the sandbox makes it possible, the Library
makes it real.

**Determinism rules.** Inside the spine, `Date.now()`, `Math.random()`, and
argless `new Date()` throw — they would break resume. Pass timestamps via `args`
and stamp results after the workflow returns; vary by loop index instead of
randomness.

**Catalog format (proposed — pending catalog support).** First-class workflows
live under `library.workflows` in `library.yaml`. The installer's awareness of
this shape, plus its tests, are deferred to the catalog/installer bead noted in
ADR-0006:

```yaml
- name: bead-context-pack
  description: Gather code/standards/architecture/prior-work for a bead, synthesize a pack.
  source: https://github.com/cognovis/cognovis-core/blob/main/.claude/workflows/bead-context-pack.js
  format: claude-workflow-js
  metadata:
    library:
      plane: dev
      executors: [native, library-runtime, codex]
```

**Where workflows live.**

| Context | Workflow location |
|---------|-------------------|
| Claude project-local | `.claude/workflows/<name>.js` |
| Claude global | `~/.claude/workflows/<name>.js` |
| Plugin-shipped | a plugin's `workflowsPath` (the binary's `loadPluginWorkflows`) |
| Codex install target | TBD — settled by the catalog/installer bead |

**When to choose it.** Create a workflow when **all** hold:

- the work is parallel or multi-stage with a **fixed shape** that is the same
  every run;
- you want the orchestration **deterministic and resumable**;
- isolating each step in its own fresh context window is an advantage.

This is the right home for multi-phase orchestration that previously stretched an
agent (the C6 case in the `agentic-primitives` standard): a fixed, deterministic,
resumable shape belongs in a workflow, not a prose agent.

**Counter-examples.**

- One subagent, one task -> use the plain `Agent` tool, not a workflow.
- A procedure where the **model** picks the steps each run -> a [skill](skill.md).
- Pure deterministic logic that runs **no model** -> a [script](script.md).
- Orchestration whose control flow itself needs model reasoning to decide what
  happens next -> an [agent](agent.md); a workflow's spine cannot reason.

**Anti-pattern.** A multi-hundred-line prose procedure that an agent must hold in
its window and interpret phase by phase — spending tokens on control flow,
drifting under context pressure, unable to resume, forced to run with broad
permissions. Lift the deterministic spine into a workflow and leave only the
reasoning in the leaves.

---
