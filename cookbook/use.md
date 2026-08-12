# Use a Library Primitive

## Purpose

Install or refresh one typed primitive through the deterministic Library engine.
The engine owns catalog lookup, dependency resolution, cache materialization,
harness bridges, and lockfile writes; do not reproduce those steps manually.

## Current procedure

1. Inspect the current primitive help and preview the operation:

   ```bash
   library <primitive> use <name> --help
   library <primitive> use <name> --dry-run --json
   ```

2. Resolve any explicit scope or collision decision reported by the preview.
3. Apply the same operation without `--dry-run`:

   ```bash
   library <primitive> use <name> --json
   ```

4. Inspect `.library.lock` and the reported canonical and bridge targets.

For a successful project-scoped install, Library also reconciles a marked block
in the project `.gitignore`. The block contains the Library lock artifacts and
the repository-relative canonical and bridge targets recorded in the current
project lockfile. Global targets and paths outside the project are never added.
Subsequent `use` and top-level `sync` runs replace this block, so stale managed
entries disappear without changing user-authored ignore rules.

If a managed target is already tracked, the command reports the path and leaves
the Git index unchanged. Review the reported paths, then explicitly remove only
those generated installs from the index while retaining their working-tree
files:

```bash
library <primitive> use <name> --untrack --json
```

Dry runs never change `.gitignore` or the Git index. Global installs do not
manage a project `.gitignore`.

Project scope vendors content into the repository's canonical `.agents/` paths.
Global scope installs into user-global Library roots. Each primitive retains its
own harness projection and context-loading behavior.

Strict dependencies come from typed `requires:` metadata and resolve
transitively. Committed catalog entries use published HTTPS Git sources; a
historical local-source lock entry is migration state and must not be treated as
a new catalog source.

## Workspace lifecycle

`library workspace use <name>` registers a metadata-only desired-
state root and applies additions. A scope may register several Workspaces, but
ordinary primitive `use` remains available for direct roots that should survive
Workspace changes independently.
