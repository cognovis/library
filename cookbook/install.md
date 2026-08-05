# Install the Library Platform

## Purpose

Bootstrap the Library engine and conversational entrypoint from an existing
platform checkout. This is not a catalog fork workflow and does not configure a
consumer-project profile.

## Procedure

1. Confirm that the platform checkout contains `SKILL.md`, `library.yaml`,
   `install.sh`, and `scripts/library.py`.
2. Run the idempotent installer from the checkout:

   ```bash
   bash install.sh
   ```

3. Verify the deterministic engine directly:

   ```bash
   uv run --script scripts/library.py --help
   ```

4. Start a new session in each detected harness and verify that the `/library`
   Skill is discoverable.

The repository does not currently ship a standalone `bin/library` executable.
The installer links the platform checkout into detected harness Skill roots; the
chat Skill delegates deterministic operations to `scripts/library.py`.

## Bootstrap boundary

The released installer also links the five platform forge Skills globally. Under
ADR-0010 that is transitional: the irreducible pre-Workspace bootstrap contains
only the Library engine and conversational entrypoint, while forge Skills move to
the project-scoped `library-authoring` Workspace.

Do not use `project_tooling` profiles for new repository setup. Consumer projects
commit their project-local Library artifacts and `.library.lock`; marketplace
repositories keep authored primitives at their top-level source paths.

Workspace commands remain an accepted target until bead `CL-r7n6` lands.
