---
adr: "0009"
title: "git_hook chain_existing composition contract"
status: accepted
date: 2026-07-14
bead: "CL-2wg8"
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
related_adrs: ["0002"]
---

# ADR-0009: git_hook chain_existing composition contract

## Status

Accepted. This ADR documents an existing, shipped contract. It implements
nothing new: the mechanism was introduced by **CL-rkww** (the gitleaks pre-push
hook) in `scripts/sync_project_tooling.py` and `prime/hooks/pre-push.sh`, and
its operational behavior is also described in `docs/project-tooling.md`. This
ADR lifts the contract out of that implementation code so future `git_hook`
entries can reuse it as a stable interface.

## Context

`project_tooling` (`docs/project-tooling.md`, CL-3fh) distributes managed Git
hooks into every matching project at SessionStart. The original `git_hook`
target kind assumed sole ownership of a hook path: it overwrites whatever hook
exists there. That is safe for `post-commit` (beads owns it) but unsafe the
moment a project already carries a foreign hook at the same path — for example
a repository-specific `pre-push`. Overwriting it silently would drop a control
the project relied on.

CL-rkww needed to install a managed `pre-push` wrapper **without** destroying a
pre-existing foreign `pre-push`. It solved this with an opt-in flag,
`chain_existing: true`, that splits responsibility between the sync runtime and
the wrapper hook:

- the **sync runtime** preserves the foreign hook once and installs the managed
  wrapper;
- the **wrapper** owns composition — it runs its own checks first and, only on
  success, replays the Git hook's stdin and arguments to the preserved hook.

During CL-rkww's Phase 3 architecture-council review the council flagged that
this is a new, reusable declarative pattern, and that its contract (marker
convention, sidecar naming, stdin/arg replay, exit-code propagation, ordering)
should be a documented, stable interface rather than knowledge embedded in
`sync_project_tooling.py`. This ADR is that documentation.

## Decision

`chain_existing: true` on a `git_hook` `project_tooling` entry declares that the
managed source hook is a **composing wrapper** that knows how to invoke a
preserved foreign hook. The contract has six parts. All six are load-bearing;
a future `git_hook` author reusing `chain_existing` MUST satisfy every one.

### Decision 1: Managed-marker convention

A managed wrapper is identified by a fixed marker byte-string in its own source.
The canonical marker is:

```
# managed-by: cognovis-library chain_existing (CL-rkww)
```

(constant `_CHAIN_EXISTING_MARKER` in `scripts/sync_project_tooling.py`).

The marker is the runtime's proof of two independent facts:

1. **Source is composable.** If `chain_existing: true` but the source hook does
   not contain the marker, sync fails closed
   (`error:chain_existing hook source missing managed marker`). A wrapper cannot
   opt into chaining without carrying the marker that makes it identifiable.
2. **Target is already managed.** When the runtime finds an existing hook at the
   target path that *already* contains the marker, it treats that hook as a
   previously-installed managed wrapper — not as a foreign hook — and does not
   move it aside. This is what makes repeated syncs idempotent (Decision 5).

The marker line MUST be preserved verbatim by any future wrapper that reuses the
mechanism. It is a shared sentinel, not per-hook text.

### Decision 2: Foreign-hook move-aside sidecar naming

The first time the runtime installs a managed wrapper over a **foreign**
(unmarked) hook at target `<hook_name>`, it renames the foreign hook once to a
sidecar in the same directory:

```
<hook_name>  ->  <hook_name>.local
```

(e.g. `pre-push` -> `pre-push.local`). The move happens exactly once: a hook
already carrying the marker is skipped, so later syncs never re-move, nest, or
duplicate the sidecar.

If a foreign hook exists at the target **and** a `<hook_name>.local` sidecar
already exists, the runtime fails closed rather than overwriting the sidecar
(`error:foreign hook exists at target and preserved sidecar already exists`).
It never clobbers a preserved local hook.

### Decision 3: stdin/arg single-capture-and-replay requirement

Git hooks receive input on stdin (e.g. `pre-push` receives one line per ref
being pushed) and via positional arguments (e.g. `pre-push <remote> <url>`).
stdin is a stream that can be read only once. The wrapper MUST therefore:

1. **Capture stdin once** to a temporary file before doing anything that
   consumes it, and clean that file up on exit (the reference wrapper uses
   `mktemp` + `trap 'rm -f "$stdin_file"' EXIT`).
2. **Drive its own checks** from the captured copy, not from the live stream.
3. **Replay to the sidecar** by passing the original positional arguments
   through (`"$@"`) and redirecting the captured stdin file into it:

   ```bash
   "$chain_hook" "$@" < "$stdin_file"
   exit $?
   ```

A wrapper that reads stdin directly and then execs the sidecar would hand it an
empty stream and silently defeat the chained hook. Single-capture-and-replay is
mandatory, not stylistic.

### Decision 4: Exit-code propagation

The composed hook's exit code is the wrapper's exit code:

- If the wrapper's own checks fail, it exits non-zero **without** invoking the
  sidecar (the sidecar never runs on the wrapper's failure).
- If the wrapper's checks pass and a sidecar exists, the wrapper execs the
  sidecar and propagates its exit code verbatim (`exit $?`).
- If the checks pass and no sidecar exists, the wrapper exits `0`.

Git aborts the operation on any non-zero hook exit, so both the wrapper's own
veto and the sidecar's veto must be able to block. Neither may be swallowed.

### Decision 5: Short-circuit ordering (scan-first, chained-hook-runs-only-on-pass)

Ordering is fixed: **wrapper checks run first; the chained sidecar runs only if
they pass.** The managed control is the gate; the preserved foreign hook is
downstream of it. This means:

- The managed control cannot be bypassed by a permissive foreign hook, because
  the foreign hook is never reached until the managed check has already passed.
- A foreign hook that would have vetoed still gets its veto — but only for
  pushes the managed control already allowed.

The runtime's own installation is likewise idempotent: an unchanged managed
wrapper at the target is detected by byte-equality and reported `skipped` (the
executable bit is still ensured), so re-running sync is a no-op.

### Decision 6: Responsibility split (runtime preserves, wrapper composes)

The sync runtime's responsibility ends at preservation and installation:

- resolve the effective hooks directory (honoring `core.hooksPath` and worktree
  `.git` files);
- verify the source marker;
- move a foreign hook aside once to the sidecar;
- write the managed wrapper and set the executable bit.

The runtime does **not** generate composition logic, know the hook's semantics,
or wire the sidecar call. **The wrapper owns composition** (Decisions 3–5). This
split is deliberate: the runtime stays hook-agnostic and every wrapper carries
its own, reviewable chaining logic.

## Applicability

`chain_existing` is appropriate for any `git_hook` entry that (a) must coexist
with a possibly pre-existing foreign hook at the same path, and (b) is authored
as a composing wrapper honoring Decisions 1–6.

| Hook | Reuse candidate? | Condition |
|---|---|---|
| `pre-push` | Yes — originating use (CL-rkww). | — |
| `pre-commit` | Yes. | Wrapper must capture/replay stdin (usually none for `pre-commit`) and positional args, run its checks first, chain the foreign `pre-commit.local` only on pass. |
| `commit-msg` | Yes. | The commit-message file path arrives as `$1`; the wrapper must forward `"$@"` so the sidecar sees the same message file. Exit non-zero rejects the commit. |
| `post-commit` | Deferred. | `post-commit` is advisory (its exit code cannot block) and beads currently owns it outright with plain overwrite. Migrating `beads-post-commit-hook` to `chain_existing` is a separate future bead, explicitly out of scope here. |

A future author reusing the mechanism only needs to: author the hook as a
wrapper, embed the Decision 1 marker verbatim, implement Decisions 3–5 for that
hook's stdin/arg shape, and set `chain_existing: true` on the `library.yaml`
entry. No `sync_project_tooling.py` change is required — the runtime is already
generic over hook name.

## Consequences

- Managed hooks can be installed over foreign hooks without data loss; the
  foreign hook is preserved as `<hook_name>.local` and still runs (downstream of
  the managed gate).
- The marker is a fleet-wide shared sentinel. Changing its text would strand
  already-installed wrappers (they would read as foreign and be moved aside), so
  the marker string is effectively frozen.
- Composition correctness lives in each wrapper, not in the runtime. Wrapper
  authors carry the stdin-replay and exit-propagation burden; a broken wrapper
  can silently no-op its sidecar. Reviewers must check Decisions 3–4 per wrapper.
- This is a cooperative client-side control (see `docs/project-tooling.md`
  threat model): it does not survive `git push --no-verify` or direct hook edits
  and is not the sole enforcement layer.

## Alternatives Considered

1. **Overwrite the foreign hook (original `git_hook` behavior).** Rejected —
   silently drops a control the project relied on.
2. **Refuse to install when a foreign hook exists.** Rejected — leaves projects
   with a pre-existing hook permanently unprotected by the managed control.
3. **Runtime-generated composition (runtime writes the chaining shim).**
   Rejected — couples the hook-agnostic runtime to per-hook stdin/arg
   semantics; keeping composition in the wrapper keeps each wrapper's behavior
   directly reviewable.
4. **Numbered/append sidecars (`<hook_name>.local.1`, …) for multiple foreign
   hooks.** Rejected — a single `<hook_name>.local` with fail-closed sidecar
   collision is simpler and sufficient; multi-hook chaining is not a current
   requirement.

## Cross-References

- [ADR-0002](canonical-library-architecture.md) — canonical library
  architecture; `project_tooling` distribution lives under it.
- `docs/project-tooling.md` — operational description of `project_tooling`,
  the `git_hook` target kind, and the client-side hook threat model.
- `scripts/sync_project_tooling.py` — runtime (`sync_git_hook`,
  `_prepare_chained_hook_target`, `_CHAIN_EXISTING_MARKER`).
- `prime/hooks/pre-push.sh` — reference composing wrapper (stdin capture,
  scan-first ordering, sidecar replay, exit propagation).
- CL-rkww — originating implementation (managed gitleaks pre-push hook).
- CL-2wg8 — this ADR.
