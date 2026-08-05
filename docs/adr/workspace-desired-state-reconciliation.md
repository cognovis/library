---
adr: "0010"
title: "Universal Library ownership and Workspace desired-state reconciliation"
status: accepted
date: 2026-08-05
bead: CL-r7n6
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
amends: ["0003", "0004", "0005", "library-yaml-information-model"]
related_adrs: ["0002"]
---

# ADR-0010: Universal Library ownership and Workspace desired-state reconciliation

## Status

Accepted. Implementation is tracked by `CL-r7n6`; the first Cognovis
marketplace definition is tracked by `clc-tzn5`.

This ADR accepts the target architecture. Until `CL-r7n6` lands, the CLI and
lockfile implementation remain on the legacy additive model documented in the
transition section of `docs/lockfile-format.md`.

## Context

The Library can install a primitive and its transitive dependencies, but it
cannot currently express the complete Library-managed environment intended for
a repository. The flat lockfile records what was installed, not why it remains
installed. As a result, a normal sync can add and refresh content but cannot
safely decide that a formerly required transitive primitive is now removable.

This matters at two distinct scopes:

- A repository class such as a Python CLI should be able to opt into the same
  Skills, Standards, Agents, Workflows, and operating rules without copying a
  large `AGENTS.md` into every repository.
- The user-global baseline, or lobby, should remain deliberately small. Library
  content that is no longer part of that baseline should be identifiable and
  removable without treating every globally installed file as disposable.

Packages do not fill this gap. A Package is an atomic content composite: it
ships multiple cooperating artifacts together. It does not claim that its
members are the complete desired state of a project, and it does not supply the
ownership information required for safe garbage collection.

The missing capability has two layers:

1. a universal ownership model in the resolver and lockfile; and
2. a named, cataloged desired-state root that users can apply consistently.

The second layer is called a **Workspace**. This term means a Library desired-
state definition, not a filesystem directory, Git worktree, cmux workspace, or
harness session.

## Decision

### Decision 1: Ownership is universal; Workspace is its first desired-state consumer

Every user request is represented as a **requested root** in the selected
lockfile scope. A direct Skill, Standard, Agent, Workflow, Package, and Workspace
can all be roots. Every installed artifact is represented by a **materialized
receipt**.

The resolver computes reachability from the complete requested-root set. A
receipt remains required while at least one freshly resolved root reaches it.
This ownership rule is lockfile-wide; it is not special state hidden inside the
Workspace implementation.

Workspace is a first-class Library primitive for catalog lookup and lifecycle
commands, but it forms a new primitive category:

- it is a versioned, metadata-only desired-state root;
- it has no harness artifact and is never copied into `.agents/`, `.claude/`,
  `.codex/`, or another harness path;
- it is not model-triggered or user-invoked after installation; and
- its constitutive behavior is ownership-aware reconciliation of its typed root
  closure.

The deep module is the resolver, lockfile, and reconciler. Workspace intentionally
has a small interface over that mechanism.

### Decision 2: Workspace and Package remain distinct

| Concern | Package | Workspace |
|---------|---------|-----------|
| Constitutive feature | Atomic distribution of cooperating artifacts | Named desired-state ownership root |
| Contains deployable content | Yes | No |
| Install transaction | All package members succeed or the root is not committed | All newly required members succeed before prune can begin |
| Member activation | Each member follows its own trigger semantics | Each resolved primitive follows its own trigger semantics |
| Removal | Unregistering the root may make unshared member receipts pruneable | Unregistering the root may make unshared closure receipts pruneable |
| Harness projection | Inherited from package members | None |

Package atomicity is an installation transaction guarantee, not a requirement to
keep an unreachable member forever. Package members receive individual receipts.
After full re-resolution, removing a Package root may prune an unshared member
while preserving the same member when another root still reaches it.

ADR-0004's rejection of a `bundle` primitive remains valid. Workspace is not a
second bundle syntax: a bundle groups content for distribution; a Workspace names
the desired ownership boundary to reconcile.

### Decision 3: Workspace manifests are intentionally small

The v1 Workspace manifest contains only:

```yaml
schema_version: 1
name: python-cli
version: 1.0.0
description: Shared engineering baseline for Python CLI repositories
roots:
  - type: skill
    name: python-dev
    constraint: ">=1.0.0,<2.0.0"
  - type: skill
    name: python-test
    constraint: ">=1.0.0,<2.0.0"
  - type: standard
    name: beads-workflow
    constraint: ">=1.0.0,<2.0.0"
```

The catalog entry supplies the source marketplace, catalog identity, and
definition pin. Every root is a normal typed Library reference and may resolve
its own transitive `requires:` closure under ADR-0004.

The manifest does not inline routing policy, context-budget schemas, state-owner
schemas, harness configuration, or duplicated operating instructions. Those
concerns remain in their canonical primitives. For example, Beads rules or a
Workspace routing contract are modeled as Standard, Skill, Agent, Workflow, or
Package roots. This lets the same Workspace provide the same information set to
Claude Code, Codex, Pi, or a shell-facing CLI without making the Workspace a
second configuration system.

Workspace definition versions use semantic versioning. The manifest schema and
its independently versioned runtime contracts may evolve later, but unsupported
schema versions fail before dependency installation.

### Decision 4: Reconciliation is scope-homogeneous

One operation reconciles exactly one lockfile scope:

| Scope | Lockfile | Permitted targets |
|-------|----------|-------------------|
| Project | `<project>/.library.lock` | Project-local Library targets only |
| Global lobby | `~/.config/library/global.lock` | User-global Library targets only |

A Workspace-owned artifact closure cannot mix project and global targets. A
project lock cannot claim ownership of a global artifact, and a global lock
cannot claim ownership of a project artifact. Cross-scope artifact dependency
declarations fail before mutation.

Typed dependencies whose primitive contract is intrinsically global, including
`mcp:`, are global prerequisite assertions when reached from a project root.
They never create a project ownership edge or a project receipt. The resolver
checks the global lock for the required identity and compatible version before
any project mutation; absence or incompatibility is a fail-closed status finding
with the exact global install command. The same dependency reached from a global
root is a normal owned global receipt.

This makes global reconciliation safe without a cross-project registry: every
Library-owned global direct root and global Workspace root lives in the single
global lock. Projects that require reproducibility declare project-local roots;
they do not create hidden ownership edges to ambient global content.

A global Workspace can therefore define the lobby, while a project Workspace
can define a repository-class baseline. They use the same schema and resolver but
never share receipt ownership.

### Decision 5: Requested roots and receipts replace the flat installed list

Lockfile schema v2 has three top-level concerns:

```yaml
schema_version: 2
migration:
  prune_ack_required: false

requested_roots:
  - id: workspace:python-cli
    type: workspace
    name: python-cli
    catalog_identity: https://example.invalid/cognovis-catalog
    constraint: ">=1.0.0,<2.0.0"
    resolved_version: 1.0.0
    definition_commit: 0123456789abcdef

receipts:
  - id: skill:python-dev@1.0.0
    type: skill
    name: python-dev
    catalog_identity: https://example.invalid/cognovis-catalog
    source_commit: fedcba9876543210
    resolved_version: 1.0.0
    verified: true
    adopted: false
    prune_blocked_reason: null
    targets:
      - path: .agents/skills/python-dev/SKILL.md
        kind: file
        content_sha256: 9483a09400000000000000000000000000000000000000000000000000000000
      - path: .claude/skills/python-dev
        kind: symlink
        link_target: ../../.agents/skills/python-dev
    owners_cache:
      - workspace:python-cli
```

The exact field schema is owned by `docs/schema/lockfile.schema.json`. The
architectural invariants are:

- `requested_roots` is authoritative user intent.
- Each receipt identifies one materialized primitive and every exact target or
  bridge created for it.
- Content digests are per file. Directory-level summary digests may be retained
  for audit performance but cannot replace the target inventory required for
  safe deletion and adoption.
- `owners_cache` and any persisted edge snapshot are explanatory audit data
  only. They are never resolver input for a later prune.
- The authoritative owner set is recomputed from all requested roots against a
  fresh, complete, catalog-pinned resolution at plan time.

One materialization exists for a given `(scope, type, name, target)`. If two roots
have incompatible version constraints, resolution fails loudly. There is no
last-writer-wins version selection.

### Decision 6: Legacy migration grants no deletion authority

Every legacy `installed:` entry is migrated conservatively:

1. promote it to a direct requested root;
2. create a receipt with the known provenance and target information;
3. mark the receipt `verified: false` and prune-blocked because historical
   aggregate checksums are insufficient proof of every installed target; and
4. set `migration.prune_ack_required: true`.

Migration never infers that a legacy install belongs to a Workspace. A verifying
reinstall may record per-file digests and clear the prune block. The user may
later remove the direct root explicitly after seeing the resulting plan.

This deliberately retains too much rather than deleting a historical manual or
direct install.

The migration guard blocks only pruning; additive `workspace use` and ordinary
sync remain available. The first `workspace sync --prune` is always plan-only
and emits a digest of the complete selected-scope plan. The guard clears only
when a later `--prune --apply --acknowledge-plan <digest>` supplies that exact
unchanged digest. A missing or stale digest fails closed.

### Decision 7: The Workspace command surface is explicit about deletion

The v1 CLI surface is:

```text
library workspace use <name> [--scope project|global]
library workspace status [<name>|--all] [--scope project|global]
library workspace sync [<name>|--all] [--scope project|global]
library workspace sync [<name>|--all] --prune --apply [--scope project|global]
library workspace sync [<name>|--all] --prune --apply --acknowledge-plan <digest> [--scope project|global]
library workspace adopt <workspace> <type>:<name> --definition-commit <pin> [--scope project|global]
library workspace remove <name> [--scope project|global]
```

Semantics:

- `use` idempotently registers the Workspace root and applies additions and
  updates. It never prunes.
- `status` is read-only. It reports additions, updates, drift, foreign collisions,
  missing global prerequisites, adoption candidates, constraint conflicts, and
  prune candidates. Exit 0 means converged, exit 2 means the plan has changes or
  protected findings, and exit 1 means the status operation itself failed.
- `sync` refreshes additions and updates but remains non-pruning by default. It
  always prints the plan and provenance reason for each action.
- `sync --prune` without `--apply` is a read-only prune preview. Physical
  deletion requires both `--prune` and `--apply`. A prune plan explains which
  root or catalog edge disappeared and why the receipt is now ownerless.
- `adopt` acts on exactly one existing member reached by the named registered
  Workspace. The supplied definition commit must match the Workspace root's
  current resolved pin; one catalog artifact and every expected target must
  match exactly before an adopted receipt is written. Adoption never creates a
  direct root.
- `remove` unregisters the Workspace root and prints the resulting plan. It does
  not delete physical targets. It prints the exact follow-up command:
  `library workspace sync --all --prune --apply --scope <scope>`.
- The Workspace selector limits which Workspace definitions receive additions
  and updates. The prune set is always computed from the entire freshly resolved
  requested-root set in the selected lock scope, including direct and Package
  roots. `--all --prune` remains valid with zero registered Workspaces, so the
  last removed Workspace and orphaned dependencies from a direct named removal
  can still be reconciled. It is never a cross-project fleet sweep.

The existing `library sync` and primitive-specific sync commands remain
conservative and non-pruning. The shared word "sync" means "reconcile toward the
selected source" in both cases; only the Workspace subcommand accepts the
explicit `--prune --apply` capability.

### Decision 8: Pruning is provenance-bound and fail-closed

A receipt can be deleted only when all of these conditions hold:

1. a fresh and complete resolution finds no requested root that reaches it;
2. its catalog identity, resolved version, and source pin are known;
3. every deletion target is exactly recorded in the selected lockfile and lies
   inside an allowed Library-managed root for that scope;
4. every current file or link matches its install-time receipt digest or exact
   link target;
5. the receipt is verified and not prune-blocked;
6. the target is not owned by chezmoi, another desired-state manager, or a foreign
   Library catalog; and
7. all additions and updates in the same plan have completed successfully.

A directory entry is a container marker, not permission for recursive deletion.
The reconciler removes only individually recorded files and links, then removes
the directory only if it is empty. Any unrecorded nested content marks the
receipt drifted and prune-blocked.

Missing catalogs, partial resolution, cycles, incompatible constraints, ambiguous
catalog matches, drift, foreign provenance, and external-manager overlap disable
pruning for the run. They are status outcomes, not invitations to guess.

Before planning, the reconciler builds a protected-path set from configured
Library exclusions and read-only inventories supplied by supported manager
adapters such as chezmoi. If an installed manager cannot be inventoried, pruning
is disabled for the affected scope rather than assuming non-overlap.

An existing unowned path is a collision and blocks installation by default.
Adoption uses the Decision 7 command, one unambiguous pinned catalog version, and
an exact per-file digest match. Adoption records provenance and represents
consent to future Library reconciliation. Drifted Library files remain protected
until the user explicitly restores, replaces, or relinquishes them; a force flag
cannot bypass the ownership proof.

The verified-receipt rule governs ownership-derived pruning. Explicit named
`library <primitive> remove <name>` is separate user consent: it unregisters the
direct root, preserves the receipt when another root still reaches it, and may
delete the ownerless named artifact's recorded targets even when a migrated
receipt is unverified. It must show an unverified or drift warning and use the
journaled safe-delete path. Ownerless transitive receipts are not silently
deleted; the command prints the selected-scope Workspace prune follow-up.

### Decision 9: Reconciliation is locked, journaled, and re-entrant

Each selected lock scope has one reconciliation mutex. The apply sequence is:

1. acquire the scope lock;
2. resolve all requested roots completely and produce the deterministic plan;
3. apply additions and updates into temporary targets, atomically swap each
   completed clean target, and journal its verified receipt; skip a drifted
   target unless the user has explicitly chosen the primitive's existing
   restore, replace, or relinquish path;
4. if any resolution, addition, or update fails, stop before all pruning;
5. recompute and validate the prune set against current receipts and filesystem
   state;
6. durably journal the complete prune manifest, including every retired receipt,
   exact deletion target, and expected digest or link target;
7. atomically write the intended post-prune lock state before physical deletion;
8. delete only the journaled targets, recording progress; and
9. clear the journal after a successful final audit.

The ordering chooses the safe crash direction. A crash after the lock commit but
before every deletion may leave a physical orphan that a resumed reconciliation
can remove. It must never leave a receipt claiming a file that was already
deleted. On resume, the reconciler first replays completed addition receipts and
the durable prune manifest into a consistent lock view, then freshly re-resolves
before continuing; the lockfile alone is never assumed complete mid-run. Updates
at the same path use the same temporary-target and journal protocol.

### Decision 10: Installation scope is not context scope

Workspace membership says which Library primitives are present, not which text is
resident in every model context. Each member retains its primitive-specific load
semantics:

- a Skill is discovered or loaded according to the target harness;
- a Standard is loaded only through its declared consumer or injection contract;
- an Agent receives its own context when invoked;
- a Hook runs at its lifecycle event; and
- a Script runs only when called.

`workspace status` groups the closure by these load semantics. For the global
lobby it also reports the number of direct roots, materialized receipts, and any
deterministically calculable standing-context estimate. Unknown cost is reported
as unknown, never as zero. Budget policy remains a separately versioned Standard
or runtime contract referenced by the Workspace rather than an inline manifest
schema.

This separation lets the lobby stay auditable and small without confusing
"installed globally" with "fully loaded into every prompt."

### Decision 11: Platform and marketplace responsibilities remain separate

The Library platform repository owns:

- this ADR and the primitive contract;
- Workspace and lockfile JSON Schemas;
- catalog parsing and typed root resolution;
- CLI commands, planning, reconciliation, migration, and recovery;
- isolated fixtures and regression tests; and
- published schema-version compatibility.

Marketplace repositories own:

- Workspace manifests as catalog content;
- the selection and versioning of reusable primitive roots;
- documentation of the environment they provide; and
- CI validation against a pinned or published platform schema.

Platform tests use local fixtures and never read a live sibling marketplace
checkout. Marketplace tests never assume an unversioned sibling platform
checkout. An unsupported manifest schema fails with an explicit compatibility
error.

## Consequences

### Positive

- Repository classes can share one reviewable information set without copying
  project instructions.
- Direct, Package, and Workspace requests follow one ownership model.
- Shared dependencies survive until their final owner disappears.
- The global lobby can be inspected and deliberately reduced without touching
  foreign or unverified state.
- A repository remains functional if Workspace metadata disappears: installed
  primitives keep their native behavior, while future desired-state reconciliation
  becomes unavailable until the definition is restored.
- The CLI surface stays small while the reconciler owns the hard safety logic.

### Negative

- Lockfile v2 is a breaking schema migration and requires journal and lock
  machinery.
- Legacy installations are intentionally sticky until verified.
- Safe prune requires complete catalog availability and cannot proceed offline.
- Workspace introduces a metadata-only primitive category with no harness
  projection, which must be explained explicitly in primitive documentation.
- Global desired state is ambient user tooling, not a reproducible project
  dependency.

## Alternatives Considered

### Treat Workspace as a Package alias

Rejected. Package membership expresses atomic distribution, not the complete
desired state or ownership needed to remove stale transitive receipts.

### Implement pruning only inside Workspace state

Rejected. Direct primitives and Packages would retain incompatible ownership
semantics, and shared dependencies could be removed or leaked depending on which
command installed them.

### Persist owner edges as the next prune's source of truth

Rejected. Catalog and manifest changes make persisted edges stale. Requested
roots plus fresh resolution are authoritative; edge snapshots are audit-only.

### Prune on every Workspace sync by default

Rejected for v1. Agents frequently run commands non-interactively, legacy state
needs verification, and deletion deserves an explicit plan and apply signal.

### Inline routing and context-budget configuration in Workspace manifests

Rejected. It creates a parallel runtime configuration system and couples every
operating-policy change to desired-state schema evolution. Workspaces compose the
canonical primitives that already own those contracts.

### Exclude global Workspaces permanently

Rejected. A global lobby is a legitimate desired-state scope once all global
Library roots share the universal global lock. Cross-scope edges remain forbidden.

## Implementation and release gates

`CL-r7n6` must land the schema, migration, resolver, CLI, recovery protocol,
tests, and documentation as one coherent platform capability. The capability is
not release-ready until fault-injection tests cover incomplete catalogs,
constraint conflicts, concurrent sync, addition failure, lock-write failure,
crash between lock commit and delete, drift, external-manager overlap, exact
adoption, unrecorded nested directory content, missing global prerequisites,
zero-Workspace scope pruning, and multi-owner survival.

`clc-tzn5` then publishes the first `python-cli` Workspace from the Cognovis
marketplace and validates it against the supported schema without a live sibling
checkout.

The initial release keeps deletion behind `--prune --apply`. Changing that default
requires a later ADR backed by operational evidence from real lockfile v2 usage.
