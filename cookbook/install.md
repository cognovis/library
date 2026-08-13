# Install the Library Platform

## Purpose

Bootstrap the Library engine and conversational entrypoint from an existing
platform checkout. This is not a catalog fork workflow and does not configure a
consumer-project profile.

## Procedure

1. Confirm that the platform checkout contains `SKILL.md`, `library.yaml`,
   `install.sh`, `bin/library`, and `scripts/library.py`.
2. Run the idempotent installer from the checkout:

   ```bash
   bash install.sh
   ```

3. Verify the globally installed deterministic CLI:

   ```bash
   library --help
   ```

4. Run the explicit bootstrap provisioner:

   ```bash
   library bootstrap install
   ```

The installer delegates to `uv tool install` for the deterministic `library`,
`cld`, and `cdx` executables. Bootstrap then records only its enumerated product
targets, adopts existing operator-owned instruction entrypoints without changing
their content, and adds the OpenBrain singleton where compatible. It does not
link the checkout into harness Skill roots.

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
