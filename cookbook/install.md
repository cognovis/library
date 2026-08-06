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

4. Start a new session in each detected harness and verify that the `/library`
   Skill is discoverable.

The installer links `bin/library` into `~/.local/bin/library` and links the
platform checkout into detected harness Skill roots. The global command is the
deterministic shell interface; the `/library` Skill remains the dialog-oriented
entrypoint for operations that require advice or decisions.

## Bootstrap boundary

The released installer also links the five platform forge Skills globally. Under
ADR-0010 that is transitional: the irreducible pre-Workspace bootstrap contains
only the Library engine and conversational entrypoint, while forge Skills move to
the project-scoped `library-authoring` Workspace.

Do not use `project_tooling` profiles for new repository setup. Consumer projects
commit their project-local Library artifacts and `.library.lock`; marketplace
repositories keep authored primitives at their top-level source paths.

Workspace lifecycle commands are available through the global `library` CLI.
