# Add a New Entry to the Library

## Context
Register a new skill, agent, or prompt in the library catalog.

## Input
The user invokes `/library <primitive> add <details>` and provides name,
description, source, and optionally dependencies.

## Steps

### 1. Sync the Library Repo
Pull the latest changes before modifying:
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Determine the Type
Use `<primitive>` as the entry type. Validate that the source path matches it:
- `skill` sources point at `SKILL.md`
- `agent` sources point at an agent `.md` or `.toml` file
- `prompt` sources point at a prompt or command `.md` file
- `standard` sources point at a standard `.md` file
- If the source and primitive disagree, warn the user before adding the entry

### 3. Validate the Source
- **Local path**: Verify the file exists at the given path
- **GitHub URL**: Verify the URL is well-formed (matches browser or raw URL patterns)
- Confirm the source points to a specific file, not a directory

### 4. Parse Dependencies
Detect dependencies by looking through the skill/agent/prompt files, format them as typed references:
- `skill:name`, `agent:name`, `prompt:name`, `standard:name`
- Verify each dependency already exists in `library.yaml` if or warn the user
  - If they don't exist add them to `library.yaml` first. If those files have dependencies, add them recursively.
  - You can detect these sometimes by looking at the frontmatter, and then in the file content look for `/<prompt|agent|skill>:name` references. If you're not sure, ask the user the user if they have any dependencies.

### 5. Add the Entry to library.yaml
Read `library.yaml`, add the new entry under the correct section:

```yaml
# Under library.skills, library.agents, or library.prompts
- name: <name>
  description: <description>
  source: <source>
  requires: [<typed:refs>]  # omit if no dependencies
```

**YAML formatting rules:**
- 2-space indentation
- List items use `- ` prefix
- Properties are indented under the list item
- Keep entries alphabetically sorted by name within each section
- For skills reference the `.../<skill-name>/SKILL.md` file,
- For agents reference the `.../<agent name>.md` file,
- For prompts reference the `.../<prompt name>.md` file (installed to `.claude/commands/`),
- Remember we'll be adding a absolute path or a github url (https or ssh)

### 6. Commit and Push
```bash
cd <LIBRARY_SKILL_DIR>
git add library.yaml
git commit -m "library: added <type> <name>"
git push
```

### 7. Confirm
Tell the user the entry has been added and is now available for others to use via `/library <primitive> use <name>`.
