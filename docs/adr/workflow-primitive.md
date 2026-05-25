---
adr: "0006"
title: "Workflow as a first-class Library primitive"
status: accepted
date: 2026-05-24
bead: "CL-rk2"
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
related_adrs: ["0005"]
---

# ADR-0006: Workflow as a first-class Library primitive

## Status

Accepted — for the classification, spec format, execution model, and security
posture (Decisions 1–4). The cross-harness runtime that executes the spec
outside the native tool is the open implementation question; it is recorded in
Consequences and deferred to a follow-up spike, not built as part of this ADR.

## Context

Claude Code ships an unreleased, unannounced **Workflow tool**, gated behind the
`CLAUDE_CODE_WORKFLOWS` environment variable. It was confirmed present in the
2.1.150 binary (the `CLAUDE_CODE_WORKFLOWS` gate, a built-in `workflow-subagent`
agent type, strict `meta` parsing, a 512 KB script cap, and a
`loadPluginWorkflows` path that reads workflow `.js` files from a plugin's
`workflowsPath`). It does not appear in any release notes; 2.1.150's notes read
"internal infrastructure improvements (no user-facing changes)."

A workflow is a JavaScript orchestration file: an `export const meta = {…}`
literal followed by an async body. The body uses injected globals —
`agent(prompt, opts)`, `pipeline()`, `parallel()`, `phase()`, `budget`, `args`,
`workflow()` — to fan work out to fresh-context subagents under **deterministic
JavaScript control flow**. The loops, conditionals, and fan-out are plain code
that spend zero model tokens; only the leaf `agent()` calls cost context, each
in its own clean window. The orchestrator records every `agent()` call in a
journal keyed by a hash of `(prompt, opts)`, so a re-run with the same script and
args is a 100% cache hit and a crashed run resumes from where it died.

This matters to the Library because our orchestration today is **prose**. The
`bead-orchestrator` agent is a ~3800-line markdown procedure that a Claude (or
Codex) session must hold in its window *and* interpret phase by phase, while
accumulating every subagent result into that same window. The file already
carries a hand-built "Phase Summaries (Context Thread)" compaction workaround —
direct evidence that the orchestrator's context blows out on larger work. Because
the decision layer is a model running prose, it can drift or skip a gate, it
spends tokens on control flow, and it must run with broad permissions
(`--dangerously-skip-permissions`) to do its shell work.

The key observation is that a workflow file separates two things our prose
conflates:

- the **spine** — control flow, gates, loops, fan-out. Pure JavaScript, with
  nothing harness-specific in it; a `for` loop is a `for` loop in any harness.
- the **leaves** — `agent(prompt, opts)`. The only harness-specific concept:
  "spawn a fresh-context subagent and return its result."

Our leaves are already extracted as separate agents (`review-agent`,
`verification-agent`, `fix-agent`, `bead-context`). Only the spine is still
prose. The portability question therefore reduces to a single point: **who
provides `agent()`?**

The Library's primitive taxonomy (`docs/PRIMITIVES.md`) has no slot for this.
Running a workflow through the decision tree: it is deterministic logic (which
points at SCRIPT), but SCRIPT is defined as Python-only and runs no model; a
workflow is deterministic control flow that *spawns model leaves*. It is neither
SCRIPT (no model) nor AGENT (a single context window with one system prompt).
That gap is what this ADR closes, following the precedent of ADR-0005 Decision 7,
which made `script` a first-class primitive.

## Decision

### Decision 1: Workflow is a first-class Library primitive

`workflow` becomes primitive #13, alongside skill, command, agent, hook, plugin,
marketplace, standard, mcp-server, script, model-standard, agent-base, and
system-prompt. It is defined as: **a deterministic orchestration spec whose
control flow runs as code and whose leaves spawn fresh-context model subagents.**

It earns a distinct type because it fits no existing one:

- not a **script** — a script is Python-only and runs no model (ADR-0005 D7);
- not an **agent** — an agent is a single context window with one system prompt,
  not control flow over many;
- not a **plugin** — a plugin is a container of other primitives, not a spec.

`docs/PRIMITIVES.md` gains a workflow entry, a new branch in the Quick Decision
Tree ("Is it a fixed-shape orchestration of multiple subagents, deterministic and
resumable? → WORKFLOW"), and a Portability Matrix row. `library.yaml` gains a
catalog shape for workflow entries (`library.workflows`).

### Decision 2: The canonical spec format is Anthropic's Workflow JS API

A workflow primitive is authored to the exact surface the native Workflow tool
expects: a first-statement `export const meta = {…}` pure literal, then an async
body using `agent`/`pipeline`/`parallel`/`phase`/`budget`/`args`/`workflow` and
JSON-Schema `schema` for structured leaf output.

We write to Anthropic's surface rather than inventing our own format so that the
day the tool is released, our files run natively with zero rewrite. The risk that
the pre-release API changes is real and is accepted; it is mitigated by Decision 3
(we own a runtime that executes the same files, so we are never blocked on
Anthropic shipping).

### Decision 3: Execution is one spec with a pluggable `agent()` executor

A single spec file runs under any of three interchangeable backends; only the
leaf executor — the implementation of `agent()` — differs:

| Backend | `agent()` is provided by | Availability |
|---------|--------------------------|--------------|
| Native Workflow tool | the Claude Code binary, in-process | when Anthropic ships it |
| Library runtime | our runner, shelling each leaf to `claude -p --output-format json` | today |
| Codex | the same runner, shelling each leaf to `codex exec` | today |

The spine never changes across backends; it is harness-neutral JavaScript. This
is the mechanism that makes a Library workflow cross-harness and is the concrete
answer to "would this work in Codex?" — yes, by swapping the executor, not the
spec.

### Decision 4: Inert spine and scoped leaves are normative

Two properties are requirements of the primitive, not optional benefits:

- **The spine is inert.** The orchestration layer has no filesystem, no shell, no
  network. It is pure control flow over `agent()` calls. (The native tool's
  determinism sandbox already enforces this; the Library runtime MUST enforce the
  same.)
- **Leaves are scoped.** Each `agent()` call declares the least privilege its job
  needs, per `agentType`: a reviewer is read-only, a verifier is read-only plus
  test execution, an implementer gets write plus shell inside its own worktree.

Together these let orchestration stop running with blanket
`--dangerously-skip-permissions`: the layer that *decides* what happens cannot
*act*, and the layer that acts cannot decide. It also shrinks prompt-injection
blast radius, since the layer that reads untrusted input (bead bodies, web
content) has no capability to act on it directly.

The native `workflow-subagent` ships with `tools: ["*"]`, so this scoping is
something the Library engineers via per-`agentType` permission sets — the bans
make least privilege *possible*; the Library makes it *real*.

## Rationale

The Library already commits to a dev-plane / cross-harness primitive model
(ADR-0005). Workflow fits that model exactly: a portable source artifact (the
spec) plus a harness-specific projection (the executor backend). Adopting
Anthropic's format keeps the artifact forward-compatible; owning the runtime
keeps us un-blocked and gives Codex parity now.

Making the security posture normative rather than incidental is what converts the
determinism sandbox from a perceived tax ("you cannot run bash in the
orchestrator") into the architecture's main safety win. The same inversion that
makes the spine deterministic — removing the model and its tools from the control
layer — is what makes least privilege achievable.

## Alternatives Considered

### Alternative A: Keep orchestration as prose

Rejected as the long-term direction. Prose orchestration spends tokens on control
flow, drifts under context pressure, cannot resume, and forces broad permissions.
The prose agents remain valid today and are not removed by this ADR; the ADR sets
the target, not a forced cutover.

### Alternative B: Workflow as a specialization of `script`

Rejected. It breaks the ADR-0005 Decision 7 invariant that a script is
Python-only and runs no model. A workflow's defining trait is that it spawns
model leaves, which a script by definition does not.

### Alternative C: A Library-native, harness-neutral spec format

Rejected. Defining our own YAML or JS format would insulate us from Anthropic's
pre-release churn, but it forfeits native execution when the tool ships and
commits us to maintaining a translation layer permanently. Decision 3 already
gives us harness neutrality without a second format.

### Alternative D: Wait for Anthropic to release before acting

Rejected. The spine/leaves separation, the spec files, and the runtime are all
valuable independent of the native tool's release, and writing to the native
format now is what makes the eventual release a no-op. Waiting forfeits the Codex
and resume wins available today.

## Consequences

- **Done with this ADR:** `docs/PRIMITIVES.md` carries primitive #13 (definition,
  Quick Decision Tree branch, Portability Matrix row); `docs/primitives/workflow.md`
  is the focused page; the `agentic-primitives` standard and `docs/ARCHITECTURE.md`
  enumerate it.
- **Tracked by bead CL-rk2:** `library.yaml` gains a `library.workflows` catalog
  shape and the installer (`scripts/lib/primitives.py`, `catalog_inventory.py`,
  `library.py`) plus the `/library` SKILL.md and `tests/test_library_py_*` learn
  the type. Install target `.claude/workflows/` for Claude; Codex target settled
  there. Sequenced with `CL-0fj` and `CL-w5d`.
- **Still to file (ADR-0006 D5):** the cross-harness runtime and its executor
  adapters — a separate spike that builds the Library runtime and validates it
  against the read-only `bead-context-pack.js` workflow, proving determinism,
  journal/resume, and the Claude/Codex executor swap without touching anything
  that mutates state. This is distinct from CL-rk2 (catalog/installer).
- **CL-uqug (2026-05-25):** Hook and permission preservation audit completed.
  `WorkflowRuntime` now enforces a fail-closed guardrail: `MutatingExecutionBlockedError`
  is raised for any adapter whose preservation status is not `verified`. Currently no
  listed adapter is approved for mutating execution. Capability matrix and Claude leaf
  smoke evidence are in `docs/audit/hook-permission-preservation.md`. Codex-specific
  hook preservation smoke is tracked in follow-up bead CL-pabj.
- **ADAPTER_PRESERVATION_STATUS update criteria (CL-182u, 2026-05-25):** The
  `ADAPTER_PRESERVATION_STATUS` dict in `scripts/lib/workflow_runtime.py` is the
  machine-checked registry that controls whether mutating workflow execution is
  permitted for an adapter. Update criteria:
  1. **Status -> `verified`:** The adapter's PreToolUse hooks (destructive-command
     guard, `bead-author-check`, `permissions.yml`) are confirmed to fire inside
     workflow leaves. Evidence: a positive smoke test in `docs/audit/` plus a
     passing test in `tests/test_workflow_runtime_spike.py` or a successor file.
  2. **Status -> `blocked`:** The adapter's leaf smoke returned an unauthenticated
     or permission-bypassed result, or the hook fire could not be confirmed.
  3. **Status -> `separate-harness`:** The adapter runs in a separate harness
     process where the Claude Code hook layer does not apply. Hook preservation
     must be verified at the harness boundary separately.
  4. **Status -> `not-applicable`:** The adapter is not a leaf executor, such as
     an IDE composer that does not route through the Library runtime hooks.
  5. **Fail-closed default:** Any adapter whose name is absent from the dict, or
     whose status is not in `_MUTATING_ALLOWED_STATUSES` (currently `{"verified"}`),
     is treated as blocked. `MutatingExecutionBlockedError` is raised. `readOnly=True`
     bypasses this check and is required for safe read-only execution.
  6. **To add a new verified adapter:** open a bead, run the hook-preservation
     smoke for that adapter (see `docs/audit/hook-permission-preservation.md`),
     update the dict in `workflow_runtime.py`, and add or update test coverage.
- Before the runtime is trusted on any mutating workflow, it MUST be verified that
  PreToolUse hooks (the destructive-command guard, `bead-author-check`,
  `permissions.yml`) still fire inside spawned leaves. Losing those rails is a
  blocker, not a nuance. The `WorkflowRuntime.check_mutating_allowed` guardrail
  (see `scripts/lib/workflow_runtime.py`) enforces this at runtime until verification
  is complete.
- The determinism sandbox bans shell in the spine, so existing shell-heavy phases
  (bead claim, git, session-close) become leaves or pre/post steps. This informs,
  but is out of scope for, a future bead-orchestrator rearchitecture, which is
  epic-scale work and gets its own planning — not a paired ADR.
- The `workflow-creator` skill is the authoring front-end onto this primitive; it
  is not itself the primitive.
- Risk accepted: the pre-release Workflow API may change before launch. Mitigated
  by owning the runtime (Decision 3) and by the native format being the only
  external dependency.
