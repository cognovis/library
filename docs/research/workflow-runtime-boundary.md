# ADR-0006 D5 Workflow Runtime Boundary

## Decision

Library should own a minimal runtime boundary for Anthropic Workflow JS specs
that does four things only:

1. Parse the spec file and extract `meta` plus the workflow body surface.
2. Enforce inert-spine constraints before any leaf dispatch happens.
3. Provide a hash-keyed journal/resume store for leaf results.
4. Dispatch each `agent()` leaf through a pluggable executor adapter.

Library should not try to become a general JavaScript interpreter. The native
Anthropic Workflow tool remains the target execution surface; this spike is the
Library-owned compatibility layer that can run read-only specs today and keep
the spec format forward-compatible.

## Minimal Runtime Boundary

The smallest useful boundary is a source-level runtime, not a JS VM.

- Owned by Library:
  - file loading
  - `meta` extraction
  - spine constraint checks
  - leaf journaling and replay
  - adapter resolution for `agent()`
- Not owned by Library:
  - arbitrary JS execution
  - mutation inside the spine
  - shell or filesystem access from the control layer
  - replacement of Anthropic's native Workflow tool

That boundary is enough to prove the architecture on a read-only workflow while
avoiding a false promise of full JS compatibility.

## Inert Spine Constraints

The spine must stay deterministic so a replay hashes to the same leaf plan.
The spike bans the operations that break determinism or capability isolation:

- `require(...)`
- imports from `fs`, `child_process`, or `net`
- `Date.now()`
- `Math.random()`
- `new Date()` with no arguments
- obvious shell or network entry points in the spine

The reason is simple:

- filesystem, shell, and network calls make the control layer capable of
  mutation or exfiltration
- wall-clock time and randomness break journal replay because the same input no
  longer yields the same leaf plan

This spike uses regex and lightweight source scanning. That is sufficient for a
boundary proof and intentionally not a full JS parser.

## Journal / Resume Model

The journal key is the hash of the leaf request payload:

`sha256(json.dumps({"prompt": prompt, "opts": opts}, sort_keys=True))`

The journal stores the leaf result under that hash. On rerun:

- if the hash already exists, the executor is skipped
- if the hash is new, the leaf is executed and the result is recorded

That gives the workflow a replayable leaf cache and a resumable spine without
needing a process checkpoint format.

The prototype keeps the journal in memory and can persist to JSON for resume
across instantiations. That is the right scale for the spike. A production
implementation can later decide whether to keep the same JSON shape or move the
storage behind a project service.

## Executor Interface

`agent()` should resolve to an executor adapter, not to a model name prefix.
The runtime should map a leaf request to the active route-profile slot target
when that metadata is available.

The route-profile contract is:

- `route_profile` selects the profile
- `workflow` selects `full` or `quick`
- `slot` selects the leaf slot inside the workflow
- the slot provides the adapter contract

For this spike the important mapping is:

- `claude-agent` -> `ClaudeAgentExecutor`
- `codex-impl`, `codex-exec`, `cursor-composer`, `opencode-agent` are
  adapter contracts that the runtime can route later, but they are not fully
  implemented in this spike

This keeps the runtime boundary aligned with the existing route-profile model
from CL-iye.1 instead of inventing a second dispatch table.

## Hook / Permission Preservation

The user-level Claude configuration on this machine includes a `PreToolUse`
Bash hook in `~/.claude/settings.json`, so the spawned `claude -p` path has a
real hook chain available.

What is verified here:

- the `claude-agent` adapter path exists locally
- the user-level Claude config does define `PreToolUse` enforcement

What is not yet verified in this spike:

- a live `claude -p` leaf invocation proving that the hook chain fires inside
  the spawned subagent process
- codex-side hook preservation for the non-Claude adapters

That means hook preservation is a blocker for mutating workflow runtime work,
not for the read-only spike itself.

## Decision Outcome

Accepted runtime path for the spike:

- Library-owned source reader
- inert spine checker
- hash-keyed journal/resume
- pluggable leaf adapter dispatch

No-go for production mutating execution until live hook preservation is proven
for the spawned leaves and the non-Claude adapters have matching verification.
