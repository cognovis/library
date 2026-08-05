# Sync Installed Library Primitives

## Purpose

Refresh installed Library entries through the deterministic engine. The current
operation is conservative and non-pruning.

## Current procedure

Preview all installed entries first:

```bash
uv run --script <LIBRARY_SKILL_DIR>/scripts/library.py sync --dry-run --json
```

Apply the reported additions and updates:

```bash
uv run --script <LIBRARY_SKILL_DIR>/scripts/library.py sync --json
```

Use `library <primitive> sync <name>` when only one named entry should refresh.
The engine reads the current lockfile, resolves catalog state, preserves scope,
updates canonical targets and harness bridges, and records the resulting source
pin. Do not clone, copy, hash, or rewrite lock entries manually.

The released v1 lock is an additive installed list. Historical local-source
entries may report unknown or protected state; do not reinterpret them as remote
catalog provenance.

## Workspace target

After `CL-r7n6`, Workspace sync adds contribution and ownership-aware planning:

```text
library workspace status --all --scope project
library workspace sync --all --scope project
library workspace sync --all --prune --apply --scope project
```

The first two forms remain non-pruning. Physical deletion requires the explicit
prune-and-apply form, complete fresh resolution, exact verified receipts, and all
migration acknowledgements. Ordinary `library sync` never gains pruning authority.
