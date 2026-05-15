# List Available Library Primitives

## Context
Show library catalog entries with install status, plugin-marketplace installs,
and lockfile-recorded library installs. The canonical command is
primitive-scoped:

```text
/library <primitive> list
```

Valid primitive values are `skill`, `agent`, `prompt`, `standard`, `guardrail`,
`mcp`, `model-standard`, and `agent-base`.

## CLI Shortcut (preferred for deterministic output)

For machine-readable output, use the CLI directly:

```bash
# List skills in JSON (for agent processing):
python3 <LIBRARY_SKILL_DIR>/scripts/library.py skill list --json

# List standards as human-readable table:
python3 <LIBRARY_SKILL_DIR>/scripts/library.py standard list
```

The CLI reads `library.yaml` and returns stable JSON. Use the steps below when
you need install-status enrichment (plugin-marketplace + lockfile cross-reference)
that the CLI does not yet provide.

## Steps

### 1. Sync the Library Repo
Before changing directories, remember the **original working directory** (the directory where the user invoked `/library <primitive> list`) — you will need it in Step 5 to read the lockfile.

Pull the latest catalog before reading:
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Read the Catalog
- Read `library.yaml`
- Map `<primitive>` to exactly one catalog section:
  - `skill` -> `library.skills`
  - `agent` -> `library.agents`
  - `prompt` -> `library.prompts`
  - `standard` -> `library.standards`
  - `guardrail` -> `library.guardrails`
  - `mcp` -> `library.mcp_servers`
  - `model-standard` -> `library.model_standards`
  - `agent-base` -> `library.agent_bases`
- Parse only that section

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
  - Split the key at the **last** `@` — everything before it is the plugin name, everything after it is the marketplace id.
  - Collect: `name`, `marketplace`, `version`, `scope` (user or project).
  - If `scope == "project"`, also collect `projectPath`.
- Build a set of installed plugin names (without marketplace suffix) for use in catalog annotation.

### 5. Read Library Installs (Lockfile)

Read `.library.lock` from the **original working directory** (where the user invoked the command, saved in Step 1 — NOT from `<LIBRARY_SKILL_DIR>`):

- If the file does not exist, record an empty install list and note "No library installs found (no .library.lock in current directory)" for Section 3 output.
- Parse the YAML `installed` list.
- Keep only entries whose `type` matches `<primitive>`.
- For each kept entry collect: `name`, `type`, `install_target`, `install_timestamp` (date portion only, e.g. `2026-04-30`).

### 6. Display Results (3 Sections)

Output all three sections in sequence.

---

**Section 1: Catalog**

Format the output as a table for the requested primitive.
For each catalog entry whose `name` appears in the installed plugin names set (from Step 4):
- If the catalog status is `installed (default)` or `installed (global)`: append `[also: plugin-marketplace]` to the Status column.
- If the catalog status is `not installed`: append `[via plugin-marketplace]` to the Status column instead.
- If the catalog status is `not installed` and the entry is NOT in the installed plugin names set: no annotation.

```
## Section 1: Catalog

### <Primitive>
| Name | Description | Source | Status |
|------|-------------|--------|--------|
| entry-name | entry-description | github.com/... | not installed |
```

If the requested catalog section is empty, show: `No <primitive> entries in catalog.`

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

**Section 3: Library Installs**

```
## Section 3: Library Installs
| Name | Type | Install Target | Installed At |
|------|------|----------------|--------------|
| dolt | skill | .claude/skills/dolt/ | 2026-04-30 |
```

- If `.library.lock` is not found: `No library installs found (no .library.lock in current directory)`

### 7. Summary
At the bottom, show:
- Total entries in the requested catalog section (Section 1)
- Total installed locally (default + global)
- Total not installed
- Total plugin-marketplace installs (Section 2)
- Total library installs from lockfile (Section 3)
