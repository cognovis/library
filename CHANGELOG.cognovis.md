# Cognovis Library Changelog

This changelog tracks changes made by Cognovis on top of the upstream fork.
Upstream: https://github.com/disler/the-library (forked at commit `47f455c`)

---

## [Unreleased]

### Changed

- **Architecture Documentation** (`docs/ARCHITECTURE.md`): Expanded Primitive Definitions section with decision rule for new artifacts (4-question workflow) and harness portability matrix (8 primitive types × 4 harnesses). Fixed factual errors in Codex paths, hook configuration, and MCP syntax; corrected placeholder inconsistency in install paths.
- **Library Use Cookbook** (`cookbook/use.md`): Added Step 5d (Name Collision Check) — mandatory collision detection for all skill installs using Step 5b resolved paths. Detects two-real-directory collision state, emits warning with three resolution options, enforces bridge-first ordering. Former Step 5d (Translation Warnings) renumbered to 5e. Closes CL-b4o.
- **Agentic Primitives Glossary** (`docs/PRIMITIVES.md`): Added Precedence and Name Collision Policy section summarizing canonical/bridge path roles, per-harness precedence rules, name uniqueness requirement, uninstall completeness rule, and admin override policy. Closes CL-b4o.
- **Smoke Tests** (`tests/smoke/`): Added `smoke_name_collision()` function (10 structural checks) validating all CL-b4o policy rules for Claude Code and Codex harnesses. Updated `smoke_codex()` bridge direction to match CL-b4o policy (.agents/skills symlinks to .claude/skills). Added `name-collision` harness target to runner. Updated README with claims 23–32. Closes CL-b4o.

### Added

- **Name Collision and Precedence Policy** (`docs/policy/name-collision.md`): Authoritative 7-decision policy for how the library handles skill name collisions across harness paths. Covers per-harness precedence (project-local wins over global), canonical/bridge install pattern (Claude Code path is canonical real file; Codex path is bridge symlink), symlink lifecycle and preservation rules, cross-harness name uniqueness requirement, versioned install behavior, uninstall completeness (bridge-first removal), and admin override semantics for Anthropic marketplace force-enable. Includes enforcement checklist for `/library use` and cross-references to cookbook, PRIMITIVES.md, and smoke tests. Closes CL-b4o.
- **Cross-Harness Smoke Tests** (`tests/smoke/`): End-to-end validation suite confirming skill discovery, install paths, and symlink handling across harnesses (Claude Code, Codex, Pi, OpenCode). Per-harness fixture skills and test runner (justfile recipe `test-smoke`); comprehensive README documenting verified claims (8 smoke test categories including name collision behavior, project-local overrides, and symlink git preservation). Validates empirically that Library install paths work correctly before broader multi-harness migration. Closes CL-zda.
- **Marketplace Registry** (`library.yaml` + JSON Schema): Added `marketplaces:` category to library.yaml schema to reference third-party GitHub orgs/repos publishing skills, agents, and prompts. New `/library add-marketplace` and `/library list-marketplaces` cookbooks. Catalog entries now support `from_marketplace` field to pull content from registered marketplaces. Marketplace validation integrated into `validate-library.py`.
- **Agentic Primitives Glossary** (`docs/PRIMITIVES.md`): Comprehensive v0 taxonomy defining 9 primitive types (skill, command, agent, guardrail, plugin, marketplace, standard, mcp-server, plus design principle on scripts) with decision tree, worked examples, and per-harness capability matrix labeled as NORMATIVE or INFERRED claims. Cross-referenced from `docs/ARCHITECTURE.md`.
- **Layer 2 Format Translation Spec** (`docs/research/agents-format-mapping.md`): Comprehensive mapping for agent portability between Claude Code `.md` and Codex `.toml` formats. Includes field-by-field translation table (13 fields), canonical source rationale (Claude Code as primary), forward/reverse translation algorithms with 9-step workflows, model vocabulary mapping, sandbox_mode derivation rules, and worked example translating the researcher agent. Identifies lossy fields and proposes `codex_*` extended frontmatter convention for round-trip fidelity. Closes CL-11p.
- **MCP Server Audit** (`docs/audit/mcp-servers.md`): Classification of 11 installed MCP servers across all harnesses (Codex, Claude Desktop, Claude Code) against the PRIMITIVES.md decision matrix. Per-server migration recommendations (convert to CLI+Skill vs. keep MCP for stateful/mobile use) with 8 follow-up implementation beads identified.
- **Layer 2 Format Translation Spec** (`docs/research/agents-format-mapping.md`): Comprehensive mapping for agent portability between Claude Code `.md` and Codex `.toml` formats. Includes field-by-field translation table, canonical source rationale (Claude Code as primary), forward/reverse translation algorithms with 9-step workflows, model vocabulary mapping, sandbox_mode derivation rules, and worked example translating the researcher agent. Identifies 3 lossy fields (tools→sandbox_mode, mcpServers→comment, system_prompt_file→inline) and proposes `codex_*` extended frontmatter convention for round-trip fidelity.

---

## [v2026.04.2] - 2026-04-16

### Added

- `docs/research/codex-prompts.md` (324 lines): CL-qzw research on Codex Layer 3
  (prompts/skills) parity. Scope expanded during research to cover all 4 layers +
  Hooks + Observability because findings cross-cut multiple epic deliverables.
  Key findings:
  - Codex modern Layer 3 primitive is Skills (`.agents/skills/<name>/SKILL.md`),
    not custom prompts (`~/.codex/prompts/` is deprecated).
  - Codex has 3 hook events vs Claude Code's 13 — observability is asymmetric.
  - No `--bead` flag in Codex CLI; `cdx` wrapper must inject bead context via prompt.
  - `tools:` frontmatter is Claude-Code-only; Codex uses coarser `sandbox_mode`.
  - Go/No-Go confirmed for CL-6hg, CL-tap, CL-06x.
- New bead CL-7hp: Adapt indydevdan multi-agent observability pattern (P2, blocked
  by CL-xcm + CL-06x).
- Research notes injected into CL-6hg, CL-tap, CL-06x, CL-xcm.

### Changed

- `.gitignore`: Added `.claude/anatomy.json` (tool-internal open-brain cache).

---

## [v2026.04.1] - 2026-04-16

### Added

- Forked from `disler/the-library` at commit `47f455c` as the basis for Cognovis
  multi-harness distribution (Claude Code + Codex + marketplaces).
- `docs/ARCHITECTURE.md`: Captures the fork rationale and design decisions:
  - Catalog + content-repo split (one catalog, many content repos)
  - Per-repo on-demand distribution over BMAD deploy-all
  - Codex subagents as first-class citizens alongside Claude Code
  - Open agent-skills standard shared by both harnesses
  - IndyDevDan's original pattern as the foundation
- `AGENTS.md`: Agent instructions for this repo (non-interactive shell, beads workflow)
- `CLAUDE.md`: Claude Code project instructions (beads integration, session close protocol)
- `.claude/settings.json`: Project hooks (SessionStart/PreCompact run `bd prime`)
- `.claude/anatomy.json`: Open-brain anatomy config
- `.gitignore`: Added beads/Dolt entries (`.dolt/`, `*.db`, `.beads-credential-key`)
- Seeded 11 beads for multi-harness extension work:
  - Epic `CL-36o`: Multi-harness library (parent of all sub-beads)
  - `CL-nvp`: Document architecture
  - `CL-6hg`: Add Codex paths to default_dirs in library.yaml
  - `CL-06x`: Extend /library use cookbook with tool-awareness
  - `CL-7ii`: Add marketplaces: category to library.yaml schema
  - `CL-xcm`: Add hooks as fourth artifact type
  - `CL-tap`: Build cdx wrapper script
  - `CL-qzw`: Research Codex layer-3 format and install path
  - `CL-11p`: Layer 2 agents format translation spec
  - `CL-23z`: Third-party origin audit
  - `CL-1rr`: Bootstrap content repos
  - Dependency graph wired: epic depends on all subs; inter-sub deps correctly set
