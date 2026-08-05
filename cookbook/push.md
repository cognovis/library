# Publish a Primitive Source Change

## Purpose

Return an intentional change to the primitive's canonical marketplace repository.
A deployed Library target is not automatically a writable source checkout.

## Procedure

1. Read the installed receipt and aggregate catalog entry to identify the exact
   source catalog, path, and installed pin.
2. Inspect drift between the deployed copy and the published source. Stop if the
   source identity is missing, ambiguous, local-only, or has advanced in a way that
   would make the intended patch unclear.
3. Apply the intended change in a task worktree of the owning marketplace
   repository. Do not overwrite the source directory from the deployed copy as a
   whole.
4. Run the primitive forge validator and the marketplace's focused tests.
5. Update aggregate catalog metadata only when the source path, dependencies,
   version, or searchable metadata changed.
6. Commit and push through the owning repository's normal review workflow.
7. Preview `library <primitive> sync <name>` from a consumer after the published
   revision is available.

Committed catalog sources are published HTTPS Git references. Historical local
source entries are migration state, not a supported publication path.
