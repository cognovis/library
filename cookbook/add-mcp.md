# Register an MCP Server in the Library

> **Bead**: CL-mfz | **Epic**: CL-36o | **Last updated**: 2026-04-30
>
> **Scope**: This cookbook covers how to add a server to the `mcp_servers:` catalog in
> `library.yaml`. It does NOT cover per-harness config mutation (install/remove), which is a
> follow-up bead.

## Overview

`mcp_servers:` is the canonical registry for MCP servers in the cognovis-library. Each entry
defines a server once; the `/library use` command (future) will translate the canonical
definition into the correct harness-specific config.

## Schema

The canonical shape for one server entry is:

```yaml
mcp_servers:
  - name: <kebab-case-identifier>        # required
    description: <human-readable string>  # required
    coding_strategy: cli | mcp            # optional — how coding harnesses consume this
    mobile_strategy: cli | mcp            # optional — how mobile/web harnesses consume this
    capabilities:                         # optional
      stateless: true | false
      streaming: true | false
      auth: token | oauth | none
    install:                              # optional — per-harness install metadata
      cli:                                # present when coding_strategy: cli
        package: <package-name>
        manager: npm | pip | cargo | brew | none
      mcp:                                # present when any strategy is mcp
        claude_code:
          config_path: ~/.claude/settings.json
          snippet: { ... }               # harness-specific MCP descriptor
        codex:
          config_path: ~/.codex/config.toml
          snippet: { ... }
        opencode:
          config_path: ~/.config/opencode/opencode.json
          snippet: { ... }
        claude_ai:
          install_url: https://...        # URL for manual add
        claude_ios:
          install_url: https://...
    tags: []                              # optional search tags
```

Full schema definition: `docs/schema/library.schema.json` — `$defs/mcp_server_entry`.

## Deciding `coding_strategy` vs `mobile_strategy`

| Strategy | When to use |
|----------|-------------|
| `cli` | The server ships a CLI package that coding harnesses call directly. The harness does NOT need to add the server to its MCP config — it just installs the package. |
| `mcp` | The server must be registered in the harness MCP config so the harness can spawn it as a local subprocess or connect to a remote endpoint. |

Most servers will be `coding_strategy: cli` (install via npm/pip) and `mobile_strategy: mcp`
(claude.ai/iOS must configure it). See the `open-brain` entry in `library.yaml` as the
reference example.

## Steps to Register a New MCP Server

### 1. Determine required fields

You need at minimum:

- `name` — unique, kebab-case identifier (e.g. `my-server`)
- `description` — one-sentence description of what the server does

### 2. Determine strategies

Ask: "Does this server ship a CLI wrapper?" If yes: `coding_strategy: cli`. If it must be
wired into harness MCP config directly: `coding_strategy: mcp`.

For mobile/web (claude.ai, iOS): these harnesses do not run local packages, so if there is
an add URL available: `mobile_strategy: mcp` with `install_url`.

### 3. Fill in capabilities

- `stateless`: does each call start fresh, or does the server maintain session state?
- `streaming`: does the server stream partial results?
- `auth`: what credentials does the caller need?

### 4. Fill in install metadata

For `coding_strategy: cli`:
```yaml
install:
  cli:
    package: <npm-package-or-pypi-name>
    manager: npm   # or pip, cargo, brew, none
```

For `mcp` harnesses:
```yaml
install:
  mcp:
    claude_code:
      config_path: ~/.claude/settings.json
      snippet:
        type: stdio
        command: <command-name>
    # ... add other harnesses as needed
```

### 5. Add to library.yaml

Add the new entry under `mcp_servers:` in `library.yaml`. Keep entries alphabetically sorted
by `name` for readability.

### 6. Validate

```bash
python3 scripts/validate-library.py
```

Must exit 0 before committing.

### 7. Commit

```bash
git add library.yaml
git commit -m "feat: register <name> in mcp_servers catalog"
```

## Out of Scope (follow-up beads)

The following are NOT part of this bead or cookbook:

- **Per-harness config mutation** — writing the snippet into `~/.claude/settings.json` etc.
  is the translator bead (successor to CL-mfz).
- **Secrets / auth token storage** — handled by a separate security-model bead.
- **Mobile install instructions** — the `install_url` fields are stored here, but the UI
  for presenting them to users is a follow-up bead.
- **Removing or updating a server** — future `/library remove` and `/library sync` commands.

## Reference

- Schema: `docs/schema/library.schema.json` — `$defs/mcp_server_entry`
- Validator: `scripts/validate-library.py`
- Tests: `tests/test_mcp_servers_schema.py`
- Example: `open-brain` entry in `library.yaml`
- PRIMITIVES.md: `docs/PRIMITIVES.md` — decision tree for primitive type selection
