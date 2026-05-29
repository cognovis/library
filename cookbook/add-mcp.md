# Register an MCP Server in the Library

> **Bead**: CL-mfz | **Epic**: CL-36o | **Last updated**: 2026-04-30
>
> **Scope**: This cookbook covers how to add a server to the `library.mcp_servers:` catalog in
> `library.yaml`, including the canonical per-harness `install.mcp` blocks that the installer or
> a human operator will later materialize. It does NOT cover the installer implementation itself.

## Overview

`library.mcp_servers:` is the canonical registry for MCP servers in the cognovis-library. Each entry
defines a server once; the `/library mcp use <name>` command translates the canonical
definition into the correct harness-specific config.

## Schema

The canonical shape for one server entry is:

```yaml
library:
  mcp_servers:
    - name: <kebab-case-identifier>        # required
      description: <human-readable string>  # required
      source: <source-of-truth URL>         # recommended for catalog provenance
      species: external-capability | library-tool-surface
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
          antigravity:
            config_path: ~/.config/gemini/settings.json
            snippet: { ... }
          cursor:
            config_path: ~/.cursor/mcp.json
            snippet: { ... }
          claude_ai:
            install_url: https://...        # URL for manual add
          claude_ios:
            install_url: https://...
      tags: []                              # optional search tags
```

Full schema definition: `docs/schema/library.schema.json` — `$defs/mcp_server_entry`.

## Species Field (`species:`)

Use `species: external-capability` for third-party capability providers such as `open-brain`,
`executive-circle`, or `heypresto`. Use `species: library-tool-surface` for first-party Library
servers that expose typed tool families over existing Library CLIs or Scripts.

`cognovis-tools` is the reference `library-tool-surface` entry. Its job is to register the typed
tool surface into all four coding harness families:

- `claude_code` for `cld`
- `codex` for `cdx`
- `antigravity` for `agr`
- `cursor` for `cra`

Registration is not orchestration. Claude Code and Codex remain the bead orchestration runners;
Antigravity and Cursor are implementation-surface consumers that need the MCP registration so their
agents call `bead.*`, `git.*`, and `library.exec` directly instead of reconstructing CLI flags.

## Registering for All 4 Harnesses

Use all four coding-harness keys when a first-party `library-tool-surface` must be available in
every implementation surface:

```yaml
install:
  mcp:
    claude_code:
      config_path: ~/.claude/settings.json
      snippet: {command: uv}
    codex:
      config_path: ~/.codex/config.toml
      snippet: {command: uv}
    antigravity:
      config_path: ~/.config/gemini/settings.json
      snippet: {command: uv}
    cursor:
      config_path: ~/.cursor/mcp.json
      snippet:
        type: stdio
        command: uv
```

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

For `species: library-tool-surface`, `coding_strategy` should normally be `mcp`, and the
`install.mcp` block should register every coding harness surface that will consume the typed tools.
For `cognovis-tools`, that means `claude_code`, `codex`, `antigravity`, and `cursor`.

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
    codex:
      config_path: ~/.codex/config.toml
      snippet:
        command: <command-name>
        args: [<arg>, <arg>]
    antigravity:
      config_path: ~/.config/gemini/settings.json
      snippet:
        command: <command-name>
        args: [<arg>, <arg>]
        env: {}
    cursor:
      config_path: ~/.cursor/mcp.json
      snippet:
        type: stdio
        command: <command-name>
        args: [<arg>, <arg>]
        env: {}
```

Reference example for `cognovis-tools`:

```yaml
install:
  mcp:
    claude_code:
      config_path: ~/.claude/settings.json
      snippet:
        type: stdio
        command: uv
        args:
          - run
          - --project
          - ~/.local/share/library/cognovis-library-core/mcp-servers/cognovis-tools
          - cognovis-tools-mcp
    codex:
      config_path: ~/.codex/config.toml
      snippet:
        command: uv
        args:
          - run
          - --project
          - ~/.local/share/library/cognovis-library-core/mcp-servers/cognovis-tools
          - cognovis-tools-mcp
    antigravity:
      config_path: ~/.config/gemini/settings.json
      snippet:
        command: uv
        args:
          - run
          - --project
          - ~/.local/share/library/cognovis-library-core/mcp-servers/cognovis-tools
          - cognovis-tools-mcp
    cursor:
      config_path: ~/.cursor/mcp.json
      snippet:
        type: stdio
        command: uv
        args:
          - run
          - --project
          - ~/.local/share/library/cognovis-library-core/mcp-servers/cognovis-tools
          - cognovis-tools-mcp
```

### Registration smoke

After registering a `library-tool-surface` server, perform a harness-local smoke check:

1. Launch the target harness.
2. Confirm the MCP server appears in the harness config view or `tools/list`.
3. Verify the typed tool list includes the expected family, for example `bead.*` for
   `cognovis-tools`.

For this bead, a minimal acceptable manual smoke is Cursor (`~/.cursor/mcp.json`) because `cra` is
an actively used implementation surface.

### 5. Add to library.yaml

Add the new entry under `library.mcp_servers:` in `library.yaml`. Keep entries alphabetically sorted
by `name` for readability.

### 6. Validate

```bash
uv run python scripts/validate-library.py
```

Must exit 0 before committing.

### 7. Commit

```bash
git add library.yaml
git commit -m "feat: register <name> in library.mcp_servers catalog"
```

## Out of Scope (follow-up beads)

The following are NOT part of this bead or cookbook:

- **Per-harness config mutation** — writing the snippet into `~/.claude/settings.json` etc.
  is installer work; this cookbook defines the canonical `install.mcp` blocks but does not
  implement the writes.
- **Secrets / auth token storage** — handled by a separate security-model bead.
- **Mobile install instructions** — the `install_url` fields are stored here, but the UI
  for presenting them to users is a follow-up bead.
- **Removing or updating a server** — `/library mcp remove <name>` and `/library sync`.

## Reference

- Schema: `docs/schema/library.schema.json` — `$defs/mcp_server_entry`
- Validator: `scripts/validate-library.py`
- Tests: `tests/test_mcp_servers_schema.py`
- Example: `open-brain` entry in `library.yaml`
- PRIMITIVES.md: `docs/PRIMITIVES.md` — decision tree for primitive type selection
