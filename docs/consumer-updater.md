# Consumer Project Updater

> **Status: transitional and closed to expansion.** This is the released legacy
> consumer-refresh path. ADR-0010 replaces `library_entries` with each
> consumer's registered Workspace and direct requested roots after Workspace
> rollout. It does not carry the `managed_files` escape hatch forward.

`scripts/update-consumers.py` is the controlled updater for projects that
consume Library-managed primitives from this platform and its catalogs.

It exists to prevent stale consumer checkouts after a catalog publishes a new
standard, script, or other primitive. It does not silently merge or push target
projects. The default mode is dry-run; apply mode mutates consumer working
trees and reports the files that changed so the caller can review and commit
them deliberately.

## Workspace replacement

After lockfile v2 rollout, a consumer records its own desired state:

```text
library workspace use <catalog>:<name> --scope project --dry-run
library workspace use <catalog>:<name> --scope project
library workspace status --all --scope project
library workspace sync --all --scope project
```

Several Workspaces may be registered in one consumer. Shared receipts remain
installed while any Workspace or direct root reaches them. A catalog publisher
does not keep a separate fleet manifest naming consumer checkouts.

Each legacy `managed_files` item must be classified before this updater is
removed:

- make it a real Library primitive or a transitive dependency when it is
  reusable Library content; or
- keep it project-owned and frozen with a provenance marker when it is
  repository-specific; or
- retire it explicitly when no consumer still requires it.

The updater exports a read-only target inventory in the manager-adapter shape.
For each consumer, its updater entry is removed in the same reviewed change that
registers replacement Workspace or direct roots. This prevents a two-writer
state in which a retired updater recreates reconciler-managed files.

Workspace must not become another arbitrary source-to-target copy manifest.

The exact consumer targets and cutover gates are maintained in
[Workspace legacy-writer inventory](migration/workspace-legacy-inventory.md).

## Legacy manifest

Consumer update targets live in `consumer-projects.yml`.

Each consumer can declare:

- `root`: the local project checkout.
- `library_entries`: installed Library entries to refresh via `scripts/library.py`.
- `managed_files`: explicit source-to-target file copies for repo-local runtime
  files that are not yet modeled as first-class primitive dependencies.

The first managed consumers are `polaris` and `mira` for the
`seed-data-parity` workflow:

- sync the canonical `seed-data-parity` standard,
- ensure `scripts/refinement/check-seed-data-parity.py` is present,
- ensure `scripts/refinement/bead_status.py` is present.

## Legacy usage

Dry-run all configured consumers:

```bash
uv run python scripts/update-consumers.py --json
```

Dry-run selected consumers:

```bash
uv run python scripts/update-consumers.py --consumer polaris --consumer mira --json
```

Apply selected consumers:

```bash
uv run python scripts/update-consumers.py --consumer polaris --consumer mira --apply --json
```

After apply, inspect each target repo with `git status`, run its project-specific
smoke checks, then commit and push in that target repo. The updater intentionally
does not do those last steps.
