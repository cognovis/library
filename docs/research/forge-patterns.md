# Forge Patterns — Industry Research

> Status: research artifact, 2026-05-13.
> Drives AC refinements for the Primitive Forge Symmetry epic
> (cognovis-core bead `clc-0ym` and its children).
> Knowledge cutoff Jan 2026, supplemented by WebSearch verification May 2026.

## Why this exists

The four primitive forges (`skill-forge`, `agent-forge`, `hook-creator`/`hook-forge`,
`standard-forge`) are the **generators** of new primitives going forward. Whatever
discipline they bake in becomes the de-facto fleet-wide convention by accretion —
new primitives are modern, old primitives drift until refactored. So:

> **The forges drive the primitives. Industry-standard forges produce
> industry-standard primitives without a separate fleet retrofit.**

This document captures verified industry patterns (May 2026) and maps them to
concrete AC additions for the forge beads.

## Verified findings (May 2026)

### 1. agentskills.io SKILL.md spec

Verified against agentskills.io specification + Anthropic Claude API docs.

| Field | Spec status | Notes |
|-------|------------|-------|
| `name` | required, 1-64 chars, `[a-z-]+`, MUST match parent directory name, no leading/trailing/consecutive hyphens | We don't currently enforce |
| `description` | required, max 1024 chars, describes what AND when | We align |
| `license` | optional, recommended-short | Often empty in our lockfile |
| `compatibility` | optional, 1-500 chars, intended product / system packages / network access | **We don't use** |
| `metadata` | optional, string->string map | **We don't use** |
| `allowed-tools` | optional, space-delimited, experimental — note the hyphen | We use `tools:` (Claude extension); different field |

Body is unrestricted markdown.

### 2. Codex CLI subagents

Verified against `developers.openai.com/codex/subagents` and Daniel Vaughan's
2026-04-12 walkthrough.

- Built-ins: `default` (general), `worker` (execution-focused), `explorer` (read-heavy)
- Custom TOML at `~/.codex/agents/<name>.toml` (global) or `.codex/agents/<name>.toml` (project)
- Required keys: `name`, `description`, `developer_instructions`
- Optional config carries over: `model`, `model_reasoning_effort`, `sandbox_mode`, `mcp_servers`, `skills.config`
- **`agents.max_depth = 1` default** — Codex prevents nesting deeper than direct child.
  Multi-level orchestration (orchestrator -> sub-orchestrator -> worker) blocks
  unless explicitly overridden.
- `agents.max_threads` caps parallel agents

### 3. Cursor rules

Verified against `cursor.com/docs/context/rules` and 2026 community walkthroughs.

- `.cursorrules` (legacy single-file): supported but **deprecated**; migration to
  Project Rules OR **AGENTS.md** recommended.
- Cursor 2.2+ creates rules as **folders** under `.cursor/rules/<rulename>/`, not
  single `.mdc` files — direct convergence with our `.agents/skills/<name>/` layout.
- Three application modes in MDC frontmatter:
  - `alwaysApply: true` -> loaded every chat
  - `globs: ["..."]` -> loaded when matching files are open/mentioned
  - description-only -> "Apply Intelligently" (model decides)

### 4. Claude Code hooks — current event list

Verified against `code.claude.com/docs/en/hooks` (May 2026).

Three cadences:

| Cadence | Events |
|---------|--------|
| Per session | `SessionStart`, `SessionEnd` |
| Per turn | `UserPromptSubmit`, `UserPromptExpansion`, `Stop`, `StopFailure` |
| Per tool call | `PreToolUse`, `PostToolUse`, `PostToolUseFailure` |
| Per permission | `PermissionRequest`, `PermissionDenied` |
| Per subagent | `SubagentStart`, `SubagentStop` |
| Other | `PreCompact`, `Notification` |

14 events total. Our `meta/docs/primitives/guardrail-hook.md` lists 13 and includes a stale
`Setup` event; missing `UserPromptExpansion`, `PermissionDenied`, `StopFailure`.

## Cross-cutting industry signals

1. **AGENTS.md is the cross-tool common ground.** Cursor (migration target), Codex
   (native), us (adapter). Strong validation that our standards architecture is on
   the right shape.
2. **Folder-per-primitive convergence.** Cursor 2.2+, agentskills.io, us. The
   "single mega-rules-file" approach (Copilot, Aider, legacy `.cursorrules`) is the
   losing pattern.
3. **Three triggering modes** (always / glob / description) is the richer taxonomy
   than description-only.
4. **Test fixtures next to artifacts.** pre-commit framework, agentskills cookbook,
   modern Yeoman generators all do this; we do not.
5. **Decision-envelope output for policy** (OPA/Rego pattern) — beats raw exit codes
   for hooks.

## Per-forge AC additions (for clc-0ym children)

### clc-0ym.2 — skill-forge

Augment original ACs with:

- (a) Validate `name` per agentskills.io regex + parent-dir-match rule.
- (b) Cap `description` at 1024 chars.
- (c) Scaffold offers `compatibility:` field (Claude Code, Codex CLI, etc.).
- (d) Scaffold offers `metadata:` (string-string map) replacing ad-hoc tags.
- (e) Scaffold offers optional `globs:` field (Cursor-style fallback trigger).
- (f) Emit BOTH `allowed-tools:` (agentskills standard) AND `tools:` (Claude
  extension) where applicable, or document divergence in SKILL.md body.
- (g) Dual install path: `.agents/skills/<name>/` canonical + `.claude/skills/<name>`
  bridge per cookbook 5c.
- (h) Scaffold a `tests/<name>.test.md` fixture (input -> expected behavior).
- (i) Print library.yaml entry snippet (name, description, source, requires, tags).

### clc-0ym.3 — agent-forge

Augment original ACs with:

- (a) ALWAYS offer Claude `.md` + Codex `.toml` sibling generation via
  `meta/scripts/convert-agent.py`. Emit a Codex coverage warning if user declines.
- (b) Add structured Role/Goal/Background section at top of agent body
  (CrewAI-inspired clarity discipline).
- (c) Tool-grant prompt refuses kitchen-sink (`Read,Write,Edit,Bash,Grep,Glob,Agent`)
  without an explicit C-criterion justification per agentic-primitives standard.
- (d) **Warn when the agent declares it spawns other agents** — Codex
  `agents.max_depth = 1` default blocks depth>1 without explicit config override.
- (e) Print `sources:` map snippet (claude + codex) for library.yaml.

### clc-0ym.4 — hook-creator / hook-forge

Augment original ACs with:

- (a) Per-harness event-coverage matrix uses the **current Claude Code 14-event
  list** (SessionStart, SessionEnd, UserPromptSubmit, UserPromptExpansion, Stop,
  StopFailure, PreToolUse, PostToolUse, PostToolUseFailure, PermissionRequest,
  PermissionDenied, SubagentStart, SubagentStop, PreCompact, Notification).
- (b) Scaffold asks "which cadence — session / turn / tool-call / permission /
  subagent / other?" and derives the event set from the answer.
- (c) PreToolUse hooks scaffold a decision-envelope output `{decision: allow|block,
  reason: "..."}` (OPA/Rego pattern) rather than raw exit codes.
- (d) Paired positive (should-block) + negative (should-allow) test fixtures
  scaffolded under `tests/hooks/<name>/`.
- (e) Emit `capability:` map for library.yaml `library.guardrails` entry
  `{claude: pre-tool-veto|post-tool-reaction|..., codex-cli: workaround|none, ...}`.
- (f) Hook script template includes a "<100ms target" comment for PreToolUse
  (pre-commit framework discipline).

### clc-0ym.5 — standard-forge

Augment original ACs with:

- (a) Scaffolded standards GET YAML frontmatter: `name`, `description`,
  `triggers`, optional `globs`, optional `alwaysApply`, optional `version`.
  Establish forward standard (existing fleet retrofits via separate bead).
- (b) Scaffold informs user how Codex will see the standard: via AGENTS.md adapter
  generated by `/library standard sync --emit-agents-md` or by Codex's native
  `.agents/standards/` read.
- (c) Bundle-vs-single decision gate at scaffold start.
- (d) Print `requires_standards: [<name>]` snippet for consuming skills/agents.
- (e) `globs:` + `alwaysApply:` fields adopted from Cursor for trigger-richness.
- (f) Primitive Gate refuses imperative-workflow content and dispatches to
  skill-forge (already in original ACs — reinforce).

## Implications for the meta library installer (`meta/`)

These are NOT covered by clc-0ym children — they are library-installer-level work
and need their own bead(s).

### M1. Implement `/library agent use` in `scripts/library.py`

Currently returns `blocked` ("not yet implemented"). The wave-orchestrator install
during this research session hit this gap. Required for cross-harness agent installs
(claude `.md` + codex `.toml` siblings via `sources:` map) to work via the CLI.

### M2. Extend `library.yaml` schema for industry-standard fields

Add to `docs/schema/library.schema.json`:

- `globs:` (array of string) on skill and standard entries — file-pattern trigger
  fallback (Cursor convergence).
- `always_apply:` (bool) on skill and standard entries — cross-cutting always-on
  rules (Cursor convergence). Use sparingly.
- `compatibility:` (string, 1-500 chars) on skill entries — agentskills.io standard.
- `metadata:` (map<string,string>) on skill entries — agentskills.io standard,
  replaces ad-hoc tags for non-trigger data.
- `version:` (semver string) on all entries — optional but recommended; helps
  humans and lets `/library sync` log version changes.

### M3. Validate skill name + description per agentskills.io

Extend `scripts/validate-library.py` to enforce:

- `name`: 1-64 chars, `[a-z-]+`, no leading/trailing/consecutive hyphens, must
  match the basename of the install target dir.
- `description`: max 1024 chars.

These are non-controversial agentskills.io rules; we're already aligned in spirit.

### M4. Document the lockfile-location convention

`~/.library.lock` is implicit for user-global installs; per-project `.library.lock`
is implicit for project-local installs. Document in `docs/lockfile-format.md`.

### M5. Cursor-rule importer (deferred / nice-to-have)

`/library skill use --from-cursor <path/to/.cursor/rule/>` could ingest Cursor
rules into our marketplace. Cursor's MDC frontmatter maps cleanly to our entries
(description, globs, alwaysApply). Defer until demand surfaces.

### M6. Refresh `meta/docs/primitives/guardrail-hook.md`

Update the Claude Code hook event list (currently 13 with stale `Setup`; should be
14 with the three-cadences taxonomy). Small task, but the guardrail primitive doc is the
authoritative reference for hook-forge and any future hook authoring.

## What we already do well (worth keeping)

- C1-C6 justification (`standards/agentic-primitives.md`) is more rigorous than
  CrewAI/AutoGen role definitions. Keep.
- Three-layer composition (golden_prompt + body + model-standard) via
  `compose-agent.py` — closest analog is hand-rolled system-prompt fragments in
  other teams. Our automation is ahead.
- AGENTS.md adapter (CL-v56 loader) — industry is converging here.
- Marketplace-via-yaml + content-addressable tree-SHA cache — analogous to npm/pip,
  ahead of most agentic tooling.
- Folder-per-primitive layout (`.agents/skills/<name>/`) — converges with Cursor
  2.2+. Keep.

## What we are behind on (covered by ACs above)

- No `globs:` / `alwaysApply:` triggering modes.
- No test-fixture scaffolding.
- No formal `compatibility:` declaration.
- Standards lack frontmatter (fleet retrofit needed; standard-forge produces
  frontmatter-bearing from day one).
- Hooks have no decision-envelope discipline.
- No latency-budget assertions on PreToolUse hooks.

## Sources

- agentskills.io specification: https://agentskills.io/specification
- Anthropic Agent Skills overview: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- Codex subagents: https://developers.openai.com/codex/subagents
- Codex CLI customisation stack walkthrough (2026-04-12): https://codex.danielvaughan.com/2026/04/12/codex-cli-customisation-stack-unified-system/
- Cursor rules docs: https://cursor.com/docs/context/rules
- Claude Code hooks reference: https://code.claude.com/docs/en/hooks
