# Sync Installed Library Primitives

## Purpose

Refresh installed Library entries through the deterministic engine. The current
operation is conservative and non-pruning.

## Current procedure

Preview all installed entries first:

```bash
library sync --dry-run --json
```

Apply the reported additions and updates:

```bash
library sync --json
```

Successful top-level syncs that include project scope reconcile the
Library-managed block in the project `.gitignore`. The entries come from the
current schema-v2 project `.library.lock`: lock artifacts and only
project-owned `receipts[].targets[].path` values. The managed-ignore feature
does not fall back to the deprecated `installed` projection. User-authored
content outside the marked block is preserved and stale entries are removed;
malformed, absolute, or escaping targets fail before `.gitignore` or index
mutation.

Project sync uses one root for Git, `.library.lock`, and `.gitignore`. Without
`--project`, Library resolves the current Git top-level. An explicit `--project`
must name that top-level exactly, including when the checkout is a linked
worktree; nested directories are rejected before mutation.

Tracked managed paths are reported as warnings but remain in the Git index.
After reviewing the warning, remove exactly those paths from the index while
keeping their working-tree files with:

```bash
library sync --untrack --json
```

`library sync --dry-run` mutates neither `.gitignore` nor the Git index.

Use `library <primitive> sync <name>` when only one named entry should refresh.
The engine reads the current lockfile, resolves catalog state, preserves scope,
updates canonical targets and harness bridges, and records the resulting source
pin. Do not clone, copy, hash, or rewrite lock entries manually.

The released v1 lock is an additive installed list. Historical local-source
entries may report unknown or protected state; do not reinterpret them as remote
catalog provenance.

## Workspace lifecycle

Workspace sync provides contribution and ownership-aware planning:

```text
library workspace status --all --scope project
library workspace sync --all --scope project
library workspace sync --all --prune --apply --scope project
```

The first two forms remain non-pruning. Physical deletion requires the explicit
prune-and-apply form, complete fresh resolution, exact verified receipts, and all
migration acknowledgements. Ordinary `library sync` never gains pruning authority.
