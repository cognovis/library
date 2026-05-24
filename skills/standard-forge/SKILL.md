---
name: standard-forge
description: >-
  Scaffold or validate a Library standard — a factual, harness-injected markdown
  context file that skills and agents declare via `requires_standards`. Use when
  creating a new standard, validating an existing one, deciding "is this a
  standard or a skill?", scaffolding judge-layer Action Proposal or Mandate
  standards, or wiring `requires_standards:` into a skill.
  Triggers on create standard, new standard, standard-forge, scaffold standard,
  validate standard, check standard, requires_standards.
disableModelInvocation: true
requires_standards: [agentic-primitives, primitive-placement, judge-layer, english-only, no-emoji]
---

# Standard Forge

Scaffold new Library standards — factual, harness-injected context files that skills
and agents declare via `requires_standards`.

This skill is the **operational source-of-truth for how to write a standard**.
`meta/docs/PRIMITIVES.md §7` defines what a standard IS (taxonomy); this skill
defines how to author one (rules, layout, catalog wiring). Do not create
parallel policy documents.

## When to Use

- "create a standard for X"
- "scaffold a standard named Y"
- "validate standard X" / "check this standard"
- "is this content a standard or a skill?"
- "I need a standard my skill can require"
- Any time someone asks about `requires_standards:` wiring

## What a Standard Is

Per `agentic-primitives` §Standard Justification:

> Standards are model-context, not model-invoked. Choose a standard when the content
> is **factual** guidance (conventions, lookup tables, NORMATIVE claims) that should
> be loaded into the model's window when relevant triggers fire.

**Standards are NOT:**
- Imperative step-by-step workflows (those are skills)
- Enforcement rules that must fire unconditionally (those are hooks/guardrails)
- Agent orchestration logic

## Standard vs Skill-Reference (Maturity Arc)

A factual markdown file can live in two places: as a private reference inside one
skill (`skills/<skill>/references/<file>.md`) or as a catalog standard
(`standards/<id>/<id>.md`). The structural difference is ownership and
addressability, not content.

**Operative test:** Would a second primitive want to declare this as a dependency
via `requires_standards`? If yes → standard. If no → keep it as a skill-internal
reference.

**Mechanical test:** Has the file a `name:` entry in `library.yaml`? Yes →
standard. No → skill-internal.

Lifecycle: content typically starts as a skill reference and gets **promoted** to
a standard once a second primitive needs it. The inverse (**demotion**) applies
when a standard is only used by one primitive — it folds back into that skill's
`references/`. Mechanics are in §Promotion / Demotion below.

## Primitive Gate (run before scaffolding)

Before creating anything, verify the content is genuinely a standard:

1. **Ask:** "Does the content start with Step 1, Step 2...?" or "Is it telling the model
   what to DO rather than what to KNOW?"
   - YES → **STOP.** Tell the user: "This looks like an imperative workflow — it belongs
     in a skill, not a standard. Recommend running `skill-forge` instead."

2. **Ask:** "Must this fire unconditionally at a lifecycle event, without the model
   being able to opt out?"
   - YES → **STOP.** Tell the user: "This sounds like a guardrail/hook rather than
     a standard. Recommend running `hook-forge` instead."

3. Content is factual guidance, conventions, or lookup tables → proceed to the
   Placement Gate.

## Placement Gate (run before Create Mode)

Use `standards/agentic-primitives/primitive-placement.md` before deciding where
the standard belongs.

| Question | Standard-forge rule |
|----------|---------------------|
| Steward marketplace? | Platform self-description standards belong in `library-platform`; other reusable dev-plane standards belong in `cognovis-core` or `sussdorff-core`; third-party standards keep third-party provenance; product-specific overlays stay `repo-local`. |
| Dev-plane or product-plane? | Library standards are dev-plane context. Product documentation, runtime behavior, or end-user feature specifications are product-plane artifacts and must stay in the product repo. |
| Product counterpart? | A dev-plane standard may reference paired product work with `metadata.library.product_counterpart`, but the product artifact is not copied into Library. |
| Repo-local escape hatch? | Keep the standard repo-local when it depends on private ADRs, concrete product paths, local credentials, tenant details, or one repo's topology. |
| Harness support? | Ask whether the standard works in all harnesses or is harness-specific. For one-harness standards, set `metadata.library.harness_support.<harness>: supported` and mark the others `not-supported`. |
| Runtime requirements? | Ask whether the standard requires external binaries such as `bun`, `rg`, `sushi`, or `shellcheck`; declare them under `runtime_requirements.binaries` when needed. |
| Deterministic script route? | Parsing, validation, export, or transformation logic belongs in `script-forge`; standards may state the factual rules the script checks. |
| Gas City projection? | Gas City projection metadata describes generated PackV2 output only; it does not make Gas City the source owner. Use `metadata.library.gascity.projections[]` when exporting. |

Product-plane refusal block:

```text
This is product documentation, not a Library standard.
Ship it in the product repo's README/docs.
A dev-plane standard may reference the product surface via metadata.library.product_counterpart, but the product documentation stays with the product.
```

## Create Mode

### Step 1: Gather Requirements

Ask the user (one question at a time, skip if already answered):

1. **Identifier:** What is the standard's kebab-case identifier? (e.g.
   `python-cli-patterns`, `english-only`)
2. **Kind:** Is the content a **domain** (body of knowledge about a topic — e.g.
   `python-cli-patterns`, `healthcare-control-areas`), a **rule** (broad
   convention or prohibition — e.g. `english-only`, `no-emoji`), an
   **action proposal schema**, or a **mandate schema**?
3. **Description:** One sentence — what factual guidance does this provide?
4. **Sub-topics?** If the content exceeds 600 tokens or has multiple sub-areas,
   what are they? (Each becomes a sibling `.md` in the same folder.)

### Judge-layer Template Dispatch

If Kind is **action proposal schema**, scaffold from
`assets/action-proposal-template.md`. If Kind is **mandate schema**, scaffold from
`assets/mandate-template.md`. These are specialized domain standards: they still
use exactly one `domain:` frontmatter key, register once in `library.yaml`, and
load through `requires_standards: [<id>]`.

Dispatch rules:
- Replace the template `domain:` value with the requested standard identifier.
- Replace the `Contract URI:` line with the new contract identity. Use
  `standard://<namespace>/proposals/<proposal-name>.v1` for Action Proposal
  schemas and `standard://<namespace>/mandates/<mandate-name>.v1` for Mandate
  schemas. Do not leave a canonical judge-layer URI on a specialist standard.
- Keep the Action Proposal template's mandate reference field for any
  `external-side-effect` or `high-risk` action.
- Keep the Mandate template's scope, limits, evidence, grant, expiry, and
  supersession fields.
- Do not add `rule:` alongside `domain:`.
- Do not add `_triggers.yml`.

### Step 2: Where Standards Live

A standard is **always folder-form**: the identifier names a folder, and the
entry file inside has the same stem. "Single-file" means the folder holds only
the entry; "folder-form with siblings" means additional `<topic>.md` files live
alongside the entry.

| Context | Path | When to use |
|---------|------|-------------|
| **Marketplace source** | `standards/<id>/<id>.md` | You are authoring inside a marketplace source repo. This is the published source. |
| **Project-local install** | `.agents/standards/<id>/<id>.md` | A downstream project pulled the standard via `/library standard use <id>`. Resolver checks this path first. |
| **User-global install** | `~/.agents/standards/<id>/<id>.md` | Installed for all projects of one user. Resolver fallback. |

When `standard-forge` runs inside this marketplace repo, default to
`standards/<id>/<id>.md` (no `.agents/` prefix). The `.agents/` prefix is for
installed copies in downstream consumer projects, not for marketplace sources.

### Step 3: Choose the Layout

| Form | When | Layout |
|------|------|--------|
| **Single-file** | <600 tokens, single topic | `standards/<id>/<id>.md` — folder holds only the entry file |
| **Folder-form with siblings** | 600-3000 tokens, multiple sub-topics | `standards/<id>/<id>.md` (entry, has frontmatter) + sibling `<topic>.md` files (no frontmatter) in the same folder |
| **Split** | >3000 tokens of disparate content | Two separate standards, not one mega-folder |

The entry file is what `requires_standards: [<id>]` loads. Siblings are reached
on demand via relative links from the entry.

### Step 4: Generate the Entry File

Scaffold with one of two frontmatter shapes. Choose `domain:` or `rule:` based
on Step 1's "Kind" answer — never both, never `name:` (that field is for the
catalog entry in `library.yaml`, not for the standard file itself).

**Domain-style** (body of knowledge):

```markdown
---
domain: <id>
description: <one-line description of what factual guidance this provides>
---

# <Title Case Name>

> **Scope**: <Which skills/agents load this and why. Keep to 1-2 sentences.>

## Overview

<Brief framing of the domain.>

## Sub-topics

- [<Topic A>](<topic-a>.md)
- [<Topic B>](<topic-b>.md)
```

**Rule-style** (convention or prohibition):

```markdown
---
rule: <id>
description: <one-line description of what factual guidance this provides>
---

# <Title Case Name>

> **Scope**: <Which skills/agents load this and why. Keep to 1-2 sentences.>

## Rule

<The factual rule, table-shaped if it covers multiple cases.>

## Exceptions

<Carved-out cases, if any.>
```

**Frontmatter fields:**
- Exactly one of `domain:` or `rule:` — the identifier, kebab-case, matches the
  folder name and the entry-file stem.
- `description`: one sentence, factual, no "step 1, step 2" language.
- `maturity:` is optional metadata, not part of the minimum v2 contract. The
  maturity arc is the promotion/demotion lifecycle, not a key on every file.

**Content rules:**
- Factual and reference-style — NOT "do this, then do that".
- Short and load-bearing — every sentence earns its token cost.
- Tables and lists preferred over prose paragraphs for scannability.
- Target: 200-600 tokens per file. Hard cap: 1500 tokens per file. Above that,
  promote sub-areas to sibling `.md` files in the same folder and link them
  from the entry.

**Folder-form sibling files:** Each sibling `<topic>.md` has no frontmatter —
only the entry file does. Siblings are detail pages, not separately addressable
in the catalog. Link to them from the entry using relative paths:

```
standards/<id>/
  <id>.md               <- entry, has frontmatter, loaded by requires_standards
  <topic-a>.md          <- detail, plain markdown, model follows link
  <topic-b>.md
  scripts/              <- optional, deterministic Python enforcement/tooling
    check-<rule>.py
```

### Step 5: Optional `scripts/` Directory

A standard may ship a `scripts/` directory alongside its markdown when parts of
the standard can be enforced or automated deterministically.

| Standard kind | Typical script role |
|---------------|---------------------|
| `rule:` | Enforcement — e.g. `scripts/check-english.py` scans source and exits non-zero on violation. Called by pre-commit hooks or guardrails. |
| `domain:` | Tooling — e.g. `scripts/scaffold-cli.py` generates argparse boilerplate. Called by skills that consume the standard. |

Scripts in a standard are **not invoked by the standard itself** — the `.md`
remains pure context. Scripts are called from outside: by hooks (rules) or by
skills (domains).

All standard scripts must be Python. If the script should be reused
independently or exported into a Gas City command/doctor/formula surface,
scaffold it with `script-forge` and register it under `library.scripts`.

Output contract: scripts with multiple distinguishable failure modes follow the
JSON envelope (`{"status":"ok|warning|error", "summary":"...", "data":{...},
"errors":[], "next_steps":[]}`). Pre-commit-style binary pass/fail uses a
non-zero exit code with stderr diagnostics.

### Step 6: Register in `library.yaml`

Add a catalog entry under `library.standards:` matching the actual shape used
in `meta/library.yaml`. The `source:` URL shape depends on whether the standard
has sibling files:

**Single-entry standard** (entry file only, no siblings) — use a `blob` URL:

```yaml
- name: <id>
  description: >-
    <one-line description matching the file's frontmatter description>
  source: https://github.com/cognovis/library-core/blob/main/standards/<id>/<id>.md
  tier: domain          # core | domain | global
  default_scope: ask    # ask | global
  tags:
    - origin:original
    - tier:domain
    - category:standard
```

**Folder-form with siblings** — use a `tree` URL so the installer copies the
whole folder, not just the entry file:

```yaml
- name: <id>
  description: >-
    <one-line description matching the file's frontmatter description>
  source: https://github.com/cognovis/library-core/tree/main/standards/<id>/
  tier: domain
  default_scope: ask
  tags:
    - origin:original
    - tier:domain
    - category:standard
```

> **Known platform limitation.** `meta/scripts/lib/source.py:parse_source` currently
> recognizes only `blob/` and raw URLs — `tree/` URLs do not yet resolve. Use a
> tree URL anyway (so the catalog records authorial intent), but expect installs
> of folder-form-with-siblings standards to be incomplete until the parser is
> extended. A blob URL pointing at the entry file installs only the entry and
> silently drops siblings — that is worse than a tree URL the parser rejects
> loudly.

Field guidance:

| Field | Values | Notes |
|-------|--------|-------|
| `name` | matches the file's `domain:`/`rule:` identifier | Catalog-internal identifier, kebab-case |
| `tier` | `core` (forge-loaded core context), `domain` (topic-specific), `global` (always-applicable rule like `english-only`) | Use `global` only for cross-cutting rules; `domain` is the default |
| `default_scope` | `ask` (prompt the user on `/library standard use`), `global` (install user-globally without prompting) | `global` is reserved for tier `global` |
| `source` | `blob` URL to entry file for **single-entry** standards; `tree` URL to the folder for **folder-form-with-siblings** | Mismatch causes the installer to drop sibling files |

**Optional: Gas City export.** Only add this block when the standard should be
materialized into a Gas City pack:

```yaml
  metadata:
    library:
      plane: dev
      gascity:
        exportable: true
        projections:
          - target: overlay
            pack: <pack-name>
            scope: <city|rig|provider|global>
            session_class: none
            provider_neutral: true
```

If the standard supports paired product documentation, add a pointer without
moving product documentation into Library:

```yaml
  metadata:
    library:
      plane: dev
      product_counterpart:
        repo: <product-repo>
        path: <product-doc-path>
        name: <product-doc-or-feature-name>
        primitive_type: other
        notes: <why this dev-plane standard supports the product surface>
```

Omit `metadata:` entirely when the standard has neither a Gas City projection
nor a product counterpart. Most standards have neither.

Do **not** create a `_triggers.yml` file for folder-form standards. The
delivery contract is `library.standards:` catalog registration plus explicit
`requires_standards:` in consuming skills — there is no keyword auto-injection.

### Step 7: Output the `requires_standards` Snippet

After creating the file, print:

```
Standard created: standards/<id>/<id>.md
Catalog entry added: library.yaml -> library.standards[name=<id>]

To load this standard in a skill, add to your SKILL.md frontmatter:

  requires_standards: [<id>]

Or alongside existing standards:

  requires_standards: [existing-standard, <id>]
```

## Consumer Update Gate

Run this gate before closeout when creating, changing, promoting, or demoting a
standard that may be installed in downstream project repos.

- Check `consumer-projects.yml` for consumers of the standard or its workflow
  bundle.
- If the standard is listed, run a consumer updater dry-run:

```bash
python3 scripts/update-consumers.py --json
python3 scripts/update-consumers.py --consumer <name> --json
```

- If the dry-run reports planned changes, either run
  `python3 scripts/update-consumers.py --consumer <name> --apply --json` and
  finish the target repo commit, or file/follow a consumer propagation bead.
- If the standard is not listed in `consumer-projects.yml`, state that no
  managed consumer update is required.

The updater is a release propagation check, not standard authoring logic. Do
not copy project-local `.agents/standards/**` files by hand when the consumer is
configured for updater-managed sync.

## Promotion / Demotion

The maturity arc is a lifecycle, not a frontmatter field. Apply these mechanics
when a skill-internal reference is reused or a standard collapses to a single
consumer.

**Promotion (skill reference → standard):**

1. Move the file: `skills/<skill>/references/<file>.md` → `standards/<id>/<id>.md`
2. Add the catalog entry to `library.yaml` under `library.standards:` (Step 6 shape)
3. Add `requires_standards: [<id>]` to every skill that needs it
4. Delete the original `references/<file>.md` from the source skill
5. Update intra-skill links to rely on `requires_standards` loading

**Demotion (standard → skill reference):** the inverse — fold the standard's
content back into the one skill's `references/`, drop the catalog entry, and
remove `requires_standards:` declarations.

## Runtime Loader Snippet

When a skill's script needs to read the standard at runtime, resolve
project-local first, then user-global:

```bash
STD_PATH=".agents/standards/<id>/<id>.md"
[ -f "$STD_PATH" ] || STD_PATH="${HOME}/.agents/standards/<id>/<id>.md"
STANDARD=$(cat "$STD_PATH")
```

Skills do not need to load the standard themselves when the harness already
honors `requires_standards:` injection — the snippet above is for scripts that
re-read the file directly (e.g., validators).

## Validate Mode

Use when the user asks to "validate", "check", or "review" an existing standard file.

### What to Check

Read the standard file and evaluate each rule:

| Check | Pass Condition | Fail |
|-------|---------------|------|
| **Frontmatter present** | Entry file starts with `---` block | Missing `domain:`/`rule:` or `description` |
| **Identifier field** | Exactly one of `domain:` or `rule:` set, kebab-case, matches folder + filename stem | Both set, neither set, `name:` used in frontmatter, CamelCase, or mismatch with folder/stem |
| **`description` field** | One sentence, factual, no "step 1" language | Imperative workflow language |
| **`maturity:` field** | Optional only; absence is valid | Treating `maturity:` as required or as a substitute for `domain:`/`rule:` |
| **Folder-form layout** | Entry file at `standards/<id>/<id>.md` (or `.agents/standards/<id>/<id>.md` if validating installed copy) | Flat file without folder, or stem mismatch |
| **Sibling files** | If present, no frontmatter, linked relatively from entry | Sibling has frontmatter, or unreferenced from entry |
| **Content type** | Factual/reference (conventions, tables, NORMATIVE claims) | Step-by-step instructions → should be a skill |
| **Token budget (entry)** | 200-600 tokens target, 1500 hard cap | Over 1500 tokens → split sub-topics into siblings |
| **No imperative verbs** | No "Run this", "Execute", "Do X then Y" as primary instructions | Imperative workflow embedded |
| **Catalog entry** | `library.yaml` has `library.standards[].name=<id>` with matching `source:` URL | Missing entry or mismatched name |
| **`source:` shape** | `blob/.../<id>.md` for single-entry; `tree/.../<id>/` for folder-form-with-siblings | Blob URL on a standard with siblings (installer drops siblings); tree URL on a single-entry standard (over-broad source) |
| **Catalog `tier`** | One of `core`, `domain`, or `global` | Missing or unrecognized value |
| **Catalog `default_scope`** | One of `ask` or `global` | Missing or unrecognized value |
| **Dependency reachability** | Consumers use `requires_standards: [<id>]`; no `_triggers.yml` needed | Standard relies on keyword auto-injection |
| **Gas City metadata (optional)** | If present, `metadata.library.gascity.exportable` is boolean and `target`/`pack`/`scope` are set | Half-filled metadata block |
| **Scripts (optional)** | Any scripts are Python `.py` files and declared in catalog `scripts:` when bundled | Shell scripts or undeclared reusable helpers |

### Output Format

```
## Standard Validation: <id>

Status: PASS | WARN | FAIL

| Check | Result | Note |
|-------|--------|------|
| Frontmatter | PASS | — |
| Identifier field | PASS | `domain:` matches folder and file stem |
| description | PASS | — |
| maturity | PASS | Optional; not required |
| Folder-form layout | PASS | Entry path matches `standards/<id>/<id>.md` |
| Sibling files | PASS | 5 siblings, all link-reachable, none with frontmatter |
| Content type | PASS | Factual reference |
| Token budget | WARN | ~820 tokens (target 600) |
| No imperative verbs | PASS | — |
| Catalog entry | PASS | `library.yaml` has `library.standards[].name=<id>` |
| Catalog tier | PASS | `tier: domain` |
| Catalog default_scope | PASS | `default_scope: ask` |
| Dependency reachability | PASS | Load via `requires_standards: [<id>]` |
| Gas City metadata | n/a | Not exportable |

Recommendations:
- <actionable fix for each FAIL/WARN>
```

## Spec Conflict Handling

If a bead, prompt, or existing doc asks for behavior that contradicts the current
Standards v2 contract, surface the discrepancy before closing the work. Record the
chosen resolution in bead notes and, when the mismatch is reusable or likely to
recur, file a focused follow-up bead. Do not silently satisfy stale `_triggers.yml`
or "domain and rule and maturity" wording when the v2 contract says otherwise.

## Resources

| File | Purpose |
|------|---------|
| `assets/action-proposal-template.md` | Specialized standard scaffold for Action Proposal schemas |
| `assets/mandate-template.md` | Specialized standard scaffold for AP2-style Mandate schemas |

## Do NOT

- Create a standard that contains step-by-step workflow instructions — dispatch to `skill-forge`.
- Create a standard that must fire unconditionally — dispatch to `hook-forge`.
- Use `name:` in the standard's frontmatter — that field belongs in the `library.yaml` catalog entry. Inside the file, use `domain:` or `rule:`.
- Set both `domain:` and `rule:` — pick the one that fits the content.
- Treat `maturity:` as required frontmatter — it is optional metadata only.
- Exceed 1500 tokens in a single entry file — promote sub-topics to sibling `.md` files in the same folder.
- Use the `.agents/standards/<id>/<id>.md` path when authoring inside this marketplace repo — that path is for installed copies. The marketplace source lives at `standards/<id>/<id>.md`.
- Add or require `_triggers.yml` for folder-form standards — use catalog entries and `requires_standards:` instead.
- Use imperative language ("Run this command", "Execute step 3") in standard content.
- Embed workflow logic in `scripts/` — scripts are deterministic enforcement/tooling, not model-invoked workflow (that is a skill).
- Add `metadata.library.gascity:` blocks unless the standard is genuinely Gas City-packable. Half-filled metadata is worse than none.
