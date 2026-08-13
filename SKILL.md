---
name: library
description: Inspect a repository's Library state and recommend explicit project-local Workspaces or primitives before installation.
argument-hint: "<init|status|primitive> [verb] [name-or-query] [options]"
disable-model-invocation: true
---

# The Library

Use this skill only when the user explicitly invokes Library distribution or
asks what Library capabilities a repository should use.

The Library has one normal desired-state scope: the current Git repository.
The global bootstrap is deliberately limited to the `library`, `cld`, and `cdx`
executables, global instruction entrypoints, launcher runtime configuration, and
the OpenBrain MCP singleton. It is not a primitive-installation scope.

## Inspect and recommend

Before recommending an addition, inspect the repository without mutation:

```bash
library status --offline --json
library workspace list --scope project --json
```

Use observable repository facts such as language, package manager, CI files,
tracked harness configuration, and existing `.library.lock` roots. Clearly
separate those facts from recommendations. For each recommendation, state why a
Workspace or direct primitive fits and ask the user to confirm it. Never infer
selection from the retired global lock and never install before confirmation.

## Representative flow

Evidence: `pyproject.toml` and `uv.lock` are present, and `library status
--offline --json` reports no registered Python development Workspace.

Recommendation: add `cognovis-library-core:python-cli`; its declared roots
provide the Python development and test procedures that match those files.

Confirmation: ask, “Should I add `cognovis-library-core:python-cli` to this
repository?” Do not run an installation command until the user explicitly says
yes.

After that confirmation, use the deterministic public command:

```bash
library workspace use cognovis-library-core:python-cli --scope project
```

## Deterministic commands

```bash
# Register exactly the canonical baseline in the current Git worktree.
library init

# Explore before selecting additional desired state.
library workspace list --scope project
library workspace show <catalog>:<workspace> --scope project
library workspace use <catalog>:<workspace> --scope project --dry-run --json

# Install a user-confirmed direct primitive.
library skill use <name> --scope project --dry-run --json
library skill use <name> --scope project

# Inspect repository health without mutation.
library status --offline --json
```

`library init` takes no Workspace selector. It is fixed to `cognovis-base`,
fails before mutation outside an eligible Git root, and fails clearly when the
canonical Workspace is not published in the selected catalog.

`library status` is the read-only health boundary. Its JSON report covers
desired state, projections, managed-Gitignore hygiene, bootstrap prerequisites,
and unmanaged supported-harness content. Exit 0 is healthy, exit 2 signals a
deterministic repair, exit 3 asks for a human decision, and exit 1 indicates a
check failure.

Only Claude Code, Codex, and Pi are supported Library projection targets.
`--scope global` is rejected deterministically in human and JSON output before
catalog, lockfile, filesystem, or installer mutation.
