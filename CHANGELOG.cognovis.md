# Cognovis Library Changelog

This changelog tracks changes made by Cognovis on top of the upstream fork.
Upstream: https://github.com/disler/the-library (forked at commit `47f455c`)

---

## [Unreleased]

### Added

- **Agentic Primitives Glossary** (`docs/PRIMITIVES.md`): Comprehensive v0 taxonomy defining 9 primitive types (skill, command, agent, guardrail, plugin, marketplace, standard, mcp-server, plus design principle on scripts) with decision tree, worked examples, and per-harness capability matrix labeled as NORMATIVE or INFERRED claims. Cross-referenced from `docs/ARCHITECTURE.md`.
- **MCP Server Audit** (`docs/audit/mcp-servers.md`): Classification of 11 installed MCP servers across all harnesses (Codex, Claude Desktop, Claude Code) against the PRIMITIVES.md decision matrix. Per-server migration recommendations (convert to CLI+Skill vs. keep MCP for stateful/mobile use) with 8 follow-up implementation beads identified.
- **Layer 2 Format Translation Spec** (`docs/research/agents-format-mapping.md`): Comprehensive mapping for agent portability between Claude Code `.md` and Codex `.toml` formats. Includes field-by-field translation table, canonical source rationale (Claude Code as primary), forward/reverse translation algorithms with 9-step workflows, model vocabulary mapping, sandbox_mode derivation rules, and worked example translating the researcher agent. Identifies 3 lossy fields (tools→sandbox_mode, mcpServers→comment, system_prompt_file→inline) and proposes `codex_*` extended frontmatter convention for round-trip fidelity.

### Changed

- **Architecture Documentation** (`docs/ARCHITECTURE.md`): Expanded Primitive Definitions section with decision rule for new artifacts (4-question workflow) and harness portability matrix (8 primitive types × 4 harnesses). Fixed factual errors in Codex paths, hook configuration, and MCP syntax; corrected placeholder inconsistency in install paths.

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
