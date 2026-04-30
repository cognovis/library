# Add a Marketplace to the Library

## Context
Register a new third-party marketplace source in the library catalog so its skills, agents, and prompts can be referenced via `from_marketplace` in catalog entries.

## Input
The user provides: marketplace short name, base GitHub URL, and optionally a description.

## Steps

### 1. Sync the Library Repo
Pull the latest changes before modifying:
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Validate the Source
- Confirm the provided URL is a valid GitHub organization or user URL (e.g. `https://github.com/<org>`)
- Check that the name is a unique short identifier (no spaces, lowercase, alphanumeric with hyphens)
- If a marketplace with the same name already exists in `library.yaml`, warn the user and stop

### 3. Add Entry to library.yaml
Read `library.yaml` and add the new entry under the `marketplaces:` section:

```yaml
marketplaces:
  - name: <short-name>
    source: <github-url>
    description: <one-line description>
```

**YAML formatting rules:**
- 2-space indentation
- List items use `- ` prefix
- Keep entries alphabetically sorted by `name`
- `name` and `source` are required; `description` is strongly recommended

**Example entry:**
```yaml
  - name: disler
    source: https://github.com/disler
    description: Public skill/agent/hooks repos for Claude Code and AI agents
```

### 4. Run Validator
Confirm the file is still valid after the edit:
```bash
python3 scripts/validate-library.py
```
Must output `PASS`. If it fails, review the YAML syntax and fix before proceeding.

### 5. Commit and Push
```bash
cd <LIBRARY_SKILL_DIR>
git add library.yaml
git commit -m "library: add marketplace <name>"
git push
```

### 6. Confirm
Tell the user the marketplace has been registered. They can now reference it in catalog entries using one of two approaches:

**Option A: Explicit source URL (no marketplace reference)**
```yaml
library:
  skills:
    - name: some-skill
      source: https://github.com/<org>/<repo-name>/blob/main/.claude/skills/some-skill/SKILL.md
```

**Option B: Marketplace reference (source derived at install time)**
```yaml
library:
  skills:
    - name: some-skill
      from_marketplace: <name>
      repo: <repo-name>
      path: .claude/skills/some-skill
```

You may provide either `source` (explicit URL) or `from_marketplace + repo + path` (derived at install time), but not both — if both are present, `source` takes precedence.
