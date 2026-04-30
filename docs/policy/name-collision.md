# Name Collision and Precedence Policy

> **Status**: NORMATIVE — this document is the authoritative policy for how the
> cognovis-library handles skill name collisions across harness paths.
>
> **Bead**: CL-b4o | **Epic**: CL-36o | **Last updated**: 2026-04-30
>
> **Applies to**: `/library use`, `/library remove`, `/library sync`, and any
> tooling that installs or manages skills, agents, or prompts across harnesses.

---

## Quick Reference: Decision Tree

```
A skill with this name already exists somewhere. What do I do?

Is the collision within the same harness (same path prefix)?
 └─ YES → Same-harness collision (Decision 1):
           Project-local wins over global ALWAYS.
           More specific scope wins over less specific.
 └─ NO  → Cross-harness collision (Decision 4):
           The harness-native path wins for that harness.
           .claude/skills/foo wins for Claude Code.
           .agents/skills/foo wins for Codex.
           A symlink bridges both to the same file.

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

Codex loads skills from `.agents/skills/` (project-local) and `~/.agents/skills/`
(user-global), in the same precedence order:

| Priority | Path | Scope |
|----------|------|-------|
| 1 (wins) | `.agents/skills/<name>/SKILL.md` | Project-local |
| 2 | `~/.agents/skills/<name>/SKILL.md` | User-global |

**Rule**: Project-local **always** overrides global for the same skill name.

**Evidence level**: NORMATIVE — follows Open Agent Skills Standard, consistent with
CL-qzw research findings on Codex skill discovery.

**Example (Codex)**:

```
# User has a global version:
~/.agents/skills/researcher/SKILL.md     ← global (shadowed)

# Project has a project-specific override:
.agents/skills/researcher/SKILL.md       ← project-local (WINS for this project)
```

---

## Decision 2: Library Policy — Canonical Path and Bridge

When `/library use` installs a skill for **both** harnesses simultaneously (dual-install):

| Role | Path | Description |
|------|------|-------------|
| **Canonical** | `.claude/skills/<name>/` | Real file lives here. This is the source of truth. |
| **Bridge** | `.agents/skills/<name>` | Symlink pointing to the canonical path. |

**Policy**: The Claude Code path is canonical. The Codex path is the bridge (symlink).

**Rationale**:
- Claude Code requires SKILL.md to exist as a real file (not a symlink target that
  might resolve differently across systems).
- Codex CLI follows symlinked skill directories (NORMATIVE — confirmed via smoke
  test check 11 in `tests/smoke/README.md`).
- Using Claude Code as canonical avoids two separate file copies drifting apart.

**Installation sequence** (MANDATORY ORDER):

```
1. Copy SKILL.md to .claude/skills/<name>/SKILL.md   ← canonical (real file)
2. Create symlink: .agents/skills/<name> -> ../../.claude/skills/<name>   ← bridge
```

The bridge must be created AFTER the canonical install. Reversing the order produces
a dangling symlink.

**Bridge symlink command** (from cookbook/use.md Step 5c):

```bash
claude_target=".claude/skills/<name>"
codex_target=".agents/skills/<name>"
mkdir -p "$(dirname "$codex_target")"
if [ -d "$codex_target" ] && [ ! -L "$codex_target" ]; then
  rm -rf "$codex_target"
fi
ln -sfn "$(realpath "$claude_target")" "$codex_target"
```

---

## Decision 3: Symlink Preservation

### What happens when the user edits the symlink target?

A bridge symlink at `.agents/skills/foo` points to `.claude/skills/foo`.

If the user edits `.agents/skills/foo/SKILL.md` (the symlink target):
- The edit goes to `.claude/skills/foo/SKILL.md` — the canonical file.
- Both harnesses immediately see the change (there is only one file).
- **This is the intended behavior.**

If the user replaces the bridge with a real directory:
- The bridge is destroyed. Two files now exist independently.
- Drift is possible. `/library sync` will warn.

**Library convention for this case**:
1. Detect: `[ -d ".agents/skills/foo" ] && [ ! -L ".agents/skills/foo" ]`
2. Warn the user: "Bridge at `.agents/skills/foo` was replaced with a real directory.
   The canonical skill is at `.claude/skills/foo`. These may have drifted. Run
   `/library sync foo` to inspect and reconcile."
3. Never silently overwrite — always warn first.

### Symlink lifecycle rules

| Event | Action |
|-------|--------|
| `/library use foo` (dual-install) | Create canonical at `.claude/skills/foo`, bridge at `.agents/skills/foo` |
| User edits via bridge | Edit lands on canonical — correct, no action needed |
| User replaces bridge with real dir | Warn on next `/library use` or `/library sync` |
| `/library remove foo` | Remove both canonical AND bridge (see Decision 6) |
| `/library sync foo` | Refresh canonical from source; bridge continues to point to it |

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

**Policy: Skill names must be globally unique across all harnesses within a project.**

**Rationale**: A dual-install creates a symlink bridge so both harnesses load the
same SKILL.md. If two different skills with the same name exist in `.claude/skills/foo`
(Claude Code) and `.agents/skills/foo` (Codex) as separate real files, they will
diverge silently. Bug reports will be untriageable.

**Uniqueness scope**: Within a single project (repository). A `researcher` skill in
Project A and a different `researcher` skill in Project B do not collide.

**Detection in `/library use`**:

Before installing, check for cross-harness collision:

```bash
claude_path=".claude/skills/<name>"
codex_path=".agents/skills/<name>"

claude_exists=false
codex_exists=false
codex_is_bridge=false

[ -d "$claude_path" ] && claude_exists=true
[ -d "$codex_path" ] && codex_exists=true
[ -L "$codex_path" ] && codex_is_bridge=true
```

**Collision scenarios and responses**:

| Scenario | Response |
|----------|---------|
| Neither exists | Fresh install — proceed |
| Claude exists, Codex absent | Claude Code only was installed — add Codex bridge if dual-install requested |
| Codex bridge exists (is a symlink) | Bridge already set — refresh canonical and bridge is updated automatically |
| Both exist as REAL directories | COLLISION — warn user, do NOT silently overwrite |
| Claude absent, Codex real dir exists | Orphaned Codex install — warn user, offer to set up canonical |

**Warning message for real-directory collision**:

```
Warning: Name collision detected for skill '<name>':
  .claude/skills/<name>/ exists (real directory)
  .agents/skills/<name>/ exists (real directory, NOT a symlink)

These are two independent copies that may have diverged.
Policy: Claude Code path is canonical; Codex path should be a symlink bridge.

Options:
  1. Overwrite Codex copy with symlink bridge (recommended — eliminates drift)
  2. Keep both as separate files (not recommended — you must maintain them manually)
  3. Cancel and inspect manually

Default: option 1.
```

**Concrete examples per harness**:

**Claude Code example**:
```
.claude/skills/researcher/SKILL.md   ← real file (canonical)
.agents/skills/researcher            ← symlink → ../../.claude/skills/researcher
```
Claude Code reads: `.claude/skills/researcher/SKILL.md` (direct, no symlink needed)
Codex reads: `.agents/skills/researcher/SKILL.md` (via symlink, resolves to canonical)
Result: one file, two harnesses, zero drift.

**Codex-only example** (no dual-install):
```
.agents/skills/researcher/SKILL.md   ← real file
```
No collision possible — Claude Code is not configured for this skill. Fine.

**Dual-install collision example** (BAD — two real directories):
```
.claude/skills/researcher/SKILL.md   ← real file (v1, old)
.agents/skills/researcher/SKILL.md   ← real file (v2, newer)
```
These have drifted. Claude Code users get v1. Codex users get v2. This is the bug
this policy exists to prevent.

---

## Decision 5: Versioned Installs

**Policy: Version is tracked by content, not by path.**

Paths do not encode version numbers. `.claude/skills/foo/` does not become
`.claude/skills/foo-v2/` for an update.

**Update behavior**:
- `/library use foo` on an already-installed skill: overwrite in place (refresh).
- Old SKILL.md is replaced. Old bridges continue to point to the same directory (no
  symlink change needed — the directory remains, only the file inside changes).

**Scenario: v1 in one path, v2 in another**:

```
.claude/skills/foo/SKILL.md     ← v1 (installed earlier, Claude Code only)
.agents/skills/foo/SKILL.md     ← v2 (installed later, Codex only)
```

This is the two-real-directories collision described in Decision 4. Resolution:
1. Determine which version is canonical (typically the more recent).
2. Write that version to `.claude/skills/foo/SKILL.md`.
3. Replace `.agents/skills/foo/` with a symlink bridge.

**What the model actually gets** (not a naming issue — a load-order issue):

| Harness | Path loaded | Result |
|---------|------------|--------|
| Claude Code | `.claude/skills/foo/SKILL.md` | Gets whatever is at that path |
| Codex | `.agents/skills/foo/SKILL.md` | Gets whatever is at that path |

If the paths are diverged (two real files), each harness gets a different version.
If a symlink bridge is in place, both harnesses get the same file.

---

## Decision 6: Uninstall Behavior

**Policy: `/library remove` must reverse ALL bridges, not just the canonical.**

When a skill was dual-installed (canonical + bridge), removing only the canonical
leaves a dangling symlink. That dangling symlink will cause Codex to fail on skill
discovery.

**Uninstall sequence** (MANDATORY):

```bash
# 1. Remove bridge first (symlink)
if [ -L ".agents/skills/<name>" ]; then
  rm ".agents/skills/<name>"
fi

# 2. Remove bridge real-directory version (if bridge was replaced by user)
if [ -d ".agents/skills/<name>" ] && [ ! -L ".agents/skills/<name>" ]; then
  echo "Warning: Bridge at .agents/skills/<name> is a real directory — removing."
  rm -rf ".agents/skills/<name>"
fi

# 3. Remove canonical
rm -rf ".claude/skills/<name>"
```

**Global paths**: Same pattern applies for `~/.claude/skills/<name>` and
`~/.agents/skills/<name>`.

**Example — complete removal**:

Before removal:
```
.claude/skills/researcher/SKILL.md   ← canonical (real file)
.agents/skills/researcher            ← bridge (symlink)
~/.claude/skills/researcher/         ← global canonical (if globally installed)
~/.agents/skills/researcher          ← global bridge (if globally installed)
```

After `/library remove researcher`:
```
(all four paths removed)
```

After `/library remove researcher --local-only`:
```
~/.claude/skills/researcher/         ← still present
~/.agents/skills/researcher          ← still present
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
| User tries `/library remove foo` on a managed skill | Library removes the local copy. The managed version persists (it was never in the local path). Warn: "Managed skill 'foo' is force-enabled — the local copy has been removed but the managed version remains active." |
| User installs `foo` via `/library use` and a managed `foo` exists | Install proceeds. Warn: "A managed skill named 'foo' already exists. Installing a local copy. If names conflict, Anthropic's managed version may take precedence." |

**Evidence level**: INFERRED — Anthropic's force-enable behavior is not publicly
documented in detail. The policy above is conservative (treat managed as higher
authority). Revisit when vendor docs become available.

---

## Enforcement Checklist for `/library use`

This checklist is extracted from the above policies for quick implementation reference.
See `cookbook/use.md` Step 5b–5d for the full procedure.

```
Before installing:
[ ] Check if canonical path (.claude/skills/<name>/) already exists
[ ] Check if bridge path (.agents/skills/<name>) exists and whether it is a symlink
[ ] If both exist as real directories → emit collision warning, prompt user

During dual-install:
[ ] Install canonical (real file) to .claude/skills/<name>/ FIRST
[ ] Then create bridge symlink: .agents/skills/<name> -> ../../.claude/skills/<name>
[ ] Use ln -sfn + explicit rm -rf guard for real-dir replacement
[ ] Verify symlink resolves correctly after creation

After install:
[ ] Confirm SKILL.md exists at canonical path
[ ] Confirm bridge symlink resolves to the same SKILL.md
[ ] Report: "Installed to .claude/skills/<name>/ (canonical). Bridge created at .agents/skills/<name>."

On removal:
[ ] Remove bridge symlink first
[ ] Handle real-directory bridge (warn + remove)
[ ] Remove canonical
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
