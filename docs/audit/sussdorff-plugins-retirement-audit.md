# sussdorff-plugins Retirement Audit

**Date**: 2026-05-12
**Bead**: CL-ast
**ADR**: docs/adr/canonical-library-architecture.md (ADR-0002 Phase 2a)

## Summary

8 bundles audited. Artefacts across all bundles have been classified.
beads-workflow and architecture-trinity artefacts are EQUIVALENT in cognovis-core.
All other bundles require follow-up migration (7 follow-up beads filed).
All 8 bundles successfully uninstalled. Critical hooks registered in settings.json.
Agents deployed to ~/.claude/agents/ to preserve functionality post-retirement.

---

## Bundle: core

| Artefact | Type | Canonical Location | Status |
|---|---|---|---|
| agents/branch-synchronizer.md | agent | cognovis/library-core/plugins/core/ | MISSING-TEAM → CL-bpt |
| agents/ci-monitor.md | agent | cognovis/library-core/plugins/core/ | MISSING-TEAM → CL-bpt |
| agents/git-operations.md | agent | cognovis/library-core/plugins/core/ | MISSING-TEAM → CL-bpt |
| agents/researcher.md | agent | cognovis/library-core/plugins/core/ | MISSING-TEAM → CL-bpt |
| agents/session-close.md | agent | cognovis/library-core/plugins/core/ | MISSING-TEAM → CL-bpt |
| agents/session-close-handlers/ (15 files) | agent scripts | cognovis/library-core/plugins/core/ | MISSING-TEAM → CL-bpt |
| hooks/rules-loader.py | hook | ~/.claude/hooks/SessionStart-rules-loader.py | DEPLOYED-DIRECT |
| hooks/read-before-edit.py | hook | ~/.claude/hooks/read-before-edit.py | DEPLOYED-DIRECT |
| hooks/worktree-create.sh | hook | — (not found in ~/.claude/hooks/) | MISSING-TEAM → CL-bpt |
| hooks/hooks.json | hook config | — (plugin-internal) | MISSING-TEAM → CL-bpt |
| scripts/adr-context.py | script | ~/.claude/scripts/adr-context.py | DEPLOYED-DIRECT |
| skills/cmux | skill | cognovis/library-core/ | MISSING-TEAM → CL-bpt |
| skills/daily-brief | skill | cognovis/library-core/ | MISSING-TEAM → CL-bpt |
| skills/dolt | skill | cognovis/library-core/ | MISSING-TEAM → CL-bpt |
| skills/event-log | skill | cognovis/library-core/ | MISSING-TEAM → CL-bpt |
| skills/inject-standards | skill | cognovis/library-core/ | MISSING-TEAM → CL-bpt |
| skills/prompt-refiner | skill | cognovis/library-core/ | MISSING-TEAM → CL-bpt |
| skills/standards | skill | cognovis/library-core/ | MISSING-TEAM → CL-bpt |
| skills/summarize | skill | cognovis/library-core/ | MISSING-TEAM → CL-bpt |
| skills/vision | skill | cognovis/library-core/ | MISSING-TEAM → CL-bpt |

**Note**: Agents deployed to ~/.claude/agents/core/ as interim measure. Hooks registered directly in settings.json.

---

## Bundle: beads-workflow

| Artefact | Type | Canonical Location | Status |
|---|---|---|---|
| agents/bead-orchestrator.md | agent | cognovis/library-core/plugins/beads-workflow/agents/ | EQUIVALENT |
| agents/changelog-updater.md | agent | cognovis/library-core/plugins/beads-workflow/agents/ | EQUIVALENT |
| agents/doc-changelog-updater.md | agent | cognovis/library-core/plugins/beads-workflow/agents/ | EQUIVALENT |
| agents/feature-doc-updater.md | agent | cognovis/library-core/plugins/beads-workflow/agents/ | EQUIVALENT |
| agents/plan-reviewer.md | agent | cognovis/library-core/plugins/beads-workflow/agents/ | EQUIVALENT |
| agents/quick-fix.md | agent | cognovis/library-core/plugins/beads-workflow/agents/ | EQUIVALENT |
| agents/review-agent.md | agent | cognovis/library-core/plugins/beads-workflow/agents/ | EQUIVALENT |
| agents/verification-agent.md | agent | cognovis/library-core/plugins/beads-workflow/agents/ | EQUIVALENT |
| agents/wave-monitor.md | agent | cognovis/library-core/plugins/beads-workflow/agents/ | EQUIVALENT |
| agents/wave-orchestrator.md | agent | cognovis/library-core/plugins/beads-workflow/agents/ | EQUIVALENT |
| hooks/bd-cache-invalidator.py | hook | ~/.claude/hooks/bd-cache-invalidator.py | DEPLOYED-DIRECT |
| hooks/pre-compact-state.py | hook | ~/.claude/hooks/pre-compact-state.py | DEPLOYED-DIRECT |
| hooks/session-context.py | hook | ~/.claude/hooks/session-context.py | DEPLOYED-DIRECT |
| hooks/session-end.py | hook | cognovis/library-core/plugins/beads-workflow/hooks/ | EQUIVALENT |
| hooks/feature-scenario-reminder.py | hook | cognovis/library-core/plugins/beads-workflow/hooks/ | EQUIVALENT |
| lib/orchestrator/ (metrics.py etc.) | library | cognovis/library-core/plugins/beads-workflow/lib/ | EQUIVALENT |
| scripts/ (bd-wrapper, wave-poll.py, etc.) | scripts | cognovis/library-core/plugins/beads-workflow/scripts/ | EQUIVALENT |
| skills/bd-release-notes | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/bead-metrics | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/compound | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/create | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/epic-init | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/factory-check | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/impl | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/intake | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/plan | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/refactor-note | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/retro | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/review-conventions | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/wave-orchestrator | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/wave-reviewer | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |
| skills/workplan | skill | cognovis/library-core/plugins/beads-workflow/skills/ | EQUIVALENT |

**Note**: Agents deployed to ~/.claude/agents/beads-workflow/ from cognovis-core (not plugin cache).

---

## Bundle: meta

| Artefact | Type | Canonical Location | Status |
|---|---|---|---|
| agents/convention-reviewer.md | agent | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| agents/learning-extractor.md | agent | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| agents/skill-auditor.md | agent | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| plugins/architecture-trinity/agents/architecture-scout.md | agent | cognovis/library-core/plugins/architecture-trinity/ | EQUIVALENT |
| plugins/architecture-trinity/skills/adr-gap | skill | cognovis/library-core/plugins/architecture-trinity/ | EQUIVALENT |
| skills/agent-forge | skill | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| skills/claude-md-pruner | skill | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| skills/entropy-scan | skill | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| skills/hook-creator | skill | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| skills/nbj-audit | skill | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| skills/plugin-management | skill | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| skills/skill-auditor | skill | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| skills/sync-standards | skill | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| skills/system-prompt-audit | skill | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| skills/token-cost | skill | sussdorff/library-core | MISSING-PERSONAL → CL-hcc |
| skills/vision-review | skill | cognovis/library-core/plugins/architecture-trinity/skills/ | EQUIVALENT |

---

## Bundle: infra

| Artefact | Type | Canonical Location | Status |
|---|---|---|---|
| agents/home.md | agent | sussdorff/library-core | MISSING-PERSONAL → CL-6r4 |
| skills/hetzner-cloud | skill | sussdorff/library-core | MISSING-PERSONAL → CL-6r4 |
| skills/home-infra | skill | sussdorff/library-core | MISSING-PERSONAL → CL-6r4 |
| skills/infra-principles | skill | sussdorff/library-core | MISSING-PERSONAL → CL-6r4 |
| skills/local-vm | skill | sussdorff/library-core | MISSING-PERSONAL → CL-6r4 |
| skills/paperless-cli | skill | sussdorff/library-core | MISSING-PERSONAL → CL-6r4 |
| skills/piler-cli | skill | sussdorff/library-core | MISSING-PERSONAL → CL-6r4 |
| skills/portless | skill | sussdorff/library-core | MISSING-PERSONAL → CL-6r4 |
| skills/ui-cli | skill | sussdorff/library-core | MISSING-PERSONAL → CL-6r4 |

---

## Bundle: business

| Artefact | Type | Canonical Location | Status |
|---|---|---|---|
| skills/ai-readiness | skill | sussdorff/library-core | MISSING-PERSONAL → CL-q78 |
| skills/amazon | skill | sussdorff/library-core | MISSING-PERSONAL → CL-q78 |
| skills/angebotserstellung | skill | sussdorff/library-core | MISSING-PERSONAL → CL-q78 |
| skills/career-check | skill | sussdorff/library-core | MISSING-PERSONAL → CL-q78 |
| skills/collmex-cli | skill | sussdorff/library-core | MISSING-PERSONAL → CL-q78 |
| skills/council | skill | sussdorff/library-core | MISSING-PERSONAL → CL-q78 |
| skills/google-invoice | skill | sussdorff/library-core | MISSING-PERSONAL → CL-q78 |
| skills/mail-send | skill | sussdorff/library-core | MISSING-PERSONAL → CL-q78 |
| skills/mm-cli | skill | sussdorff/library-core | MISSING-PERSONAL → CL-q78 |
| skills/op-credentials | skill | sussdorff/library-core | MISSING-PERSONAL → CL-q78 |

---

## Bundle: content

| Artefact | Type | Canonical Location | Status |
|---|---|---|---|
| skills/brand-forge | skill | sussdorff/library-core | MISSING-PERSONAL → CL-141 |
| skills/cmux-browser | skill | sussdorff/library-core | MISSING-PERSONAL → CL-141 |
| skills/cmux-markdown | skill | sussdorff/library-core | MISSING-PERSONAL → CL-141 |
| skills/linkedin | skill | sussdorff/library-core | MISSING-PERSONAL → CL-141 |
| skills/pencil | skill | sussdorff/library-core | MISSING-PERSONAL → CL-141 |
| skills/transcribe | skill | sussdorff/library-core | MISSING-PERSONAL → CL-141 |

---

## Bundle: medical

| Artefact | Type | Canonical Location | Status |
|---|---|---|---|
| agents/compliance-reviewer.md | agent | sussdorff/library-core | MISSING-PERSONAL → CL-gak |
| agents/human-factors-reviewer.md | agent | sussdorff/library-core | MISSING-PERSONAL → CL-gak |
| skills/billing-reviewer | skill | sussdorff/library-core | MISSING-PERSONAL → CL-gak |
| skills/mira-aidbox | skill | sussdorff/library-core | MISSING-PERSONAL → CL-gak |

---

## Bundle: dev-tools

| Artefact | Type | Canonical Location | Status |
|---|---|---|---|
| agents/chrome-devtools-tester.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/codex-guide.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/constraint-checker.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/feedback-extractor.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/file-analyzer.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/gui-review.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/holdout-validator.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/implementer.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/integration-test-runner.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/pester-test-engineer.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/playwright-tester.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/prd-generator.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/scenario-generator.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/spellcheck-test-engineer.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/test-author.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/test-engineer.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| agents/uat-validator.md | agent | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| hooks/anatomy-index.py | hook | ~/.claude/hooks/anatomy-index.py | DEPLOYED-DIRECT |
| hooks/buglog.py | hook | ~/.claude/hooks/buglog.py | DEPLOYED-DIRECT |
| codex-agents/bead-orchestrator.toml | codex agent | ~/.codex/agents/ | DEPLOYED-DIRECT |
| codex-agents/session-close.toml | codex agent | ~/.codex/agents/ | DEPLOYED-DIRECT |
| codex-agents/wave-orchestrator.toml | codex agent | ~/.codex/agents/ | DEPLOYED-DIRECT |
| skills/binary-explorer | skill | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| skills/bug-triage | skill | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| skills/codex | skill | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| skills/playwright-cli | skill | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| skills/project-context | skill | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| skills/project-health | skill | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| skills/project-setup | skill | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| skills/spec-developer | skill | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |
| skills/vision-author | skill | cognovis/library-core/plugins/dev-tools/ | MISSING-TEAM → CL-ayf |

---

## Deployed Artefacts (Operational Changes to ~/.claude/)

These changes were made to preserve functionality after plugin retirement.
They are NOT committed to git (operational scope) but documented here as evidence.

### ~/.claude/agents/ (newly created)
| Directory | Count | Source |
|---|---|---|
| ~/.claude/agents/beads-workflow/ | 10 agents | cognovis-core/plugins/beads-workflow/agents/ |
| ~/.claude/agents/core/ | 5 agents + session-close-handlers/ | plugin cache 2026.05.3 |
| ~/.claude/agents/dev-tools/ | 17 agents | plugin cache 2026.05.3 |
| ~/.claude/agents/infra/ | 1 agent | plugin cache 2026.05.3 |
| ~/.claude/agents/medical/ | 2 agents | plugin cache 2026.05.3 |
| ~/.claude/agents/meta/ | 4 agents (incl. architecture-scout from cognovis-core) | mixed |

### ~/.claude/scripts/ (pre-existing, extended)
- adr-context.py — copied from core bundle plugin cache

### ~/.codex/agents/ (pre-existing)
- bead-orchestrator.toml, session-close.toml, wave-orchestrator.toml — from dev-tools bundle

### ~/.claude/settings.json (hooks registered)
| Hook Event | Script | Previously Registered? |
|---|---|---|
| SessionStart | SessionStart-rules-loader.py | No (was via plugin) |
| SessionStart | session-context.py | No (was via plugin) |
| PreToolUse (Edit/Write/MultiEdit) | read-before-edit.py | No (was via plugin) |
| PostToolUse (Bash) | bd-cache-invalidator.py | No (was via plugin) |
| PreCompact | pre-compact-state.py | No (was via plugin) |

---

## Smoke Test Results (2026-05-12)

| Check | Result |
|---|---|
| installed_plugins.json: 0 sussdorff-plugins entries | PASS |
| known_marketplaces.json: sussdorff-plugins absent | PASS |
| settings.json: rules-loader SessionStart hook registered | PASS |
| settings.json: session-context SessionStart hook registered | PASS |
| ~/.claude/agents/ directory exists with subdirectories | PASS |
| beads-workflow agents deployed: 10 | PASS |
| core agents deployed: 5 + session-close-handlers | PASS |
| library.yaml marketplaces: section has no sussdorff-plugins | PASS |

---

## Follow-up Beads Filed

| Bead ID | Title | Type |
|---|---|---|
| CL-bpt | Migrate core bundle artefacts to cognovis/library-core | MISSING-TEAM |
| CL-ayf | Migrate dev-tools bundle to cognovis/library-core | MISSING-TEAM |
| CL-hcc | Migrate meta bundle to sussdorff/library-core | MISSING-PERSONAL |
| CL-6r4 | Migrate infra bundle to sussdorff/library-core | MISSING-PERSONAL |
| CL-q78 | Migrate business bundle to sussdorff/library-core | MISSING-PERSONAL |
| CL-141 | Migrate content bundle to sussdorff/library-core | MISSING-PERSONAL |
| CL-gak | Migrate medical bundle to sussdorff/library-core | MISSING-PERSONAL |
