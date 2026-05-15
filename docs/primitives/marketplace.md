# Marketplace

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** A GitHub org or repository that publishes a discoverable collection
of skills, agents, or plugins. The library catalog can reference a marketplace so
users can browse and pull from it.

**Key constitutive feature.** Discovery surface: a marketplace is defined by its role
as a catalog entry point — it publishes primitives for others to find and install, but
does not itself contain installed primitives.

**Trigger semantics.** Marketplaces are not invoked. They are registered via
`library add-marketplace <github-url>`. Users browse or search them and then pull
specific items into their repos.

**Promotion routing metadata.** Registered source providers in `library.yaml`
can declare routing fields used by `lib catalog match`:

- `local_path`: local checkout path, or `null` for remote-only sources.
- `writable`: whether tools may create or update primitives in that source.
- `content_types`: primitive families the source accepts, such as `skills`,
  `agents`, `standards`, or `hooks`.
- `scope.topics`: positive topic tags used for ranking promotion targets.
- `scope.excludes`: optional anti-tags that disqualify a source for a request.

Promotion tools should query the catalog instead of hard-coding repository
knowledge. Example:

```bash
lib catalog match --primitive-type=standard --topics=python,uv --writable-only --json
```

The command returns ranked candidates plus the selected top candidate or tie
set. Writable first-party catalogs such as Cognovis Core, Sussdorff Core, and
Open-Brain can therefore become promotion targets without client-specific
repository routing tables.

**Inventory refresh.** Local writable sources can be scanned by convention with:

```bash
lib catalog sync --source=cognovis-library-core --primitive-type=standard --write --json
```

The sync path reads `local_path` and regenerates catalog entries from standard
repository locations such as `skills/**/SKILL.md`, `agents/**/*.md`, and
`standards/**/*.md`, avoiding hand-edited entry blocks for refreshed inventory.

**Cost.** No runtime cost. Marketplaces are a distribution mechanism only.

**When to choose it.** Register a marketplace when:
- An external GitHub org or repo publishes reusable primitives you want to make
  discoverable to the team.
- You want to centralize discovery without mirroring content.

**Counter-examples.**
- Do NOT mirror third-party content into your own content repos — reference via
  marketplace instead.
- A marketplace is not a primitive you configure in a project — it is a catalog-level
  registration.

**Worked examples.**

| Marketplace | Why it is a marketplace |
|-------------|------------------------|
| `cognovis/samurai-skills` | A GitHub repo that publishes multiple skills for others to pull. Registered in the library catalog; content stays at source. |
| `disler` (GitHub org) | Many public skill repos. Referenced in the library catalog; we do not mirror his content. |
| `anthropics/claude-plugins-official` | Anthropic's curated plugin directory. Third-party; referenced, not mirrored. |

---
