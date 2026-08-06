# Add a Catalog Entry

## Purpose

Register a reviewed primitive from its canonical marketplace source. This guided
flow owns author decisions; deterministic install mechanics remain in
`scripts/library.py`.

## Procedure

1. Select the real primitive with the decision tree in `docs/PRIMITIVES.md`. Do
   not create an empty Package, bundle, or dependency sentinel.
2. Author and validate the primitive in its owning marketplace repository. Use
   the matching forge Skill when one exists.
3. Publish the source through that repository's normal review and CI path.
4. Add or update the aggregate `library.yaml` entry with a published HTTPS source
   URL or a registered catalog/path reference. Committed local filesystem sources
   are forbidden.
5. Mirror the primitive's strict typed `requires:` declarations in the catalog;
   do not use a Workspace to repair missing functional dependencies.
6. Validate the aggregate catalog:

   ```bash
   uv run python scripts/validate-library.py
   ```

7. Preview a consumer install through the deterministic engine:

   ```bash
   library <primitive> use <name> --dry-run --json
   ```

8. Commit and publish each changed repository through its own review workflow.

Workspace manifests are marketplace content. They select independently meaningful
roots, may compose other same-scope Workspaces, and never contain copied operating
instructions or arbitrary file-placement rules.
