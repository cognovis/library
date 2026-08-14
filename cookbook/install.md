# Install the Library Platform

## Purpose

Bootstrap the Library engine and its required catalog sources on either a fresh
machine or an existing platform checkout. This is not a catalog fork workflow.

## Procedure

1. Install `uv` and ensure Git can read the published platform and core catalog
   repositories.
2. On a fresh machine, download the published `install.sh` and run:

   ```bash
   bash install.sh --fresh
   ```

   Fresh mode creates managed source checkouts below
   `${XDG_DATA_HOME:-~/.local/share}/library/sources`, records their portable
   locations in `${XDG_CONFIG_HOME:-~/.config}/library/catalog-sources.json`,
   installs the control plane, and reconciles the enumerated bootstrap.

   To initialize one existing Git repository in the same transaction:

   ```bash
   bash install.sh --fresh --project /path/to/repository
   ```

3. From an existing platform checkout, `bash install.sh` remains the idempotent
   control-plane-only upgrade route. Run `library bootstrap install` separately
   when its receipts need reconciliation.
4. Verify the globally installed deterministic CLI:

   ```bash
   library --help
   ```

The installer delegates to `uv tool install` for the deterministic `library`,
`cld`, and `cdx` executables. Fresh bootstrap records only its enumerated product
targets, adopts existing operator-owned instruction entrypoints without changing
their content, and adds the OpenBrain singleton where compatible. Managed source
checkouts are input catalogs, not global primitive projections, and no checkout
is linked into harness Skill roots.

## Bootstrap boundary

The released installer does not install Library Skills or other primitives
globally. Forge Skills and conversational entrypoints belong in repository-local
Workspace or direct-primitive installs.

The Library Skill remains the dialog-oriented operator surface for inspecting a
repository, explaining recommendations, and obtaining confirmation before the
deterministic CLI changes project desired state.

Do not use `project_tooling` profiles for new repository setup. Consumer projects
keep generated Library installs and lock artifacts local through the CLI-managed
`.gitignore` block; marketplace repositories keep authored primitives at their
top-level source paths.

Workspace lifecycle commands are available through the `library` CLI but manage
only the current Git repository.
