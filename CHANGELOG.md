## [unreleased]

### 🚀 Features

- Normalize library yaml information model
- *(library)* Add installed inventory view
- *(library)* Register go-live catalog entries
- Move primitive forges into platform
- Add catalog promotion routing
- *(library)* Add targeted primitive sync

### 🐛 Bug Fixes

- *(library)* Reinstall missing lockfile targets
- *(library)* Source ob-cli from open-brain
- *(library)* Align installed lifecycle scopes
- *(library)* Install codex agent targets
- *(library)* Catalog architecture-scout, rename changelog
- Harden platform forge migration
- Move platform standards into library catalog

### 💼 Other

- Add script primitive metadata
- Register judge-layer standard
- Add Gas City projection metadata
- Harden Gas City projection validation

### 📚 Documentation

- Add judge-layer taxonomy
- Fix judge-layer contract
- Clarify repository identity
- Clarify standards v2 frontmatter
- Split primitive reference
- Clarify repomix installed-tree cleanup
- Add managed worker stack reference
- *(library)* Add library-cli invariants standard from CL-uyp learnings
- *(library)* Document targeted primitive sync
- *(primitives)* Separate orchestrator and agent system prompts

### 🧪 Testing

- *(library)* Align suite with vendored layout
- *(library)* Remove obsolete migration skips
- Harden primitive regression coverage
- Cover legacy alias validator warnings

### ⚙️ Miscellaneous Tasks

- Catalog primitive placement standard
- Add primitive placement catalog metadata
- *(CL-usc)* Record repomix vulnerability remediation
- Catalog promoted healthcare standards
- Harden library yaml alias validation
- Catalog normalized healthcare standards
## [2026.05.33] - 2026-05-14

### 🚀 Features

- *(library)* Register python-cli-patterns standard (clc-oal.1 companion)
- *(library)* Register python-dev + python-test skills (clc-oal.2, clc-oal.3)
- *(library)* Vendor installs and remove standards composition

### 📚 Documentation

- *(primitives)* Standards §7 — folder-form, domain/rule frontmatter, maturity arc, scripts/
- *(primitives)* Authoring source-of-truth + axis 1 delivery clarifications

### ⚙️ Miscellaneous Tasks

- *(meta)* Gitignore library-installed symlinks; keep installed-standards in AGENTS.md
## [2026.05.32] - 2026-05-13

### 🚀 Features

- *(CL-7oy)* Green — directory hash, checksum_type, drift-only, exit code 2 for drift
- *(CL-7oy)* Green — status.py, top-level status/sync commands, git ls-remote approach
- *(CL-7oy)* Green — top-level sync skip-on-current tests pass (AK5, AK6)
- *(CL-7oy)* Green — hook script, top-level audit, hook smoke tests (AK7)
- *(clc-0ym.2)* Replace skill-auditor with skill-forge in library catalog

### 🐛 Bug Fixes

- *(CL-7oy)* Address review findings iteration 1
- *(CL-7oy)* Address codex adversarial findings
- Route library installs to target project

### 💼 Other

- Worktree-bead-CL-7oy

### 📚 Documentation

- *(CL-7oy)* Update changelog, SKILL.md, and lockfile-format.md for lifecycle commands
- *(primitives)* Add NORMATIVE rule — model: is forbidden in SKILL.md frontmatter

### 🧪 Testing

- *(CL-7oy)* Red — directory hash, drift-only filter, exit codes, checksum_type
- *(CL-7oy)* Red — status command, git ls-remote mock, upstream SHA comparison

### ⚙️ Miscellaneous Tasks

- Rename hook-creator -> hook-forge in catalog (clc-ecj follow-up)
- *(clc-c2a)* Drop stale skill/agent EXPECTED set entries
## [2026.05.31] - 2026-05-13

### 🚀 Features

- *(clc-0ym.5)* Register standard-forge skill in library.yaml
- *(CL-0l5)* Green — add pyproject.toml with PyYAML and jsonschema dependencies

### 🐛 Bug Fixes

- *(CL-0l5)* Address review findings — remove stale not-yet-implemented language from cookbook/use.md (AK30)

### 💼 Other

- Worktree-bead-CL-0l5

### 📚 Documentation

- *(CL-0l5)* Add changelog entry for full primitive coverage and pyproject.toml addition
## [2026.05.30] - 2026-05-13

### 🚀 Features

- *(CL-3kq)* Green — implement harness materializer for always_apply and globs

### 🐛 Bug Fixes

- *(CL-3kq)* Address review findings — unused import, dead var, primitive label, dry-run warnings

### 💼 Other

- Worktree-bead-CL-49a
- Worktree-bead-CL-3kq

### 📚 Documentation

- *(CL-3kq)* Update generated docs and cookbook for harness materializer
- *(CL-3kq)* Add changelog entry for harness materializer

### 🧪 Testing

- *(CL-3kq)* Red — harness materializer tests for always_apply and globs
## [2026.05.29] - 2026-05-13

### 🚀 Features

- *(CL-49a)* Green -- M2 schema adds globs/always_apply/compatibility/metadata fields
- *(CL-49a)* Green -- M3 agentskills.io name/description validation rules

### 🐛 Bug Fixes

- *(installers)* Pass temp clone dir explicitly instead of as Path attribute
- *(CL-49a)* Address review findings — temp cleanup, trailing-hyphen test, standard entry test, missing-name guard, schema descriptions

### 💼 Other

- Worktree-bead-CL-9mx

### 📚 Documentation

- *(primitives)* Align §7 Standard with compose-on-install architecture
- *(research)* Forge-patterns industry research (May 2026)
- *(CL-49a)* Add changelog entries for M2 schema fields and M3 validator rules
- *(primitives)* Refresh §4 hook event list to 15 events (CL-9mx)
- *(primitives)* Update guardrails-mapping and ARCHITECTURE for 15 events (CL-9mx)

### 🧪 Testing

- *(CL-49a)* Red -- M2/M3 validate-library acceptance tests
## [2026.05.28] - 2026-05-13

### 🚀 Features

- *(CL-8ph)* Merge — complete library.py all primitive×verb combinations, dependency resolver, --harness flag
- *(CL-c2d)* Green — agents-md-block.py insert/update/remove/check with sha256-12 hash
- *(CL-c2d)* Green — drift-check hook, library.yaml schema update (tier/default_scope, no triggers), cookbook step 5f/remove/sync updates
- *(CL-c2d)* Green — remove.py calls agents-md-block remove for standard removals (AK4)
- *(CL-c8g)* Retire standards-loader and inject-subagent-standards hooks

### 🐛 Bug Fixes

- *(CL-08k)* Cld --agent uses bare user-agent names, not plugin namespace

### 💼 Other

- Worktree-bead-CL-c8g

### 📚 Documentation

- *(CL-c2d)* Add changelog entry for compose-on-install + drift-detect hook
- *(CL-c8g)* Add changelog entry for retired standards-loader and inject-subagent-standards hooks

### 🧪 Testing

- *(CL-c2d)* Red — agents-md-block insert/update/remove/check
- *(CL-c2d)* Red — standards-drift-check hook scan_file + format_warning

### ⚙️ Miscellaneous Tasks

- *(CL-c2d)* Bump version to 2026.05.27
## [2026.05.13.1] - 2026-05-13

### 🚀 Features

- *(CL-8ph)* Green — implement all primitive×verb combinations, dependency resolver, --harness flag, sync/audit, skill/standard remove
- Register agentic-primitives standard in library catalog

### 📚 Documentation

- *(CL-8ph)* Add changelog entry for complete library.py implementation

### 🧪 Testing

- *(CL-8ph)* Red — comprehensive tests for all 34 AKs (agent/prompt/model-standard/golden-prompt/mcp/guardrail use+remove, skill remove, sync, audit, dep resolver, harness flag)
- *(CL-8ph)* Add explicit tests for AK14 (guardrail remove) and AK16 (standard remove)

### ⚙️ Miscellaneous Tasks

- Merge main into worktree-bead-CL-8ph before session-close
## [2026.05.26] - 2026-05-13

### 🚀 Features

- *(CL-0bl)* Green — implement scripts/library.py deterministic engine
- *(CL-0bl)* Merge — implement scripts/library.py deterministic library engine

### 🐛 Bug Fixes

- *(CL-4ny)* Resolve Codex startup warnings
- *(CL-0bl)* Address review findings — fix temp dir cleanup for GitHub sources

### 📚 Documentation

- *(primitives)* Add portability matrix + restructure AGENTS.md as navigation hub
- *(library)* Document primitive-scoped command grammar
- *(CL-0bl)* Update changelog with library.py engine entry

### 🧪 Testing

- *(CL-0bl)* Red — core library.py and lib/ package structure tests

### ⚙️ Miscellaneous Tasks

- *(library.yaml)* Sync cognovis-core agent fleet consolidation
- Bump version to 2026.05.26 for CL-0bl release
## [2026.05.25] - 2026-05-12

### 🚀 Features

- *(CL-o16)* Compose-on-resync for /library sync + e2e use-cookbook smoke test
- Register session-close skill in library catalog + fix .codex/ drift
- *(CL-o16)* Compose-on-resync for /library sync + e2e use-cookbook smoke test

### 🐛 Bug Fixes

- *(CL-o16)* Restore library-core section comment displaced by smoke_use_cookbook_path insertion
- *(CL-o16)* Correct awk frontmatter extraction in sync.md Step 4.5 (Codex finding)

### 💼 Other

- Integrate main (session-close skill + codex drift fix) into worktree-bead-CL-o16

### 📚 Documentation

- *(CL-o16)* Update changelog with compose-on-resync + use-cookbook smoke test

### ⚙️ Miscellaneous Tasks

- Bump version to 2026.05.25 for CL-o16 release
## [2026.05.24] - 2026-05-12

### 🚀 Features

- *(CL-08n)* Compose-on-install for agent golden-prompt + source relocation + haiku model-standard

### 💼 Other

- Resolve conflicts from main — integrate CL-l0c install-mcp.py + CL-08n compose-on-install

### ⚙️ Miscellaneous Tasks

- Bump version to 2026.05.24 for CL-08n release
## [2026.05.23] - 2026-05-12

### 🚀 Features

- *(CL-l0c)* Cross-harness install -- sources: map + Codex hook adapter + slash-command spike docs
- *(CL-l0c)* Deliverable D -- install-mcp.py per-harness MCP installer
- *(CL-08n)* Green — Part A: relocate golden-prompts and model-standards to cognovis-core
- *(CL-08n)* Green — Parts B-E: schema extension, library.yaml catalog entries, compose-agent.py, cookbook Step 6.5, smoke test

### 🚜 Refactor

- *(CL-8qr)* Point sources.codex URLs at agents/ (not .codex/agents/)

### 📚 Documentation

- *(CL-08n)* Add changelog entry for compose-on-install, source relocation, haiku model-standard

### 🧪 Testing

- *(CL-08n)* Red — schema tests for model_standards/golden_prompts + compose-agent tests

### ⚙️ Miscellaneous Tasks

- Release v2026.05.23 -- CL-83q + CL-l0c (D) + CL-8qr
## [2026.05.22] - 2026-05-12

### 🚀 Features

- *(CL-4bv)* Library-managed standards-loader hook + inject-subagent-standards (single-hook kind)
- *(CL-l0c)* Green -- agent_entry sources map + install-hook codex branch + cookbook docs

### 🐛 Bug Fixes

- *(CL-4bv)* /library use ASK whether standard goes global or project-local (cookbook §5f)
- *(CL-4bv)* Per-file trigger selection in standards-loader (62% payload reduction)

### 💼 Other

- Resolve conflicts from main -- integrate single-hook kind + codex harness functions

### 🚜 Refactor

- *(CL-83q)* Invert canonical/bridge polarity for skills

### 📚 Documentation

- *(CL-l0c)* Add changelog entry for cross-harness install + sources map + codex hook adapter

### 🧪 Testing

- *(CL-l0c)* Red -- agent_entry sources map + install-hook codex branch tests
## [2026.05.21] - 2026-05-12

### 🚀 Features

- *(CL-bgo)* ADR-0004 library architecture cleanup
- Register open-brain marketplace + 9 skills + 5 samurai skills per ADR-0004
- *(CL-bgo)* Hook-install via /library use per ADR-0004 Phase 2
- *(CL-bgo)* Drop redundant harness: from skills, derive coverage from source URL
- *(CL-79m)* Register 14 standard bundles in library.yaml + add triggers field
- *(CL-bgo)* Mirror mcp:open-brain in 5 agent registry entries
- *(CL-bgo)* Add standards-loader hook source + fix standard source URLs

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.05.21 and update changelog
## [2026.05.20] - 2026-05-12

### 🐛 Bug Fixes

- *(CL-ns6)* Correct session-close canonical path to ~/.claude/agents/core/session-close.md

### 📚 Documentation

- *(CL-ns6)* Cognovis-marketplace retirement audit — content-equivalence verified, all 5 artefacts superseded in cognovis-core
- *(CL-ns6)* Update changelog — cognovis-marketplace retirement Phase 2b

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.05.20 and update changelog
## [2026.05.19] - 2026-05-12

### 🚀 Features

- *(CL-ast)* Content-equivalence audit for sussdorff-plugins retirement

### 💼 Other

- Origin/main into worktree-bead-CL-ast (resolve changelog conflict)
- Worktree-bead-CL-ast
- Worktree-bead-CL-9au

### ⚙️ Miscellaneous Tasks

- *(CL-ast)* Update changelog for sussdorff-plugins retirement (Phase 2a)
## [2026.05.18] - 2026-05-12

### 🚀 Features

- *(CL-9au)* Populate mcp_servers registry with keep-mcp and ship-both entries

### 🐛 Bug Fixes

- *(CL-9au)* Clean up description meta-commentary in mcp_servers entries
- *(CL-9au)* Document claude_desktop install gap in pencil and filesystem entries

### 💼 Other

- Worktree-bead-CL-l4f

### 📚 Documentation

- *(CL-9au)* Update changelog with mcp_servers registry population

### ⚙️ Miscellaneous Tasks

- *(CL-ast)* Update changelog for sussdorff-plugins retirement (Phase 2a)
- Bump version to 2026.05.18
## [2026.05.17] - 2026-05-12

### 💼 Other

- Worktree-bead-CL-w4g

### ⚙️ Miscellaneous Tasks

- *(CL-w4g)* Update changelog for bin/ canonicalization (ADR-0002 Phase 1)
## [2026.05.16] - 2026-05-12

### 🚀 Features

- *(CL-w4g)* Canonicalize cld/cdx in bin/, add install-bin.sh, update docs

### 🐛 Bug Fixes

- *(CL-w4g)* Address review findings iteration 1
- *(CL-xlz)* Document CalVer 4-part tag crash fix in version.sh

### 💼 Other

- Worktree-bead-CL-xlz
## [2026.05.15] - 2026-05-12

### 🚀 Features

- *(CL-yx2)* Extend lockfile schema with marketplace + cache_path fields

### 💼 Other

- Worktree-bead-CL-603
- Worktree-bead-CL-yx2

### ⚙️ Miscellaneous Tasks

- Bump version to 2026.05.15
## [2026.05.14] - 2026-05-12

### 🚀 Features

- *(CL-yx2)* Extend lockfile schema with marketplace + cache_path fields (AK1)
- *(CL-yx2)* Update lockfile-format.md with new fields, three-layer examples, global lockfile (AK2)
- *(CL-yx2)* Update cookbooks with three-layer model steps (AK3)
- *(CL-yx2)* Add scripts/migrate-lockfile.py — ADR-0003 lockfile migration (AK4)
- *(CL-r92)* Extend marketplace_entry schema with type + auth fields

### 🐛 Bug Fixes

- *(CL-yx2)* Address review findings iteration 1
- *(CL-603)* Update removal example to use ~/.codex/skills/ as global Codex path

### 💼 Other

- *(CL-603)* Codex skill-loading smoke test — ~/.codex/skills confirmed as real load path
- Worktree-bead-CL-r92

### 📚 Documentation

- *(CL-lti)* Mark ADR-0003 as accepted

### 🧪 Testing

- *(CL-yx2)* Red — lockfile schema requires marketplace + cache_path

### ⚙️ Miscellaneous Tasks

- Bump version to 2026.05.14
## [2026.05.13] - 2026-05-12

### 📚 Documentation

- *(CL-7na)* ADR-0002 — full marketplace retirement, library-core canonicalization, deployment-only harness dirs
- *(CL-lti)* ADR-0003 — three-layer skill deployment architecture (proposed)

### ⚙️ Miscellaneous Tasks

- Bump version to 2026.05.13
## [2026.05.12] - 2026-05-02

### 📚 Documentation

- *(CL-0va)* ADR-0001 — retire sussdorff-plugins partially, adopt hybrid model
## [2026.05.11] - 2026-05-02

### 🚀 Features

- *(CL-yko)* Green — register 55 skills, 38 agents, 12 prompts in library.yaml + check-coverage.py

### 🐛 Bug Fixes

- *(CL-yko)* Address codex adversarial findings — check-coverage.py now verifies standards as prompts

### 📚 Documentation

- *(CL-yko)* Update changelog — library catalog registration with 107 entries

### 🧪 Testing

- *(CL-yko)* Red — coverage tests for library.yaml migration registration

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.05.11 and update changelog
## [2026.05.10] - 2026-05-02

### 🚀 Features

- *(CL-8vb)* Green — migration script + tests pass for ~40 missing artefacts

### 🐛 Bug Fixes

- *(CL-8vb)* Address review findings — wave-reviewer, pyc cleanup, standards, audit-diff test
- *(CL-8vb)* Update stale skill+agent count assertions (41→44 skills, 27→37 agents after CL-8vb additions)

### 💼 Other

- Worktree-bead-CL-8vb

### 📚 Documentation

- *(CL-8vb)* Update changelog — complete library-core migration with ~40 missing artefacts
## [2026.05.01.9] - 2026-05-01

### 💼 Other

- Worktree-bead-CL-sxt

### ⚙️ Miscellaneous Tasks

- Merge main into worktree-bead-CL-sxt (resolve changelog conflict)
## [2026.05.9] - 2026-05-01

### 💼 Other

- Resolve CHANGELOG conflict — keep detailed CL-4mt entry from feature branch

### ⚙️ Miscellaneous Tasks

- Stage CL-4mt+CL-2x4 changelog entries before CL-4mt merge
## [2026.05.01.8] - 2026-05-01

### 🚀 Features

- *(CL-sxt)* Green — add migrate_originals.py script
- *(CL-2x4)* Extend /library list with 3-section layout (catalog + plugins + lockfile)
- *(CL-2x4)* Extend /library list with 3-section layout (catalog + plugins + lockfile)

### 🐛 Bug Fixes

- *(CL-sxt)* Address review findings iteration 1
- *(CL-sxt)* Address codex adversarial findings
- *(CL-sxt)* Address auto-fixable verification disputes
- *(CL-4mt)* Update test to expect SKILL.md (uppercase) for transcribe skill
- *(CL-4mt)* Address codex adversarial findings
- *(CL-2x4)* Address review findings iteration 1
- *(CL-2x4)* Address codex adversarial findings

### 💼 Other

- Worktree-bead-CL-2x4

### 📚 Documentation

- *(CL-sxt)* Update changelog — populate cognovis/library-core with 77 ORIGINAL artefacts
- *(CL-4mt)* Add changelog entry for personal artefacts migration

### 🧪 Testing

- *(CL-sxt)* Red — migration tests failing before populate
- *(CL-sxt)* Green — add library-core smoke test section
- *(CL-4mt)* Red — verify 13 personal artefacts in sussdorff/library-core
- *(CL-2x4)* Red — verify 3-section list layout in cookbook

### ⚙️ Miscellaneous Tasks

- *(prime)* Switch bd body-file convention from stdin heredoc to file path
## [2026.05.01.7] - 2026-05-01

### 🐛 Bug Fixes

- *(CL-qwt)* Drop force flag from cookbook cleanup commands

### 📚 Documentation

- *(CL-qwt)* Update changelog — drop force flag from cookbook cleanup commands
## [2026.05.01.6] - 2026-05-01

### 🚀 Features

- *(CL-16n)* Register pbakaus marketplace + impeccable skill

### 🐛 Bug Fixes

- *(CL-wn8)* Remove duplicate changelog entry from merge artifact
- *(CL-6cl)* Simplify dolt-auth-fix.md to minimal project note
- *(CL-6cl)* Clarify dolt-auth-fix.md — reference the LaunchAgent implementation

### 💼 Other

- Worktree-bead-CL-6cl

### 📚 Documentation

- *(CL-6cl)* Record dolt persistent auth infrastructure change
- *(CL-6cl)* Update changelog — dolt persistent auth via LaunchAgent

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.05.01.6 and update changelog
## [2026.05.01.5] - 2026-05-01

### 💼 Other

- Worktree-bead-CL-wn8

### 📚 Documentation

- *(CL-3fh)* Update changelog for project_tooling session close

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.05.01.5
## [2026.05.01.4] - 2026-05-01

### 💼 Other

- Worktree-bead-CL-3fh

### ⚙️ Miscellaneous Tasks

- Gitignore .session-close.lock
- Bump version to v2026.05.01.4
## [2026.05.01.3] - 2026-05-01

### ⚙️ Miscellaneous Tasks

- Add gitignore entries for runtime artifacts and promote changelog section
- *(CL-36o)* Session close — release epic multi-harness library v2026.05.01.3
- Bump version to v2026.05.01.3
## [2026.05.01.2] - 2026-05-01

### 🚀 Features

- *(prime)* Provisional canonical home for bd workflow primer (refs CL-3fh)
- *(CL-3fh)* Green — add project_tooling schema to library.schema.json
- *(CL-3fh)* Green — add project_tooling entries to library.yaml
- *(CL-3fh)* Green — add sync_project_tooling.py runtime
- *(CL-3fh)* Green — add project-tooling.md documentation

### 🐛 Bug Fixes

- *(CL-wn8)* Address review findings in chezmoi-externals doc
- *(CL-wn8)* Address codex adversarial findings
- *(CL-3fh)* Address review findings iteration 1
- *(CL-3fh)* Address codex adversarial findings

### 📚 Documentation

- *(prime)* Update README to reflect XDG cache location (refs CL-3fh)
- *(CL-wn8)* Add chezmoi-externals categorization guide
- *(CL-wn8)* Update changelog
- *(prime)* Update changelog and bump version to v2026.05.01.2

### 🧪 Testing

- *(CL-3fh)* Red — project_tooling schema validator tests
## [2026.05.01.1] - 2026-05-01

### 🚀 Features

- *(CL-1rr)* Register sussdorff/library-core and cognovis/library-core in catalog

### 📚 Documentation

- *(CL-1rr)* Update changelog

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.05.01.1
## [2026.04.30.8] - 2026-04-30

### 🐛 Bug Fixes

- *(CL-xpg)* Address codex adversarial findings in fleet-migration smoke

### 📚 Documentation

- *(CL-xpg)* Update changelog for Golden-Prompt fleet migration

### 🧪 Testing

- *(CL-xpg)* Red — fleet-migration smoke checks for golden_prompt_extends + model_standards + agent-forge template

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.04.30.8
## [2026.04.30.7] - 2026-04-30

### 🐛 Bug Fixes

- *(CL-717)* Address codex adversarial findings in smoke_migration

### 📚 Documentation

- *(CL-717)* Update changelog for standards-loader migration

### 🧪 Testing

- *(CL-717)* Add smoke_migration test for standards-loader migration

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.04.30.6
- Bump version to v2026.04.30.7
## [2026.04.30.6] - 2026-04-30

### 🚀 Features

- *(CL-tap)* Add cdx wrapper script with beads workflow integration

### 🐛 Bug Fixes

- *(CL-tap)* Add explicit BD_BIN check inside each bead mode block
- *(CL-tap)* Address codex adversarial findings

### 📚 Documentation

- *(CL-tap)* Update changelog
## [2026.04.30.5] - 2026-04-30

### 🚀 Features

- *(CL-xcm)* Green — guardrails: schema + library.yaml entry (AK1)
- *(CL-xcm)* Green — block-destructive-bash guardrail source files (AK4)
- *(CL-xcm)* Green — cookbook entries add/use/remove-guardrail (AK2 + AK5)
- *(CL-xcm)* Green — guardrails-mapping.md + PRIMITIVES.md 5-harness matrix (AK3)

### 🐛 Bug Fixes

- *(CL-xcm)* Address codex adversarial findings

### 📚 Documentation

- *(CL-xcm)* Update changelog

### 🧪 Testing

- *(CL-xcm)* Red — guardrails schema tests (11 tests, 7 failing vs stub)
## [2026.04.30.4] - 2026-04-30

### 🚀 Features

- *(CL-9b1)* Green — golden-prompt composition + model-standards primitive
- *(CL-9b1)* Green — golden-prompt-composition.md design doc + prototype validation

### 🐛 Bug Fixes

- *(CL-9b1)* Address codex adversarial findings

### 📚 Documentation

- *(CL-9b1)* Update changelog

### 🧪 Testing

- *(CL-9b1)* Red — smoke_golden_prompts checks for golden-prompt composition artifacts
## [2026.04.30.3] - 2026-04-30

### 🚀 Features

- *(CL-23z)* Inventory and classify all primitives in claude-code-plugins

### 🐛 Bug Fixes

- *(CL-23z)* Add missing people-query skill to audit inventory
- *(CL-23z)* Address codex adversarial findings
- *(CL-23z)* Correct JSON summary artifact counts to match array

### 📚 Documentation

- *(CL-23z)* Update changelog
## [2026.04.30.2] - 2026-04-30

### 🚀 Features

- *(CL-mfz)* Green — mcp_servers canonical schema, library.yaml entry, cookbook doc

### 📚 Documentation

- *(CL-mfz)* Update changelog with mcp_servers canonical schema entries

### 🧪 Testing

- *(CL-mfz)* Red — mcp_servers schema validation tests
## [2026.04.30.1] - 2026-04-30

### 🚀 Features

- *(CL-v56)* Green — standards-loading ADR, cross-harness loader prototype, updated PRIMITIVES

### 🐛 Bug Fixes

- *(CL-v56)* Address codex adversarial findings — PROJ_ROOT from PWD, dedup, frontmatter validation, macOS realpath
- *(CL-v56)* Address codex re-check — portable dedup without declare -A, safe tmpfile EXIT trap

### 📚 Documentation

- *(CL-v56)* Update changelog with standards-loading mechanism entries

### 🧪 Testing

- *(CL-v56)* Red — add smoke_standards() checks for standards-loading mechanism
## [2026.04.12] - 2026-04-30

### 🚀 Features

- *(CL-t21)* Green — implement .library.lock format, schema, and cookbook integration

### 🐛 Bug Fixes

- *(CL-t21)* Address codex adversarial findings — source_commit timing + sync pinning

### 📚 Documentation

- *(CL-t21)* Update changelog with lockfile entries

### 🧪 Testing

- *(CL-t21)* Red — add smoke_lockfile() checks for .library.lock infrastructure

### ⚙️ Miscellaneous Tasks

- Gitignore transient orchestrator IPC files
## [2026.04.30] - 2026-04-30

### 🚀 Features

- *(CL-b4o)* Green — name collision policy, cookbook update, and smoke tests

### 🐛 Bug Fixes

- *(CL-b4o)* Fix step reference in use.md detection rule (5e -> 5d)
- *(CL-b4o)* Address codex adversarial findings

### 📚 Documentation

- *(CL-b4o)* Update changelog with name collision policy entries

### 🧪 Testing

- *(CL-b4o)* Red — docs/policy/name-collision.md scaffolded (policy doc created, smoke test not yet updated)

### ⚙️ Miscellaneous Tasks

- Commit CLAUDE.md schema ownership convention (from prev session)
- Bump version to v2026.04.30
## [2026.04.11] - 2026-04-30

### 🚀 Features

- *(CL-zda)* Add cross-harness smoke-test fixtures for skill discovery + install

### 🐛 Bug Fixes

- *(CL-zda)* Address review findings iteration 1
- *(CL-zda)* Address codex adversarial findings

### 💼 Other

- Worktree-bead-CL-zda

### 📚 Documentation

- *(CL-zda)* Update changelog

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.04.11
## [2026.04.10] - 2026-04-30

### 💼 Other

- Worktree-bead-CL-7ii

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.04.10
## [2026.04.9] - 2026-04-30

### 🚀 Features

- *(CL-7ii)* Add marketplaces category to library.yaml schema and cookbooks

### 🐛 Bug Fixes

- *(CL-7ii)* Address review findings iteration 1
- *(CL-7ii)* Address codex adversarial findings

### 💼 Other

- Worktree-bead-CL-06x

### 📚 Documentation

- *(CL-7ii)* Update changelog

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.04.9
## [2026.04.8] - 2026-04-30

### 🚀 Features

- *(CL-wud)* Add JSON Schema for library.yaml and validator script

### 🐛 Bug Fixes

- *(CL-wud)* Require default_dirs+library at root and source in catalog entries

### 💼 Other

- Worktree-bead-CL-wud

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.04.8
## [2026.04.7] - 2026-04-30

### 💼 Other

- Worktree-bead-CL-nvp

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.04.7
## [2026.04.6] - 2026-04-30

### 🐛 Bug Fixes

- *(CL-11p)* Address review findings — consistency, algorithm clarity, model mapping
- *(CL-11p)* Address codex adversarial findings

### 💼 Other

- Resolve CHANGELOG conflict with origin/main

### 📚 Documentation

- Update CHANGELOG with CL-11p and ARCHITECTURE.md entries
- *(CL-11p)* Add agents format mapping spec for Claude Code .md ↔ Codex .toml
- *(CL-11p)* Add changelog entry for agents format mapping spec

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.04.6
## [2026.04.5] - 2026-04-30

### 🐛 Bug Fixes

- *(CL-p91)* Correct open-brain CLI assessment — hooks ≠ on-demand CLI

### 💼 Other

- Worktree-bead-CL-p91

### 📚 Documentation

- *(CL-p91)* Add changelog entry for MCP server audit
- *(CL-p91)* Add MCP server audit — classification and migration plan

### ⚙️ Miscellaneous Tasks

- Bump version to v2026.04.5
## [2026.04.4] - 2026-04-30

### 🚀 Features

- *(CL-6hg)* Add Codex paths to default_dirs in library.yaml

### 🐛 Bug Fixes

- *(CL-nvp)* Use <name> placeholder consistently in install paths
- *(CL-nvp)* Address codex adversarial findings — correct portability matrix facts

### 💼 Other

- Worktree-bead-CL-6hg

### 📚 Documentation

- *(CL-nvp)* Add decision rule and harness portability matrix to ARCHITECTURE.md
- *(CL-nvp)* Add changelog entry for ARCHITECTURE.md expansion
## [2026.04.3] - 2026-04-30

### 🐛 Bug Fixes

- *(CL-cmz)* Address review findings — numbering, placeholders, structure, provenance
- *(CL-cmz)* Address codex adversarial findings

### 💼 Other

- Worktree-bead-CL-cmz

### 📚 Documentation

- *(CL-cmz)* Add PRIMITIVES.md v0 — agentic primitives glossary
- *(CL-cmz)* Add changelog entry for PRIMITIVES.md v0

### ⚙️ Miscellaneous Tasks

- Gitignore .context/ directory (Codex session tracking files)
- Bump version to v2026.04.3
## [2026.04.2] - 2026-04-16

### 📚 Documentation

- Add CL-qzw research on Codex layer 3 (prompts/skills) parity

### ⚙️ Miscellaneous Tasks

- Gitignore .claude/anatomy.json (tool-internal cache)
- Update changelog and add VERSION for v2026.04.2
## [2026.04.1] - 2026-04-16

### 📚 Documentation

- Add ARCHITECTURE.md capturing fork rationale and design decisions

### ⚙️ Miscellaneous Tasks

- Bootstrap cognovis fork with beads, agent files, and changelog
