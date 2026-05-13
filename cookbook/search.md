# Search the Library

## Context
Find entries in the catalog by keyword when the user doesn't remember the exact name.

## Input
The user provides a keyword or description.

## CLI Shortcut (preferred)

Use the CLI for deterministic search:

```bash
# Search across all primitives:
python3 <LIBRARY_SKILL_DIR>/scripts/library.py search <keyword> --json

# Search within one primitive:
python3 <LIBRARY_SKILL_DIR>/scripts/library.py skill search <keyword> --json
```

Use the steps below when you need to present results interactively or need
install-status context that the CLI search does not yet return.

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

### 3. Search
- Match the keyword (case-insensitive) against:
  - Entry `name`
  - Entry `description`
- A match is any entry where the keyword appears as a substring in either field
- Collect all matches across all types

### 4. Display Results

If matches found, format as:

```
## Search Results for "<keyword>"

| Primitive | Name | Description | Source |
|------|------|-------------|--------|
| skill | matching-skill | description... | source... |
| agent | matching-agent | description... | source... |
```

If no matches:
```
No results found for "<keyword>".

Tip: Try broader keywords or run `/library <primitive> list` once you know which primitive to inspect.
```

### 5. Suggest Next Step
If matches were found, suggest: `Run /library <primitive> use <name> to install one of these.`
