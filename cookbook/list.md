# List Available Skills

## Context
Show the full library catalog with install status, plugin-marketplace installs, and `/library use` lockfile installs.

## Steps

### 1. Sync the Library Repo
Pull the latest catalog before reading:
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Read the Catalog
- Read `library.yaml`
- Parse all entries from `library.skills`, `library.agents`, and `library.prompts`

### 3. Check Install Status
For each entry:
- Determine the type and corresponding default/global directories from `default_dirs`
- Check if a directory matching the entry name exists in the **default** directory
- Check if a directory matching the entry name exists in the **global** directory
- Search recursively for name matches
- Mark as: `installed (default)`, `installed (global)`, or `not installed`

### 4. Read Plugin-Marketplace Installs

Read `~/.claude/plugins/installed_plugins.json`:

- If the file does not exist or is missing, record an empty plugin list and note "No plugin-marketplace installs found" for Section 2 output.
- Parse the `plugins` object (version 2 format): each key is `name@marketplace`.
  - Strip the `@marketplace` suffix to get the plugin name.
  - Collect: `name`, `marketplace`, `version`, `scope` (user or project).
  - If `scope == "project"`, also collect `projectPath`.
- Build a set of installed plugin names (without marketplace suffix) for use in catalog annotation.

### 5. Read /library use Installs (Lockfile)

Read `.library.lock` from the **current working directory** (the user's project root):

- If the file does not exist, record an empty install list and note "No /library use installs found (no .library.lock in current directory)" for Section 3 output.
- Parse the YAML `installed` list. For each entry collect: `name`, `type`, `install_target`, `install_timestamp` (date portion only, e.g. `2026-04-30`).

### 6. Display Results (3 Sections)

Output all three sections in sequence.

---

**Section 1: Catalog**

Format the output as a table grouped by type.
For each catalog entry whose `name` appears in the installed plugin names set (from Step 4), append `[also: plugin-marketplace]` to the Status column.

```
## Section 1: Catalog

### Skills
| Name | Description | Source | Status |
|------|-------------|--------|--------|
| skill-name | skill-description | /local/path/... | installed (default) |
| other-skill | other-description | github.com/... | not installed |
| beads | beads skill | ... | not installed [also: plugin-marketplace] |

### Agents
| Name | Description | Source | Status |
|------|-------------|--------|--------|
| agent-name | agent-description | /local/path/... | installed (global) |

### Prompts
| Name | Description | Source | Status |
|------|-------------|--------|--------|
| prompt-name | prompt-description | github.com/... | not installed |
```

If a catalog subsection is empty, show: `No <type> in catalog.`

---

**Section 2: Plugin-Marketplace Installs**

```
## Section 2: Plugin-Marketplace Installs
| Name | Marketplace | Version | Scope |
|------|-------------|---------|-------|
| beads | beads-marketplace | 1.0.3 | user |
| core | sussdorff-plugins | 2026.04.140 | user |
| code-simplifier | claude-plugins-official | 1.0.0 | project (/Users/malte/code/swamp) |
```

- For project-scoped plugins, append the project path in parentheses to the Scope column.
- If installed_plugins.json is missing or has no entries: `No plugin-marketplace installs found`

---

**Section 3: /library use Installs**

```
## Section 3: /library use Installs
| Name | Type | Install Target | Installed At |
|------|------|----------------|--------------|
| dolt | skill | .claude/skills/dolt/ | 2026-04-30 |
```

- If `.library.lock` is not found: `No /library use installs found (no .library.lock in current directory)`

### 7. Summary
At the bottom, show:
- Total entries in catalog (Section 1)
- Total installed locally (default + global)
- Total not installed
- Total plugin-marketplace installs (Section 2)
- Total /library use installs from lockfile (Section 3)
