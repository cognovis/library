## [unreleased]

### Fixed

- *(CL-r3rt)* `cdx -bq` default quick-fix launches now default the Codex
  working directory to the current project instead of failing under nounset
  with `run_codex_exec:2: 2: parameter not set`.

- *(CL-6zkk)* `cdx -b` now tells the top-level Codex orchestrator to keep
  repository edits inside configured workflow leaf slots and fail closed when a
  required adapter is unavailable, instead of making inline implementation or
  verification fixes.

- *(CL-cchg)* `cdx -b` now pre-resolves and exports `BEADS_RUNTIME_DIR`
  before launching Codex, tells the orchestrator to avoid helper discovery
  searches before Phase 0/1, and restores a timestamped `WORKFLOW_EVENT`
  output contract for deterministic phase/helper calls.

- *(CL-5zag)* `cdx -b` now avoids spawning a nested top-level bead
  orchestrator, supports explicit `--tui`/`--exec` modes with auto TUI
  selection for terminals, and starts full-bead Codex sessions in a
  bead-specific git worktree via `-C`.

- *(CL-ue5f)* `cdx -b` now starts Codex as the top-level
  bead-orchestrator by default, keeping deterministic workflow helpers inside
  the orchestrator path. The direct Python full-workflow runner remains
  available behind `CDX_BEAD_WORKFLOW=python` for smoke tests and CI.

- *(CL-emu5)* Deterministic `cdx -b` Phase 3 architecture review now resolves
  a Claude-compatible model from `full.adversarial_review`/`full.verification`
  slots before falling back, so `cdx` route metadata with
  `reviewer_model=codex` no longer dispatches `claude --model codex`.

- *(CL-snca)* Deterministic `cdx -b` now executes Phase 2/3 prep before
  implementation: Phase 2 performs a Python pre-mortem/module-impact pass and
  appends a concise bead note; Phase 3 skips cleanly when no architecture
  signals exist and otherwise runs a bounded `review-agent` architecture review
  with metrics before dispatching the implementation leaf.

- *(CL-oacf)* Deterministic `cdx -b` now runs Phase 1 context gathering before
  implementation, injects the context-provider bundle and standards preamble
  into leaf prompts, emits timestamped `WORKFLOW_EVENT` lines with durations,
  records runner metrics for direct `claude-agent` slots, and marks missing
  Phase 2/3 Python implementations with `WORKFLOW_DEGRADED` instead of
  silently jumping from Phase 0 to Phase 5.

- *(CL-l5f3)* `cdx -b` and `cdx -bq --route-profile cdx-composer` now invoke
  the installed beads `phase0-claim.py` helper with `uv run --with pyyaml`, so
  Phase 0 no longer depends on the target repository declaring PyYAML.

- *(CL-uhac)* `cdx -b` and non-inline `cdx -bq` compact modes now run
  `codex exec --json` through a JSONL filter, suppressing hook/tool-event
  command noise while preserving phase, leaf-dispatch, and Cursor lifecycle
  markers.

- *(CL-vaiw)* `cdx -b` and `cdx -bq` now default to a compact output
  contract that discourages full diffs, full file bodies, and broad command
  dumps while preserving route-profile propagation and leaf-dispatch markers;
  bead context is compacted from `bd show --json` before entering the prompt.

- *(CL-h3a8)* `library agent use --harness all` now includes OpenCode
  agent sources in `.opencode/agents/`, so a subsequent
  `library agent remove --harness all` removes Claude, Codex, and OpenCode
  agent files in one pass.

- *(CL-kpt1)* `cdx -bq --route-profile <name>` now exports `CLD_ROUTE_PROFILE`
  and carries the selected route profile into the quick-fix prompt, matching
  full `cdx -b` behavior.

### 🛡️ Security / Safety

- *(CL-182u)* Workflow runtime production-readiness hardening
  - `MutatingExecutionBlockedError` is raised unless the caller passes `readOnly=True`; top-level `readOnly` from CLI `--read-only` flag or `args["readOnly"]=True` propagates to every leaf via `opts.setdefault("readOnly", True)`, closing the per-leaf bypass gap
  - Inert-spine checks now scan template literal interpolation blocks (`${…}`) for banned operations — not just top-level source — so `fs.${method}` style obfuscation is caught
  - `agent()` extraction is fully comment-and-string-safe: `_strip_comments` (char-by-char) removes `//` and `/* */` only outside string literals; `_find_marker_outside_strings` skips `await agent(` occurrences inside string literals before extraction
  - `ADAPTER_PRESERVATION_STATUS` update criteria anchored in ADR-0006 Consequences (criteria 1–6, including fail-closed default for unknown adapters)

- *(CL-uqug)* Fail-closed guardrail for mutating workflow execution in `WorkflowRuntime`
  - `MutatingExecutionBlockedError` is raised for any adapter whose hook-preservation status is not `verified`
  - `ADAPTER_PRESERVATION_STATUS` map records current statuses: `claude-agent` → `blocked` (leaf smoke returned unauthenticated), `codex-impl`/`codex-exec` → `separate-harness`, `cursor-composer` → `not-applicable`
  - Read-only leaves (`readOnly: true`) bypass the guardrail and remain allowed for all adapters
  - Capability matrix and Claude leaf smoke reproduction steps committed to `docs/audit/hook-permission-preservation.md`
  - Follow-up bead CL-pabj filed for Codex-specific hook preservation smoke evidence

- *(CL-pabj)* Codex adapter hook-preservation status corrected to `blocked`
  - `codex-impl` and `codex-exec` reclassified from `separate-harness` to `blocked`: Codex `--ignore-user-config` flag suppresses `config.toml` hook trust hashes, so hook preservation cannot be verified
  - Audit document (`docs/audit/hook-permission-preservation.md`) updated with Codex leaf smoke evidence and corrected capability matrix
  - Test added asserting `blocked` status for both Codex adapters; previously-passing `separate-harness` assertion now fails fast on regression

### 🚀 Features

- *(CL-8s73)* The deterministic `cdx -b` workflow now continues after
  implementation through `full.adversarial_review`, `full.verification`, and
  `full.session_close`. Each slot is resolved from the Phase 0
  `execution_plan`, emits a `LEAF_DISPATCH` marker, invokes the selected
  adapter directly (`claude-agent`, `codex-exec`, `cursor-composer`, or
  `codex-impl`), and stops before later slots on failure.

- *(CL-96nv)* `cdx -b` now enters a deterministic bead-orchestrator workflow
  runner instead of the large Codex bead-orchestrator prompt. The runner uses
  `phase0-claim.py`, resolves the `full.implementation` slot from the
  `execution_plan`, defaults to the `cdx-composer` route profile, and dispatches
  the selected script adapter directly with `LEAF_DISPATCH` and Cursor lifecycle
  markers. `cld -b` remains on the existing Claude agent path.

- *(CL-182u)* CLI entrypoint for read-only workflow execution (`scripts/lib/workflow_runtime.py`)
  - `uv run python scripts/lib/workflow_runtime.py <spec.js> [--read-only] [--route-profile NAME] [--args JSON] [--journal PATH]`
  - `--read-only` sets `readOnly=True` for all leaves; combined with `--journal` provides safe dry-run with full resume support
  - `--route-profile NAME` merges the named profile into `args["route_profile"]` for slot dispatch without model-prefix inference
  - Route-profile slot dispatch resolves `args.route_profiles[route_profile].slots[workflow][slot]` to an adapter target; no model-name prefix heuristics involved
  - Journal identity (`spec_hash`, `route_profile`, `workflow`, schema `version`) tracked per run; mismatched journal is cleared automatically on spec or profile change

- *(CL-mr2q)* OpenCode harness support for agent install and remove
  - `library.yaml` declares `default_opencode: .opencode/agents/` and `global_opencode: ~/.opencode/agents/` under `default_dirs.agents`
  - `library agent use --harness opencode` installs agents to `.opencode/agents/` (project) or `~/.opencode/agents/` (global), using `.md` format (mirroring Claude Code)
  - `library agent remove --harness opencode` removes from the correct opencode directory without leaving dangling Claude-path artifacts
  - `--harness all` on `agent remove` now covers `claude_code`, `codex`, and `opencode` in one pass
  - `--harness` flag added to `library agent remove` CLI (choices: `claude_code`, `codex`, `cursor`, `opencode`, `all`; default: `claude_code`)
  - Cursor agent remove is blocked with a clear error (consistent with install behavior)
  - `default_dirs` resolution follows the same `_resolve_opencode_agent_base` pattern as the existing Codex resolver
  - Existing `claude_code`, `codex`, and `cursor` agent behavior is unchanged

- *(CL-iye.4)* Slot-based adapter dispatch in bead-orchestrator and quick-fix
  - `bead-orchestrator` reads `execution_plan` slots for all six phases: `full.implementation`, `full.regression_fix`, `full.verification_fix`, `adversarial_review`, `verification`, and `session_close`
  - `quick-fix` reads `execution_plan` slots for `quick.implementation`, `quick.fix_loop`, `review`, and `session_close`
  - Dispatch is determined by `slot.adapter`, replacing the previous model-name prefix matching heuristic
  - Backward-compatible: falls back to `route_decision.impl_model` when `execution_plan` is absent
  - `cdx-composer` route profile wires Phase 5 and repair/fix slots to `cursor-composer` (cursor-impl.py adapter)
  - `cld-default` and `cdx-default` profiles preserve existing behavior unchanged
  - `resolve_slot_dispatch.py` adapter utility extracted to `skills/beads/scripts/` for reuse across orchestrators
  - Phase Progress marker format remains compatible with wave-monitor
  - `standards/orchestrator/orchestrator-config.md` documents the `route_profiles` schema including slot keys, adapter field, and fallback behavior
  - 65 integration and unit tests cover slot resolution, fallback, and profile fixture correctness

- *(CL-rk2)* Workflow as a first-class catalog and installer primitive
  - `library.yaml` supports a `library.workflows` catalog shape with `format: claude-workflow-js`
  - `scripts/lib/primitives.py` registers `workflow` as a recognized primitive type (yaml section `library.workflows`)
  - `scripts/lib/catalog_inventory.py` counts workflow entries and scans `.claude/workflows/**/*.js` for audit
  - `scripts/library.py` dispatches `add`, `use`, `remove`, `list`, `sync`, and `search` for workflows via the existing simple-file installer
  - Install targets: `.claude/workflows/<name>.js` (project-local) and `~/.claude/workflows/<name>.js` (global); Codex and Cursor use the same storage path but have no native workflow executor
  - `scripts/lib/installers/simple_file.py` extended to emit `.js` filenames for workflow installs and removals
  - `scripts/lib/sync_audit.py` handles workflow reinstall during sync and detects missing `.js` install targets as drift (Codex adversarial finding addressed)
  - Lockfile schema adds `workflow` to the `type` enum
  - Library schema adds `workflow_entry` definition and `library.workflows` array under the `library` section
  - Dry-run contract (`docs/schema/dry-run-contract.md`) extended to cover workflow entries
  - `SKILL.md` updated: workflow listed as a valid primitive name, default directories documented, harness routing notes added
  - `docs/primitives/workflow.md` catalog format section drops "proposed" status — installer support is live

### 📚 Documentation

- *(CL-182u)* `docs/primitives/workflow.md` — runtime section added
  - CLI usage examples (read-only, route-profile, journal resume)
  - Supported workflow subset: `meta` literal, `await agent()` leaves with JSON-literal args, route-profile slot dispatch, journal/resume by `(spec_hash, route_profile, workflow)`, inert-spine checks, fail-closed mutating-execution guard
  - Adapter support table with current statuses (`blocked`, `separate-harness`, `not-applicable`)
  - Unsupported cases: template literal args, dynamic `opts` spread, `pipeline`/`parallel`/`phase`/`budget`/`workflow()` globals, nested execution, mutating execution without verified adapter, native `CLAUDE_CODE_WORKFLOWS` tool
- *(CL-182u)* `docs/adr/workflow-primitive.md` — ADAPTER_PRESERVATION_STATUS update criteria (6 rules) added to Consequences section; fail-closed default and `readOnly` bypass documented

- *(CL-99c)* Add project harness baseline checklist for collaboration projects
  - `docs/harness-baseline.md` defines what each harness directory (`.claude/`, `.agents/`, `.codex/`, `.cursor/`) must and must not commit
  - Separates project-local committed content from user-global credentials, MCP config, and personal overrides
  - `.gitignore` patterns for secret-bearing files (`settings.local.json`, `worktrees/`, `anatomy.json`, `buglog.json`) and generated runtime artifacts
  - Baseline generalizes beyond `.claude/` to `.agents/`, `.codex/`, and `.cursor/`
  - Reference implementation verified against mira on 2026-05-24 — all baseline requirements pass
  - `templates/project-gitignore-harness.txt` provides a copy-paste `.gitignore` snippet

### ⚙️ Miscellaneous Tasks

- *(CL-37yu)* Workflow journal/resume hardening in `scripts/lib/workflow_runtime.py`
  - Journal format is versioned (`SCHEMA_VERSION = "1"`); each entry records `slot`, `adapter`, `prompt_opts_hash`, and `result` metadata alongside workflow identity fields (`spec_hash`, `route_profile`, `workflow`)
  - `bind_identity()` compares current run identity against the stored journal on every `run()` call; mismatched entries are cleared before execution resumes
  - Journal writes are atomic via a `.tmp` rename, preventing partial-write corruption
  - Parent directories are created safely (`mkdir(parents=True, exist_ok=True)`) before any write
  - Corrupt or unreadable journals are quarantined to a timestamped `.corrupt` sidecar; execution continues with a fresh journal
  - Incompatible schema versions raise `JournalSchemaError` with an actionable message including the journal file path
  - `from_dict` rejects malformed `entries` fields with a descriptive error instead of silently substituting an empty dict
  - Existing read-only workflow runtime spike behavior is unchanged

### 🚀 Features

- *(CL-w5d)* Uniform dry-run JSON contract for all primitive installers — `library.py <primitive> use --dry-run --json` now emits a versioned envelope with `status`, `operations`, `target_paths`, `harness_routing`, `conflict_policy`, `lockfile_changes`, and `requires_user_confirmation` fields; project scope and conflict detection are consistently reflected across skill, standard, agent, prompt, script, model-standard, agent-base, MCP, and guardrail installers; contract schema documented in `docs/schema/dry-run-contract.md`
- *(schema)* Add `harness_support` and `runtime_requirements` as optional fields on all catalog entry shapes
- *(schema)* Require `metadata.library.plane` on `tier:domain` and `tier:project` entries (enforced by schema conditional and `validate-library.py`)
- *(installer)* Refuse `--harness <h>` installs when an entry declares `harness_support.<h>: not-supported` — check runs before any dependency installs to avoid partial mutations
- *(forges)* All five forges (agent, hook, script, skill, standard) now ask harness-support and runtime-requirements questions during creation flow
- **CL-iye.2**: Add `cursor-impl.py` — Cursor Agent/Composer implementer adapter for bead workflow leaves. Headless dispatch via `cursor-agent --print --force --trust`, preflight checks (binary, auth, model availability), timeout+cleanup, CompletionReport JSON, and metrics recording. Implementer leaf only — not an orchestrator. Source in `cognovis-core/skills/beads/scripts/cursor-impl.py`.
- *(CL-iye.8)* Generalize `harness_support` to a closed enum of five harness IDs — `claude_code`, `codex`, `cursor`, `opencode`, and `gemini`; schema now accepts and validates all five IDs, `library.py --harness` accepts `cursor` and `opencode`, and `_check_harness_support` enforces `not-supported` for any accepted ID; MCP server entries and project tooling entries intentionally carry no `harness_support` (documented in schema descriptions and `docs/PRIMITIVES.md`); CL-iye.3 can implement a Cursor projection without changes to the core gate
- *(CL-d7e)* Compatibility pre-install gate in `library.py` — catalog entries can declare a `compatibility` field (e.g. `claude_code>=4.0`); `library use` exits with code 4 and a clear error message when the current harness version does not satisfy the constraint. Entries without a `compatibility` field are unaffected. Version detection is best-effort: if the harness binary is absent or non-versioned, a warning is emitted and installation proceeds.
- *(CL-iye.1)* `--route-profile NAME` flag for `bin/cld` and `bin/cdx` — selects a named route profile, exports `CLD_ROUTE_PROFILE`, and injects the profile name into the bead execution prompt so `phase0-claim.py` resolves the correct `execution_plan` (slots, adapter, model, reasoning_effort, timeout) from `orchestrator-config.yml`. Built-in profiles: `cld-default`, `cdx-default`, `cdx-composer`. Backward-compatible: `perspective_policy` remains the fallback when no profile is given.
- *(CL-iye.3)* Cursor harness projection for skills, agents, rules, and runtime requirements — `library use --harness cursor` installs skills to `.cursor/skills/<name>/` (project) or `~/.cursor/skills/<name>/` (global); agent installs are explicitly rejected with a compatibility message; MCP and guardrail installs under `--harness cursor` or `--harness opencode` are rejected before any side effects; `runtime_requirements` can declare `cursor-agent` as a required binary (checked via the existing binary gate); dry-run `--json` output includes `target_paths`, `harness_routing`, and `conflict_policy` for Cursor targets; Cursor harness targets documented in `docs/PRIMITIVES.md`, `docs/harness-baseline.md`, and `docs/primitives/skill.md`

### 🐛 Bug Fixes

- *(CL-iye.7)* Enforce `runtime_requirements.binaries` gate before any install or dependency mutation — `library use` now exits with code 3 and a structured error when a declared binary is absent from PATH; the check runs for all supported primitive types (skills, agents, prompts, scripts, standards, model-standards, agent-bases, guardrails, MCP, and workflow entries); the gate fires on both the main entry and each dependency before any filesystem change occurs, preventing partial installs when a fuzzy query resolves to an incompatible entry; `--dry-run --json` and non-dry-run `--json` both return a stable `error_result` payload that includes the list of missing binary names
- *(installer)* Move `lookup_entry` import to module level to avoid repeated local imports in `_resolve_default_scope`
- *(fhir-sync-versions)* Register skill in library catalog

### 🐛 Bug Fixes

- *(library)* Skip unchanged paths during bulk sync
- Classify fhir sync versions as skill
- Harden catalog inventory sync
- *(library)* Resolve marketplace-backed skill sources

### 💼 Other

- Add fix-agent to catalog, wire as bead-orchestrator dependency
- Register customer-invoice skill
- Flatten sussdorff skill paths

### 📚 Documentation

- *(adr)* ADR-0006 — workflow as a first-class Library primitive

### ⚙️ Miscellaneous Tasks

- *(clc-i8qc)* Wave-reviewer sweep — remove create/epic-init/wave-reviewer from library catalog
- *(catalog)* Add seed-data-parity standard entry
## [2026.05.37] - 2026-05-21

### 🚀 Features

- *(launchers)* Export CLD_BEAD_LINE in cdx and cld bead modes
- *(models)* Align gpt-* and claude-opus reasoning_effort vocab to xhigh canonical (refs: clc-dty AK4b)
- *(CL-zyk)* Capture upstream commit SHA for MCP entries at install time

### 🐛 Bug Fixes

- *(CL-pq4)* Upgrade drift_kind to 'both' when path+upstream drift co-occur
- *(cdx)* Allow quick-fix implementer dispatch
- *(catalog)* Preserve top-level comments + scrub factory-check refs
- *(catalog)* Two sync warnings — agentic-primitives category + mcp:open-brain upstream source

### 💼 Other

- Worktree-bead-CL-zyk

### ⚙️ Miscellaneous Tasks

- Remove factory-check zombie catalog entry
## [2026.05.36] - 2026-05-19

### 🚀 Features

- *(CL-pq4)* Green — standard installer uses category-mirror paths for single-file installs

### 🐛 Bug Fixes

- *(CL-pq4)* Address review findings iteration 1
- *(CL-pq4)* Address codex adversarial findings

### 💼 Other

- Worktree-bead-CL-pq4

### 🧪 Testing

- *(CL-pq4)* Red — add TestStandardInstallCategoryMirror for all 6 ACs

### ⚙️ Miscellaneous Tasks

- Bump version to 2026.05.36
## [2026.05.35] - 2026-05-19

### 🚀 Features

- *(catalog)* Add judge-default agent entry
- *(clc-dyw.6)* Register bead-hygiene standard + bead-reviewer skill

### 🐛 Bug Fixes

- Repair source-url-liveness workflow and clear open-brain skill drift
- *(CL-brl)* Honor default_scope from catalog entries in cmd_use
- *(CL-brl)* Use fuzzy=True in _resolve_default_scope to match installer lookup semantics

### 💼 Other

- Worktree-bead-CL-brl

### 📚 Documentation

- *(catalog)* Clarify integration-test scope and resolution paths in error message

### 🧪 Testing

- *(catalog)* Add builder coverage + anti-stub assertions for catalog agents
- *(catalog)* Fix stub-detection fixture, use structural checks, add resolver tests
- *(catalog)* Add plugin-prefixed body-ref resolver for subagent_type body refs
- *(catalog)* Scan all composed layers for plugin-prefixed body refs

### ⚙️ Miscellaneous Tasks

- *(source-url-liveness)* Allow private catalog access via LIBRARY_CATALOG_READ_TOKEN
- Ignore beads JSONL export + strip obsolete cld update-check flags
- Bump version to 2026.05.35
## [2026.05.34] - 2026-05-17

### 🚀 Features

- Normalize library yaml information model
- *(library)* Add installed inventory view
- *(library)* Register go-live catalog entries
- Move primitive forges into platform
- Add catalog promotion routing
- *(library)* Add targeted primitive sync
- *(agent)* Audit claude frontmatter
- Rename golden prompts to agent bases
- Split agent bases by harness
- Add unified agent builder
- Add capability-based agent builder
- Harden agent capability migration
- Anchor agent migration policy

### 🐛 Bug Fixes

- *(library)* Reinstall missing lockfile targets
- *(library)* Source ob-cli from open-brain
- *(library)* Align installed lifecycle scopes
- *(library)* Install codex agent targets
- *(library)* Catalog architecture-scout, rename changelog
- Harden platform forge migration
- Move platform standards into library catalog
- *(agent)* Preserve claude frontmatter
- Restore agent base migration fallback
- Surface agent base migration warnings
- *(CL-wjr)* Library audit/use detect upstream drift
- *(CL-wjr)* Also auto-refresh on local tamper in 'use'

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
- Add bash tool lockdown research
- Refresh codex guardrail mapping

### 🧪 Testing

- *(library)* Align suite with vendored layout
- *(library)* Remove obsolete migration skips
- Harden primitive regression coverage
- Cover legacy alias validator warnings
- Drop retired home agent assertions

### ⚙️ Miscellaneous Tasks

- Catalog primitive placement standard
- Add primitive placement catalog metadata
- *(CL-usc)* Record repomix vulnerability remediation
- Catalog promoted healthcare standards
- Harden library yaml alias validation
- Catalog normalized healthcare standards
- Update changelog
- Bump version to 2026.05.34
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
