# .library.lock Format

> **Status**: NORMATIVE — this document is the authoritative format
> specification for `.library.lock`. Schema v2 implements ADR-0010; schema v1
> remains accepted only as conservative migration input.
>
> **Bead**: CL-t21 / CL-yx2 / CL-yum0 / CL-r7n6 | **Epic**: CL-36o | **Last updated**: 2026-08-05
>
> **Applies to**: `library <primitive> use`, `library <primitive> remove`,
> `library sync`, `library workspace use|status|sync|remove`, `library audit`,
> and any tooling that installs or manages Library items.

---

## Overview

Library lockfiles record Library intent and materialized state. Most primitives
may use either the project or global lockfile; MCP registrations are always
user-global and therefore exist only in the global lockfile. They provide:

- **Reproducibility**: any clone of the project can restore the locked roots and
  exact source pins. Legacy v1 sync reads the flat lock entries; v2 reconciliation
  reads requested roots and resolves their definitions from the recorded catalog
  identities and pins.
- **Drift detection**: `/library audit` compares the `content_sha256`/`checksum_sha256` stored at install
  time against the current on-disk file to identify modifications made outside the Library.
- **Audit trail**: every new entry records the producing catalog identity, source URL,
  commit SHA, license, and install timestamp for security and compliance review.
- **Ownership** in schema v2: explicit requested roots are separated from
  materialized receipts so a freshly resolved graph can preserve shared
  dependencies and identify only clean ownerless receipts as prune candidates.

## Version Status and Transition

| Version | State | Top-level model | Deletion authority |
|---------|-------|-----------------|--------------------|
| v1 | Legacy migration input | `installed:` flat list | Explicit primitive removal only; no desired-state prune |
| v2 | Current write format | `requested_roots:` plus `receipts:` | Workspace prune only after fresh resolution and `--prune --apply` |

Readers implementing new behavior must follow v2. The CLI migrates v1 in memory,
promotes every legacy install to a direct root, and grants no deletion authority
until receipts are verified. It rejects a schema newer than it supports rather
than interpreting it as v1.

---

## File Location

Two lockfile instances exist, sharing the same schema:

### Per-project lockfile (existing)

`.library.lock` is placed at the repository root:

```
<project-root>/
├── .library.lock       ← per-project lockfile (committed to git)
├── library.yaml
├── .agents/
│   └── skills/
└── ...
```

`.library.lock` must be **committed to git** so all collaborators share the same install
manifest. It should NOT be gitignored.

### Global lockfile (new — ADR-0003)

`~/.config/library/global.lock` records globally installed items (installed with
`/library <primitive> use <name> --global`) and every MCP registration:

```
~/.config/library/
└── global.lock         ← global lockfile (NOT git-tracked; user-local only)
```

The global lockfile uses the same schema as the per-project lockfile. It is NOT committed
to version control — it is a user-local file managed by `library` tooling. The path
`~/.config/library/` follows the XDG Base Directory specification for user configuration.

### Concurrent writers

Both lockfiles are shared mutable state. The global one especially: a bulk
`library agent sync --scope global` and a launcher's self-heal install are two
processes writing one file, and CL-1f36 recorded what that cost — interleaved
YAML, a half-written `install_timestamp` inside another entry's target list, and
24 of 27 sync entries failing with "Invalid YAML".

Two rules make that safe, and both are needed:

1. **Every save is atomic.** The document is serialized in full, written to a
   staged sibling, and renamed over the lockfile. A reader always sees a
   complete document; a writer that dies mid-serialization changes nothing.
2. **Every read-modify-write holds the write guard.** Atomic replacement says
   nothing about the read that decided what to write, so two unguarded writers
   each save a snapshot taken before the other and one install's receipt
   disappears while its content stays on disk. `lib.lockfile.mutate_lockfile`
   loads, yields, and saves inside an advisory `flock` on a `<lockfile>.lock`
   sidecar; `lockfile_transaction` holds the same guard around a critical
   section that manages its own save.

The guard is advisory: it serializes cooperating Library processes and is no
defense against something that writes the lockfile without it. Never call
`save_lockfile` after a bare `load_lockfile` — that pair is exactly the defect.

Workspace mutations take their non-blocking `<lockfile>.workspace-lock` guard
first and the write guard second, always in that order. Both sidecars and the
transient `<lockfile>.*.staged` file are tool-local and gitignored.

### MCP scope and ownership

`library mcp use <name>` and `library mcp remove <name>` default to global scope.
`--scope global` remains accepted for explicit automation. Project-scoped MCP use and
sync are rejected before any harness configuration or lockfile mutation. Explicit
`library mcp remove <name> --scope project` is a migration-only exception: it removes
only the matching legacy project lock record and never unregisters a harness, stops a
service, or changes global state. This matches the actual ownership boundary: supported
MCP harness registrations are stored in user-global config files, so their authoritative
lock records live in `~/.config/library/global.lock`.

During migration, a provenance-less harness registration may be adopted only when its
complete normalized descriptor exactly matches the catalog's current snippet or one
explicitly declared legacy descriptor. Normalization excludes only `_origin`; extra,
missing, or changed fields and entries with foreign provenance are never overwritten.
Lower-level MCP install and removal functions reject project scope. Removing a stale
historical MCP record from a project lockfile must use the explicit lock-only CLI path,
because ordinary MCP removal also unregisters the global service.

---

## Schema v2 Target Format

The file remains YAML and uses the same project and global locations. Schema v2
separates user intent from materialized state:

```yaml
schema_version: 2
migration:
  prune_ack_required: false

requested_roots:
  - id: workspace:python-cli
    type: workspace
    name: python-cli
    scope: project
    catalog_identity: https://example.invalid/cognovis-catalog
    constraint: ">=1.0.0,<2.0.0"
    resolved_version: 1.0.0
    definition_commit: 0123456789abcdef

receipts:
  - id: skill:python-dev@1.0.0
    type: skill
    name: python-dev
    scope: project
    catalog_identity: https://example.invalid/cognovis-catalog
    source: https://example.invalid/cognovis-catalog/skills/python-dev/SKILL.md
    source_commit: fedcba9876543210
    resolved_version: 1.0.0
    cache_path: /Users/example/.local/share/library/skills/cognovis-core/python-dev@fedcba98/
    install_timestamp: 2026-08-05T10:00:00Z
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

### v2 requested root fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | YES | Stable root identity unique within the selected lock scope. |
| `type` | YES | Any directly requestable artifact primitive type or `workspace`. Package is not a Library root type. |
| `name` | YES | Catalog name of the requested primitive. |
| `scope` | YES | `project` or `global`; every resolved member must use the same scope. |
| `catalog_identity` | YES | Stable identity of the catalog that supplied the root. |
| `constraint` | Optional | User-requested compatible version range or pin. |
| `resolved_version` | YES | Version selected by the last complete resolution. |
| `definition_commit` | YES | Exact catalog or definition pin used for that resolution. |
| `catalogs` | Workspace roots registered from a schema v2 manifest | The identity, pin kind, and pin value of every catalog the manifest declared **at registration**. A later resolution that finds a different pin fails naming both values; a changed pin is never silently adopted. Absent on v1 roots and on roots registered before this field existed, which are compared against nothing rather than against an invented baseline. |

Direct artifact primitives and Workspaces use the same root model. Transitive
artifact dependencies are graph nodes, not implicit direct roots.

One lock scope may contain several Workspace requested roots. Their effective
closure is an unordered union with all direct artifact roots. Workspace schema
v1 rejects cross-catalog manifest roots, so a v1 consumer composes across
catalogs by registering several Workspaces at the scope boundary; schema v2
admits cross-catalog roots inside one manifest, qualified by an alias from its
pinned `catalogs:` block. Nested Workspace roots are rejected by both versions.
Every resolved node records canonical catalog identity and the pin of the
catalog it resolved from, regardless of the operator's display alias.

### v2 prerequisite assertion fields

`prerequisites` records intrinsically global dependencies reached from project
roots. Each entry names its global identity, compatible constraint, and requesting
roots. It is reproducibility and status evidence only: it has no project targets,
never becomes a project receipt, and creates no project ownership edge.

### v2 receipt fields

| Field | Required | Description |
|-------|----------|-------------|
| `id`, `type`, `name`, `scope` | YES | Identity of one materialized primitive in one lock scope. |
| `catalog_identity` | YES | Catalog provenance used for collision, adoption, and prune safety. |
| `source`, `source_commit`, `resolved_version` | YES | Exact resolved source identity. |
| `cache_path` | When cached | Layer-B cache location; retained for rollback and cache GC. |
| `install_timestamp` | YES | UTC completion time for the verified materialization. |
| `verified` | YES | Whether every recorded target has install-time proof. Unverified receipts are never pruneable. |
| `adopted` | YES | Whether an exact pre-existing target was explicitly adopted. |
| `prune_blocked_reason` | YES, nullable | Drift, migration, foreign manager, or another reason deletion is blocked. |
| `targets` | YES | Exact file, directory, or symlink inventory created or adopted for this receipt. |
| `targets[].content_sha256` | Every file | Per-file install-time digest. Aggregate directory hashes may supplement but not replace it. |
| `targets[].link_target` | Every symlink | Literal `readlink` value recorded immediately after install. |
| `owners_cache` | Optional | Derived explanation only. Never resolver input for later pruning. |

### v2 receipt fields for foreign-sourced content

> Added by [ADR-0011](adr/heterogeneous-marketplace-workspaces.md) (`CL-2p73`,
> 2026-08-08). Additive: absent fields read as `unknown`, and a receipt without
> them remains valid and prune-blocked until it is re-materialized.

| Field | Required | Description |
|-------|----------|-------------|
| `provider_identity` | For foreign content | Canonical provider identity from the ADR-0011 provider contract; not the operator's display alias |
| `upstream_id` | For foreign content | Provider-native item identity, opaque to the Library |
| `upstream_name` | For foreign content | Preserved verbatim from upstream; never a rename |
| `collection_membership` | For foreign content | Ordered upstream grouping (repository category, prompt-kit ID); may be empty |
| `upstream_revision` | YES, nullable | `null` marks a revisionless provider whose pin is trust-on-first-use |
| `normalized_content_digest` | YES | Library-computed digest over normalized content bytes. The authoritative integrity proof; a provider-native proof is supplementary evidence only |
| `transformation_version` | YES | Identity of the projection rule applied to produce installed bytes. Part of the cache key, so a rule change produces a new cache object rather than rewriting one |
| `rights` | For foreign content | Four independent grants — `fetch_authorization`, `install_rights`, `redistribution_rights`, `derivative_rights` — each `granted`/`denied`/`unknown` with a named `evidence` source |
| `executable_admission` | YES | `inert`, `admitted`, `pending`, or `refused`. Bound to `projected_content_digest` — the bytes actually installed — because a transformation that rewrites content produces bytes no reviewer saw. Any digest change returns it to `pending`. Corrected by `CL-y5z4`; the field previously named `normalized_content_digest`, which is the upstream identity and the trust-on-first-use pin subject |
| `projection_eligibility` | YES | Per target class: `machine_local` and `project_committed`, each `allowed`, `opt-in`, or `blocked`. `unknown` redistribution rights bind `project_committed` to `blocked` |
| `upstream_state` | YES | `present` or `upstream-vanished`. A durable, queryable state entered when a reachable and complete provider no longer lists a previously installed item. Never converted into deletion authority |
| `provider_availability` | YES | Last observed provider state with its observation timestamp. Freshness is reported as `unknown` when the provider is unreachable; never as current |

Three further fields are added by the slice-3 implementation (`CL-y5z4`), for
the same reason as the rest: each answers a question that was otherwise
answerable only by guessing.

| Field | Required | Description |
|-------|----------|-------------|
| `projected_content_digest` | For foreign content | Digest of the bytes actually stored and installed, after the transformation. `normalized_content_digest` remains the upstream identity and the trust-on-first-use pin subject; this is what an executable-admission decision and a target inventory are about. Under the identity transformation the two are equal |
| `planned_targets` | For foreign content | Target paths this receipt declared **before** its projection was activated. A failure between activation and finalization therefore leaves an intent on record instead of an installed target that no receipt describes |
| `completeness_evidence` | For foreign content | How the retrieval's completeness was established: `member-manifest`, `pinned-digest`, or `adapter-declaration`. The last is the honest name for "nothing but the adapter's contract", recorded so an operator can query which installs rest on it |

### Where foreign receipts live (fold decision, `CL-dbam`)

`CL-y5z4` made foreign receipts durable in their own JSON document and left one
decision to the Workspace slice: fold them into `.library.lock` v2. The fold is
**a relocation to the lock scope, not an inlining into the lock body.**

- **What moved.** The store is now addressed through its lock scope:
  `workspace_receipt_store(<lock path>)` reads and writes
  `<lock path>.foreign-receipts.json`. "Which foreign receipts belong to this
  scope" is answerable from the lock path alone, with no scan and no second
  configuration entry. No record was translated: the fields already are the ones
  documented above, which is what the previous slice chose them for.
- **What deliberately did not move.** The records are not serialized inside the
  YAML lock body. Doing that would route them through `save_lockfile` and
  through `apply_post_prune_lock`'s list filtering, and each of those drops one
  of the three properties the store exists to hold:

  | Invariant | What inlining would lose |
  |---|---|
  | The whole load-modify-save is one cross-process transaction | The lock body's writers do not hold the receipt store's lock; two writers would each save a snapshot taken before the other, and an installed artifact would lose the only record describing it |
  | `planned_targets` are durable **before** a projection is activated | A pre-activation write would have to commit the whole lock body, which is a much larger transaction than the intent it records |
  | Retirement is reachable only through `remove_named_receipt` | `lock["receipts"]` is a plain list that existing code filters directly; a retirement would become a list comprehension, and a projection could be left installed with no receipt |

- **What unblocks the container move.** Inlining becomes correct once the lock
  write path itself carries all three properties. That is CLI-wiring work and
  belongs with `CL-mvet`; until then the relocation gives the scope binding
  without weakening the guarantees.
- **No new receipt scope.** `retention.REQUIRED_SCOPES` stays `("project",
  "global")`. Scope isolation means a cross-catalog Workspace reconciles exactly
  one existing lock scope, so a third "workspace" scope would have no distinct
  location — and the reference index refuses two scopes reading one location,
  because a label standing in for another scope's location hides every receipt
  that scope holds.

Rules that bind these fields:

- **No projection is activated before its cache object and receipt are complete.**
  An unreceipted materialized projection is unreproducible and is a defect
  regardless of who authored the content.
- **A verified cache object plus a blocked committed projection is a normal
  state**, not a contradiction: `cache_state` and `projection_eligibility` are
  independent axes.
- **Credentials never appear here.** A receipt carries only artifact bytes'
  digests and non-secret provenance. Credential *references* live in provider
  configuration.
- **`upstream-vanished` receipts protect their cache objects.** Automatic garbage
  collection fails closed for an unreferenced foreign object while its provider is
  unavailable, access is revoked, or the upstream item no longer exists. Only an
  operator-explicit purge, requiring an object digest and an acknowledgement of
  permanent loss, may delete it.
- **Explicit named removal remains available under every degraded-inventory
  condition.** It records the degraded state and operator intent in receipt
  history, is never triggered by ownership-derived prune, and never implicitly
  deletes the underlying cache object.

Project locks persist project-owned `install_target`, bridge link paths, and
`targets[].path` values relative to the directory containing `.library.lock`.
Status, verification, removal, adoption, and reconciliation resolve them against
the selected project root. This is a serialization boundary: the in-memory
operation may use absolute paths, Layer-B `cache_path` values remain absolute,
and global-lock targets remain absolute.

Library-created v2 harness bridges within one scope use normalized relative
targets computed from the bridge parent to the canonical target. For example,
the literal target from `.claude/skills/python-dev` to
`.agents/skills/python-dev` is `../../.agents/skills/python-dev`. Verification
compares the exact recorded `readlink` value; it does not normalize a different
absolute or relative spelling into a match.

In each `bridge_symlinks` string, the left side is a lock-root-relative bridge
path and the right side is the literal symlink payload interpreted relative to
that bridge's parent directory. The two sides therefore use different relative
bases by design.

A directory target is only a container marker. Prune removes its individually
recorded files and links, then removes the directory only when empty. Any
unrecorded nested entry is drift and makes the receipt prune-blocked; recursive
deletion of a recorded directory is forbidden.

The authoritative owner set is recomputed from every requested root against a
fresh, complete, catalog-pinned dependency graph. Persisted owners and edges are
only an audit cache. Conflicting constraints for one materialization abort the
operation before mutation.

### v1 to v2 migration

Migration is conservative and one-way unless a backup is restored:

1. Every v1 `installed:` entry becomes its own direct requested root.
2. Its known install fields become a receipt and target inventory where possible.
3. The receipt is marked `verified: false` and prune-blocked until
   `workspace sync --verify-receipts` records per-file digests and exact link
   targets.
4. `migration.prune_ack_required` is set. Additive Workspace operations remain
   allowed, but pruning is blocked until `workspace sync --verify-receipts`
   re-installs every selected-scope direct root from its catalog source and
   records exact current targets. The guard clears only when no unverified
   receipt remains in that scope.
5. Migration never attributes an old entry to a Workspace, even when the current
   Workspace closure contains the same primitive.
6. `workspace adopt <workspace> --from-direct --all-reachable` previews a
   lock-only bulk demotion for migrated direct roots reached by that Workspace.
   Applying the acknowledged plan removes only requested-root records and never
   touches files.

Unknown state is retained. It is never converted into deletion authority.

### v2 write, recovery, and prune ordering

The selected lock scope has one write mutex. Reconciliation resolves the entire
root set before mutation, journals verified additions and updates per artifact,
and aborts all pruning on any incomplete catalog, conflict, addition, or update.
For an approved prune, the complete deletion manifest and retired receipts are
durably journaled before the intended post-prune lock state is written
atomically. Only then are exact recorded targets deleted. A crash may therefore
leave a physical orphan recoverable from the journal but must never leave a
receipt claiming a deleted file. Resume replays completed receipt operations
into a consistent lock view before fresh re-resolution.

Workspace deletion additionally requires `--prune --apply`. Drifted,
unverified, foreign, ambiguous, project-authored, or externally managed targets
remain untouched and are surfaced by Workspace status.

The prune preflight enforces ADR-0010 Decision 8 condition 2 directly: a
candidate whose catalog identity, resolved version, or source pin is unknown is
refused immediately before deletion, re-derived from the candidate rather than
trusted from the plan that produced it. A prune plan that records no resolved
catalog closure is refused outright, because a plan carrying no ownership
evidence must not be read as one whose owners are all registered.

If journal replay encounters drift, `library workspace recover --scope <scope>`
reports the journal digest and makes no further changes. An operator may repair
the drift and retry, or explicitly discard only that journal with
`--discard --acknowledge-plan <journal-digest>`. Discarding never deletes the
remaining filesystem content; it becomes untracked project-owned residue.

## Legacy v1 Format

The remainder of this format section documents the released v1 implementation.
It is retained for migration and current operator compatibility; it is not the
target shape for new Workspace code.

The file is YAML. The top-level key is `installed`, containing an ordered list of entries.

### Minimal example

```yaml
installed:
  - name: dolt
    type: skill
    catalog_identity: https://github.com/cognovis/library
    marketplace: cognovis-core
    source: https://github.com/cognovis/library-core/blob/main/skills/dolt/SKILL.md
    source_commit: abc123def456abc123def456abc123def456abc123def456abc123def456ab12
    cache_path: /Users/malte/.local/share/library/skills/cognovis-core/dolt@abc123def456ab/
    install_target: .agents/skills/dolt/
    install_timestamp: 2026-04-30T10:23:00Z
    checksum_sha256: 9483a0941234567890abcdef1234567890abcdef1234567890abcdef12345678
    content_sha256: 9483a0941234567890abcdef1234567890abcdef1234567890abcdef12345678
    install_mode: vendor
    license: MIT
    bridge_symlinks:
      - .claude/skills/dolt -> .agents/skills/dolt
```

### Symlink opt-in example (developer mode)

```yaml
installed:
  - name: dolt
    type: skill
    catalog_identity: https://github.com/cognovis/library
    marketplace: cognovis-core
    source: https://github.com/cognovis/library-core/blob/main/skills/dolt/SKILL.md
    source_commit: abc123def456abc123def456abc123def456abc123def456abc123def456ab12
    cache_path: /Users/malte/.local/share/library/skills/cognovis-core/dolt@abc123def456ab/
    install_target: .agents/skills/dolt/
    install_timestamp: 2026-04-30T10:23:00Z
    checksum_sha256: 9483a0941234567890abcdef1234567890abcdef1234567890abcdef12345678
    content_sha256: 9483a0941234567890abcdef1234567890abcdef1234567890abcdef12345678
    install_mode: symlink
    license: MIT
    bridge_symlinks:
      - .claude/skills/dolt -> /Users/malte/.local/share/library/skills/cognovis-core/dolt@abc123def456ab/
```

The `bridge_symlinks` list records every symlink created during a dual-install. See
`docs/policy/name-collision.md` (Decision 2) for the canonical/bridge model.

### Three-Layer model (Source → Cache → Harness)

Per ADR-0003, skill deployment passes through three layers:

```
Layer A — Source:  https://github.com/cognovis/library-core/...  (canonical git repo)
Layer B — Cache:   ~/.local/share/library/skills/<marketplace>/<name>@<commit>/
Layer C — Harness: ~/.agents/skills/<name>/  or  .agents/skills/<name>/
```

The lockfile records Layer A (`source`, `source_commit`) and Layer B (`cache_path`).
Layer C is recorded as `install_target`. The harness directory at Layer C is a
**vendored copy** by default so consumer projects can commit real files. The
Layer-B cache is a per-machine resolver source, not a runtime path. `--symlink`
keeps Layer C as a symlink into the Layer-B cache for local development.

**Global install example (ADR-0003):**

```yaml
installed:
  - name: agent-forge
    type: skill
    marketplace: cognovis-core
    source: https://github.com/cognovis/library-core/blob/9b1e72c98f3e21/.claude/skills/agent-forge/SKILL.md
    source_commit: 9b1e72c98f3e21abc00000000000000000000000000000000000000000000000
    cache_path: /Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/
    install_target: /Users/malte/.agents/skills/agent-forge/
    install_timestamp: 2026-05-12T07:30:00Z
    checksum_sha256: 9483a09400000000000000000000000000000000000000000000000000000000
    content_sha256: 9483a09400000000000000000000000000000000000000000000000000000000
    install_mode: vendor
    license: MIT
    bridge_symlinks:
      - /Users/malte/.claude/skills/agent-forge -> /Users/malte/.agents/skills/agent-forge/
```

**Project-scoped install example (ADR-0003):**

```yaml
installed:
  - name: agent-forge
    type: skill
    marketplace: cognovis-core
    source: https://github.com/cognovis/library-core/blob/9b1e72c98f3e21/.claude/skills/agent-forge/SKILL.md
    source_commit: 9b1e72c98f3e21abc00000000000000000000000000000000000000000000000
    cache_path: /Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/
    install_target: .agents/skills/agent-forge/
    install_timestamp: 2026-05-12T07:30:00Z
    checksum_sha256: 9483a09400000000000000000000000000000000000000000000000000000000
    content_sha256: 9483a09400000000000000000000000000000000000000000000000000000000
    install_mode: vendor
    license: MIT
    bridge_symlinks:
      - .claude/skills/agent-forge -> .agents/skills/agent-forge/
```

---

## Field Reference

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | YES | string | Unique item name. Must match the catalog entry in `library.yaml`. |
| `type` | YES | string | Registered primitive type, including project-native `pi-extension`, `pi-profile`, and `just-module` bridge entries. |
| `catalog_identity` | New entries | string | Stable identity of the catalog that produced the install, normally its canonical repository URL. Entries created before this field existed remain valid and audit as `undetermined`. |
| `marketplace` | YES | string | Name of the source marketplace from `library.yaml` `sources.marketplaces`. Legacy v1 entries may contain `local`; new catalog installs use a registered remote marketplace identity. |
| `source` | YES | string | Published HTTPS Git source used for the install. A migrated v1 entry may retain a historical local path until it is verified and refreshed; committed catalog definitions may not create new local-source entries. |
| `source_commit` | YES | string | Git commit SHA of the source repo at install time. Historical non-git entries may contain `local` and remain migration-protected. |
| `cache_path` | YES | string | Absolute Layer-B cache path (`~/.local/share/library/skills/<marketplace>/<name>@<first-14-hex-chars-of-source_commit>/`). Empty string `""` for migrated entries pending next sync. |
| `install_target` | YES | string | Relative (project) or absolute (global) path of the install directory (trailing slash required). |
| `install_timestamp` | YES | string | ISO 8601 UTC datetime of the install or last refresh. |
| `checksum_sha256` | YES | string | Backward-compatible SHA-256 hex digest (64 chars). New entries compute it from the local installed content. |
| `checksum_type` | NO | string | `file` (default) or `directory`. Skills and standards use `directory`; agents and prompts use `file`. Entries without this field are treated as unknown by `library audit`. |
| `content_sha256` | NO | string | Explicit SHA-256 of the local installed content at `install_target`. New vendor-mode entries set this and `checksum_sha256` to the same value. |
| `install_mode` | NO | string | `vendor` (default, real copied files) or `symlink` (explicit opt-in pointing Layer C at Layer B). If omitted, `/library sync` writes `vendor` on the next refresh. |
| `license` | NO | string | SPDX license identifier (e.g. `MIT`, `Apache-2.0`). Default: `unknown`. |
| `bridge_symlinks` | NO | array | List of symlink strings created for dual-install. Format: `<link-path> -> <target-path>`. Default: `[]`. |

The JSON Schema for this format lives at `docs/schema/lockfile.schema.json`.

---

## Checksum Computation

The `checksum_sha256` field and `checksum_type` field together specify how the digest is computed.

### Directory hash (`checksum_type: directory`)

Skills and standards use a Merkle-style directory hash over **all files** in the local installed directory:

| Item type | Checksum scope |
|-----------|----------------|
| `skill` | All files in `<install_target>/` (sorted, recursive) |
| `standard` | All files in `<install_target>/` (sorted, recursive) |

The hash is computed by `scripts/lib/lockfile.py:compute_directory_hash()`:

1. Walk all files under the directory, sorted by relative path.
2. For each file, feed the relative path string + NUL separator + SHA-256 of the file contents + NUL separator into an outer SHA-256 digest.
3. Return the final 64-character hex digest.

This means any file edit, addition, or deletion inside the vendored project copy is detected as drift.

### File hash (`checksum_type: file`)

Agents and prompts use a single-file hash over the primary artifact:

| Item type | Primary artifact |
|-----------|-----------------|
| `agent` | `<install_target>/<name>.md` |
| `prompt` | `<install_target>/<name>.md` |

Compute with:

```bash
# macOS
shasum -a 256 <primary_artifact_path> | awk '{print $1}'

# Linux
sha256sum <primary_artifact_path> | awk '{print $1}'
```

### Entries without `checksum_type`

Entries without this field are not auditable with a known strategy. `/library audit`
reports them as `unknown` — it does not report them as drifted. Run `/library <primitive> use <name>`
to refresh the entry and write `checksum_type`.

`/library audit` recomputes the checksum (using the strategy from `checksum_type`) and compares
it to the stored value to detect drift. A mismatch means the installed files were modified after
the lock record was written.

---

## Lockfile Lifecycle

### Schema v2 Workspace lifecycle

- `library workspace list`, `show`, and `validate` provide discovery and the
  marketplace-CI validation entrypoint. `use --dry-run` plans an unregistered
  Workspace and reports collisions without mutation.
- `library workspace use <catalog>:<name>` registers an idempotent requested root
  and applies additions and updates only. Bare names are accepted only for one
  configured candidate; the lock records canonical catalog identity.
- `library workspace status` resolves all roots in the selected scope and emits
  the registered Workspace-root inventory plus a read-only plan with ownership
  reasons, drift, conflicts, adoption candidates, missing global prerequisites,
  and prune candidates. Exit 2 means changes are pending, while exit 3 means
  protected or blocked findings.
- `library workspace explain <type>:<name>` reports the recomputed direct-root
  owner set reaching one receipt. Schema v1 does not persist full dependency
  paths, so the command does not claim an intermediate-edge trace.
- `library workspace sync` refreshes additions and updates but does not prune by
  default. `--verify-receipts` is the named verifying reinstall for migrated
  receipts. `--prune` without `--apply` previews deletion. Physical deletion
  requires `--prune --apply` after a complete plan.
- `library workspace adopt <workspace> <type>:<name> --definition-commit <pin>`
  records one exact-match existing member as adopted without creating a direct
  root.
- `library workspace adopt <workspace> --from-direct
  [<type>:<name>|--all-reachable]` previews and applies direct-root demotion. It
  changes lock intent only and never deletes files.
- `library workspace remove` unregisters the root and reports the resulting plan;
  it does not delete targets by itself and prints
  both the selected-scope prune preview and digest-bound apply commands.
- Workspace selectors limit additions and updates. Prune always evaluates the
  complete requested-root set in the selected lock scope, and `--all --prune`
  remains valid when zero Workspaces are registered.
- General `library sync` remains conservative and non-pruning while reading and
  refreshing schema v2 receipts.

Global-only primitive types such as MCP and catalog entries declared with
`default_scope: global` are prerequisite assertions when reached from a project
root. They are checked against the global lock before project mutation and
recorded as non-owning project-lock assertions, but never become project receipts
or project ownership edges.

Ownership-derived prune requires a verified, clean receipt. Explicit named
primitive removal is separate user consent, but uses the same exact-target,
manager-aware, journaled transaction whenever a v2 receipt exists. Remaining
Workspace owners retain the files; ownerless verified targets are removed;
unverified, drifted, foreign-managed, or unrecorded content blocks physical
deletion. An unverified direct receipt whose supplying catalog no longer lists
the entry may be unregistered by an explicit named remove, but every recorded
path is retained. Legacy targetless records retain their primitive-specific
compatibility handler only after the same fresh Workspace-ownership check.

The complete safety and recovery protocol is normative in ADR-0010.

### Legacy v1 lifecycle

### `/library <primitive> use` writes/updates an entry

After a successful install, write or update the entry:

1. If an entry for `name` already exists (refresh): update all fields in place.
2. If no entry exists: append a new entry.
3. Write the updated `installed` list back to `.library.lock`.
4. Compute checksum immediately after copying to `install_target`: use `directory` hash for skills/standards, `file` hash for agents/prompts. Write `checksum_type`, `content_sha256`, and `install_mode` accordingly.

See `cookbook/use.md` Step 9 for the full procedure.

### `/library <primitive> remove` removes an entry

After deleting the installed files:

1. Remove the entry matching `name` from the `installed` list.
2. Write the updated list back to `.library.lock`.
3. If `bridge_symlinks` is non-empty, verify all listed symlinks were also removed.

See `cookbook/remove.md` Step 5 for the full procedure.

### `/library sync` uses the lockfile as source of truth

Instead of reading `library.yaml` to discover what to sync, `/library sync` reads
`.library.lock` directly. The top-level `sync` command (no primitive prefix) iterates
all entries across all primitives:

1. For each entry in `installed`, compare `source_commit` against the remote HEAD via `git ls-remote`.
2. Skip entries that are already current (unless `--force` is passed).
3. Re-fetch and re-install only entries that are behind or cannot be verified.
4. Re-checksum after fetching using the appropriate `checksum_type` strategy.
5. Update `install_timestamp` and `source_commit` to the new HEAD.

Use `--dry-run` to print the planned skip vs. refresh decisions without performing any writes.

This guarantees that two clones with the same `.library.lock` end up with identical
installed content. See `cookbook/sync.md` for the full procedure.

### `/library audit` detects drift

For each entry in `installed`:

1. Inspect `checksum_type` to determine the audit strategy.
2. For `directory` entries: recompute the Merkle-style directory hash over `cache_path`.
3. For `file` entries: recompute the SHA-256 of the primary artifact.
4. For entries without `checksum_type`: report `unknown` — do not report as drift.
5. Compare against `checksum_sha256`. Report `clean`, `drift`, or `unknown` per entry.
6. Compare `catalog_identity` with the audited catalog. A matching identity whose
   catalog no longer lists the entry is `orphaned` and includes the exact
   `library {primitive} remove {name} --scope {scope}` command. A different
   identity is `foreign` and is not reported as orphaned. A legacy entry without
   identity is informationally `undetermined` and is never accused of being orphaned.

Use `--drift-only` to filter output to only drifted entries and exit with code 2.
The top-level `audit` command (no primitive prefix) checks all primitives in one pass.

See `cookbook/audit.md` for the full procedure.

### `/library status` checks upstream without cloning

For each entry in `installed`:

1. Extract the `source` URL and `source_commit` from the lockfile.
2. Call `git ls-remote <clone_url> HEAD` (or the pinned branch) — no clone.
3. Compare the returned SHA against `source_commit`.
4. Report `current`, `behind`, or `unknown` (for local sources or network failures).

The `overall` field in the JSON result is `behind` if any entry is behind, otherwise
`current` or `unknown`. Exit code is 0 in all cases (status is informational only).

---

## Example: Full Lockfile

```yaml
installed:
  - name: researcher
    type: skill
    catalog_identity: https://github.com/cognovis/library
    marketplace: disler
    source: https://github.com/disler/claude-code-hooks-mastery/blob/main/.claude/skills/researcher/SKILL.md
    source_commit: deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
    cache_path: /Users/malte/.local/share/library/skills/disler/researcher@deadbeef/
    install_target: .claude/skills/researcher/
    install_timestamp: 2026-04-30T09:00:00Z
    checksum_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    checksum_type: directory
    license: MIT
    bridge_symlinks:
      - .agents/skills/researcher -> /Users/malte/.local/share/library/skills/disler/researcher@deadbeef/

  - name: dolt
    type: skill
    catalog_identity: https://github.com/cognovis/library
    marketplace: local
    source: /Users/malte/code/cognovis-library-core/skills/dolt/SKILL.md
    source_commit: local
    cache_path: ""
    install_target: .claude/skills/dolt/
    install_timestamp: 2026-04-30T10:23:00Z
    checksum_sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    license: proprietary
    bridge_symlinks: []
```

---

## Cross-References

- `docs/adr/workspace-desired-state-reconciliation.md` (ADR-0010) — universal ownership, Workspace commands, prune safety, and recovery ordering.
- `docs/schema/workspace.schema.json` — target Workspace manifest schema (`CL-r7n6`).
- `docs/schema/lockfile.schema.json` — JSON Schema for machine validation (`checksum_type` field, expanded `type` enum).
- `docs/adr/three-layer-cache-architecture.md` (ADR-0003) — Three-layer deployment model that introduced `marketplace` and `cache_path`.
- `docs/policy/name-collision.md` — Canonical/bridge model for `bridge_symlinks`.
- `scripts/lib/lockfile.py` — `compute_directory_hash()` for Merkle-style directory checksums; `make_entry()` for lockfile entry construction.
- `scripts/lib/status.py` — `cmd_status_impl()` upstream SHA check via `git ls-remote`.
- `scripts/lib/sync_audit.py` — `cmd_audit_impl()` drift detection logic; `reinstall_entry()` for sync.
- `cookbook/use.md` — How `/library <primitive> use` writes lockfile entries (including cache materialization).
- `cookbook/remove.md` — How `/library <primitive> remove` removes lockfile entries (including GC hints).
- `cookbook/sync.md` — How `/library sync` uses the lockfile as source of truth (including cache reconciliation).
- `cookbook/audit.md` — How `/library audit` detects drift (including symlink target verification).
- `scripts/migrate-lockfile.py` — Migration script to add `marketplace` and `cache_path` to existing lockfiles.
