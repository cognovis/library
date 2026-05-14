# Standard

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** A markdown document containing project-specific or cross-cutting
context that supplements skills and agents. Standards are not invoked by the user
or model. They are dependency content loaded only when a consuming primitive
declares `requires_standards:`.

**Key constitutive feature.** Dependency-scoped context: a standard is surfaced
through a consuming skill or agent, not by automatic project-wide injection.

**Delivery semantics — current mechanism (NORMATIVE, Axis 1 lock-in, 2026-05-14):**

**Never auto-injected.** `/library standard use <name>` installs the standard file
at its canonical path and updates `.library.lock`. It does not write to
`AGENTS.md`, `CLAUDE.md`, or any other harness context file. Standards reach the
model only when a consuming primitive declares `requires_standards: [<name>]`.
Folder-form standards do not use `_triggers.yml`; catalog registration plus
`requires_standards` is the delivery contract.

**Update + remove.** `/library sync` refreshes the vendored standard files under
`.agents/standards/<name>/` or `~/.agents/standards/<name>/` and updates the
lockfile content hash. `/library standard remove <name>` deletes the installed
files and lockfile entry only.

**Standard file paths (cross-harness convention, CL-v56).**

| Priority | Path | Scope |
|----------|------|-------|
| 1 (wins) | `.agents/standards/<name>/<name>.md` | Project-local, folder-form |
| 2 | `~/.agents/standards/<name>/<name>.md` | User-global, folder-form |

**Standard file layout (single-file vs folder-form).**

| Form | When to use | Layout |
|------|-------------|--------|
| Single-file | <600 tokens, single topic | `standards/<name>/<name>.md` (the folder holds only the one entry file) |
| Folder-form | 600-3000 tokens with multiple sub-topics | `standards/<name>/<name>.md` (entry) + sibling `<topic>.md` files in the same folder |

Convention: **entry file = stem matches folder name**. Sibling `.md` files in the
same folder are detail pages reachable via relative links from the entry. The entry
file is what `requires_standards: [<identifier>]` loads; sibling files are pulled
on demand by the model when it follows a link.

For >3000 tokens of disparate content, prefer two separate standards over one
folder with many sibling files.

**Frontmatter convention (domain vs rule).**

A standard's entry file declares either `domain:` or `rule:` in its frontmatter —
one of the two, not both. The choice tells the agent at a glance what kind of
shared knowledge it just opened.

| Field | Use when content is | Example |
|-------|---------------------|---------|
| `domain:` | A body of knowledge about a topic | `domain: python-cli-patterns`, `domain: healthcare-control-areas` |
| `rule:` | A convention or prohibition that applies broadly | `rule: english-only`, `rule: no-emoji`, `rule: adr-location` |

```yaml
# Domain-style standard:
---
domain: python-cli-patterns
description: How to author Python CLIs with argparse, click, and the release flow.
---

# Rule-style standard:
---
rule: english-only
description: All source code is English; user-facing strings may be localized.
---
```

Loader and validator accept either field as the standard's identifier. In
`library.yaml` the catalog entry still uses `name:` — that is catalog-internal and
not user-facing.

Minimum v2 frontmatter is exactly one identifier field (`domain:` or `rule:`)
plus `description:`. `maturity:` is optional metadata, not a required field. The
"maturity arc" is the lifecycle between skill-internal reference and catalog
standard; it is not a mandate to add a `maturity:` key to every standard.

The folder name matches the identifier value: `domain: python-cli-patterns` →
`standards/python-cli-patterns/python-cli-patterns.md`.

**Judge-layer standard subtypes.** NORMATIVE as Library taxonomy.
These are standards, not new primitive classes, because they are shared context and
schema contracts consumed by skills, agents, and judges.

| Subtype | Definition | Required shape |
|---------|------------|----------------|
| Action Proposal Schema | A structured object an actor must produce before a side effect. | intended action, evidence, authorization context, expected consequence, rollback path |
| Mandate | An AP2-style authorization-as-evidence record that can be attached to an Action Proposal. | scope, limits, evidence, granted_at, granted_by, expires_at, supersedes |

Action Proposal Schema standards define what a side-effecting actor must submit to
the judge. Mandate standards define durable authorization records: they are evidence
that the actor has permission within a bounded scope, not permission to do anything
outside that scope.

**Optional `scripts/` directory.**

A standard folder may include Python helpers under `scripts/<name>.py` alongside its markdown
when parts of the standard can be enforced or automated deterministically.

| Standard kind | Typical script role | Called by |
|---------------|---------------------|-----------|
| `rule:` | Enforcement — e.g. `scripts/check-english.py` scans source files and exits non-zero on violation | Pre-commit hooks, guardrails |
| `domain:` | Tooling — e.g. `scripts/scaffold-cli.py` generates argparse boilerplate | Skills that consume the standard |

Scripts are **not invoked by the standard itself** — the standard's `.md` remains
pure model-context. Scripts are called from outside: by hooks (for rules) or by
skills (for domains). This keeps the standard contract clean (context-only) while
allowing deterministic enforcement to ship in the same package.

Output contract: scripts with multiple failure modes follow the
`execution-result-envelope` JSON shape (`status`, `summary`, `data`, `errors`,
`next_steps`). Pre-commit-style binary enforcement uses a non-zero exit code
with stderr diagnostics.

**Maturity arc (skill reference ↔ standard).**

Markdown files containing factual knowledge can live in two places — inside one
skill as a private reference, or in the catalog as a standard. The structural
difference is ownership and addressability, not content.

| Criterion | Skill-internal reference (`skills/<skill>/references/foo.md`) | Standard (`standards/<name>/<name>.md`) |
|-----------|---------------------------------------------------------------|-----------------------------------------|
| Entry in `library.yaml` | No | Yes (under `library.standards:`) |
| Reachable by other primitives | No — bundled with parent skill | Yes, via `requires_standards: [name]` |
| Versioned with | Parent skill commit | Independent source/commit |
| Reachable when parent skill not loaded | No | Yes |
| Installable standalone | No | Yes (`library standard use <name>`) |

**Operative test:** Would a second primitive (another skill, agent, or project)
want to declare this as a dependency? If yes → standard. If no → skill-internal
reference.

**Mechanical test:** Does the file have a `name:` entry in `library.yaml`? If
yes, it is a standard. If no, it is a skill-internal reference. (Inside the
standard file itself, the identifier appears as `domain:` or `rule:`; the
library.yaml entry maps that to `name:`.)

**Lifecycle:**

```
new idea
   │
   ▼
skill reference         "useful only for this skill"
   │ (promotion: another primitive needs the same content)
   ▼
catalog standard        "shared knowledge with its own lifecycle"
   │ (demotion: only one primitive still uses it)
   ▼
skill reference (back)
```

Promotion mechanics:
1. Move the file: `skills/<skill>/references/<file>.md` → `standards/<name>/<name>.md`
2. Register the entry in `library.yaml` under `library.standards:`
3. Add `requires_standards: [<name>]` to every skill that needs it
4. Remove the original `references/<file>.md` from the source skill
5. Update intra-skill links to rely on `requires_standards` for loading

Demotion is the inverse: fold the standard back into the one skill's `references/`,
drop the catalog entry, remove `requires_standards:` declarations.

**Skills declare dependencies** via `requires_standards` frontmatter:

```yaml
---
name: dolt
description: Dolt version-controlled database skill.
requires_standards: [dolt-server, branch-naming]
---
```

**Runtime loading (skill-script-side):** Individual skill scripts read the cached file
directly from its resolved path (project-local `.agents/standards/<name>/` wins over
user-global `~/.agents/standards/<name>/`):

```bash
STD_PATH=".agents/standards/<name>/<name>.md"
[ -f "$STD_PATH" ] || STD_PATH="${HOME}/.agents/standards/<name>/<name>.md"
STANDARD=$(cat "$STD_PATH")
```

**When to choose it.** Create a standard when:
- A project has coding conventions, architectural decisions, or integration patterns
  that every agent working on the project must know.
- The content is context (factual guidance), not executable workflow (which would be
  a skill).
- The content crosses multiple skills and would need to be duplicated if embedded in
  each skill individually.

**Counter-examples.**
- Do NOT use a standard as an invocable skill — it is not addressable by `/name` or
  by model description-matching.
- Do NOT put imperative workflow steps in a standard — that is a skill or command.

**Metadata note.** Library-owned metadata (e.g., `metadata.library.requires_standards`)
lives in the Library's own namespace. Do NOT pollute standard SKILL.md frontmatter
fields with Library-internal metadata.

**Authoring source-of-truth.** Day-to-day rules for writing a standard
(`rule:` vs `domain:` frontmatter, folder-form vs single-file layout, required
and optional fields, maturity-arc test, promotion mechanics) live in the
`standard-forge` skill itself — it is the operational source-of-truth for
standard authoring. This document defines the primitive; `standard-forge`
defines how to write one. Do NOT create parallel policy documents.

---
