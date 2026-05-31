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

**Execution model (canonical: native, clc-j7mn).** A workflow is authored once as
native Claude Workflow JS and the **native Workflow tool is the canonical executor**.
ADR-0006 Decision 3's "three interchangeable backends" framing is **superseded**:
the backends are not equivalent, and the canonical spec form is the native one
(`export const meta` + top-level async body — no `run()` wrapper). The spine is
still harness-neutral JavaScript.

| Backend | `agent()` provided by | Status |
|---------|------------------------|--------|
| Native Workflow tool | the Claude Code binary, in-process | **Canonical.** Ships in Opus 4.8 — not gated, no env var. The only supported native executor today. Deploys are gated by the workflow parse-check (`installers/simple_file.py`; `workflow-forge/scripts/check-workflow-parse.mjs`). |
| Library runtime (`scripts/lib/workflow_runtime.py`) | our runner, shelling each leaf to `claude -p --output-format json` | **Non-canonical spike/subset.** Textual extraction, no native `agent()`/`parallel()`/journal/resume semantics. For experiments/tests only; do not treat the form it accepts as the contract. |
| Codex / other harnesses | interpretive prompt projection or a dedicated runner | **Compatibility projection, not workflow execution.** Loses native `agent()`, `parallel()`, journal/resume, and structured leaf isolation. Must not weaken the canonical spec. |

Cross-harness reach is a **projection**, not interchangeable execution (clc-j7mn):
the canonical spec runs natively under Claude Code, and other harnesses get
interpretive projections that deliberately drop native semantics. The Library
runtime below is a non-canonical spike retained for experiments/tests; its
read-only path is implemented and tested, and mutating execution requires adapter
verification (see Adapter Support table below and ADR-0006 Consequences, now
superseded by clc-j7mn for the canonical-form question).

## Runtime: Library Workflow Runtime

The Library cross-harness runtime (`scripts/lib/workflow_runtime.py`) implements
the read-only execution path described in ADR-0006 Decision 5.

### CLI Usage

```bash
# Run a workflow spec in read-only mode
uv run python scripts/lib/workflow_runtime.py path/to/spec.js --read-only

# With route-profile slot dispatch
uv run python scripts/lib/workflow_runtime.py path/to/spec.js --read-only \
  --route-profile cld-default \
  --args '{"route_profiles": {...}}'

# With journal for resume support
uv run python scripts/lib/workflow_runtime.py path/to/spec.js --read-only \
  --journal /tmp/workflow-journal.json
```

### Supported Workflow Subset

The runtime supports:

- specs with an `export const meta = {...}` pure literal header (JSON-parseable);
- `await agent(prompt, opts)` leaves with JSON-literal string and object arguments;
- route-profile slot dispatch via `route_profiles`, `route_profile`, and
  `workflow` args;
- journal/resume: specs are journaled by `(spec_hash, route_profile, workflow)`
  identity;
- inert-spine constraint checks before execution (see `SpineConstraintChecker`);
- fail-closed mutating-execution guard (see `ADAPTER_PRESERVATION_STATUS`).

### Adapter Support

| Adapter | Status | Notes |
|---------|--------|-------|
| `claude-agent` | `blocked` | Leaf smoke returned unauthenticated; hook preservation unverified |
| `codex-impl` | `blocked` | Hook chain suppressed: `--ignore-user-config` skips config.toml trust hashes (CL-pabj) |
| `codex-exec` | `blocked` | Hook chain suppressed: `--ignore-user-config` skips config.toml trust hashes (CL-pabj) |
| `cursor-composer` | `not-applicable` | IDE composer; not a Library runtime leaf executor |

No adapter is currently `verified` for mutating execution. All workflow runs
must use `readOnly=True` until adapter hook-preservation smoke tests pass.
Codex hook-preservation smoke completed in CL-pabj (2026-05-25): adapters are `blocked`.

`ADAPTER_PRESERVATION_STATUS` update criteria and the fail-closed default are
anchored in [ADR-0006](../adr/workflow-primitive.md).

### Unsupported Cases

The following are not supported by the runtime:

- template literal argument expressions in `agent()` calls, such as
  `` `${variable}` ``; only JSON-literal string arguments are parseable;
- dynamic `opts` objects, such as `{...baseOpts, slot: s}`; only plain JSON
  object literals are parseable;
- `pipeline()`, `parallel()`, `phase()`, `budget`, and `workflow()` globals; the
  runtime executes `await agent()` leaves only;
- mutating execution for any adapter not listed as `verified` in
  `ADAPTER_PRESERVATION_STATUS`;
- nested workflow execution;
- the native Claude Code Workflow tool (`CLAUDE_CODE_WORKFLOWS`); this runtime
  is a cross-harness alternative, not a replacement for the native tool.

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

**Catalog format.** First-class workflows live under `library.workflows` in
`library.yaml`. `format: claude-workflow-js` is metadata; the installer treats
the workflow as a regular JavaScript file copy:

```yaml
- name: bead-context-pack
  description: Gather code/standards/architecture/prior-work for a bead, synthesize a pack.
  source: https://github.com/cognovis/cognovis-core/blob/main/workflows/bead-context-pack.js
  format: claude-workflow-js
  metadata:
    library:
      plane: dev
      executors: [native, library-runtime, codex]
```

**Where workflows live.**

| Context | Workflow location |
|---------|-------------------|
| Marketplace source-of-truth (cognovis-core) | `cognovis-core/workflows/<name>.js` |
| Project-local cross-harness | `<repo>/.agents/workflows/<name>.js` |
| Claude Code project-local install | `<repo>/.claude/workflows/<name>.js` |
| Claude Code global install | `~/.claude/workflows/<name>.js` |
| Package-shipped | a package's `workflowsPath` (the binary's `loadPluginWorkflows`) |
| Codex / Cursor install target | `.claude/workflows/<name>.js` storage only; Codex and Cursor have no native workflow executor, so this does not claim runtime support |

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
