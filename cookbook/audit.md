# Audit Installed Library Items

## Context
Detect drift between what `.library.lock` says was installed (including checksums) and what is
actually present on disk. A drift means the installed file was modified outside the Library after
the lock record was written.

## Input
Optional: a skill name to audit a single entry. If omitted, all entries in `.library.lock` are audited.

## Steps

### 1. Sync the Library Repo
Pull the latest catalog before reading:
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Read the Lockfile
- Read `.library.lock` from the project root
- If `.library.lock` does not exist, tell the user:
  > "No .library.lock found. Run /library use to install items and create the lockfile."
  Then exit.

### 3. Select Entries to Audit
- If the user provided a name: find the single entry matching that name. If not found, report "not found in lockfile" and exit.
- If no name provided: audit all entries in `installed`.

### 4. For Each Entry: Check Presence and Checksum

For each entry:

#### 4a. Determine the primary artifact path

| `type` | Primary artifact |
|--------|-----------------|
| `skill` | `<install_target>/SKILL.md` |
| `agent` | `<install_target>/<name>.md` |
| `prompt` | `<install_target>/<name>.md` |

#### 4b. Check file existence
- If the primary artifact does NOT exist:
  - Status: **MISSING**
  - Note: "Expected at `<path>` — file not found. Run /library use <name> to reinstall."
  - Continue to next entry.

#### 4c. Compute current checksum
```bash
# macOS
current_hash=$(shasum -a 256 "<primary_artifact_path>" | awk '{print $1}')

# Linux
current_hash=$(sha256sum "<primary_artifact_path>" | awk '{print $1}')
```

#### 4d. Compare against locked checksum
- If `current_hash == entry.checksum_sha256`:
  - Status: **CLEAN** — no drift detected.
- If `current_hash != entry.checksum_sha256`:
  - Status: **DRIFT** — file was modified after install.
  - Note: "Locked checksum: <locked_hash>. Current: <current_hash>."

#### 4e. Check bridge symlinks (if `bridge_symlinks` is non-empty)

For each bridge listed in `bridge_symlinks`:
- Parse the link path from the entry (format: `<link-path> -> <target-path>`)
- Check if `<link-path>` exists as a symlink: `[ -L "<link-path>" ]`
- If not a symlink (missing or a real directory):
  - Status: **BRIDGE-BROKEN**
  - Note: "Bridge symlink `<link-path>` is missing or replaced by a real directory."

### 5. Check for Unlocked Installs (optional)
For completeness, scan the default install directories for items NOT present in `.library.lock`:

```bash
# Claude Code skills
for d in .claude/skills/*/; do
  name=$(basename "$d")
  # check if name appears in lockfile
done

# Codex skills (skip symlinks — they are bridges of Claude Code canonicals)
for d in .agents/skills/*/; do
  [ -L "$d" ] && continue   # skip bridges
  name=$(basename "$d")
  # check if name appears in lockfile
done
```

Any directory found here but absent from the lockfile is an **UNLOCKED** install — installed
manually or by a tool that did not update the lockfile.

### 6. Report Results

Display a summary table:

```
## Audit Report

| Name | Type | Status | Detail |
|------|------|--------|--------|
| dolt | skill | CLEAN | — |
| researcher | skill | DRIFT | Checksum mismatch (locked=aaaa..., actual=bbbb...) |
| old-agent | agent | MISSING | Expected at .claude/agents/old-agent.md |
| manual-skill | skill | UNLOCKED | Found in .claude/skills/ but not in .library.lock |

Audited: 3 locked entries + 1 unlocked installs found

CLEAN: 1
DRIFT: 1  ← these need /library use <name> to refresh
MISSING: 1  ← these need /library use <name> to reinstall
BRIDGE-BROKEN: 0
UNLOCKED: 1  ← these need /library use <name> to add to lockfile
```

### 7. Actions Available

After reporting, offer the user remediation options:

| Status | Suggested action |
|--------|-----------------|
| DRIFT | `/library use <name>` to refresh from source and re-lock |
| MISSING | `/library use <name>` to reinstall and add to lockfile |
| BRIDGE-BROKEN | `/library use <name>` to recreate the bridge symlink |
| UNLOCKED | `/library use <name>` to create a lockfile entry (will overwrite the existing install) |
| CLEAN | No action needed |

Do NOT automatically fix drift. Always report and let the user decide — the modification may
be intentional (e.g. a local patch the user wants to keep).
