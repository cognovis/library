# Cognovis Library Changelog

This changelog tracks changes made by Cognovis on top of the upstream fork.
Upstream: https://github.com/disler/the-library (forked at commit `47f455c`)

---

## [Unreleased]

---

## [v2026.05.01.3] - 2026-04-30

### Added

- **Provisional Canonical Home for bd Workflow Primer** (`prime/PRIME.md`, `prime/README.md`): Established `cognovis-library/prime/PRIME.md` as the provisional single source of truth for the bd workflow primer (formerly scattered across `~/.claude/templates/PRIME.md`, the beads SKILL, and AGENTS.md blocks). The beads SKILL has been deleted from claude-code-plugins; AGENTS.md beads blocks trimmed to 12-line stubs pointing to `bd prime`. PRIME.md rewritten with all 9 bd built-in types, Priority/Effort taxonomy, MoC-at-create-time pattern, and memory routing exclusively to open-brain. Distribution chain: SessionStart hooks in both Claude Code and Codex harnesses now sync PRIME.md from this library to `$XDG_CACHE_HOME/cognovis-prime/PRIME.md` (content-based, not mtime) and from there to each project's `.beads/PRIME.md`. This provisional setup will be superseded by `project_tooling` schema entries when CL-3fh is implemented. Refs CL-3fh.

- **Bootstrap First-Party Content Repos** (`library.yaml`, `docs/schema/library.schema.json`): Created `sussdorff/library-core` (private, personal agentic content) and `cognovis/library-core` (private, team agentic content). Each repo is initialized with a full skeleton: `.claude/{agents,skills,commands,hooks}/`, `.agents/{skills,standards}/`, `.codex/agents/`. Each README documents audience, directory structure, contribution model, lockfile reference (CL-t21), and canonical-vs-bridge convention per name-collision policy (CL-b4o). Both repos registered in `library.yaml` under a new `catalog:` section (first-party, distinct from `marketplaces:`). `library.schema.json` extended with `catalog_entry` definition including typed `content_types`, `skeleton`, `visibility`, `audience`, and `owner` fields. JSON-schema validator and all 22 schema tests pass. Last bead in epic CL-36o. Closes CL-1rr.

- **Golden-Prompt Fleet Migration: All Agents Migrated to Composition Model** (`tests/smoke/run-smoke.sh`): Completed CL-xpg migration follow-up to CL-9b1. All 39 agents in claude-code-plugins (beads-workflow, core, dev-tools, infra, medical, meta) now declare `golden_prompt_extends: cognovis-base` and `model_standards` frontmatter. Sonnet agents get `model_standards: [claude-sonnet-4-6]`, opus agents get `model_standards: [claude-opus-4-7]`, haiku agents get `model_standards: []`. Updated `agent-forge/scripts/init-agent.py` template to emit both composition fields by default for all new agents. Added `smoke_fleet_migration` harness to run-smoke.sh (8 structural checks: agent count, all-agents golden_prompt_extends coverage, all-agents model_standards coverage, cross-harness validation for 3 plugins, agent-forge template check). Fleet-migration harness is user-state-dependent (excluded from `all` suite; run explicitly: `./run-smoke.sh fleet-migration`). Closes CL-xpg.

- **Standards-Loader Migration: Fleet-Wide requires_standards Adoption** (`tests/smoke/run-smoke.sh`): Completed CL-717 migration follow-up to CL-v56. All 85 skills across claude-code-plugins (beads-workflow, business, content, core, dev-tools, infra, medical, meta) now declare `requires_standards:` frontmatter. Copied 62 global standards from `~/.claude/standards/` to `~/.agents/standards/` (flat naming per ADR) with valid YAML frontmatter. Project-local standards from `claude-code-plugins/.claude/standards/` accessible via the loader's legacy fallback path. `inject-subagent-standards.py` hook marked DEPRECATED with Phase 3 removal planned. Added `smoke_migration` harness to run-smoke.sh (8 structural checks: directory existence, count, core standard presence, frontmatter validity, loader resolution, skill coverage, hook deprecation). Migration harness is user-state-dependent (excluded from `all` suite to avoid CI breakage). Closes CL-717.

- **cdx — Codex Launcher with Beads Workflow Integration** (`scripts/cdx`, `justfile`, `README.md`): Added `cdx` as the Codex parallel to `cld`. The wrapper mirrors the `cld` bead-mode signatures (`-b`, `-bq`, `-br`) using prompt injection via `codex exec` (Codex has no `--bead` flag equivalent). Bead context is fetched via `bd show <id>` and injected as an initial prompt. Added four Justfile targets: `install-cdx` (installs to `~/.local/bin/cdx`), `cdx`, `cdx-quick`, and `cdx-review`. Documented in README with install instructions, usage examples, and how-it-works explanation. Closes CL-tap.

- **Guardrails as Fourth Primitive — Cross-Harness Capability Matrix** (`library.yaml`, `docs/schema/library.schema.json`, `docs/schema/lockfile.schema.json`, `docs/research/guardrails-mapping.md`, `cookbook/add-guardrail.md`, `cookbook/use-guardrail.md`, `cookbook/remove-guardrail.md`, `guardrails/block-destructive-bash/`): Introduced `guardrails:` as a first-class catalog category in `library.yaml`, replacing the earlier stub. Each guardrail entry is a conceptual enforcement primitive that compiles to per-harness native format. The schema defines `purpose` (pre-tool-veto / post-tool-reaction / session-init / cleanup / audit-log), per-harness `capability` declarations, and per-harness `source` file paths. Added `default_dirs.guardrails` path map for all five harnesses. Shipped `block-destructive-bash` as the reference guardrail with implementations for Claude Code (PreToolUse bash hook reading from stdin, exits 2 to hard-block), Codex CLI (SessionStart advisory .mjs), Codex Cloud (approval_policy fragment), and OpenCode (JSON deny rules). Lockfile schema extended to accept `type: guardrail`. Three cookbooks added: `add-guardrail.md` (registration with harness compat table), `use-guardrail.md` (install with mandatory capability-mismatch warnings per harness/purpose combination), `remove-guardrail.md` (uninstall + config cleanup). `docs/research/guardrails-mapping.md` documents the full 5-harness event coverage and mismatch decision table. `docs/PRIMITIVES.md` §4 expanded to the full capability matrix. Closes CL-xcm.

- **Agent Golden Prompt Composition + MODEL-STANDARD Primitive** (`.agents/golden-prompts/cognovis-base.md`, `.agents/model-standards/`, `docs/research/golden-prompt-composition.md`): Introduced the three-layer Agent System Prompt composition model. Agents now compose their effective system prompt from: Layer 1 (Cognovis Base Golden Prompt — shared safety rules, confirmation gates, tool constraint encoding), Layer 2 (agent persona body), and Layer 3 (model-specific behavioral guidance). Composition happens at Library install time — the harness receives the fully-composed prompt with no runtime overhead. Added `cognovis-base.md` as canonical Layer 1 source; created `claude-sonnet-4-6.md` (conciseness rules) and `claude-opus-4-7.md` (thinking budget + reasoning guidance) as first two model-standards. Agent frontmatter extended with `golden_prompt_extends` and `model_standards` fields. `changelog-updater` migrated as prototype. `scripts/standards-loader.sh` extended with `--load-model-standard` including alias resolution. Closes CL-9b1.

- **MODEL-STANDARD Primitive** (`docs/PRIMITIVES.md` §10 extended): Loading spec, path resolution table, composition algorithm (install-time, source/target separation, alias-based model name resolution), per-harness realization, and tool constraint encoding guidance added. Closes CL-9b1.

- **Skills & Primitives Origin Audit** (`docs/audit/skills-origin.md`, `docs/audit/skills-origin.json`): Complete inventory and classification of all 169 artifacts across `~/code/claude-code-plugins/` (beads-workflow, business, content, core, dev-tools, infra, medical, meta), `~/.claude/standards/` (63 standards), `~/.claude/hooks/` (20 hooks), Codex agents, and installed skill copies. Each artifact classified with Origin (ORIGINAL/PERSONAL/WRAPPER), Intent, Correct Type per PRIMITIVES.md, Migration Action, and Tier (core/domain/project). Identifies 13 PERSONAL artifacts for `sussdorff/library-core`, 9 marketplace candidates, and 4 artifacts needing reclassification. Machine-readable JSON output for downstream automation. Closes CL-23z.

- **MCP Server Canonical Schema** (`docs/schema/library.schema.json`, `library.yaml`, `cookbook/add-mcp.md`): Extended `library.schema.json` with a fully typed `mcp_server_entry` definition replacing the former stub. Each entry captures `name`, `description`, `coding_strategy`, `mobile_strategy`, `capabilities` (stateless, streaming, auth), and per-harness `install` metadata (cli package + manager, mcp config_path + snippet per harness). Added canonical `open-brain` entry to `library.yaml` as reference example. New cookbook `cookbook/add-mcp.md` documents the schema, strategy decision rules, and registration steps. Per-harness translator logic is explicitly out of scope (follow-up bead). JSON-schema validator passes. Closes CL-mfz.

- **Standards Loading Mechanism** (`docs/research/standards-loading.md`, `scripts/standards-loader.sh`): Design ADR and working prototype for cross-harness standards loading. Defines loader contract: path resolution (project-local `.agents/standards/<name>.md` overrides user-global), warn-and-continue on missing standards, merge order (first-declaration-wins deduplication), frontmatter validation schema, re-read-on-invoke caching policy, and 4-phase compatibility migration timeline. Prototype implements mechanism (a) adapter generation into `AGENTS.md` (`--generate-adapter`) and mechanism (b) skill-script-side runtime loader (`--load`). Recommends mechanism (d) Hybrid (a+b) as primary approach. Portable across macOS and Linux. Closes CL-v56.

### Changed

- **Agentic Primitives Glossary** (`docs/PRIMITIVES.md`): Updated STANDARD primitive §7 trigger semantics to describe both the legacy SessionStart hook (Claude Code only) and the new cross-harness convention (`.agents/standards/<name>.md` + adapter generation into `AGENTS.md`). Added `requires_standards` frontmatter documentation. Closes CL-v56.
- **Smoke Tests** (`tests/smoke/run-smoke.sh`): Added `smoke_standards()` function (10 structural checks) validating research doc existence, all loader contract sections, prototype script existence/executability, precedence rules, warn-on-missing behavior, mechanism (a) and (b) implementation, PRIMITIVES.md update, and index.yml schema documentation. Runnable via `just test-smoke standards`. Closes CL-v56.

### Added

- **Library Lockfile** (`.library.lock` format — `docs/lockfile-format.md`, `docs/schema/lockfile.schema.json`): Introduced `.library.lock` as the per-project provenance manifest for all installed library items. Records name, type, source URL, source commit SHA, install target, ISO 8601 timestamp, SHA-256 checksum, SPDX license, and bridge symlinks per entry. JSON Schema provided for machine validation. Closes CL-t21.
- **Audit Cookbook** (`cookbook/audit.md`): New `/library audit` procedure that reads `.library.lock`, recomputes SHA-256 checksums of installed primary artifact files, and reports CLEAN / DRIFT / MISSING / BRIDGE-BROKEN / UNLOCKED status per item. Detects on-disk modifications made outside the Library without auto-fixing. Closes CL-t21.
- **Lockfile Smoke Tests** (`tests/smoke/run-smoke.sh`): Added `smoke_lockfile()` (13 structural checks) validating schema presence, format docs, cookbook references, checksum computation, write/read round-trip, drift detection, remove-entry, and bridge_symlinks field. Runnable via `just test-smoke lockfile`. Closes CL-t21.

### Changed

- **Library Use Cookbook** (`cookbook/use.md`): Added Step 8 (Update .library.lock) — after a successful install, computes SHA-256 checksum of the primary artifact, resolves `source_commit` from the cloned repo (before `rm -rf` cleanup), and writes/updates the lockfile entry. Closes CL-t21.
- **Library Remove Cookbook** (`cookbook/remove.md`): Step 5 now reads `install_target` and `bridge_symlinks` from `.library.lock` before deletion, removes bridge symlinks first (per CL-b4o policy), removes the canonical directory, then removes the lockfile entry. Closes CL-t21.
- **Library Sync Cookbook** (`cookbook/sync.md`): Rewritten to use `.library.lock` as source of truth instead of `library.yaml`. Pins each re-fetch to `entry.source_commit` (full clone + `git checkout`) for reproducible installs. Documents upgrade behavior (omit pin when explicitly upgrading). Closes CL-t21.

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
