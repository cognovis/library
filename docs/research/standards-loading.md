# Standards Loading Mechanism: Design + Prototype

> **Bead:** CL-v56 | **Epic:** CL-36o (Multi-Harness Library) | **Date:** 2026-04-30
> **Status:** NORMATIVE — this document is the design decision record for cross-harness
> standards loading. It supersedes the hook-injection-only approach currently in
> `~/.claude/standards/`.
>
> **Depends on:**
> - `docs/PRIMITIVES.md` §7 Standard — defines the STANDARD primitive
> - `docs/policy/name-collision.md` — project-local > global precedence rule
> - `tests/smoke/run-smoke.sh` smoke_standards() — validates structural guarantees

---

## Executive Summary

The current inject-standards hook is Claude Code-only. Codex, OpenCode, and Pi cannot
benefit from project-specific behavioral standards. This bead evaluates four candidate
mechanisms and selects a recommended approach.

**Decision**: Implement **Mechanism (d) Hybrid** — primary adapter generation into
`AGENTS.md`/`CLAUDE.md` at install time (mechanism a), with skill-script-side loader
as the runtime fallback (mechanism b). This combination delivers deterministic context
injection for session-start standards while preserving skill-specific runtime loading.

---

## Loader Contract

This section defines the behavioral contract that any standards-loading implementation
MUST satisfy, regardless of which mechanism is used.

### Path Resolution

Standards are resolved in the following order, highest priority first:

| Priority | Path | Scope |
|----------|------|-------|
| 1 (wins) | `.agents/standards/<name>.md` | Project-local |
| 2 | `~/.agents/standards/<name>.md` | User-global |

**Rule**: Project-local **always** overrides global for the same standard name.
This is consistent with the name-collision precedence policy in
`docs/policy/name-collision.md` (CL-b4o).

**Canonical path convention**: `.agents/standards/<name>.md` is the primary path.
For Claude Code legacy compatibility, standards may also exist at
`~/.claude/standards/<domain>/<name>.md` — this path is consulted ONLY if no
`.agents/standards/<name>.md` path exists (fallback for migration period).

**Path resolution algorithm** (implemented in `scripts/standards-loader.sh`):

```
For each standard name in requires_standards:
  1. Check ${PROJ_ROOT}/.agents/standards/<name>.md   → use if exists
  2. Check ~/.agents/standards/<name>.md               → use if exists
  3. Check ~/.claude/standards/<domain>/<name>.md      → use if exists (legacy fallback)
  4. None found → emit warning to stderr, continue
```

### Missing Standard

**Behavior**: Warn and continue. Do NOT fail-loud.

**Rationale**: A missing standard means the model gets less context, not broken behavior.
Failing-loud on a missing standard would block all skill invocations in projects that
have not yet migrated — too disruptive during the transition period.

**Warning format** (emitted to stderr):

```
[standards-loader] WARNING: standard '<name>' not found. Checked:
  - <proj>/.agents/standards/<name>.md
  - ~/.agents/standards/<name>.md
  - ~/.claude/standards/ (legacy)
Proceeding without this standard.
```

**Future evolution**: Once migration to `.agents/standards/` is complete and the
Claude Code hook is removed, this can be changed to fail-loud for all harnesses.

### Merge Order

When multiple standards apply (e.g., a skill declares
`requires_standards: [dolt-server, branch-naming]`):

1. Standards are loaded in the order declared in `requires_standards`.
2. If the same standard is declared multiple times (across nested skill dependencies),
   it is loaded exactly once (deduplicate by name, first declaration wins).
3. No merging of conflicting content: standards are concatenated, not merged.

**Concatenation order** (for adapter generation into AGENTS.md):

```
# <standard-1-name>
<content of standard 1>

---

# <standard-2-name>
<content of standard 2>
```

### Validation

Standard files MUST have valid YAML frontmatter with at least:

```yaml
---
name: <string>          # required — must match the filename stem
version: <string>       # required — semver or calver (e.g., "1.0.0" or "2026-04-30")
description: <string>   # required — one-line summary of what this standard covers
---
```

Optional frontmatter fields:

```yaml
scope: project | global | harness   # default: project
harnesses: [claude-code, codex, pi, opencode]  # default: all
deprecated: true | false            # default: false
replaces: <standard-name>           # for migration: name of the standard being replaced
```

**Validation behavior**: Invalid frontmatter (missing required fields) produces a
warning to stderr. The standard is still loaded — malformed frontmatter should not
block context delivery.

### Caching

**Policy**: Re-read on every invocation. No session-level cache.

**Rationale**:
- Standards files are small markdown documents (typically < 5 KB).
- Re-reading on every invocation guarantees freshness after a `/library sync`.
- Session-level caching would require invalidation logic that adds complexity
  without proportionate benefit.

**Exception**: Adapter generation (mechanism a) writes a compiled artifact at install
time. The artifact is cached until `/library use` or `/library sync` is re-run. This
is intentional: the compiled AGENTS.md section reflects the standards available at
install time, not at every session start.

### Compatibility Mode

During the migration period, the following compatibility behaviors apply:

1. **Legacy inject-standards hook**: The Claude Code SessionStart hook at
   `~/.claude/settings.json` continues to work unchanged. It reads from
   `~/.claude/standards/` and injects into context via hook mechanism.
   This is NOT being removed — it is being supplemented.

2. **Fallback path**: `standards-loader.sh` checks `~/.claude/standards/<domain>/`
   as the lowest-priority fallback. This ensures that standards already migrated
   to `~/.claude/standards/` continue to work for harnesses that use the script-side
   loader.

3. **Deprecation timeline**:
   - Phase 1 (now, CL-v56): Introduce `.agents/standards/` convention. Both paths work.
   - Phase 2 (CL-717): Migrate all existing skills to use `requires_standards` frontmatter.
   - Phase 3 (post-CL-717): Deprecate inject-standards hook. Remove from Claude Code
     settings. Legacy path becomes read-only reference.
   - Phase 4 (TBD): Remove legacy path entirely once all projects have migrated.

---

## Candidate Mechanism Evaluation

### Mechanism (a): Generated Harness-Native Adapter

**Description**: At `/library use` install time, the Library reads all standards
declared in a skill's `requires_standards` frontmatter, concatenates their content,
and writes a section into the harness-native instruction file:
- `AGENTS.md` (shared by both Claude Code and Codex)
- `CLAUDE.md` (Claude Code only, for project-specific extensions)

**Implementation**: `scripts/standards-loader.sh --generate-adapter <skill-name>`
reads the skill's `requires_standards`, resolves each standard file, and appends
a delimited section to `AGENTS.md`.

**Pros:**
- Fully deterministic: standards are in context at session start, no model action needed.
- Works for ALL harnesses that read `AGENTS.md` (Claude Code and Codex confirmed;
  Pi and OpenCode likely, pending verification).
- No runtime overhead: context is pre-compiled.
- Human-readable: standards are visible in `AGENTS.md` for onboarding.

**Cons:**
- Install-time coupling: `AGENTS.md` must be regenerated after every `/library sync`.
- `AGENTS.md` can become large if many standards are installed (Codex 32 KiB limit).
- Standards in `AGENTS.md` are always present in context — no per-invocation scoping.
  A skill's dolt standard appears even in sessions where dolt is not used.

**Portability:** NORMATIVE for Claude Code + Codex. INFERRED for Pi/OpenCode.

**Verdict: RECOMMENDED as primary mechanism.**

---

### Mechanism (b): Skill-Script-Side Loader

**Description**: Each skill's `scripts/` directory contains (or imports) a loader
that reads `.agents/standards/<name>.md` at runtime and injects the content into
the model's context via the skill's SKILL.md template or via a Bash `read` call
that the model executes as part of the skill workflow.

**Implementation**: `scripts/standards-loader.sh --load <standard-name>` resolves
and cats the standard file. Skills call this via:

```bash
# In a skill's bin/ script or SKILL.md instructions:
STANDARD_CONTENT=$(bash scripts/standards-loader.sh --load dolt-server)
# Pass $STANDARD_CONTENT to the model prompt
```

**Pros:**
- Per-invocation: standard content is loaded only when the skill is actually used.
- No `AGENTS.md` bloat: standards don't accumulate in the session file.
- Works for any harness that gives the model Bash/Read tool access.
- Easy to test: `standards-loader.sh --load <name>` is a simple shell command.

**Cons:**
- Requires model cooperation: the model must actually execute the loader call.
  If the model skips the skill's initialization script, the standard is not loaded.
- Not deterministic at session start: the standard is loaded mid-session.
- More complex skill authoring: every skill using standards must include the loader call.

**Portability:** Requires Bash access. Works for Claude Code + Codex. Pi/OpenCode: SKIP.

**Verdict: RECOMMENDED as secondary/fallback mechanism (covers skill-specific standards
not suitable for the global AGENTS.md context).**

---

### Mechanism (c): Guardrail-Enforced Loading

**Description**: A SessionStart-equivalent guardrail per harness reads all standards
declared in `library.yaml` (or a dedicated `standards.yml`) and injects them into
the model context at session start, before any user prompt is processed.

**Implementation**: Extend the existing Claude Code SessionStart hook to also read
from `.agents/standards/`. For Codex, use the Codex `SessionStart` hook event
(one of 3 supported hook events per `docs/research/codex-prompts.md`).

**Pros:**
- Most deterministic: fires before any model reasoning.
- Natural extension of existing Claude Code hook infrastructure.
- Standards are injected regardless of which skill is invoked.

**Cons:**
- Claude Code: already implemented (the existing inject-standards hook IS this
  mechanism). Adding `.agents/standards/` path support is a small change.
- Codex: SessionStart hook exists but requires a `hooks.json` file in the plugin
  or Codex config. This works only for installed plugins, not standalone projects.
- Pi + OpenCode: NO SessionStart hook equivalent. This mechanism is not portable
  to all four harnesses.
- Same "always in context" problem as mechanism (a): all standards loaded regardless
  of which capability is being invoked.

**Portability:** Claude Code (NORMATIVE). Codex (INFERRED — requires hooks.json).
Pi + OpenCode: NOT SUPPORTED.

**Verdict: VIABLE for Claude Code + Codex but not cross-harness portable. Do not
use as the primary mechanism. Retain existing Claude Code hook as compatibility layer.**

---

### Mechanism (d): Hybrid

**Description**: Combine mechanism (a) as primary (adapter generation into AGENTS.md
at install time) with mechanism (b) as secondary fallback (skill-script-side loader
for skills with standards not suitable for global injection).

**Implementation**: 
- `/library use <name>` calls `standards-loader.sh --generate-adapter <skill-name>`
  to append the skill's required standards to `AGENTS.md`.
- Individual skills can call `standards-loader.sh --load <standard-name>` for
  runtime loading of skill-specific standards not in the global AGENTS.md section.
- Mechanism (c) (Claude Code SessionStart hook) continues in parallel for
  backward compatibility.

**Pros:**
- Best of (a) and (b): session-start standards via AGENTS.md, skill-specific runtime
  loading when needed.
- Backward compatible: existing Claude Code hook keeps working.
- Incremental migration: skills can adopt `requires_standards` one at a time.
- Cross-harness: AGENTS.md works for both Claude Code and Codex.

**Cons:**
- Two code paths to maintain (adapter generator + runtime loader).
- AGENTS.md still accumulates all install-time standards.
- Developer must know which standards go in AGENTS.md vs. runtime.

**Portability:** Claude Code + Codex (via AGENTS.md). Pi/OpenCode: mechanisms (a)
generates AGENTS.md which they may read (pending harness verification).

**Verdict: RECOMMENDED — this is the selected approach.**

---

## Recommended Choice: Mechanism (d) Hybrid

### Decision

Implement **Mechanism (d) Hybrid** as the primary standards-loading approach.

**Rationale:**

1. **Cross-harness portability without harness-specific code.** `AGENTS.md` is the
   one file that all four harnesses are documented to read (NORMATIVE for Claude Code
   and Codex; INFERRED for Pi and OpenCode). Mechanism (a) uses this to deliver
   session-start standards without any harness-specific hook configuration.

2. **Determinism without hook dependency.** Mechanism (c) (hooks) is the most
   deterministic but least portable. Mechanism (a) achieves the same determinism
   at session start via file-based injection, which works everywhere.

3. **Runtime flexibility.** Mechanism (b) provides a safety net for skill-specific
   standards that would bloat AGENTS.md if installed globally (e.g., a dolt standard
   is relevant only when the dolt skill is active).

4. **Backward compatibility.** The existing Claude Code inject-standards hook is NOT
   removed. It continues to serve Claude Code-only projects that have not yet migrated.
   New projects use the `.agents/standards/` convention via mechanism (d).

5. **Incremental migration path.** CL-717 (skill migration) can adopt
   `requires_standards` one skill at a time. No flag day required.

### Scope of This Bead

CL-v56 delivers:
1. This design document (the loader contract above).
2. `scripts/standards-loader.sh` — prototype implementing mechanisms (a) and (b).
3. Smoke tests in `tests/smoke/run-smoke.sh` (smoke_standards).
4. Updated trigger semantics in `docs/PRIMITIVES.md` §7 Standard.

CL-v56 does NOT deliver:
- Migration of existing skills to `requires_standards` frontmatter (CL-717).
- Removal of inject-standards hook (post-CL-717).
- Integration of `standards-loader.sh` into `/library use` cookbook (follow-up bead).
- Harness verification for Pi and OpenCode (requires live sessions).

---

## standards/index.yml Schema

The `standards/index.yml` (or `.agents/standards/index.yml`) file maps standard names
to trigger conditions and file paths. This schema is used by the adapter generator
and the runtime loader to discover available standards.

**File location**: `.agents/standards/index.yml` (project-local) or
`~/.agents/standards/index.yml` (user-global).

**Schema** (YAML):

```yaml
# .agents/standards/index.yml
standards:
  <standard-name>:
    description: "<one-line description>"
    triggers:                         # optional — used by hook-based injection
      - "<keyword>"
    path: "<name>.md"                 # relative to this index.yml's directory
    scope: project | global           # default: project
    harnesses:                        # optional — list of supported harnesses
      - claude-code
      - codex
```

**requires_standards frontmatter** (in SKILL.md):

```yaml
---
name: dolt
description: Dolt version-controlled database skill.
requires_standards: [dolt-server, branch-naming]
---
```

The `requires_standards` list is the primary input to `standards-loader.sh`. Each
name is resolved via the path resolution algorithm defined in the Loader Contract above.

---

## Prototype Implementation Notes

The prototype `scripts/standards-loader.sh` implements two operations:

### Operation 1: `--load <standard-name>`

Mechanism (b) — skill-script-side loader.

```bash
bash scripts/standards-loader.sh --load dolt-server
```

Resolves `dolt-server` via the path resolution algorithm, cats the file to stdout.
If not found, emits a warning to stderr and exits 0 (warn-and-continue policy).

### Operation 2: `--generate-adapter <skill-name> [--target <file>]`

Mechanism (a) — adapter generation.

```bash
bash scripts/standards-loader.sh --generate-adapter dolt --target AGENTS.md
```

Reads the skill's `requires_standards` frontmatter, loads each standard via the
path resolution algorithm, concatenates them, and appends a delimited section to
the target file (default: `AGENTS.md`).

The generated section is delimited for idempotent regeneration:

```
<!-- BEGIN STANDARDS dolt -->
# Standard: dolt-server
<content>
---
# Standard: branch-naming
<content>
<!-- END STANDARDS dolt -->
```

Re-running `--generate-adapter` replaces the existing section (idempotent).

### Operation 3: `--list`

Lists all available standards by scanning `.agents/standards/` and
`~/.agents/standards/` directories.

```bash
bash scripts/standards-loader.sh --list
```

---

## Cross-References

- `docs/PRIMITIVES.md` §7 Standard — STANDARD primitive definition
- `docs/policy/name-collision.md` — project-local > global precedence rule (CL-b4o)
- `scripts/standards-loader.sh` — prototype implementing mechanisms (a) and (b)
- `tests/smoke/run-smoke.sh` `smoke_standards()` — structural validation
- `AGENTS.md` — harness-native instruction file (target for mechanism a)
- CL-717 — follow-up bead: migrate existing skills to `requires_standards` frontmatter
- CL-9b1 — depends on this: Model-Standards reuses this loader for model-standard injection

### Bead context

- `CL-v56` — this bead
- `CL-cmz` — PRIMITIVES.md (defines STANDARD primitive, depended on here)
- `CL-zda` — cross-harness smoke fixtures (smoke infrastructure used by smoke_standards)
- `CL-b4o` — name-collision policy (project-local > global precedence rule reused here)
- `CL-t21` — lockfile (install-time artifact tracking; adapter generation writes to AGENTS.md
  which should be tracked as a non-lockfile artifact)

---

### Debrief

**Key decisions:**

1. Mechanism (d) Hybrid was chosen over pure mechanism (c) (hooks) because hooks require
   harness-specific configuration and are not portable to Pi/OpenCode. AGENTS.md is the
   one cross-harness injection point that requires no harness-specific wiring.

2. Warn-and-continue for missing standards was chosen over fail-loud to avoid breaking
   existing projects that have not migrated to `.agents/standards/`. This can be
   tightened to fail-loud after CL-717 completes migration.

3. The `.agents/standards/<name>.md` path (flat, no domain subdirectory) was chosen
   over the `~/.claude/standards/<domain>/<name>.md` nested path. Rationale: cross-harness
   convention should be as simple as possible. The domain subdirectory in the legacy Claude
   path adds complexity without benefit for discovery (names are already unique).

4. Adapter generation targets `AGENTS.md` (shared) rather than `CLAUDE.md` (Claude-only)
   as the primary target. This ensures Codex also gets the adapter content without a
   separate code path. CLAUDE.md generation is reserved for Claude Code-specific overrides.

**Challenges:**

- The `requires_standards` frontmatter field in SKILL.md creates a tension with the
  Metadata note in PRIMITIVES.md §7: "Library-owned metadata lives in Library's own
  namespace. Do NOT pollute standard SKILL.md frontmatter fields with Library-internal
  metadata." Resolution: `requires_standards` is a skill-authoring field (belongs in
  the skill definition), not a Library install-time metadata field. It is conceptually
  equivalent to `dependencies` in package.json — part of the skill's definition, not
  the Library's tracking data. The PRIMITIVES.md §7 note applies to install-tracking
  metadata (e.g., `installed_by`, `library_version`), not skill-declared dependencies.

- AGENTS.md size limit: Codex has a 32 KiB `project_doc_max_bytes` limit. If many
  standards are installed, the accumulated content could exceed this. Mitigation: the
  adapter generator should check AGENTS.md size after writing and warn if the limit
  is approached. Actual enforcement deferred to CL-717.

**Surprising findings:**

- The Codex SessionStart hook does exist (confirmed in `docs/research/codex-prompts.md`),
  but requires a `hooks.json` in the plugin config — it cannot be added to a standalone
  project without creating a plugin artifact. This makes mechanism (c) much less attractive
  for Codex than initially assumed.

- `AGENTS.md` is already read by both Claude Code and Codex (NORMATIVE from
  `docs/research/codex-prompts.md`). This makes mechanism (a) effectively cross-harness
  today, without any new harness-specific code. The adapter generator just needs to
  write into this already-shared file.

**Follow-up items:**

- CL-717: Migrate existing skills to `requires_standards` frontmatter.
  Candidates: core:dolt (needs dolt-server standard), core:session-close (needs
  branch-naming standard).
- Update `/library use` cookbook to call `standards-loader.sh --generate-adapter`
  as Step N of the install procedure.
- Verify Pi and OpenCode read AGENTS.md (pending live harness sessions).
- Define AGENTS.md size budget and add size check to adapter generator.
- Add `standards: []` section to `library.yaml` to track installed standards entries.
