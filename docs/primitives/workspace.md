# Workspace

> Primitive contract established by
> [ADR-0010](../adr/workspace-desired-state-reconciliation.md).

> **Implementation status:** implemented by `CL-r7n6`. The first published
> Workspace definition is tracked by marketplace bead `clc-tzn5`.

**Definition.** A versioned, metadata-only Library desired-state root that names
a reusable set of typed roots contributing to one project or the user-global
lobby. A scope may register several Workspaces.

**Key constitutive feature.** Ownership-aware reconciliation. A Workspace does
not merely install a collection; it lets the Library resolve the complete root
set, preserve receipts still reachable from another root, and identify clean
ownerless Library receipts as explicit prune candidates.

**Category.** Workspace is first-class in the Library catalog and CLI, but it is
not an artifact primitive. Its manifest is consumed by the Library platform and
is never copied into a harness directory.

**Trigger semantics.** A Workspace is not invoked by a model. A user or
automation manages it through:

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
library workspace recover --scope project|global [--json]
library workspace recover --scope project|global --discard --acknowledge-plan <journal-digest> [--json]
library workspace adopt <catalog>:<workspace> <type>:<name> --definition-commit <pin> --scope project|global [--json]
library workspace adopt <catalog>:<workspace> --from-direct [<type>:<name>|--all-reachable] --scope project|global [--apply --acknowledge-plan <digest>] [--json]
library workspace remove <catalog>:<name> --scope project|global [--json]
```

Every operational command supports `--json`. `list`, `show`, `validate`, and
`use --dry-run` let an operator discover and preview a Workspace before
registration. `use` and ordinary `sync` are additive. Filesystem `adopt` records
one exact pinned member whose existing targets all match. `adopt --from-direct`
previews and applies a lock-only ownership transfer for one or every reachable
direct root; it never deletes files. `remove` unregisters the root and shows the
plan. Only `sync --prune --apply` may delete verified, clean, ownerless Library
receipts after a complete selected-scope resolution. The prune form remains valid
after the final Workspace root is removed.

Operator identity is `<catalog>:<name>`. A bare name is accepted only when one
configured catalog candidate exists; ambiguity reports every candidate. The
catalog registry maps display names to canonical identities, and locks use the
canonical identity for resolution and ownership. Status exits 0 when converged,
2 for applicable changes, 3 for blocked or protected findings, and 1 when the
operation itself fails. Human and JSON status output both inventory the
registered Workspace roots in the selected scope before reporting their resolved
members, prerequisites, and reconciliation plan.

Workspace commands keep the current repository as the project target, but the
repository's own `library.yaml` must not hide a Workspace published through the
Library tool's consolidated catalog. The resolver first uses the current catalog
when it can resolve every selected Workspace. Otherwise it falls back to the tool
catalog only when that catalog resolves the complete selected Workspace set.
Primitive commands continue to use the current repository catalog. This permits
a catalog repository such as `cognovis-pi` to consume `library-authoring` without
copying platform definitions into its own catalog or adding a machine-local
source path.

**Manifest.** Versioned identity, description, and 2-10 typed artifact roots
with optional version constraints. A manifest references Skills, Standards,
Agents, Workflows, and other artifact primitives from its own canonical catalog
rather than copying their content or inlining routing, context-budget,
state-owner, or harness-runtime schemas. Schema v1 rejects nested Workspace and
cross-catalog roots.

**Schema v2 — cross-catalog roots (implemented by `CL-dbam`; approval final since 2026-08-09).**
[ADR-0011](../adr/heterogeneous-marketplace-workspaces.md) defines schema v2, in
which a manifest may declare a pinned `catalogs:` block of alias-to-identity
mappings and each root may carry a `catalog:` alias qualifier. Rules: the
`catalogs:` block is the only place a Workspace may name a source, a root may
never carry a URL, every declared catalog carries a `pin`, an unqualified root
resolves from the Workspace's own steward catalog, and alias-to-identity mapping
is manifest-local while locks and diagnostics use canonical identity throughout.
v1 manifests remain valid and unchanged; a `catalog:` qualifier in a v1 manifest
is a validation error.

A pin is a typed mapping, not a bare string:

```yaml
catalogs:
  - alias: upstream
    identity: https://example.invalid/upstream
    pin:
      kind: commit            # or inventory-snapshot, for a revisionless source
      value: 4f2c1e9a8b7d6c5e4f3a2b1c0d9e8f7a6b5c4d3e
```

`kind: commit` takes a 40- or 64-character hexadecimal revision;
`kind: inventory-snapshot` takes a 64-character digest over the source's
normalized inventory listing. A branch name in the `value` position is refused:
resolution uses the pin, never a moving reference.

Two resolution rules follow from the block being the whole trust boundary:

- **Every resolved catalog must be declared.** A dependency may not pull the
  closure into a source the manifest does not pin, even one this repository
  registers. The diagnostic names the member and the undeclared identity.
- **Two catalogs supplying one projection target collide.** They do not layer.
  The refusal names both canonical identities and both stewards, before any
  mutation.

Every resolved node records its canonical catalog identity and the pin of the
catalog it came from, regardless of the display alias the manifest used.

**A v2 closure is not produced without pin verification.** Resolving a manifest
that declares catalogs requires a verifier that answers what each declared source
currently serves. There is no default: a resolution that cannot check its pins
does not produce a closure at all, so nothing can report a live, moving member
set as pinned. A source that answers with a different value, with nothing, or
with an error is fail-closed drift naming both values.

The honest residual: a verified pin proves the *source* has not moved. It does
not prove that this repository's catalog document describes that revision,
because members are still read locally until an adapter fetches at the pin. That
is the second half of the same guarantee, it belongs to the provider slice, and
it is why materialization is refused meanwhile.

**Pin drift is never silent.** Registering a v2 Workspace also records the
identity and pin of every catalog it declared. A later resolution that finds a
different pin in the manifest fails naming both values and requires explicit
re-registration. Without this the `catalogs:` block would be reviewable exactly
once.

**A failed resolution names its root, constraint, identity, and steward.** That
includes failures the shared resolver reports in display names — cycles and
ambiguous matches — which are re-raised with the root and its canonical
provenance attached.

**Mutation gate.** A completed cross-catalog resolution reaches the filesystem
only through `gate_workspace_mutation`, which refuses an item the resolution did
not select, an item carrying a selected member's name from a different source, a
duplicate item, an item with no content, and — critically — a selection that
does not cover every resolved artifact. A mutation covers the whole resolved
closure or none of it; a partial selection is the silent skip the
executable-admission gate exists to refuse. The writer receives the exact
immutable content the gate digested; it never sources its own bytes.

**A v2 Workspace resolves, validates, and previews; it does not install yet.**
`library workspace use` refuses to materialize a closure with declared catalogs.
Installing it safely needs the declared pin verified against the source, its
members normalized into inventory items, and the mutation gate in the write
path, which is reference-adapter work. The current installer would instead fetch
each member from the live catalog and ignore the pin entirely — shipping a
`catalogs:` block that looks pinned and is not, which is worse than not
installing.

> **This approval is FINAL as of 2026-08-09.** The ADR-0010 two-consumer evidence
> gate was **amended, not satisfied** — a Human Decision by Malte Sussdorff
> (2026-08-08), finalized 2026-08-09 after implementation slice 1 (`CL-coif`,
> provider core and normalized inventory) delivered all four evidence items
> listed in ADR-0011 `Approval Finalization`, which records the artifacts.

**Nested Workspaces remain deferred.** ADR-0011 admits cross-catalog roots only.
Nested Workspaces change the graph shape itself and keep their original gate:
independent justification plus cycle handling, ownership visibility, and removal
semantics.

**Composition across catalogs stays no-overlay.** ADR-0011 restates the rule
unchanged rather than replacing it. Across a trust boundary an overlay would be a
redirection mechanism, reintroducing at the composition layer exactly what the
pinned `catalogs:` block prevents at the manifest layer.

**Foreign-catalog prune guard.** A catalog is *registered in the resolved
Workspace closure* when either of two things holds:

1. it is the catalog this scope reconciles against, or one of the first-party
   source catalogs that catalog configures — ADR-0010's shipped provenance
   comparison, which is why removing content installed from your own catalog
   keeps working after the last root referencing it is gone; or
2. its canonical identity appears in the pinned `catalogs:` block of a Workspace
   in the selected scope's freshly resolved root set, or is that Workspace's own
   steward — ADR-0011's addition.

A marketplace or provider is deliberately outside (1). Configuring one is not
registration; it becomes registered by being declared with a pin in a v2
manifest, which is the reviewable act the trust boundary rests on.

A receipt whose `catalog_identity` is not registered is a foreign owner and is
never pruned by this scope. When closure registration cannot be determined —
unresolvable catalog, degraded provider, missing identity, or a legacy
`catalog_identity: unknown` — the receipt is treated as foreign. The fail-closed
default is authoritative.

"Unresolvable catalog" means the catalogs themselves could not be read, not that
a member vanished. A registered Workspace whose manifest can no longer be
resolved suspends the whole scope's prune; a stale direct root whose member left
the catalog is reported as a blocker but still registers the catalog it records.

**Prune under a cross-catalog closure fails closed on provider health.** When a
scope's resolved closure reaches a source through a v2 `catalogs:` block, every
such identity needs a conclusive, source-scoped inventory observation before
this scope has deletion authority. Refusals: a missing observation, an
observation of a different source, an unreachable source, a reachable source
that answered incompletely, a "complete" answer that lists nothing, and an
observation older than the caller's declared evidence window. Observations are
supplied as one value carrying the observations, the run's own timestamp, and
that window. Freshness is measured against the real clock, not against a run
time the caller supplies, and evidence dated in the future is refused as well as
evidence that is too old. One refusal fails the scope's whole prune, not only
that source's receipts. Additive work is unaffected: offline operation stays
additive and repair-only.

Under a cross-catalog closure a receipt is prunable only when the source's
complete listing still contains it. A receipt absent from that listing is
`upstream-vanished` — when the local copy is most valuable, and never deletion
authority — and a receipt that records no upstream identity at all cannot be
looked up, which is undeterminable and therefore also not deletable.

**ADR-0010 Decision 8 condition 2 is enforced, not assumed.** A receipt is
prunable only when its catalog identity, resolved version, and source pin are
all known. The check runs in the plan and again in the preflight immediately
before deletion, and a prune plan that records no resolved catalog closure at all
is refused rather than read as "every owner is registered".

**Composition.** A project or global scope may register several Workspaces. The
effective desired state is their unordered set union together with direct roots
and all `requires:` dependencies. Cross-catalog composition uses qualified roots
inside one v2 manifest; composing at the scope boundary with one Workspace per
catalog remains valid and is what v1 consumers do. There are no overlay,
exclusion, precedence, or last-writer-wins semantics: version conflicts, target
collisions, and scope mismatches fail before mutation, whether the collision
arises inside one manifest or between two Workspaces in the same scope.

**Scope.** One Workspace use is either project-scoped or global-scoped, and its
entire closure stays in that scope. A project Workspace cannot own global
artifacts. A global Workspace can define the lobby because every direct global
Library root shares the same global lock.

An intrinsically global dependency such as MCP is a prerequisite assertion when
reached from a project Workspace. The project gains no ownership edge or artifact
receipt, but its lock records the non-owning assertion for reproducibility. Use
and sync fail before mutation until the compatible global root is present.

**Load semantics.** Installed is not the same as loaded. Every member keeps its
own trigger and context behavior. Workspace status groups members by load
semantics so a global lobby can be audited for standing context without forcing
every installed primitive into every prompt.

**Portability.** The manifest is harness-neutral Library metadata. Its resolved
members inherit their individual portability and projection behavior. The
Workspace itself has no Claude Code, Codex, Pi, Cursor, or OpenCode file format.

**When to choose it.** Use a Workspace when a project class or global lobby
needs a reusable, reviewable desired-state baseline and must safely retire
Library-managed content that leaves that baseline. Prefer several orthogonal
Workspaces over combined variants: a FHIR Python repository can use both
`fhir-ig-authoring` and `python-cli`.

Admission requires at least two independently meaningful, standalone-installable
roots and evidence from two committed consumer locks. The default policy caps
project closures at 30 receipts and the global lobby at five direct roots, 15
receipts, no domain or customer content, and one percent standing context.
Deployments may lower these values through top-level `workspace_policy`; the
catalog schema rejects invalid budgets. If a consumer wants "all except one
member," split the Workspace instead of adding an override.

**Counter-examples.**

- Put a strict functional dependency in the entrypoint primitive's `requires:`;
  do not use Workspace membership to repair an incomplete primitive.
- Use a Standard for factual operating context consumed by Skills or Agents.
- Use direct primitive roots for one-off additions that must survive Workspace
  changes independently.
- Keep repository-specific instructions and files project-owned; do not put them
  into a shared Workspace solely to make them removable.
- Keep a one-member alias as a direct root unless the alias has an independent,
  reusable lifecycle meaning.

**Worked examples.**

| Workspace | Scope | Purpose |
|-----------|-------|---------|
| `python-cli` | project | First pilot: shared Python CLI development and test baseline composed from canonical primitives |
| `library-authoring` + `python-cli` | same project | Two directly registered Workspaces in `library/meta`; neither is nested in the other |
| `fhir-ig-authoring` | project | Conditional candidate only if at least two independent roots survive its `requires:` audit |
| `engineering-lobby` | global | Deferred until its member list, bootstrap receipts, collision path, and manager inventory adapter satisfy the lobby gates |

The evidence-backed initial portfolio and repository mapping live in
[ADR-0010](../adr/workspace-desired-state-reconciliation.md) and
[ADR-0011](../adr/heterogeneous-marketplace-workspaces.md).

The term **Library Workspace** should be used when ambiguity is possible. It is
not a Git worktree, filesystem directory, cmux workspace, product runtime
workspace, or harness session.
