# Name Collision and Precedence Policy

> **Status**: NORMATIVE — this document is the authoritative policy for how the
> cognovis-library handles skill name collisions across harness paths.
>
> **Bead**: CL-b4o | **Epic**: CL-36o | **Last updated**: 2026-04-30
>
> **Applies to**: `/library skill use`, `/library skill remove`, `/library sync`, and any
> tooling that installs or manages skills, agents, or prompts across harnesses.

---

## Quick Reference: Decision Tree

```
A skill, agent, or prompt with this name already exists somewhere. What do I do?

Is this an agent or prompt already installed at the target from a different source?
 └─ YES → Cross-marketplace agent/prompt collision (Decision 8):
           Stop. Do not silently overwrite.
           Choose --replace, --merge-into=<canonical-repo>, or --skip.
 └─ NO  → Continue with the skill-specific checks below when installing a skill.

Is the collision within the same harness (same path prefix)?
 └─ YES → Same-harness collision (Decision 1):
           Project-local wins over global ALWAYS.
           More specific scope wins over less specific.
 └─ NO  → Cross-harness collision (Decision 4):
           .agents/skills/foo is canonical (real files / Layer-B symlink).
           Both harnesses see it: Codex natively (r1 root), Claude via the
           bridge symlink at .claude/skills/foo -> .agents/skills/foo.
           One real copy, two resolution paths, zero drift.

Am I installing a new version of an existing skill?
 └─ YES → Versioned collision (Decision 5):
           Same path = most recent install wins (overwrite).
           Different paths = see cross-harness rule above.

Am I removing a skill?
 └─ YES → Uninstall rule (Decision 6):
           Remove BOTH canonical and all bridge symlinks.
           Do NOT leave dangling bridges.

Is this a managed/marketplace skill that Anthropic force-enables?
 └─ YES → Admin override (Decision 7):
           Library does NOT override Anthropic's force-enable.
           Treat managed skills as read-only; warn user on conflict.
```

---

## Decision 1: Per-Harness Precedence Rules

### Claude Code

Claude Code loads skills from `CLAUDE.md`-registered paths and the following locations
(in precedence order, highest first):

| Priority | Path | Scope |
|----------|------|-------|
| 1 (wins) | `.claude/skills/<name>/SKILL.md` | Project-local |
| 2 | `~/.claude/skills/<name>/SKILL.md` | User-global |

**Rule**: Project-local **always** overrides global for the same skill name.

**Evidence level**: NORMATIVE — confirmed via Open Agent Skills Standard. Claude Code
loads all installed skills at session start. When both project-local and global exist,
the project-local file is what the model operates from (global is shadowed).

**Example (Claude Code)**:

```
# User has a global version of the "researcher" skill:
~/.claude/skills/researcher/SKILL.md     ← global (shadowed)

# Project has a project-specific override:
.claude/skills/researcher/SKILL.md       ← project-local (WINS for this project)
```

Within this project, the model uses the project-local SKILL.md. Another project
without a local override continues to use the global.

### Codex CLI

Codex 0.130.0 loads skills from multiple roots. The skill roots observed via
`codex debug prompt-input` (empirical, CL-603 smoke test, 2026-05-12):

| Root | Path | Notes |
|------|------|-------|
| r0 (primary) | `~/.codex/skills/` | Always present; user-global primary |
| r1 (secondary) | `~/.agents/skills/` | Included dynamically when directory exists and has content |
| r2 | `~/.codex/skills/.system` | System/bundled skills |
| r3+ | `~/.codex/plugins/cache/...` | Plugin caches |

**Important empirical note** (CL-603, codex 0.130.0; library install policy
updated by CL-83q): The OpenAI docs specify `~/.agents/skills/` as the global
path. `codex debug prompt-input` shows that Codex loads BOTH `~/.codex/skills/`
(r0) and `~/.agents/skills/` (r1) when present. The library installs ONLY to
`~/.agents/skills/` (r1) — this is the canonical Codex install path going
forward. `~/.codex/skills/` may still hold legacy installs from earlier
versions of `sync-codex-skills` or the now-retired `global_codex` setting; the
collision check in cookbook/use.md Step 5d offers to remove those.

The project-local path `.agents/skills/` behavior was not verified by smoke test
CL-603 — only the global path was tested.

Precedence for same-named skills within Codex (post-CL-83q install policy):

| Priority | Path | Scope | Library install? |
|----------|------|-------|------------------|
| 1 (wins) | `.agents/skills/<name>/SKILL.md` | Project-local (unverified by CL-603) | Yes (canonical) |
| 2 | `~/.agents/skills/<name>/SKILL.md` | User-global secondary (r1, confirmed CL-603) | Yes (canonical) |
| 3 | `~/.codex/skills/<name>/SKILL.md` | User-global primary (r0, confirmed CL-603) | **No** — legacy only |

**Rule**: Project-local **always** overrides global for the same skill name.
`/library skill use` writes to priority-1 or priority-2 paths depending on scope; it
never installs to `~/.codex/skills/` (Codex reads `~/.agents/skills/` natively,
so the bridge is unnecessary).

**Evidence level**: PARTIAL — Codex root order confirmed empirically (CL-603
smoke test). Project-local `.agents/skills/` follows Open Agent Skills Standard
but was not live-tested in CL-603.

**Example (Codex)**:

```
# User has a global version:
~/.codex/skills/researcher/SKILL.md     ← global primary (r0, WINS over r1)

# Project has a project-specific override:
.agents/skills/researcher/SKILL.md       ← project-local (WINS for this project)
```

---

## Decision 2: Library Policy — Canonical Path and Bridge

When `/library skill use` installs a skill (single workflow for all harnesses — there
is no longer a "dual-install" mode; cross-harness reach is the default):

| Role | Path | Description |
|------|------|-------------|
| **Canonical** | `.agents/skills/<name>/` | Real files (or a symlink into the Layer-B cache, per ADR-0003). This is the source of truth. |
| **Claude bridge** | `.claude/skills/<name>` | Symlink to the canonical path. Claude Code resolves through it. |
| **Codex** | reads `.agents/skills/<name>` directly | No separate install path. Codex 0.130.0+ loads `~/.agents/skills/` as the r1 root (CL-603). |

**Policy**: `.agents/skills/<name>` is canonical. `.claude/skills/<name>` is a
symlink bridge to it. No `.codex/skills/<name>` install target.

**Rationale**:
- `.agents/skills/` is the cross-harness convention (agentskills.io standard).
  Codex reads it natively as the r1 root (CL-603 empirical, 2026-05-12).
- Claude Code does NOT natively read `.agents/skills/`, so it needs a bridge
  symlink at `.claude/skills/<name>`. Claude follows symlinks transparently.
- A single canonical real file (or symlink-into-cache) eliminates drift between
  harnesses.

**Installation sequence** (MANDATORY ORDER):

```
1. Materialize Layer-B cache: ~/.local/share/library/skills/<m>/<n>@<tree-sha>/
2. Point canonical at cache: ln -s <cache> .agents/skills/<name>
3. Create Claude bridge:     ln -s <canonical> .claude/skills/<name>
```

The bridges must be created AFTER the canonical is in place. Reversing the
order produces dangling symlinks.

**Bridge symlink command** (from cookbook/use.md Step 5c):

```bash
canonical_target=".agents/skills/<name>"        # already pointing at cache
claude_bridge_target=".claude/skills/<name>"
mkdir -p "$(dirname "$claude_bridge_target")"
if [ -d "$claude_bridge_target" ] && [ ! -L "$claude_bridge_target" ]; then
  rm -r "$claude_bridge_target"
fi
ln -sfn "$(realpath "$canonical_target")" "$claude_bridge_target"
```

---

## Decision 3: Symlink Preservation

### What happens when the user edits the symlink target?

A Claude bridge symlink at `.claude/skills/foo` points to `.agents/skills/foo`,
which itself points into the Layer-B cache.

If the user edits `.claude/skills/foo/SKILL.md` (through the bridge):
- The edit follows the symlink chain into the Layer-B cache directory.
- Both harnesses immediately see the change (there is only one real file).
- **This is the intended behavior**, although editing the canonical
  `.agents/skills/foo/SKILL.md` directly is cleaner.

If the user replaces a bridge or canonical with a real directory:
- The link chain is broken. Two files now exist independently.
- Drift is possible. `/library sync` will warn.

**Library convention for this case**:
1. Detect (canonical replaced): `[ -d ".agents/skills/foo" ] && [ ! -L ".agents/skills/foo" ]`
   AND the lockfile lists a `cache_path`. The user has materialized a real copy
   over the canonical symlink.
2. Detect (bridge replaced): `[ -d ".claude/skills/foo" ] && [ ! -L ".claude/skills/foo" ]`.
   The user has put real files where the Claude bridge should be.
3. Warn the user: "Skill `<name>` has drifted from the canonical Layer-B
   cache. Run `/library sync <name>` to inspect and reconcile."
4. Never silently overwrite — always warn first.

### Symlink lifecycle rules

| Event | Action |
|-------|--------|
| `/library skill use foo` | Materialize Layer-B cache, create canonical at `.agents/skills/foo` (-> cache), create Claude bridge at `.claude/skills/foo` (-> canonical) |
| User edits through any link | Edit lands on the cache file — correct, no action needed |
| User replaces canonical or bridge with real dir | Warn on next `/library skill use foo` or `/library sync` |
| `/library skill remove foo` | Remove Claude bridge AND canonical symlink AND lockfile entry (see Decision 6); Layer-B cache is GC'd separately |
| `/library sync foo` | Recompute tree-SHA; if changed, materialize new cache + re-point canonical; bridge auto-resolves |

### Git tracking of symlinks

Symlinks are committed to git as mode `120000`. When another developer clones the
repo:
- The symlink is restored exactly.
- The canonical file is also present.
- No post-clone setup needed.

To verify a symlink is correctly tracked:
```bash
git ls-files --stage .agents/skills/foo
# Expected: 120000 <hash> 0   .agents/skills/foo
```

---

## Decision 4: Cross-Harness Name Uniqueness

**Policy: Skill names must be globally unique within a project.**

**Rationale**: The canonical install at `.agents/skills/<name>` is reached by
Codex natively and by Claude Code through the bridge symlink at
`.claude/skills/<name>`. If a second real directory exists at the bridge
path, two copies of the same skill diverge silently. Bug reports become
untriageable.

**Uniqueness scope**: Within a single project (repository). A `researcher`
skill in Project A and a different `researcher` skill in Project B do not
collide.

**Detection in `/library skill use`**:

Before installing, check the canonical and Claude bridge paths:

```bash
canonical_path=".agents/skills/<name>"
claude_bridge_path=".claude/skills/<name>"

canonical_exists=false
canonical_is_link=false
claude_bridge_exists=false
claude_is_bridge=false

[ -d "$canonical_path" ] && canonical_exists=true
[ -L "$canonical_path" ] && canonical_is_link=true
[ -d "$claude_bridge_path" ] && claude_bridge_exists=true
[ -L "$claude_bridge_path" ] && claude_is_bridge=true
```

**Collision scenarios and responses**:

| Scenario | Response |
|----------|---------|
| Neither exists | Fresh install — proceed |
| Canonical is a symlink to cache; Claude is a symlink to canonical | Already installed correctly — refresh canonical; bridge auto-updates |
| Canonical is a real dir (no symlink, no cache) | Legacy install — promote to Layer-B cache + symlink, leave bridge alone |
| Claude bridge is a real dir, canonical absent | Legacy claude-canonical install — migrate content into canonical, replace `.claude/` with bridge |
| Both canonical and Claude bridge are real dirs (neither a symlink) | COLLISION — warn user, do NOT silently overwrite |
| Legacy `.codex/skills/<name>` exists | Warn and offer to remove — Codex reads `.agents/` natively, no Codex install needed |

**Warning message for real-directory collision**:

```
Warning: Name collision detected for skill '<name>':
  .agents/skills/<name>/ exists (real directory)
  .claude/skills/<name>/  exists (real directory, NOT a symlink)

These are two independent copies that may have diverged.
Policy: .agents/skills/<name>/ is canonical.
        .claude/skills/<name>  is the Claude harness bridge symlink.

Options:
  1. Use .agents/ as canonical, replace .claude/ with bridge symlink (recommended)
  2. Use .claude/ as canonical, move content into .agents/ and bridge from .claude/
  3. Keep both as separate files (not recommended — manual maintenance)
  4. Cancel and inspect manually

Default: option 1.
```

**Concrete examples per harness**:

**Standard install (single source of truth)**:
```
~/.local/share/library/skills/<m>/researcher@<tree-sha>/SKILL.md   ← real file (Layer B)
.agents/skills/researcher    ← symlink → Layer-B cache (canonical, Layer C)
.claude/skills/researcher    ← symlink → .agents/skills/researcher (Claude bridge)
```
Codex reads `.agents/skills/researcher/SKILL.md` directly (r1 root).
Claude Code follows `.claude/skills/researcher` → `.agents/skills/researcher` → cache.
Result: one file, two harnesses, zero drift.

**Codex-only example** (no Claude install):
```
.agents/skills/researcher/SKILL.md   ← real file or symlink into cache
```
No collision possible — Claude bridge is not present. Fine; Claude won't see
the skill until a bridge is created.

**Collision example** (BAD — two real directories):
```
.agents/skills/researcher/SKILL.md   ← real file (v1)
.claude/skills/researcher/SKILL.md   ← real file (v2, drifted)
```
Codex sees v1. Claude sees v2 (because its path is real, not a bridge).
This is the bug this policy exists to prevent.

---

## Decision 5: Versioned Installs

**Policy: Version is tracked by content, not by path.**

Paths do not encode version numbers. `.claude/skills/foo/` does not become
`.claude/skills/foo-v2/` for an update.

**Update behavior**:
- `/library skill use foo` on an already-installed skill: overwrite in place (refresh).
- Old SKILL.md is replaced. Old bridges continue to point to the same directory (no
  symlink change needed — the directory remains, only the file inside changes).

**Scenario: v1 in one path, v2 in another**:

```
.agents/skills/foo/SKILL.md     ← v1 (real file, installed earlier)
.claude/skills/foo/SKILL.md     ← v2 (real file, installed later via legacy path)
```

This is the two-real-directories collision described in Decision 4. Resolution:
1. Determine which version is canonical (typically the more recent).
2. Materialize that version into the Layer-B cache (Step 8c).
3. Point `.agents/skills/foo` at the cache via symlink.
4. Replace `.claude/skills/foo/` with a bridge symlink to `.agents/skills/foo`.

**What the model actually gets** (not a naming issue — a load-order issue):

| Harness | Path loaded | Result |
|---------|------------|--------|
| Claude Code | `.claude/skills/foo/SKILL.md` | Resolves through bridge into canonical; gets canonical content |
| Codex | `.agents/skills/foo/SKILL.md` | Native r1 root; gets canonical content |

If the paths are diverged (two real directories, no bridge), each harness gets
its own copy. If the canonical + bridge layout is intact, both harnesses get
the same file.

---

## Decision 6: Uninstall Behavior

**Policy: `/library skill remove` must reverse ALL bridges, not just the canonical.**

When a skill was dual-installed (canonical + bridge), removing only the canonical
leaves a dangling symlink. That dangling symlink will cause Codex to fail on skill
discovery.

**Uninstall sequence** (MANDATORY):

```bash
# 1. Remove the Claude harness bridge first (symlink).
if [ -L ".claude/skills/<name>" ]; then
  rm ".claude/skills/<name>"
fi
# If the bridge was replaced by a real directory at some point, remove it too.
if [ -d ".claude/skills/<name>" ] && [ ! -L ".claude/skills/<name>" ]; then
  echo "Warning: .claude/skills/<name> is a real directory (legacy install) — removing."
  rm -r ".claude/skills/<name>"
fi

# 2. Remove the canonical (a symlink into Layer-B cache, or a legacy real dir).
if [ -L ".agents/skills/<name>" ]; then
  rm ".agents/skills/<name>"
elif [ -d ".agents/skills/<name>" ]; then
  rm -r ".agents/skills/<name>"
fi

# 3. (Optional) Remove legacy ~/.codex/skills/<name> if present.
# Codex reads ~/.agents/skills/ natively (r1 root); this path is no longer
# managed by /library skill use but may exist from older installs.
if [ -e "~/.codex/skills/<name>" ]; then
  echo "Notice: ~/.codex/skills/<name> exists from a legacy install — remove?"
  # prompt user; default yes
fi

# 4. The Layer-B cache entry (~/.local/share/library/skills/<m>/<n>@<sha>/) is
# garbage-collected separately by /library prune-cache once no lockfile entry
# references it. /library skill remove does NOT delete cache content directly.

# 5. Remove the lockfile entry.
yq -i 'del(.installed[] | select(.name=="<name>"))' .library.lock
```

**Global paths**: Same pattern applies for `~/.claude/skills/<name>` (Claude
harness bridge global), `~/.agents/skills/<name>` (canonical global), and
`~/.codex/skills/<name>` (legacy Codex install — remove if present).

**Example — complete removal**:

Before removal:
```
~/.local/share/library/skills/cognovis/researcher@4f8a2b9c/SKILL.md   ← Layer B (real)
.agents/skills/researcher            ← canonical (symlink -> Layer B)
.claude/skills/researcher            ← Claude bridge (symlink -> .agents/skills/researcher)
~/.agents/skills/researcher          ← global canonical (if globally installed)
~/.claude/skills/researcher          ← global Claude bridge (if globally installed)
```

After `/library skill remove researcher`:
```
~/.local/share/library/skills/cognovis/researcher@4f8a2b9c/   ← still present
                                                              (orphaned; GC by /library prune-cache)
(all four Layer-C paths removed)
```

After `/library skill remove researcher --local-only`:
```
~/.agents/skills/researcher          ← still present
~/.claude/skills/researcher          ← still present
```

---

## Decision 7: Admin Override — Anthropic Marketplace Force-Enable

**Policy: Library does NOT override Anthropic's force-enable. Treat managed skills
as read-only.**

Anthropic's marketplace "managed settings force-enable" pushes a skill to all
Claude Code instances regardless of what the project has locally. This operates
outside the Library's install path.

**What this means for the Library**:

| Scenario | Library behavior |
|----------|-----------------|
| Managed skill `foo` force-enabled by Anthropic | Library skill named `foo` coexists. Claude Code loads BOTH (the managed version and the project-local version). The managed version's precedence is determined by Anthropic's infrastructure — not by Library's path rules. |
| User tries `/library skill remove foo` on a managed skill | Library removes the local copy. The managed version persists (it was never in the local path). Warn: "Managed skill 'foo' is force-enabled — the local copy has been removed but the managed version remains active." |
| User installs `foo` via `/library skill use foo` and a managed `foo` exists | Install proceeds. Warn: "A managed skill named 'foo' already exists. Installing a local copy. If names conflict, Anthropic's managed version may take precedence." |

**Evidence level**: INFERRED — Anthropic's force-enable behavior is not publicly
documented in detail. The policy above is conservative (treat managed as higher
authority). Revisit when vendor docs become available.

---

## Decision 8: Cross-Marketplace Agent (and Prompt) Collisions — Combine, Don't Shadow

Two marketplaces shipping an agent (or prompt) with the same name is an
anti-pattern: if the name is the same, the agent is doing the same job and the
two versions should be reconciled into a single canonical version, not silently
shadowed.

**Rule**: `/library use <agent>` MUST fail loudly when an agent of the same name
already exists at the install target from a different source. The user is
presented three resolution options:

1. `--replace` — overwrite (use only when intentionally swapping).
2. `--merge-into=<canonical-repo>` — fold the new version's content into the
   existing canonical repo; the installer then re-installs from the canonical
   source only.
3. `--skip` — leave existing install; do not register the new source for this
   name.

Same-marketplace re-install (CL-83q tree-SHA cache) is unaffected and continues
to use last-write-wins.

**Canonical homes for orchestrator-family agents** (informational, by current
convention; not enforced by tooling): `cognovis-core` owns
`bead-orchestrator`, `wave-orchestrator`, `session-close`, `review-agent`,
`verification-agent`, `quick-fix`, `doc-changelog-updater`,
`feature-doc-updater`, `wave-monitor`, `judge-default`. `sussdorff-core` MUST
NOT ship same-named alternatives — if a personal customization is needed,
contribute upstream to cognovis-core or fork into a differently-named agent.

The same rule applies to prompts because they share the flat install-target
model. It does not apply to skills (covered by Decisions 1-7) or standards.

---

## Enforcement Checklist for `/library skill use`

This checklist is extracted from the above policies for quick implementation reference.
See `cookbook/use.md` Step 5b–5d for the full procedure.

```
Before installing:
[ ] Check if canonical path (.agents/skills/<name>) exists and what kind (real dir / symlink-into-cache)
[ ] Check if Claude bridge path (.claude/skills/<name>) exists and whether it is a symlink
[ ] Check for legacy ~/.codex/skills/<name>; offer to remove
[ ] If canonical AND Claude bridge both exist as real directories → emit collision warning, prompt user

During install:
[ ] Materialize Layer-B cache at ~/.local/share/library/skills/<m>/<n>@<tree-sha>/ FIRST
[ ] Point canonical at cache: ln -sfn <cache> .agents/skills/<name>
[ ] Point Claude bridge at canonical: ln -sfn <canonical> .claude/skills/<name>
[ ] Use ln -sfn + explicit rm -r guard for real-dir replacement
[ ] Verify the full symlink chain resolves (cat through to cache)

After install:
[ ] Confirm SKILL.md exists at the Layer-B cache
[ ] Confirm .agents/skills/<name>/SKILL.md is reachable (canonical)
[ ] Confirm .claude/skills/<name>/SKILL.md is reachable (through bridge)
[ ] Report: "Installed to .agents/skills/<name> (canonical -> Layer-B cache). Claude bridge at .claude/skills/<name>."

On removal:
[ ] Remove Claude bridge symlink first
[ ] Handle real-directory Claude path (warn + remove)
[ ] Remove canonical symlink (or real dir if legacy)
[ ] Offer to remove legacy ~/.codex/skills/<name>
[ ] Remove lockfile entry
[ ] Layer-B cache stays; /library prune-cache GCs it once no entries reference it
[ ] Check global paths too if --global flag used
```

---

## Cross-References

- `cookbook/use.md` — Step 5b (target path selection), Step 5c (symlink strategy),
  Step 5d (translation warnings) enforce this policy at the procedure level.
- `docs/PRIMITIVES.md` — §Precedence Policy section describes the same rules in
  primitive taxonomy terms.
- `tests/smoke/run-smoke.sh` — `smoke_name_collision()` function validates this
  policy structurally on Claude Code and Codex harnesses.
- `docs/ARCHITECTURE.md` — Layer 1 (Skills) section describes the path architecture
  that motivates this policy.
- `library.yaml` → `default_dirs` — source of canonical path values used throughout
  this document.
