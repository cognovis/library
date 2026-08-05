# Workspace

> Primitive contract established by
> [ADR-0010](../adr/workspace-desired-state-reconciliation.md).

**Definition.** A versioned, metadata-only Library desired-state root that names
the typed primitive roots intended for one project or the user-global lobby.

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
library workspace use <name>
library workspace status [<name>|--all]
library workspace sync [<name>|--all]
library workspace sync [<name>|--all] --prune --apply
library workspace sync [<name>|--all] --prune --apply --acknowledge-plan <digest>
library workspace adopt <workspace> <type>:<name> --definition-commit <pin>
library workspace remove <name>
```

`use` and ordinary `sync` are additive. `adopt` records one exact pinned member
whose existing targets all match. `remove` unregisters the root and shows the
plan. Only `sync --prune --apply` may delete verified, clean, ownerless Library
receipts after a complete selected-scope resolution. The prune form remains
valid after the final Workspace root is removed.

**Manifest.** Versioned identity, description, and typed roots with optional
version constraints. A manifest references Skills, Standards, Agents,
Workflows, Packages, and other primitives rather than copying their content or
inlining routing, context-budget, state-owner, or harness-runtime schemas.

**Scope.** One Workspace use is either project-scoped or global-scoped, and its
entire closure stays in that scope. A project Workspace cannot own global
artifacts. A global Workspace can define the lobby because every direct global
Library root shares the same global lock.

An intrinsically global dependency such as MCP is a prerequisite assertion when
reached from a project Workspace. The project gains no ownership edge; use and
sync fail before mutation until the compatible global root is present.

**Load semantics.** Installed is not the same as loaded. Every member keeps its
own trigger and context behavior. Workspace status groups members by load
semantics so a global lobby can be audited for standing context without forcing
every installed primitive into every prompt.

**Portability.** The manifest is harness-neutral Library metadata. Its resolved
members inherit their individual portability and projection behavior. The
Workspace itself has no Claude Code, Codex, Pi, Cursor, or OpenCode file format.

**When to choose it.** Use a Workspace when a project class or global lobby
needs a reusable, reviewable desired-state baseline and must safely retire
Library-managed content that leaves that baseline.

**Counter-examples.**

- Use a Package when cooperating artifacts must ship atomically as content.
- Use a Standard for factual operating context consumed by Skills or Agents.
- Use direct primitive roots for one-off additions that must survive Workspace
  changes independently.
- Keep repository-specific instructions and files project-owned; do not put them
  into a shared Workspace solely to make them removable.

**Worked examples.**

| Workspace | Scope | Purpose |
|-----------|-------|---------|
| `python-cli` | project | Shared Python CLI development, test, routing, and Beads baseline composed from canonical primitives |
| `engineering-lobby` | global | Deliberately small ambient engineering baseline, reconciled only through the global lock |

The term **Library Workspace** should be used when ambiguity is possible. It is
not a Git worktree, filesystem directory, cmux workspace, product runtime
workspace, or harness session.
