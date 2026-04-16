# Codex Layer 3 Research: Prompts / Slash Commands / Skills

> **Bead:** CL-qzw | **Epic:** CL-36o (Multi-Harness Library) | **Date:** 2026-04-16
> **Scope:** Originally Layer 3 (Prompts/Commands). Expanded during research to cover all 4 layers + Hooks + Observability, because the findings cross-cut multiple epic deliverables.

---

## Executive Summary

**Layer 3 Parity: PARTIAL.** Format-compatible on surface (both use `.md` + YAML frontmatter), but architecturally divergent:

| | Claude Code | Codex CLI |
|---|---|---|
| Primitive | Slash commands (single `.md` file, explicit `/name` invocation) | **Skills** (directory with `SKILL.md`, invoked via `$name` mention or `/skills` picker) — modern; custom prompts are deprecated |
| Built-ins | No native built-in slash commands for user content | 25+ built-in slash commands (`/model`, `/review`, `/plan`, `/mcp`, …) |
| Per-command tool constraint | `tools:` frontmatter (fine-grained) | **Not supported** — use `sandbox_mode` + `mcp_servers` allowlist + `skills.config` (coarser) |
| Task/bead reference flag | `/dispatch <id>`, `cld -b <id>` | **No equivalent** — subagents invoked via natural prompt |

**Implication for library:** We can translate Claude Code slash commands to Codex skills (directory-generation), but cannot preserve per-command tool scoping semantics. Bead orchestration requires a custom `cdx` wrapper with prompt-based invocation.

**Go/No-Go for CL-6hg, CL-tap, CL-06x: GO**, with adjustments documented below.

---

## Install Paths (feeds CL-6hg)

### Layer 3 (Prompts / Slash Commands / Skills)

| Tool | Project-local | User-global | File format |
|------|---------------|-------------|-------------|
| **Claude Code** | `.claude/commands/<name>.md` | `~/.claude/commands/<name>.md` | Single `.md` with YAML frontmatter |
| **Codex (legacy, deprecated)** | — | `~/.codex/prompts/<name>.md` | Single `.md` with YAML frontmatter |
| **Codex (modern, preferred)** | `.agents/skills/<name>/SKILL.md` | `~/.agents/skills/<name>/SKILL.md` | Directory with `SKILL.md` + optional `agents/openai.yaml` + assets |

**Decision for library.yaml `default_dirs`:** Target **Codex skills** (modern). Deprecated custom prompts should NOT be a supported target.

```yaml
default_dirs:
  skills:
    - default: .claude/skills/
    - default_codex: .agents/skills/
    - global: ~/.claude/skills/
    - global_codex: ~/.agents/skills/
  agents:
    - default: .claude/agents/
    - default_codex: .codex/agents/
    - global: ~/.claude/agents/
    - global_codex: ~/.codex/agents/
  commands:
    - default: .claude/commands/
    - default_codex: .agents/skills/   # Codex has no "commands" primitive — use skills
    - global: ~/.claude/commands/
    - global_codex: ~/.agents/skills/
```

### Shared Instructions (cross-cut)

- **`AGENTS.md`** at repo root — read by BOTH tools. Codex has sophisticated discovery (walks project root → CWD, concatenates with override precedence, 32 KiB default limit via `project_doc_max_bytes`).
- **`.claude/CLAUDE.md`** — Claude-Code-only private guidance.
- **`~/.codex/config.toml`** — Codex global config.

### Hooks (feeds CL-xcm)

| Tool | Hook events supported | Configuration |
|------|----------------------|---------------|
| **Claude Code** | 13 events: `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `Notification`, `SubagentStart`, `SubagentStop`, `Stop`, `PreCompact`, `Setup` | `.claude/settings.json` + `.claude/hooks/*` |
| **Codex CLI** | **3 events only**: `SessionStart`, `SessionEnd`, `Stop` | `hooks.json` in plugin or Codex config; matcher field supported |

**Implication:** Codex is a **second-class citizen for observability**. Hook-based observability (indydevdan pattern) captures ~4x more events in Claude Code. Cross-tool observability dashboards would show asymmetric coverage.

---

## Invocation Syntax (feeds CL-tap)

### Claude Code
- Slash menu: `/name [args]`
- Bead orchestrator: `cld -b <bead-id>` or `/dispatch <id>`
- Non-interactive: Direct shell invocation of Claude CLI with prompt

### Codex
- **Built-in slash commands** (always available): `/model`, `/fast`, `/personality`, `/permissions`, `/agent`, `/init`, `/diff`, `/status`, `/plan`, `/review`, `/mcp`, `/clear`, `/compact`, `/mention`, `/skills`, …
- **Skills (user-defined Layer 3)**: `$skill-name` mention in prompt, or `/skills` picker
- **Custom prompts (deprecated Layer 3)**: `/prompts:name ARG1=value ARG2=value`
- **Non-interactive**: `codex exec "prompt text"` — plain text only, no slash commands processed
- **Subagents**: Natural-language invitation ("spawn one agent per point…") — NOT a CLI flag
- **Session resume/fork**: `codex fork`, `/resume`

### `cdx -b <bead-id>` Design Recommendation (CL-tap)

Since Codex has no flag-based task reference, `cdx` must synthesize the invocation:

```bash
#!/usr/bin/env bash
# cdx -b <bead-id> wrapper
bead_id="$2"
initial_prompt=$(bd show "$bead_id" --format=markdown)
codex exec "Work on bead $bead_id. $initial_prompt. Use the \$bead-orchestrator skill if available."
```

This prompts Codex with full bead context instead of relying on a non-existent `--bead` flag.

---

## File Format Translation

### YAML Frontmatter Mapping

**Claude Code slash command:**
```yaml
---
description: "What this command does"
tools: [Bash, Read, Glob]        # Per-command tool scoping
model: "claude-opus-4"           # Optional model override
---
```

**Codex skill (modern, required):**
```yaml
---
name: "skill-name"               # REQUIRED, unique
description: "When this skill triggers (explicit + implicit)"  # REQUIRED
---
```

**Codex skill `agents/openai.yaml` (optional, richer metadata):**
```yaml
interface:
  display_name: "Human-facing name"
  short_description: "UI blurb"
  icon_small: "./assets/small-logo.svg"
  brand_color: "#3B82F6"
  default_prompt: "Optional surrounding prompt"
policy:
  allow_implicit_invocation: false   # Default true
dependencies:
  tools:
    - type: "mcp"
      value: "openaiDeveloperDocs"
      url: "https://developers.openai.com/mcp"
```

### Translation Rules (for CL-06x `/library use` tool-awareness)

| Claude Code field | Codex equivalent | Translation notes |
|-------------------|------------------|-------------------|
| `description:` | `description:` in `SKILL.md` | Direct copy |
| `tools: [Bash, Read]` | ⚠️ **No direct equivalent** | Must translate to `sandbox_mode` + `mcp_servers` in global Codex config — **cannot be done per-skill**. Emit warning. |
| `model: claude-opus-4` | Custom agent `.toml` with `model = "gpt-5"` | Generate sibling `.codex/agents/<name>.toml` instead of inline |
| `$ARGUMENTS` | `$1..$9` or `$NAMED` (legacy) / prompt templating (skills) | Skills handle args via prompt context — not direct substitution |
| Subagent invocation | Built-in subagents (`worker`, `explorer`) or custom `.toml` | Map `Agent(subagent_type=X)` → Codex custom agent reference |

---

## Feature Parity Gap Analysis

### Claude Code Advantages (Codex cannot match)
1. **Per-command tool constraint** (`tools:` frontmatter) — Codex scoping is coarser.
2. **Flag-based bead/task dispatch** (`cld -b <id>`) — Codex has no flag equivalent.
3. **Single-file slash commands** — Codex skills require directory structure.
4. **13 hook events** for observability — Codex has 3.

### Codex Advantages (Claude Code cannot match)
1. **First-class parallel subagents** (`spawn_agents_on_csv`, built-in `default`/`worker`/`explorer` agents). Claude Code requires manual `Agent()` scripting.
2. **Per-agent model/reasoning-effort override** via TOML (`model_reasoning_effort`).
3. **Implicit skill invocation** (`policy.allow_implicit_invocation`) — skills auto-trigger on description match.
4. **Fallback instruction filenames** (`project_doc_fallback_filenames` config).
5. **Built-in slash commands** (`/model`, `/review`, `/plan`, `/mcp`, …) reduce boilerplate.
6. **Skill installer & discovery** (`$skill-installer`).

### Incompatibilities (translation barriers)
- Tool scoping (Claude per-command vs. Codex global)
- Task orchestration (flag-based vs. prompt-based)
- Invocation UX (`/name` vs. `$name` or `/skills` picker)

---

## Additional Findings — Hooks & Observability (cross-cut to CL-xcm + future beads)

### indydevdan `claude-code-hooks-multi-agent-observability` (canonical reference)

**Architecture:** `Claude Code agents → hook scripts (Python/uv) → HTTP POST → Bun server → SQLite → WebSocket → Vue dashboard`

**Captured events (12):** Full lifecycle — `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `Notification`, `SubagentStart`, `SubagentStop`, `Stop`, `PreCompact`

**Per-event fields:** `source_app`, `session_id`, `hook_event_type`, `tool_name`, `tool_use_id`, `timestamp`, `model_name`, `payload`

**Reusable as library content:**
- Full `.claude/hooks/` directory (12 Python uv scripts)
- Bun observability server (runnable, not a library primitive)
- Vue dashboard (runnable)

### indydevdan `claude-code-hooks-mastery` (canonical hook patterns)

**Documents all 13 Claude Code hook lifecycle events**, including:
- Exit-code-based flow control (`0`=allow, `1`=block, 2=specialized)
- UV single-file scripts as hook runtime (portable, no venv)
- Validator sub-scripts pattern (`.claude/hooks/validators/`)
- Output-styles pattern (10+ reusable markdown formatters)

### indydevdan `install-and-maintain` (canonical Justfile pattern)

- `just cldi` / `just cldii` / `just cldm` / `just cldmm` = deterministic vs agentic setup/maintenance
- Hook `matcher` field enables context-aware execution (`matcher: "init"` vs `"maintenance"`)
- **Justfile is Claude-Code-only** — Codex has no first-class `just` integration

### Cross-Tool Observability Implication

Because Codex exposes only 3 hook events vs Claude Code's 13, a unified dashboard would see:

| Event | Claude Code | Codex |
|-------|:-----------:|:-----:|
| SessionStart / SessionEnd | ✅ | ✅ |
| Stop | ✅ | ✅ |
| PreToolUse / PostToolUse | ✅ | ❌ |
| UserPromptSubmit | ✅ | ❌ |
| Subagent* | ✅ | ❌ |
| PermissionRequest | ✅ | ❌ |

**Recommendation:** Build observability assuming Claude-Code-primary coverage; expose a degraded "session-only" view for Codex tasks. Document this asymmetry prominently.

---

## Tool Detection (feeds CL-06x)

No standard convention exists. Library must define one.

| Marker | Tool indicated |
|--------|----------------|
| `.claude/` directory | Claude Code |
| `.agents/` directory | Codex (modern skills) |
| `.codex/` directory | Codex (legacy / agents) |
| `~/.codex/config.toml` | Codex installed user-globally |
| `AGENTS.md` at repo root | Both tools (shared instructions) |
| `.claude/settings.json` | Claude Code plugin/hook config |

**Recommended detection order** for `/library use`:
1. Both `.claude/` and `.agents/` → dual-install, warn if skill names collide
2. Only `.claude/` → Claude Code target
3. Only `.agents/` or `.codex/` → Codex target
4. Neither → prompt user or install to both

---

## Recommendations by Dependent Bead

### CL-6hg — add Codex paths to `library.yaml` default_dirs
- Add 4 layers × 2 tools path matrix (see "Install Paths" section)
- Target Codex **skills**, not deprecated custom prompts
- Commands layer for Codex maps to `.agents/skills/` (no native commands primitive)

### CL-tap — `cdx` wrapper
- No `--bead` flag equivalent exists — wrapper must fetch bead context via `bd show` and inject into `codex exec` prompt
- Mirror `cld -b`, `cld -bq`, `cld -br` signatures but all route via `codex exec` with enriched initial prompt

### CL-11p — Layer 2 agents format translation (unchanged, confirmed)
- Claude Code `.md` + YAML frontmatter ↔ Codex `.toml` — hardest layer, as previously scoped
- Note: Codex custom agents support `model_reasoning_effort`, `max_threads`, `max_depth` — no Claude Code equivalent. Document as Codex-only fields.

### CL-06x — tool-aware `/library use` cookbook
- Implement detection order above
- Warn on tool-scoping (`tools:` frontmatter) translation — cannot preserve per-skill scoping in Codex
- Support dual-install when both markers present

### CL-xcm — hooks category
- Encode Codex's 3-event subset vs Claude's 13-event superset
- Reference indydevdan `claude-code-hooks-mastery` as canonical pattern source
- Document: skills/agents installed via library MAY ship `.claude/hooks/` but cannot ship equivalent Codex hooks (platform limitation)

### (new, potential) Observability feature bead
- Material exists in indydevdan `claude-code-hooks-multi-agent-observability`
- Cross-tool observability requires acceptance of asymmetric coverage
- Decision needed: ship the Bun-server + Vue-dashboard as library content, or only ship the hook scripts?

---

## Plan B — Fallback if translation blocks implementation

**Scenario A — tool scoping (`tools:` frontmatter) cannot be preserved:**
- Emit warning during `/library use`; install skill anyway; document that Codex-installed version runs with Codex's sandbox default.
- Long-term: propose upstream feature to Codex (per-skill tool allowlist).

**Scenario B — bead orchestration (`/dispatch`) needed but Codex lacks flag:**
- `cdx -b <id>` wrapper synthesizes prompt (already recommended above).
- Accept prompt-injection invocation as first-class pattern.

**Scenario C — hook parity missing for observability:**
- Ship full 13-hook set for Claude Code; emit degraded 3-hook set for Codex; document asymmetric observability explicitly.

**Scenario D — deprecated custom prompts resurface as demand:**
- If users want `.codex/prompts/` style installs, treat as legacy-only path; prefer modern skills; provide migration helper `bd skills migrate-from-prompts`.

---

## Open Questions (require follow-up)

1. Does Codex `$skill-name` mention support `$ARGUMENTS`-style substitution identical to Claude Code, or only the legacy `$1..$9` / `$NAMED` of deprecated custom prompts?
2. If both `.claude/commands/<name>.md` AND `.agents/skills/<name>/SKILL.md` exist for the same concept, what's the resolution behavior? (Assumption: both activate in their respective tool; needs verification.)
3. Does `agents/openai.yaml` `dependencies.tools[].type: "mcp"` permit per-skill MCP scoping, or is it documentation-only?
4. Can `spawn_agents_on_csv` be invoked from a skill's SKILL.md content, or only via top-level agent mention?
5. Does Codex CLI have a roadmap to expand hook events beyond `SessionStart`/`SessionEnd`/`Stop`?

---

## Sources

### Codex Official Docs
- `https://developers.openai.com/codex/` (Developer Docs hub)
- `https://developers.openai.com/codex/skills.md`
- `https://developers.openai.com/codex/custom-prompts.md` (marked DEPRECATED)
- `https://developers.openai.com/codex/subagents.md`
- `https://developers.openai.com/codex/cli/slash-commands.md`
- `https://developers.openai.com/codex/cli/reference.md`
- `https://developers.openai.com/codex/guides/agents-md.md`

### Open Standard
- `https://agentskills.io/specification` — Open Agent Skills standard (both tools implement)

### Local Reference Material
- `~/.claude/plugins/cache/openai-codex/codex/1.0.3/` — Codex Claude-Code-plugin payload (3 skills, 1 agent, 7 commands, 3 hooks)
- `~/code/learning-references/indydevdan/claude-code-hooks-multi-agent-observability/`
- `~/code/learning-references/indydevdan/claude-code-hooks-mastery/`
- `~/code/learning-references/indydevdan/install-and-maintain/`
- `~/code/learning-references/indydevdan/agentic-drop-zones/`
- `~/code/cognovis-library/docs/ARCHITECTURE.md`
