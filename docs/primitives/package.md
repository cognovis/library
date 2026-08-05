# Package (retired Library concept)

> Historical vocabulary note. The Library CLI and catalog schema never shipped
> Package as a requestable primitive. ADR-0004 rejected the equivalent generic
> `bundle` type, and ADR-0010 keeps that decision.

External npm, PyPI, Pi, and harness packages remain valid distribution formats.
They are not Library primitive types and do not appear as lockfile requested
roots.

The Library uses two explicit graph relationships instead:

| Need | Use |
|------|-----|
| One primitive cannot work without another | Declare the dependency in the entrypoint primitive's `requires:` metadata. The complete closure installs transactionally. |
| Independently useful capabilities should form a reusable desired-state baseline | Create a [Workspace](workspace.md). Several Workspaces may be registered in one scope and may reference each other. |

Examples:

- A Skill that requires a companion Hook declares `hook:<name>` in `requires:`.
- A Bead execution entrypoint declares its required Agents, Scripts, Standards,
  and runtime profiles through its dependency graph.
- `python-cli` groups `python-dev` and `python-test` as independently meaningful
  capabilities in a Workspace.

Do not create an empty sentinel primitive merely to simulate a package. Use a
real entrypoint when one primitive owns the capability; use a Workspace when the
selection itself has a lifecycle.

---
