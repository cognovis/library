# Action Boundary Metadata

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

`action_boundary` is not a separate primitive. It is Library metadata declared on
any side-effecting skill or agent. NORMATIVE:
the metadata keys are shared across harnesses, but the physical serialization follows
the primitive format (`SKILL.md` YAML frontmatter for skills, YAML or TOML agent
metadata for harness-specific agents).

**Catalog metadata compatibility.** `library.yaml` treats `metadata` as an open
extension bag so nested Library-owned metadata such as `metadata.library.gascity`
can coexist with agentskills-compatible top-level string metadata. External
consumers that previously expected `metadata` to be a strict string-to-string map
should ignore nested `metadata.library.*` keys or validate only the top-level
string fields they consume.
