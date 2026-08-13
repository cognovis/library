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
amended_by: ["0011"]
related_adrs: ["0002", "0011"]
---

# ADR-0010: Universal Library ownership and Workspace desired-state reconciliation

## Status

Accepted and implemented by `CL-r7n6`; the first Cognovis marketplace
definition is tracked by `clc-tzn5`. Legacy v1 lockfiles remain readable as
conservative migration input, while all new writes use the v2 ownership model.

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

Dependency closures do not fill this gap. `requires:` correctly says what one
primitive needs in order to function, but it does not say which independently
useful capabilities a user intends to keep together as a repository baseline.
The previously documented Package concept is not implemented by the Library CLI
or catalog schema and would duplicate these two graph relationships.

The missing capability has two layers:

1. a universal ownership model in the resolver and lockfile; and
2. a named, cataloged desired-state root that users can apply consistently.

The second layer is called a **Workspace**. This term means a Library desired-
state definition, not a filesystem directory, Git worktree, cmux workspace, or
harness session.

## Decision

### Decision 1: Ownership is universal; Workspace is its first desired-state consumer

Every user request is represented as a **requested root** in the selected
lockfile scope. Any directly requestable artifact primitive and any Workspace can
be a root. Every installed artifact is represented by a **materialized receipt**.

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

### Decision 2: Two graph relationships replace Package and bundle aliases

The Library has exactly two composition relationships:

| Relationship | Meaning | Authoritative declaration |
|--------------|---------|---------------------------|
| Dependency | One primitive cannot function correctly without another | The entrypoint primitive's `requires:` metadata |
| Desired-state composition | Independently meaningful capabilities are selected together and may later be retired together | A Workspace manifest's `roots:` |

Both relationships are installed transactionally: all newly required artifacts
must materialize before the requested root is committed. That transaction property
does not justify a third Package or bundle primitive.

The Package page in the primitive glossary is retained only as a retirement note.
External npm, PyPI, Pi, and harness packages remain valid distribution formats, but
they are not Library requested-root types. ADR-0004's rejection of a `bundle`
primitive therefore remains the active decision.

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
```

The catalog entry supplies the source catalog, canonical catalog identity, and
definition pin. Every v1 root is a normal artifact reference from that same
catalog and may resolve its own transitive `requires:` closure under ADR-0004.
Workspace roots and per-root `catalog` qualifiers are rejected by schema v1.
Cross-catalog composition remains possible at the scope boundary by directly
registering one Workspace from each configured catalog. Nested Workspaces and
cross-catalog manifest roots are deferred until real portfolio evidence requires
their additional lifecycle semantics.

The manifest does not inline routing policy, context-budget schemas, state-owner
schemas, harness configuration, or duplicated operating instructions. Those
concerns remain in their canonical primitives. For example, Beads rules or a
Workspace routing contract are modeled as Standard, Skill, Agent, Workflow, or
other ordinary primitive roots. This lets the same Workspace provide the same information set to
Claude Code, Codex, Pi, or a shell-facing CLI without making the Workspace a
second configuration system.

Workspace definition versions use semantic versioning. The manifest schema and
its independently versioned runtime contracts may evolve later, but unsupported
schema versions fail before dependency installation.

Publication applies enforceable admission rules rather than treating every
repeated directory name as a Workspace:

- a manifest has 2-10 independently meaningful direct roots;
- every root validates and installs standalone with its own `requires:` closure;
- a project closure contains at most the configured receipt budget (30 by default);
- the same selection is evidenced in at least two committed consumer locks;
- exactly one marketplace catalog is named as steward; and
- a consumer asking for "all except one member" is evidence that the Workspace
  is too coarse and must be split, not a reason to add exclusions or overrides.

The global lobby is stricter: by default at most five direct roots, at most 15
receipts, no domain or customer content, and deterministically calculable
standing context within one percent. Top-level `workspace_policy` may lower
these limits for a deployment. Unknown context cost blocks lobby publication
rather than counting as zero.

### Decision 3a: Composition is many-to-many and unordered

A selected lock scope may register zero or more Workspace requested roots. A
repository is not assigned a single Workspace type. Its effective desired state
is the set union of:

- direct artifact roots;
- directly registered Workspace roots;
- all transitive primitive dependencies.

Schema v1 has no nested Workspace graph. Composition has no declaration order,
override layer, exclusion layer, or last-writer-wins behavior. Incompatible
constraints, ambiguous catalog references, target collisions, and scope
mismatches fail before mutation with both roots, constraints, canonical catalog
identities, and stewards named in the diagnostic.

This permits deliberate orthogonal composition. For example,
`fhir-management` can register both `fhir-ig-authoring` and `python-cli`, while
`library/meta` can register `library-authoring` and `python-cli`. A one-member
alias with no independent lifecycle purpose should remain a direct primitive root.

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

Typed dependencies whose primitive contract or catalog entry is explicitly
global, including `mcp:` and entries with `default_scope: global`, are global
prerequisite assertions when reached from a project root.
They never create a project ownership edge or an artifact receipt. The project
lock records them as non-owning prerequisite assertions with the requesting root,
identity, and constraint so status and CI can reproduce the requirement. The
resolver checks the global lock for the required identity and compatible version
before any project mutation; absence or incompatibility is a fail-closed status
finding with the exact global install command. The same dependency reached from
a global root is a normal owned global receipt.

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

prerequisites:
  - id: mcp:example-server
    scope: global
    constraint: ">=1.0.0,<2.0.0"
    requested_by:
      - workspace:python-cli
```

The exact field schema is owned by `docs/schema/lockfile.schema.json`. The
architectural invariants are:

- `requested_roots` is authoritative user intent.
- Each receipt identifies one materialized primitive and every exact target or
  bridge created for it.
- A project lock serializes every project-owned install target, bridge path, and
  receipt target relative to the lock root. Runtime operations resolve those
  paths against the selected project. Global targets and Layer-B cache
  provenance remain absolute because they are not owned by the project tree.
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
reinstall through `workspace sync --verify-receipts` records per-file digests and
clears the per-receipt prune block. `migration.prune_ack_required` clears only
after the selected scope has no unverified receipt. After registering a
Workspace, the user can transfer intent without deleting files through a
plan-and-apply direct-root demotion:

```text
library workspace adopt <catalog>:<workspace> --from-direct <type>:<name> --scope <scope>
library workspace adopt <catalog>:<workspace> --from-direct --all-reachable --scope <scope>
```

The first form demotes one reachable direct root; the second demotes every direct
artifact root freshly reachable from the Workspace. Both preview by default and
require `--apply --acknowledge-plan <digest>` to change the lock. Their plans can
remove requested-root records only; they never delete or rewrite targets.

This deliberately retains too much rather than deleting a historical manual or
direct install.

The migration guard blocks only pruning; additive `workspace use` and ordinary
sync remain available. Only `workspace sync --verify-receipts` can clear the
guard, after every selected-scope receipt has exact verified targets. Once the
guard is clear, `workspace sync --prune` is plan-only and emits a digest of the
exact prune set; a later apply must supply that unchanged digest. Additive
catalog changes invalidate the handshake only when they change reachability or
a candidate deletion. A missing or stale digest fails closed.

### Decision 7: The Workspace command surface is explicit about deletion

The v1 CLI surface is:

```text
library workspace list [--scope project|global] [--json]
library workspace show <catalog>:<name> [--scope project|global] [--json]
library workspace validate <manifest-or-catalog-reference> [--json]
library workspace use <catalog>:<name> --scope project|global [--dry-run] [--replace-with-catalog-content] [--json]
library workspace status [<catalog>:<name>|--all] --scope project|global [--json]
library workspace explain <type>:<name> --scope project|global [--json]
library workspace sync [<catalog>:<name>|--all] --scope project|global [--verify-receipts] [--json]
library workspace sync [<catalog>:<name>|--all] --prune [--apply] --scope project|global [--json]
library workspace sync [<catalog>:<name>|--all] --prune --apply --acknowledge-plan <digest> --scope project|global [--json]
library workspace adopt <catalog>:<workspace> <type>:<name> --definition-commit <pin> --scope project|global [--json]
library workspace adopt <catalog>:<workspace> --from-direct [<type>:<name>|--all-reachable] --scope project|global [--apply --acknowledge-plan <digest>] [--json]
library workspace remove <catalog>:<name> --scope project|global [--json]
```

Semantics:

- `list`, `show`, and `validate` provide catalog discovery, resolved closure
  preview, and the same validation entrypoint used by marketplace CI.
- Operator references use `<catalog>:<name>`. A bare name is accepted only when
  exactly one configured catalog declares it; otherwise the command fails with
  the candidate list. The configured catalog registry is the only authority that
  maps an operator nickname to a canonical catalog URL. Locks record both the
  supplied display name and canonical identity; resolution and pruning use only
  the canonical identity.
- `use` idempotently registers the Workspace root and applies additions and
  updates. It never prunes. `--dry-run` plans an unregistered Workspace without
  changing requested roots or targets and emits a machine-readable collision
  report. A consented `--replace-with-catalog-content` apply option is available
  only when provenance proves the target is Library-authored content from the
  selected catalog; it cannot replace project-authored or externally owned data.
- `status` is read-only. It reports additions, updates, drift, foreign collisions,
  missing global prerequisites, adoption candidates, constraint conflicts, and
  prune candidates. With several Workspaces it distinguishes exclusive
  contribution and shared receipts. Exit 0 means converged, exit 2 means
  convergent changes are pending, exit 3 means a protected or blocked finding
  requires a decision, and exit 1 means the operation itself failed.
- `explain` shows every recomputed direct-root owner that reaches one receipt,
  plus its locked catalog identity and protection state. Full intermediate
  dependency-edge traces are not persisted in schema v1.
- `sync` refreshes additions and updates but remains non-pruning by default. It
  always prints the plan and provenance reason for each action.
- `sync --verify-receipts` rematerializes or re-hashes catalog-pinned content and
  is the named operation that can clear a migrated `verified: false` state.
- `sync --prune` without `--apply` is a read-only prune preview. Physical
  deletion requires both `--prune` and `--apply`. A prune plan explains which
  root or catalog edge disappeared and why the receipt is now ownerless.
- `adopt` acts on exactly one existing member reached by the named registered
  Workspace. The supplied definition commit must match the Workspace root's
  current resolved pin; one catalog artifact and every expected target must
  match exactly before an adopted receipt is written. Adoption never creates a
  direct root.
- `adopt --from-direct` is a separate ownership-transfer mode. It removes one or
  all freshly Workspace-reachable direct artifact roots from requested intent,
  preserves every receipt through Workspace reachability, and never touches the
  filesystem.
- `remove` unregisters a directly requested Workspace root and prints the
  resulting plan. Removal does not delete physical targets. It prints the
  selected-scope prune preview command and the digest-bound apply command.
- The Workspace selector limits which Workspace definitions receive additions
  and updates. The prune set is always computed from the entire freshly resolved
  requested-root set in the selected lock scope, including direct artifact roots.
  `--all --prune` remains valid with zero registered Workspaces, so the
  last removed Workspace and orphaned dependencies from a direct named removal
  can still be reconciled. It is never a cross-project fleet sweep.

The existing `library sync` and primitive-specific sync commands remain
conservative and non-pruning. The shared word "sync" means "reconcile toward the
selected source" in both cases; only the Workspace subcommand accepts the
explicit `--prune --apply` capability.

Every command supports stable JSON output. Scope may be inferred only when
exactly one target lock is possible; when both a project and global lock are
plausible, omission fails and asks for `--scope`.

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

The platform owns a versioned manager-inventory adapter contract. The reference
chezmoi adapter reports canonical target paths and manager identity without
granting Library ownership. Bootstrap, `project_tooling`, and the consumer
updater provide the same read-only inventory shape during their cutover. An
installed supported manager without a working adapter is a visible blocked
status, not a silently disabled prune mode.

An existing unowned path is a collision and blocks installation by default.
Adoption uses the Decision 7 command, one unambiguous pinned catalog version, and
an exact per-file digest match. Adoption records provenance and represents
consent to future Library reconciliation. Drifted Library files remain protected
until the user explicitly restores, replaces, or relinquishes them; a force flag
cannot bypass the ownership proof.

The verified-receipt rule governs both ownership-derived pruning and explicit
named removal of a v2 receipt. `library <primitive> remove <name>` unregisters
the direct root and preserves the receipt when another root still reaches it.
An ownerless verified receipt is removed through the same exact-target,
containment, external-manager, lock, and journal protocol as prune. Unverified,
drifted, externally managed, or unrecorded content blocks physical deletion.
When the supplying catalog no longer contains an unverified direct root, named
removal may unregister its Library state but must retain every recorded path;
this is an ownership relinquishment, not a prune. Ownerless transitive receipts
are never silently deleted. Legacy targetless receipts pass through the same
fresh ownership check before their primitive-specific compatibility handler may
run.

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
as unknown, never as zero. A lobby plan blocks above the top-level
`workspace_policy` budgets, whose defaults are five direct roots, 15 receipts,
and one percent standing context. These are Library platform runtime policy, not
inline Workspace manifest fields.

This separation lets the lobby stay auditable and small without confusing
"installed globally" with "fully loaded into every prompt."

### Decision 11: Platform and marketplace responsibilities remain separate

The Library platform repository owns:

- this ADR and the primitive contract;
- Workspace and lockfile JSON Schemas;
- catalog parsing and typed root resolution;
- CLI commands, planning, reconciliation, migration, and recovery;
- catalog discovery and canonical catalog-identity resolution;
- the external-manager inventory adapter contract and chezmoi reference adapter;
- isolated fixtures and regression tests; and
- published schema-version compatibility.

Publishing catalog repositories own:

- Workspace manifests as catalog content;
- the selection and versioning of reusable primitive roots;
- documentation of the environment they provide; and
- CI validation against a pinned or published platform schema;
- evidence that each Workspace root installs standalone and that the manifest
  meets reuse, size, closure, and lobby admission limits.

The platform may also publish a Workspace when every root is platform-owned;
`library-authoring` is the first example. Platform tests use local fixtures and
never read a live sibling catalog checkout. Catalog tests never assume an
unversioned sibling platform checkout. An unsupported manifest schema fails with
an explicit compatibility error.

### Decision 12: Workspace retires parallel Library desired-state manifests

The Workspace reconciler becomes the sole Library mechanism for declaring a
reusable project or global artifact baseline. Three older mechanisms are
transitional:

- ADR-0002's hand-maintained capability list becomes an `engineering-lobby`
  Workspace. An irreducible bootstrap still installs the Library engine and its
  conversational entrypoint because Workspace cannot install its own resolver.
  Platform forge Skills leave bootstrap and become roots of
  `library-authoring`.
- `consumer-projects.yml` and `scripts/update-consumers.py` stop distributing
  Library primitives after each consumer has registered equivalent Workspace or
  direct roots. Their `managed_files` escape hatch is not carried forward.
- root-level `project_tooling` stops accepting new distributable capability
  entries. Existing entries migrate according to ownership: normal Library
  artifacts become primitives with `requires:` and Workspace roots; Beads-owned
  database configuration and primer behavior move to Beads; repository policy
  patches remain project-owned.

These legacy managers are protected external owners during migration. Before a
repository cuts over, it records every distributed target with one disposition:
becomes a primitive, becomes project-owned and frozen with provenance, or is
explicitly retired. The legacy writer is disabled for that repository in the
same change that registers its replacement roots. A Workspace may neither adopt
nor prune a still-managed target. Removing a legacy mechanism requires verified
equivalence, receipts, and no remaining consumer inventory; ADR-0010 does not
reinterpret historical writes as Library ownership.

The authoritative desired-state and writer-disable contract is recorded here;
historical per-target audit evidence remains available in version history.

The irreducible bootstrap writes verified adopted receipts for every Library
path it materializes, including the engine and conversational entrypoint. It is
irreducible in install order, not exempt from ownership accounting.

Workspace does not absorb arbitrary file-copy, JSON-patch, routing-profile,
secret, or customer-data schemas. A capability that cannot be represented by a
real primitive or dependency remains with its owning project or tool.

## Consequences

### Positive

- Repository classes can share one reviewable information set without copying
  project instructions.
- Direct artifact and Workspace requests follow one ownership model.
- Orthogonal Workspaces can be composed without creating a combined variant for
  every repository class.
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
- Legacy installations require an explicit but bulk-capable verification and
  direct-root demotion runway.
- Safe prune requires complete catalog availability and cannot proceed offline.
- Workspace introduces a metadata-only primitive category with no harness
  projection, which must be explained explicitly in primitive documentation.
- Global desired state is ambient user tooling, not a reproducible project
  dependency.
- Schema v1 deliberately omits nested Workspaces and cross-catalog manifest
  roots; consumers compose catalogs by registering several direct Workspaces.

## Alternatives Considered

### Add Package as a third composite root

Rejected. The current Library has no Package catalog or CLI primitive. Strict
functional coupling belongs in `requires:` and selectable lifecycle grouping
belongs in Workspace. Transactional installation applies to both graphs without
another public abstraction.

### Implement pruning only inside Workspace state

Rejected. Direct primitives would retain incompatible ownership semantics, and
shared dependencies could be removed or leaked depending on which command
installed them.

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

### Ship nested Workspaces and cross-catalog manifest roots in v1

Deferred. The admitted v1 portfolio composes capabilities through several direct
Workspace registrations and does not require either feature. Deferral removes
cycle handling, hidden removal semantics, and nickname-to-canonical-catalog
resolution from the first deletion-capable release. A later ADR may add them when
at least two real consumers require the same nested or cross-catalog lifecycle.

> **Amended for cross-catalog manifest roots only — FINAL (CL-2p73,
> 2026-08-08; finalized 2026-08-09).** [ADR-0011](heterogeneous-marketplace-workspaces.md) defines
> Workspace schema v2 with pinned, alias-qualified cross-catalog roots. The
> two-consumer evidence gate above was **amended, not satisfied**: the three
> committed locks that compose across catalogs (`library/meta`,
> `library/cognovis-pi`, `mira`) all compose at the **scope boundary**, which is
> this ADR's own v1 escape hatch, and therefore do not evidence a manifest-root
> requirement. The amendment is an explicit Human Decision by Malte Sussdorff with
> its rationale recorded in ADR-0011 `Consumer Lock Evidence`.
>
> The amendment is **final** as of 2026-08-09: ADR-0011 implementation slice 1
> (`CL-coif`) delivered all four evidence items listed in its `Approval
> Finalization` section, which records the finalization and its artifacts.
>
> **Nested Workspaces are not amended.** They remain deferred under this gate
> exactly as written, with their original cycle-handling, ownership-visibility,
> and removal-semantics conditions.
>
> Every other decision in this ADR — in particular fail-before-mutation, the seven
> Decision 8 prune conditions, scope homogeneity, and no-overlay composition — is
> restated unchanged by ADR-0011 and is non-replaceable.

## Implementation and release gates

`CL-r7n6` must land the schema, migration, resolver, CLI, recovery protocol,
tests, and documentation as one coherent platform capability. The capability is
not release-ready until fault-injection tests cover incomplete catalogs,
constraint conflicts, concurrent sync, addition failure, lock-write failure,
crash between lock commit and delete, drift, external-manager overlap, exact
adoption, consented Library-content replacement, direct-root demotion, an
unrecorded nested directory, symlink-to-drifted-directory behavior, missing global
prerequisites, zero-Workspace scope pruning, and multi-owner survival. Contract
tests must also cover catalog discovery, qualified identity, bare-name ambiguity,
several directly registered Workspaces, contribution and overlap status, size and
lobby budgets, standalone root closure, and rejection of Package, nested
Workspace, and cross-catalog manifest roots. Migration tests must prove that
bootstrap, consumer-updater, and `project_tooling` targets remain inventoried and
protected until their per-file replacement is verified and the legacy writer is
disabled.

`clc-tzn5` then publishes the first `python-cli` Workspace from the Cognovis
marketplace and validates it against the supported schema without a live sibling
checkout.

The initial release keeps deletion behind `--prune --apply`. Changing that default
requires a later ADR backed by operational evidence from real lockfile v2 usage.
