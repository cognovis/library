# Plane And Projection Vocabulary

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

ADR-0005 (`docs/adr/library-plane-vocabulary.md`) defines the placement
vocabulary used by catalog schema and Gas City export work:

- `library/meta` is the dev-plane installer, catalog, and compiler engine.
- Marketplaces are stewarded primitive sources such as `cognovis-core` and
  `sussdorff-core`.
- Repo-local primitives are vendored or local overlays.
- Product-plane runtime agents are product features, not Library catalog
  primitives.
- Gas City PackV2 is a runtime projection target, not a Library install bundle.
- Catalog metadata (`metadata.library.*`) is separate from primitive source files.
- `script` is a first-class Python-only primitive for deterministic helpers.

---
