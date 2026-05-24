# Consumer Project Updater

`scripts/update-consumers.py` is the controlled updater for projects that
consume Library-managed primitives from this platform and its catalogs.

It exists to prevent stale consumer checkouts after a catalog publishes a new
standard, script, or other primitive. It does not silently merge or push target
projects. The default mode is dry-run; apply mode mutates consumer working
trees and reports the files that changed so the caller can review and commit
them deliberately.

## Manifest

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

## Usage

Dry-run all configured consumers:

```bash
python3 scripts/update-consumers.py --json
```

Dry-run selected consumers:

```bash
python3 scripts/update-consumers.py --consumer polaris --consumer mira --json
```

Apply selected consumers:

```bash
python3 scripts/update-consumers.py --consumer polaris --consumer mira --apply --json
```

After apply, inspect each target repo with `git status`, run its project-specific
smoke checks, then commit and push in that target repo. The updater intentionally
does not do those last steps.
