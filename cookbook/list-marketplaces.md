# List Registered Marketplaces

## Context
Show all marketplace sources registered in the library catalog.

## Steps

### 1. Sync the Library Repo
Pull the latest catalog before reading:
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Read the Marketplaces Section
- Read `library.yaml`
- Parse all entries from the top-level `marketplaces:` list
- If the `marketplaces:` key is absent or the list is empty, report: "No marketplaces registered."

### 3. Display as Table
Format the output as a table:

```
## Marketplaces
| Name | Source | Description |
|------|--------|-------------|
| anthropic-official | https://github.com/anthropics | Anthropic-curated Claude plugins and extensions |
| cognovis-samurai | https://github.com/cognovis/samurai-skills | Cognovis Samurai skills collection |
| disler | https://github.com/disler | Public skill/agent/hooks repos for Claude Code and AI agents |
| thadenorigar | https://github.com/ThadeNorigar | Private K2SO and related agent repos |
```

- Sort rows alphabetically by `Name`
- If `description` is missing for an entry, show `—` in that column

### 4. Summary
At the bottom, show:
- Total marketplaces registered
- Prompt: "To add a new marketplace, use `/library add-marketplace`"
