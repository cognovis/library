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
operation itself fails.

**Manifest.** Versioned identity, description, and 2-10 typed artifact roots
with optional version constraints. A manifest references Skills, Standards,
Agents, Workflows, and other artifact primitives from its own canonical catalog
rather than copying their content or inlining routing, context-budget,
state-owner, or harness-runtime schemas. Schema v1 rejects nested Workspace and
cross-catalog roots.

**Composition.** A project or global scope may register several Workspaces. The
effective desired state is their unordered set union together with direct roots
and all `requires:` dependencies. Cross-catalog composition uses several direct
Workspace registrations at the scope boundary. There are no overlay, exclusion,
precedence, or last-writer-wins semantics: version conflicts, target collisions,
and scope mismatches fail before mutation.

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
roots and evidence from two committed consumer locks. Project closures are capped
at 30 receipts. The global lobby is capped at five direct roots, 15 receipts, no
domain or customer content, and the configured one-percent standing-context
budget. If a consumer wants "all except one member," split the Workspace instead
of adding an override.

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
[Workspace Portfolio Audit](../research/workspace-portfolio-audit.md).

The term **Library Workspace** should be used when ambiguity is possible. It is
not a Git worktree, filesystem directory, cmux workspace, product runtime
workspace, or harness session.
