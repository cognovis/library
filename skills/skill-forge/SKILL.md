---
name: skill-forge
description: >-
  Create, validate, and audit skills (SKILL.md files). Use when creating a new skill,
  validating an existing skill for quality and extractable-code violations, or running
  a full fleet audit. Triggers on: create skill, skill-forge, new skill, validate skill,
  check skill, audit skills, skill health check, fleet quality, skill creation,
  action_boundary declarations, Gas City pack metadata for skills, script declarations,
  provider-neutral skill design.
requires_standards: [agentic-primitives, primitive-placement, judge-layer, english-only, no-emoji]
---

# Skill Forge

Create, validate, and audit `SKILL.md` files — the context files that models auto-load
via description matching. This skill owns the former `skill-auditor` checks directly.

## When to Use

- "Create a new skill" / "skill-forge" / "new skill <name>"
- "Validate skill X" / "check skill X" / "does this skill have extractable code?"
- "Audit skills" / "skill health check" / "fleet quality report"

## Mode Routing

| Request | Mode |
|---------|------|
| Create or scaffold a new skill | `create` |
| Check one skill for violations | `validate <name>` |
| Fleet-wide audit and scoring | `audit-fleet` |

---

## Mode 1: create

Interactive scaffold for a new `SKILL.md`.

### Step 1 — Gather inputs

Ask the user for:
1. **Skill name** — kebab-case identifier (e.g. `my-skill`)
2. **Description** — one sentence + trigger phrases (auto-loaded on these phrases)
3. **Purpose** — what the skill does and when it fires

Validate the name immediately:
- Pattern: `^[a-z][a-z0-9-]{0,62}[a-z0-9]$` (1-64 chars, lowercase letters/digits/hyphens)
- No leading, trailing, or consecutive hyphens
- Directory name must match skill name (parent dir = `<name>/`)

If validation fails, show the error and ask again. Do not proceed until the name is valid.

Validate the description length:
- Hard limit: **1024 chars** (Codex CLI rejects longer descriptions)
- Warn at > 500 chars; block at > 1024 chars

### Step 2 — Primitive gate (inverse check)

Load the `agentic-primitives` standard and run the inverse check against what the
user described. The check asks: "Is this actually a skill, or does it belong to
another primitive — or to an agent's private helpers?"

| Signal in what the user described | Exit path |
|-----------------------------------|-----------|
| Needs isolated context window / its own budget (C2) | DISPATCH to `agent-forge` |
| Needs different tool permissions (C1) | DISPATCH to `agent-forge` |
| Runs in parallel with sibling agents (C3) | DISPATCH to `agent-forge` |
| Needs info-barrier between instances (C4) | DISPATCH to `agent-forge` |
| Needs its own model, not the caller's (C5) | DISPATCH to `agent-forge` |
| Multi-phase stateful orchestration >3 phases (C6) | DISPATCH to `agent-forge` |
| Pre-action judge/authorization gate before a side effect (C7) | DISPATCH to `agent-forge` |
| Must fire unconditionally regardless of model reasoning | DISPATCH to `hook-forge` |
| User explicitly invokes with `/name` (not auto-matched) | Suggest `command` instead |
| Pure deterministic helper with no model context needed | DISPATCH to `script-forge` |
| **Exactly one agent in this repo would use it; no second consumer is on the horizon** | **DISPATCH to agent-handler pattern** — put it under `agents/<owner-agent>-handlers/<helper>/`, invoked by path from its owner. A skill that only one agent uses widens the auto-discovery surface for zero benefit; keep it structurally private. |
| None of the above apply | CONTINUE — skill is correct |

Ask explicitly: "Which agent(s) or skill(s) would consume this? Name them." If the
answer is one agent and no plausible second consumer, take the agent-handler path —
adding a single-consumer skill widens the auto-discovery surface for zero benefit.

Dispatch is a **soft handoff**: print a clear message explaining which primitive fits better
and why, then stop. Do not silently rewrite the request.

Example dispatch message:
```
This capability needs an isolated context window and a different model tier (C2 + C5).
It should be an Agent, not a Skill.
Recommend: invoke `agent-forge` to scaffold it correctly.
```

### Placement gate (run before writing)

Use `standards/agentic-primitives/primitive-placement.md` before writing files.
Record the placement decision in the generated catalog snippet or handoff text:

1. **Steward marketplace:** `library-platform` for platform self-description
   primitives; otherwise `cognovis-core`, `sussdorff-core`, a third-party
   source, or `repo-local`.
2. **Plane:** dev-plane Library primitive or product-plane runtime feature.
3. **Product counterpart:** if the dev skill supports runtime product work,
   capture `repo`, `path`, `name`, `primitive_type`, and `notes` for
   `metadata.library.product_counterpart`. Put bead or ADR references in `notes`.
4. **Repo-local escape hatch:** if the skill is path-heavy, ADR-heavy, credential-
   heavy, or only meaningful in one repo, stop global marketplace scaffolding and
   keep it as a repo-local overlay.
5. **Harness support:** ask whether the skill works in all harnesses or is
   harness-specific. For one-harness skills, set
   `metadata.library.harness_support.<harness>: supported` and mark the others
   `not-supported`.
6. **Runtime requirements:** ask whether the skill needs external binaries such
   as `bun`, `rg`, `sushi`, or `shellcheck`; if yes, declare them under
   `runtime_requirements.binaries`.
7. **Gas City projection:** if exportable, name the PackV2 target and operational
   city scope; projection metadata belongs in `library.yaml`.
8. **Deterministic script routing:** if the value is repeatable parsing, scanning,
   validation, export, or transformation, dispatch to `script-forge` or bundle a
   Python script before adding prompt prose.

If the answer is product-plane runtime behavior, do not create a Library skill.
Say: "This is product-plane work, not a Library primitive. Create or reference a
product repo bead, and use `metadata.library.product_counterpart` only from a
supporting dev-plane primitive."

### Action Boundary Gate (run before writing)

Ask: "Does this skill produce side effects beyond read-only analysis or draft-only
local content?"

If the answer is no, omit `action_boundary`.

If the answer is yes, require the skill frontmatter to declare:

```yaml
action_boundary:
  risk_class: external-side-effect
  effect_type: messaging
  proposal_schema: standard://judge-layer/proposals/action-proposal.v1
  judge: agent://judge-default
  requires_mandate: true
```

Allowed `risk_class` values:
- `read-only`
- `reversible-write`
- `external-side-effect`
- `high-risk`

Allowed `effect_type` values:
- `filesystem`
- `network`
- `financial`
- `messaging`
- `credential`
- `other`

Rules:
- Use `read-only` only when the skill cannot write, send, mutate, purchase, delete,
  publish, authenticate, or contact an external system.
- Use `reversible-write` for local filesystem edits or draft artifacts that can be
  reviewed before external release.
- Use `external-side-effect` for messages, network writes, publishing, API mutation,
  or any irreversible action outside the local workspace.
- Use `high-risk` for financial, credential, legal, safety, regulated, or privileged
  operations.
- Set `requires_mandate: true` for `external-side-effect` and `high-risk`.
- Use `proposal_schema: standard://judge-layer/proposals/action-proposal.v1` unless
  a specialist standard explicitly supersedes it.
- Use `judge: agent://judge-default` unless a specialist judge exists.
- Do not use the obsolete `class:` field; the current contract is `risk_class`.

### Step 3 — Determine script scaffold need

If the user's purpose involves deterministic logic (parsing, scanning, computing) over
**50 lines** of estimable code:
- Propose a Python script filename (`scripts/<name>.py`)
- If the helper is reusable across primitives or should be cataloged/exported on its
  own, dispatch to `script-forge` and make it a first-class `library.scripts` entry.
- If the helper is private to this skill, keep it bundled under `skills/<name>/scripts/`
  and declare it in the Library catalog entry's `scripts:` list.
- Ask which output contract applies:
  - **Bare value** — single output, no meaningful failure modes (just `print` it)
  - **JSON envelope** — multiple fields or distinguishable failure modes
    (`{"status":"ok|warning|error","summary":"...","data":{...},"errors":[],"next_steps":[]}`)
- Scaffold a stub script file with the chosen contract
- Register it under `## Resources` in the SKILL.md

### Step 4 — Placement, packability, and provider-neutrality gate

Ask these questions before writing the final file:

1. **Placement already decided?** Carry forward steward marketplace, plane,
   product counterpart, repo-local escape, Gas City projection, and script route
   from the placement gate.
2. **Provider-neutral?** Does the core skill avoid Claude/Codex-specific tool names,
   model names, and provider auth assumptions? If no, move those details into a
   harness adapter or agent/provider config.
3. **Gas City export?** Should this skill be exportable to a Gas City PackV2 pack?
4. **Target surface?** If exportable, choose one: `skill`, `command`, `doctor`,
   `formula`, `overlay`, `asset`.
5. **Pack and scope?** Choose pack (`cognovis-base`, `cognovis-specs`, etc.) and
   scope (`city`, `rig`, `provider`, `global`).
6. **Runtime requirements?** List binaries, environment variable names, and standards
   needed by the exported pack surface. Do not put secret values in metadata.

Gas City metadata belongs in the `library.yaml` catalog entry under
`metadata.library.gascity`, not in provider-specific prompt prose.

### Step 5 — Generate SKILL.md

Write `skills/<name>/SKILL.md` with the following structure. The description
follows the **two-contracts shape**: every description includes `use when` /
`NOT for` / `boundary` — the three signals the router needs to disambiguate.
Body of the skill is the **execution contract** (inputs, outputs, exclusions,
short workflow); methodology is NOT in the body.

```markdown
---
name: <name>
description: >-
  use when: <concrete trigger pattern this routes for — not adjectives>
  NOT for: <adjacent concerns this is wrong for — at least one hard exclusion>
  boundary: <how this differs from <neighboring-skill> in the catalog>
requires_standards: [english-only, no-emoji]
compatibility: {}
metadata: {}
# Include only when Action Boundary Gate classifies the skill as side-effecting:
# action_boundary:
#   risk_class: external-side-effect
#   effect_type: messaging
#   proposal_schema: standard://judge-layer/proposals/action-proposal.v1
#   judge: agent://judge-default
#   requires_mandate: true
---

# <Title>

<One-line purpose statement.>

## Inputs

- <What the consumer must provide before invoking>

## Outputs

- <What this skill produces>

## Exclusions

- <What this skill explicitly will NOT do, even if asked>

## Workflow

<Short imperative steps — the execution contract. Body MUST stay under ~50 lines
total after the frontmatter (thin-shell rule). If methodology is longer, extract
to a `domain:` standard via `standard-forge` and reference it via
`requires_standards:`. No fenced code blocks with >5 lines of logic — call a
script from Resources.>

## Do NOT

- <Anti-pattern 1>
- <Anti-pattern 2>

## Resources

| File | Purpose |
|------|---------|
```

**Frontmatter field notes:**
- YAML scalar safety — quote scalar values that contain brackets, braces,
  colons, hash signs, or command-like placeholders. For example, write
  `argument-hint: "[subcommand] [args]"`, not
  `argument-hint: [subcommand] [args]`. Run `validate-skill.py --strict`
  before installing; invalid frontmatter makes harnesses skip the skill.
- `model:` — **DO NOT include.** Model selection belongs to the agent that consumes the skill,
  not to the skill itself. Adding `model:` makes the skill harness-dependent (Claude Code-only)
  and prevents it from running under Codex, Cursor, or any other harness. Skills are
  harness-agnostic context files — never model-pinned.
- `disableModelInvocation:` — **AVOID for new skills.** Semantics are harness-contested
  (Claude Code Issues #26251 / #19141 / #22345) and the open `agentskills.io` standard
  does not define it. If a skill should not be auto-discoverable, it should not be a
  skill — put it under `agents/<owner>-handlers/<helper>/` instead. May survive on
  pre-existing skills during migration.
- `requires_standards:` — list every `domain:` standard whose body the skill needs at
  runtime. Extracting methodology into standards is the path that lets the body stay
  thin (under the ~50-line cap). Add `judge-layer` when the skill declares
  `action_boundary`.
- `action_boundary:` — required for side-effecting skills. Use `risk_class`,
  `effect_type`, `proposal_schema`, `judge`, and `requires_mandate`; never use the
  obsolete `class:` field. See `references/action-boundary.md`.
- `compatibility: {}` — agentskills.io standard field (currently unused; scaffold it for future use)
- `metadata: {}` — agentskills.io metadata placeholder. Gas City pack metadata
  belongs in the `library.yaml` catalog entry under `metadata.library.gascity`,
  not in provider-specific prompt prose.
- `globs:` — omit unless the skill should trigger on specific file patterns (Cursor 2.2+ fallback)
- `allowed-tools:` — agentskills.io hyphenated form; emit alongside `tools:` (Claude extension) when the skill restricts tools, otherwise omit both
- `tools:` — Claude extension form; emit alongside `allowed-tools:` when restricting tools

**Dual install path note** (print after scaffolding):
```
Dual install paths for this skill:
  Canonical:  .agents/skills/<name>/   (Library convention)
  Bridge:     .claude/skills/<name>/   (Claude Code harness fallback)
Copy SKILL.md to both locations when deploying.
```

### Step 6 — Scaffold test fixture

Create `skills/<name>/tests/<name>.test.md`:

```markdown
# Test Fixture: <name>

## Test 1 — Happy path

**Input:** <concrete trigger phrase>
**Expected behavior:** <what the model should do>
**Pass criteria:** <how to verify>

## Test 2 — Edge case

**Input:** <edge case trigger>
**Expected behavior:** <what the model should do>
**Pass criteria:** <how to verify>
```

### Step 7 — Print library.yaml snippet

After scaffolding, print the library entry for copy-paste:

```yaml
    - name: <name>
      description: >-
        <description>
      source: https://github.com/cognovis/library-core/blob/main/skills/<name>/SKILL.md
      requires:
        - "standard:english-only"
      scripts:
        - path: scripts/<helper>.py
          role: helper
          entrypoint: false
          language: python
          output_contract: json-envelope
      metadata:
        library:
          plane: dev
          product_counterpart:
            repo: <product-repo>
            path: <product-path>
            name: <product-feature-or-artifact>
            primitive_type: <agent|skill|command|workflow|pack|service|other>
            notes: <why this dev-plane skill supports the product surface>
          gascity:
            exportable: <true|false>
            projections:
              - target: <skill|command|doctor|formula|overlay|asset>
                pack: <pack-name>
                scope: <city|rig|provider|global>
                session_class: none
                provider_neutral: true
      tags:
        - origin:original
        - tier:domain
```

Omit `scripts:` when no bundled script exists. Omit `product_counterpart:` when
there is no paired product-plane artifact. Omit or set `exportable: false` when
the skill should not appear in a Gas City pack. Legacy `gascity.target`,
`gascity.pack`, and `gascity.scope` may remain on existing catalog entries, but
new snippets should use `gascity.projections[]`.

### Step 8 — Auto-validate

Run the validator on the new skill:

```bash
python3 skills/skill-forge/scripts/validate-skill.py skills/<name>/ --strict
```

Exit 0 = clean. Fix any findings before reporting success.

---

## Mode 2: validate \<name\>

Single-skill check via the deterministic validator.

```bash
python3 skills/skill-forge/scripts/validate-skill.py skills/<name>/
python3 skills/skill-forge/scripts/validate-skill.py skills/<name>/ --strict
```

Exit 0 = clean. Exit 1 = blocking finding (or any finding in `--strict` mode).
Exit 2 = file not found / parse error.

Report findings verbatim. Suggest scripts/ extraction for EXTRACTABLE_CODE violations.

---

## Mode 3: audit-fleet

Run the bundled deterministic scanners directly:

```bash
bash skills/skill-forge/scripts/scan-skills.sh
python3 skills/skill-forge/scripts/scan-codex-compat.py
```

Use the output to report skill discovery, description hard-limit checks,
extractable-code detection, and Codex portability findings. Do not dispatch to a
separate `skill-auditor` agent; that worker has been retired.

---

## Promote a Reference to a Standard

When a `references/<file>.md` inside a skill becomes useful to other skills,
agents, or projects, promote it to a Library standard. The structural diff is
ownership and addressability — content does not change.

### Promotion criteria (any one is enough)

- Two or more skills or agents would benefit from the same content
- A project's `AGENTS.md` wants to enforce the content baseline-wide
- The content needs its own version history independent of the source skill

### Choose the standard kind

| Content shape | Kind | Frontmatter |
|---------------|------|-------------|
| Body of knowledge about a topic | Domain | `domain: <identifier>` |
| Convention or prohibition | Rule | `rule: <identifier>` |

### Mechanics

1. Move file: `skills/<skill>/references/<file>.md` → `standards/<identifier>/<identifier>.md`
2. Add frontmatter (`domain:` or `rule:` + `description:`) to the new entry file
3. If detail topics exist, split them into sibling `.md` files in the same folder
4. If the rule can be enforced deterministically, ship `standards/<identifier>/scripts/check-<id>.py`
5. Add a catalog entry to `library.yaml` under `library.standards:`
6. Add `requires_standards: [<identifier>]` to every skill that uses the content
7. Remove the original `references/<file>.md` from the source skill
8. Update intra-skill links to rely on `requires_standards` for injection

### Demotion (inverse)

If only one primitive still uses a standard, fold it back into that skill's
`references/`. Drop the catalog entry. Remove `requires_standards:` declarations.

See `meta/docs/PRIMITIVES.md` §7 for full maturity-arc rationale.

## Related Skills

When a skill's core action is calling a cognovis-tools MCP tool, use
`mcp-tool-forge` to author the tool first. Skill prose that calls MCP tools
should reference the tool's SKILL.md for the contract.

## Do NOT

- Scaffold agents when a skill is sufficient — run the primitive gate first
- Scaffold a skill for a helper used by exactly one agent — that is an agent-private
  helper under `agents/<owner-agent>-handlers/<helper>/`, not a skill
- Allow a SKILL.md body to exceed ~50 lines after the frontmatter — extract
  methodology to a `domain:` standard via `standard-forge` and reference it via
  `requires_standards:` (thin-shell rule)
- Embed >5 lines of Python or >10 lines of shell logic in the SKILL.md body
- Accept skill names with uppercase, spaces, or consecutive hyphens
- Add `model:` to the scaffolded SKILL.md — skills are harness-agnostic; model selection is the agent's responsibility
- Add `disableModelInvocation: true` to a NEW skill — it is harness-contested
  (Claude Code Issues #26251 / #19141 / #22345) and not in the open `agentskills.io`
  standard. Use structural separation (agent-handler pattern) instead.
- Accept descriptions > 1024 chars (Codex CLI hard limit)
- Accept descriptions that lack the three two-contracts signals (`use when`,
  `NOT for`, `boundary`) — the router needs all three to disambiguate
- Skip auto-validate after creation
- Promote a reference to a standard before a second consumer needs it — wait until promotion criteria are actually met

## Resources

| File | Purpose |
|------|---------|
| `assets/skill-template.md` | Starter SKILL.md template including optional action_boundary shape |
| `scripts/validate-skill.py` | Deterministic EXTRACTABLE_CODE validator (single skill) |
| `scripts/scan-skills.sh` | Discover all skills, measure tokens/lines (fleet) |
| `scripts/scan-codex-compat.py` | Codex portability scanner |
| `references/action-boundary.md` | Side-effect classification and judge-routing guidance |
| `references/skill-script-first.md` | Authoring guidance for the script-first rule |
| `tests/skill-forge.test.md` | Test fixtures for skill-forge itself |
