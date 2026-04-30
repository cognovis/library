# MCP Server Audit

**Date:** 2026-04-30
**Author:** CL-p91 audit pass
**Reference:** `docs/PRIMITIVES.md §8` (MCP-Server decision rule)

This audit classifies every MCP server installed across all harnesses (Codex CLI, Claude Desktop, Claude Code).
The goal is to identify which servers should be replaced by CLI + Skill pairs, which must stay as MCP, and which need follow-up work.

---

## Summary Inventory Table

| # | Server | Harness | Stateless | Has CLI | Mobile-relevant | Recommendation |
|---|--------|---------|-----------|---------|-----------------|----------------|
| 1 | `open-brain` | Codex (`~/.codex/config.toml`) | yes | partial (hooks only; no on-demand CLI) | **yes** | Ship both: hooks cover automatic capture; build `ob` CLI for on-demand queries; keep MCP for claude.ai/iOS |
| 2 | `searxng` | Codex | yes | partial (`crwl`) | no | Build CLI wrapper (`srx`), then convert; drop MCP |
| 3 | `markitdown` | Codex | yes | **yes** (`markitdown` binary) | no | Convert to CLI+Skill, drop MCP |
| 4 | `playwright` | Codex | no (browser sessions) | yes (`playwright-cli`) | no | Keep MCP (stateful browser sessions) |
| 5 | `executive-circle` | Codex | yes | no | **yes** | Ship both: build CLI wrapper for coding harnesses; keep MCP for claude.ai/iOS |
| 6 | `pencil` | Codex + Claude Desktop | no (editor state, encrypted files) | no | no | Keep MCP (stateful, encrypted .pen format) |
| 7 | `heypresto` | Codex | yes | unknown | potentially yes | Investigate CLI; if none, build; ship both if mobile-relevant |
| 8 | `stringer` | Codex | yes (assumed) | removed | no | Removed: unused third-party tool; MCP, CLI, and skill retired |
| 9 | `lsp` | Codex | no (LSP sessions) | n/a | no | Keep MCP (stateful LSP sessions) |
| 10 | `FileSystem` | Claude Desktop | yes | n/a (no shell in Desktop) | no | Keep MCP (Desktop has no shell access; this is the only path) |
| 11 | `skill-seeker` | Claude Code (`~/.config/claude-code/mcp.json`) | yes | n/a | no | Removed: Claude Code native skill discovery is sufficient |
| 12 | `crawl4ai` | — (not in MCP configs) | yes | **yes** (`crwl`) | no | Already converted; no MCP to drop. Note in registry. |
| 13 | `claude-in-chrome` | — (Chrome extension, not MCP) | no (browser session) | no | no | Not an MCP server; extension model; no action needed. |

---

## Per-Server Details

### 1. `open-brain`

**Harness:** Codex CLI (`~/.codex/config.toml`), HTTP URL MCP (`https://open-brain.sussdorff.org`)

**Capabilities:** Memory store — `search`, `save_memory`, `get_context`, `get_wake_up_pack`, plus lifecycle tools (`compact_memories`, `triage_memories`, `run_lifecycle_pipeline`, etc.)

**Stateless:** Yes — each API call is independent; the server itself holds state but individual calls are stateless HTTP.

**Has CLI:** Partial — the open-brain plugin for Claude Code is implemented as **hooks** (SessionStart, PostToolUse, etc.), which fire automatically in the Claude Code harness for context capture and injection. However, hooks are **not** a CLI replacement: there is no `ob search "query"`, `ob save`, or other on-demand CLI for scripting, ad-hoc queries, or use outside an active Claude Code session. This is partial CLI coverage, not full — analogous to `executive-circle`, where the MCP works for mobile but the coding harness still needs a CLI wrapper.

**Mobile-relevant:** Yes — `claude.ai` web and Claude iOS have no hook mechanism; MCP is the only path for memory access on those harnesses.

**Recommendation:** Ship both: hooks already cover automatic context capture for coding harnesses; build a CLI tool for on-demand queries (e.g. `ob search "query"`, `ob save`); keep MCP for claude.ai/iOS where hooks are unavailable.

**Migration plan:**
1. Build an `ob` CLI wrapper (thin client against the open-brain HTTP API at `https://open-brain.sussdorff.org`) exposing on-demand subcommands such as `ob search "query"`, `ob save`, `ob context`, `ob wake-up`.
2. Create or extend a skill (e.g. `open-brain:ob-cli`) that wraps the CLI for scripted/ad-hoc use outside hook-driven flows.
3. Retain the existing hooks for automatic capture/injection inside Claude Code sessions.
4. Retain the MCP server for claude.ai web and Claude iOS, where neither hooks nor a local CLI are available.

---

### 2. `searxng`

**Harness:** Codex CLI, HTTP URL MCP. Codebase at `~/code/ai/searxng-mcp`.

**Capabilities:** `searxng_web_search`, `web_url_read` — web search and URL content reading.

**Stateless:** Yes.

**Has CLI:** Partial — `crwl` handles URL crawling (`crwl crawl URL`). There is no standalone `srx` or `searxng` CLI for web search queries.

**Mobile-relevant:** No — used only in coding workflows.

**Recommendation:** Build a thin CLI wrapper for web search (e.g., `srx "query"` backed by the SearXNG instance), then wrap in a Skill. Drop MCP from Codex config.

**Migration plan:**
1. Create `srx` CLI script that calls the SearXNG HTTP API.
2. Create `dev-tools:web-search` skill that wraps `srx` and `crwl`.
3. Remove `searxng` from `~/.codex/config.toml`.
4. File follow-up bead for implementation.

---

### 3. `markitdown`

**Harness:** Codex CLI, node stdio MCP (`~/code/ai/markitdown-mcp/server.mjs`).

**Capabilities:** `markitdown_convert` (file path), `markitdown_convert_url` — document-to-markdown conversion.

**Stateless:** Yes.

**Has CLI:** Yes — `/opt/homebrew/Caskroom/miniconda/base/bin/markitdown` binary exists.

**Mobile-relevant:** No.

**Recommendation:** Convert to CLI + Skill. The binary is already present. A one-line skill wrapper is sufficient.

**Migration plan:**
1. Create or extend a skill (e.g., `dev-tools:markitdown`) that calls `markitdown <path>` or `markitdown <url>`.
2. Remove `markitdown` from `~/.codex/config.toml`.
3. Decommission `~/code/ai/markitdown-mcp/` (or archive it).

---

### 4. `playwright`

**Harness:** Codex CLI, `npx @playwright/mcp@latest --extension`.

**Capabilities:** Full browser automation — navigate, click, screenshot, form fill, etc.

**Stateless:** No — requires a persistent browser session. Each navigation builds on prior state (cookies, DOM, etc.).

**Has CLI:** `playwright-cli` skill exists and wraps the Playwright CLI. However, the CLI operates on isolated invocations, not persistent sessions.

**Mobile-relevant:** No.

**Recommendation:** Keep MCP. The stateful browser session cannot be replicated with a stateless CLI wrapper. The `playwright-cli` skill is a complement for simple, isolated tasks — not a replacement for session-based automation.

---

### 5. `executive-circle`

**Harness:** Codex CLI, HTTP URL MCP.

**Capabilities:** Content library lookup — `search_posts`, `get_post`, `list_guides`, `search_guides`, `list_prompt_kits`, etc. Read-only API.

**Stateless:** Yes — pure read, no session.

**Has CLI:** No standalone CLI exists.

**Mobile-relevant:** Yes — the content library is used in `claude.ai` and Claude iOS via system prompt integrations.

**Recommendation:** Ship both. Build a CLI wrapper for coding harnesses; keep MCP for claude.ai/iOS.

**Migration plan:**
1. Create `ec` CLI tool (thin HTTP client against the executive-circle API).
2. Create `content:executive-circle-cli` skill.
3. Retain MCP for non-coding harnesses.
4. Note: PRIMITIVES.md §8 already uses this as a canonical "keep MCP" example — the MCP is correct; the gap is the missing CLI path for coding harnesses.

---

### 6. `pencil`

**Harness:** Codex CLI + Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`).

**Capabilities:** Design editor for `.pen` files — `batch_design`, `batch_get`, `get_editor_state`, `open_document`, `export_nodes`, etc.

**Stateless:** No — requires active editor state. `.pen` files are encrypted and can only be accessed through the MCP tools (not via filesystem reads).

**Has CLI:** No. The encrypted format is proprietary and tooling is only exposed via MCP.

**Mobile-relevant:** No (design/coding harness only).

**Recommendation:** Keep MCP. Stateful editor sessions and encrypted file format make CLI conversion impossible without vendor support.

---

### 7. `heypresto`

**Harness:** Codex CLI, HTTP URL MCP.

**Capabilities:** `expand_prompt` tool — purpose is prompt expansion/enhancement.

**Stateless:** Yes (assumed — single HTTP call per invocation).

**Has CLI:** Unknown — no `heypresto` binary found in PATH or standard locations.

**Mobile-relevant:** Potentially yes — prompt expansion could be used in claude.ai workflows.

**Recommendation:** Investigate whether a CLI exists or can be trivially built. If the API is a simple HTTP endpoint, build a `heypresto` CLI wrapper. If mobile-relevant, ship both; otherwise convert and drop MCP.

**Migration plan:**
1. Check if `heypresto` exposes a plain HTTP API.
2. If yes: build `hp` CLI wrapper, create skill, evaluate mobile relevance.
3. If mobile-relevant: ship both (retain MCP).
4. If coding-only: drop MCP after CLI wrapper is confirmed working.

---

### 8. `stringer`

**Harness:** Codex CLI, command stdio MCP.

**Capabilities:** Purpose was unclear from config alone. Before removal, the `beads-workflow:stringer` skill described it as "Codebase archaeology."

**Stateless:** Yes (assumed).

**Has CLI:** Removed — the Homebrew-installed `stringer` binary was retired with the MCP entry.

**Mobile-relevant:** No — codebase analysis is a coding-harness-only concern.

**Status:** Removed in `CL-ao5`. `stringer` was unused and came from a third-party Homebrew tap, so the CLI, Codex MCP entry, and `beads-workflow:stringer` skill were removed instead of preserving a CLI-only path.

**Removal plan:**
1. Uninstall the `stringer` Homebrew formula.
2. Remove `[mcp_servers.stringer]` from `~/.codex/config.toml`.
3. Delete the `beads-workflow:stringer` skill directory.

---

### 9. `lsp`

**Harness:** Codex CLI, `npx lsp-mcp-server`.

**Capabilities:** Language Server Protocol bridge — exposes LSP features (hover, go-to-definition, completions, diagnostics) as MCP tools.

**Stateless:** No — LSP requires a long-running server connection with persistent document state and incremental sync.

**Has CLI:** Not applicable — LSP is inherently protocol-based.

**Mobile-relevant:** No.

**Recommendation:** Keep MCP. LSP sessions are fundamentally stateful; there is no meaningful CLI equivalent.

---

### 10. `FileSystem`

**Harness:** Claude Desktop only (`~/Library/Application Support/Claude/claude_desktop_config.json`). `npx @modelcontextprotocol/server-filesystem`.

**Capabilities:** File read/write access for Claude Desktop (which has no shell).

**Stateless:** Yes per call, but required because the harness lacks shell access.

**Has CLI:** n/a — Claude Desktop has no shell.

**Mobile-relevant:** No (desktop-only).

**Recommendation:** Keep MCP. This is the only mechanism for filesystem access in the Claude Desktop harness. The stateless/has-CLI decision matrix does not apply here — the harness constraint overrides it.

---

### 11. `skill-seeker`

**Harness:** Claude Code (`~/.config/claude-code/mcp.json`). Python stdio (`~/code/ai/Skill_Seekers/mcp/server.py`).

**Capabilities:** Skill discovery and search — finds relevant skills from the library catalog.

**Stateless:** Yes — search queries are independent.

**Has CLI:** Not needed — Claude Code native skill discovery covers the use case.

**Mobile-relevant:** No — skill discovery is a coding-harness concern.

**Status:** Removed in `CL-byh`. The MCP entry duplicated Claude Code's native skill discovery and added local process overhead without an active workflow need.

**Removal plan:**
1. Remove `skill-seeker` from `~/.config/claude-code/mcp.json`.
2. Keep the source repository disposition as a separate user decision.

---

### 12. `crawl4ai` (already converted — no MCP)

**Harness:** None — no MCP config found in any harness.

**Capabilities:** Web crawling and content extraction.

**CLI:** `crwl` at `~/.local/bin/crwl` — fully functional CLI tool.

**Status:** Already converted. The CLI-first path is complete. No MCP to deprecate. Registry entry in `library.yaml` should reflect "CLI only, no MCP."

---

### 13. `claude-in-chrome` (not an MCP server)

**Harness:** Chrome extension — not installed via MCP config. Tools appear as `mcp__claude-in-chrome__*` in Claude Code because the extension injects them via a different mechanism.

**Capabilities:** Browser automation from within Chrome — `navigate`, `find`, `get_page_text`, `javascript_tool`, `form_input`, etc.

**Stateful:** Yes (browser session).

**Status:** Not an MCP server in the traditional sense. No config file entry to deprecate. Extension lifecycle is managed separately. No action needed in MCP audit scope.

---

## ACTION LIST

### Immediate: Drop MCP, CLI already exists

| Server | Action | CLI to use | Skill to create/extend |
|--------|--------|------------|------------------------|
| `markitdown` | Remove from `~/.codex/config.toml`; decommission `~/code/ai/markitdown-mcp/` | `markitdown` binary | `dev-tools:markitdown` |

### Short-term: Build CLI wrapper, then convert

| Server | Action | CLI to build | Skill to create |
|--------|--------|--------------|-----------------|
| `searxng` | Build `srx` CLI → create skill → drop MCP from Codex | `srx "query"` (SearXNG HTTP API) | `dev-tools:web-search` |
| `heypresto` | Investigate API → build `hp` CLI → create skill → evaluate mobile | `hp "text"` | `dev-tools:heypresto` |

### Ship both (build CLI for coding harness, keep MCP for mobile)

| Server | Action |
|--------|--------|
| `executive-circle` | Build `ec` CLI + `content:executive-circle-cli` skill; retain MCP for claude.ai/iOS |
| `open-brain` | Build `ob` CLI for on-demand queries (`ob search`, `ob save`); retain hooks for automatic capture; retain MCP for claude.ai/iOS |

### Keep MCP (state, encrypted format, or harness constraint)

| Server | Reason |
|--------|--------|
| `playwright` | Stateful browser sessions |
| `pencil` | Stateful editor + encrypted .pen format |
| `lsp` | Stateful LSP sessions |
| `FileSystem` (Desktop) | Desktop harness has no shell |

### Removed

| Entry | Rationale |
|-------|-----------|
| `stringer` | Removed entirely: unused third-party Homebrew tool; Codex MCP entry, CLI, and `beads-workflow:stringer` skill retired. |
| `skill-seeker` | Removed from Claude Code MCP config: native skill discovery is sufficient; repo disposition remains separate. |

### No action (not an MCP server / already converted)

| Entry | Status |
|-------|--------|
| `crawl4ai` | Already converted to CLI (`crwl`); no MCP to drop |
| `claude-in-chrome` | Chrome extension, not MCP; managed separately |

---

## Follow-up Beads

The following implementation beads should be created from this audit:

1. **Convert `markitdown` to CLI+Skill** — build `dev-tools:markitdown` skill, drop MCP
2. **Build `searxng` CLI wrapper** (`srx`) and `dev-tools:web-search` skill, drop MCP
3. **Investigate `heypresto`** — determine CLI viability, build if feasible
4. **Build `executive-circle` CLI** (`ec`) for coding harnesses
5. **Build `open-brain` CLI** (`ob`) for on-demand memory queries (`ob search`, `ob save`, etc.); hooks remain for automatic capture, MCP remains for claude.ai/iOS
6. **Update `library.yaml`** — reflect `crawl4ai` as CLI-only, add MCP registry entries per CL-mfz schema
