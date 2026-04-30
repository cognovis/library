# Skills & Primitives Origin Audit

**Bead**: CL-23z | **Epic**: CL-36o | **Date**: 2026-04-30
**Author**: bead-orchestrator (CL-23z)
**Taxonomy reference**: `docs/PRIMITIVES.md`
**Name-collision policy**: `docs/policy/name-collision.md`
**MCP audit** (out of scope here): `docs/audit/mcp-servers.md`
**Machine-readable output**: `docs/audit/skills-origin.json`

---

## Scope and Inventory Roots

This audit classifies every skill, agent, hook, command, and standard across:

| Root | Notes |
|------|-------|
| `~/code/claude-code-plugins/` (categories: beads-workflow, business, content, core, dev-tools, infra, medical, meta) | Primary source tree — each has skills/, agents/, commands/, hooks/ |
| `~/code/claude-code-plugins/.claude/` (standards/, commands/) | Project-local standards and commands tracked in git |
| `~/.claude/standards/` | Global user standards (legacy path, see CL-v56) |
| `~/.claude/hooks/` | Installed global hooks |
| `~/.claude/skills/open-brain/people-query/` | Single globally-installed skill with SKILL.md |
| `~/.codex/agents/` | 3 Codex agent TOML files (installed copies, source in dev-tools/codex-agents/) |
| `~/.agents/`, `~/.codex/vendor_imports/skills/` | Empty — no artifacts |
| `cognovis/library-core`, `sussdorff/library-core` | Not cloned locally — empty until CL-1rr |

**Excluded from this audit**: MCP servers (covered by `docs/audit/mcp-servers.md`, CL-p91).

---

## Origin Classification Key

| Code | Meaning |
|------|---------|
| ORIGINAL | Pure ours — no external source. Lives in cognovis/library-core. |
| PERSONAL | Malte-only (personal workflows, credentials, personal tools). Lives in sussdorff/library-core. |
| WRAPPER | We own the skill but it wraps a 3rd-party tool. Document the upstream. |
| ADOPTED | Lifted/adapted from an external repo. Switch to marketplace reference. |
| THIRD_PARTY | Someone else owns the source. Add their org as a marketplace; reference it. |

## Intent / Correct-Type Key (from PRIMITIVES.md)

| Type | Trigger |
|------|---------|
| skill | Model-triggered; auto-picks from context |
| command | User-explicit /name invocation |
| agent | Isolated context budget, own tool grant |
| guardrail | Fires unconditionally outside LLM loop (hook) |
| standard | Harness-injected context; not invokable |
| plugin | Bundle of multiple primitives |

## Tier Key

| Tier | Meaning |
|------|---------|
| core | Always-loaded everywhere |
| domain | Opt-in via library.yaml include |
| project | Ships only with specific repos |

---

## Section 1: beads-workflow Category

### Skills

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `beads-workflow/skills/bd-release-notes/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on bd release notes context) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/bead-metrics/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on metrics/bead stats context) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/compound/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on compound bead context) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/create/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on bead creation context) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/epic-init/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on epic initialization) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/factory-check/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on factory-ready check) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/impl/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on implementation dispatch) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/intake/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on bead intake/triage) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/plan/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on planning context) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/refactor-note/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on refactor annotation) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/retro/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on retrospective context) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/review-conventions/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on review context) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/wave-orchestrator/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on multi-bead wave dispatch) | skill — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/skills/workplan/SKILL.md` | skill | ORIGINAL | skill (auto-trigger on workplan context) | skill — correct | Keep in beads-workflow plugin | domain |

**Note**: `beads-workflow/skills/wave-orchestrator/SKILL.md` is a skill (auto-trigger) distinct from `beads-workflow/agents/wave-orchestrator.md` (agent with isolated context). Both are correct types for different invocation semantics.

### Agents

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `beads-workflow/agents/bead-orchestrator.md` | agent | ORIGINAL | agent (isolated context, phases 0-16) | agent — correct | Keep in beads-workflow plugin; Codex bridge via `dev-tools/codex-agents/bead-orchestrator.toml` | domain |
| `beads-workflow/agents/changelog-updater.md` | agent | ORIGINAL | agent (isolated doc update context) | agent — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/agents/doc-changelog-updater.md` | agent | ORIGINAL | agent (isolated doc changelog update) | agent — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/agents/feature-doc-updater.md` | agent | ORIGINAL | agent (isolated feature doc update) | agent — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/agents/plan-reviewer.md` | agent | ORIGINAL | agent (isolated plan review context) | agent — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/agents/quick-fix.md` | agent | ORIGINAL | agent (lightweight isolated fix context) | agent — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/agents/review-agent.md` | agent | ORIGINAL | agent (Opus review, isolated) | agent — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/agents/verification-agent.md` | agent | ORIGINAL | agent (read-only verification, isolated) | agent — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/agents/wave-monitor.md` | agent | ORIGINAL | agent (monitors wave execution state) | agent — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/agents/wave-orchestrator.md` | agent | ORIGINAL | agent (orchestrates multi-bead waves; has own context) | agent — correct | Keep in beads-workflow plugin; Codex bridge via `dev-tools/codex-agents/wave-orchestrator.toml` | domain |

### Hooks

| Path | Current Type | Origin | Hook Event | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|-----------|--------|-------------|-----------------|------|
| `beads-workflow/hooks/bd-cache-invalidator.py` | guardrail | ORIGINAL | PostToolUse(Bash) | guardrail (unconditional bd cache invalidation) | guardrail — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/hooks/feature-scenario-reminder.py` | guardrail | ORIGINAL | PostToolUse(Bash) | guardrail (reminds about scenario on bd commands) | guardrail — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/hooks/pre-compact-state.py` | guardrail | ORIGINAL | PreCompact | guardrail (saves state before context compaction) | guardrail — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/hooks/session-context.py` | guardrail | ORIGINAL | SessionStart | guardrail (injects beads context at session start) | guardrail — correct | Keep in beads-workflow plugin | domain |
| `beads-workflow/hooks/session-end.py` | guardrail | ORIGINAL | Stop | guardrail (cleanup on session end) | guardrail — correct | Keep in beads-workflow plugin | domain |

---

## Section 2: business Category

### Skills

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `business/skills/ai-readiness/SKILL.md` | skill | PERSONAL | skill (personal career/AI assessment tool) | skill — correct | Move to sussdorff/library-core | project |
| `business/skills/amazon/SKILL.md` | skill | PERSONAL | skill (personal Amazon.de purchase automation) | skill — correct | Move to sussdorff/library-core; personal purchase database dependency | project |
| `business/skills/angebotserstellung/SKILL.md` | skill | ORIGINAL | skill (Cognovis-specific offer creation; German-language) | skill — correct | Consider cognovis/library-core (org-specific); not generalizeable | project |
| `business/skills/career-check/SKILL.md` | skill | PERSONAL | skill (personal career analysis) | skill — correct | Move to sussdorff/library-core | project |
| `business/skills/collmex-cli/SKILL.md` | skill | ORIGINAL | skill (Collmex ERP wrapper; Cognovis-specific) | skill — correct | Keep in cognovis/library-core; WRAPPER around Collmex Pro API | project |
| `business/skills/council/SKILL.md` | skill | ORIGINAL | skill (multi-perspective review orchestrator) | skill — correct; could be an agent (spawns subagents) but skill semantics correct for auto-trigger | Keep in beads-workflow or meta; generalizable — move to cognovis/library-core | domain |
| `business/skills/google-invoice/SKILL.md` | skill | PERSONAL | skill (personal Google One invoice download) | skill — correct | Move to sussdorff/library-core | project |
| `business/skills/mail-send/SKILL.md` | skill | ORIGINAL | skill (Apple Mail AppleScript; macOS-specific) | skill — correct; consider guardrail (prep only, user reviews draft) | Keep in cognovis/library-core; WRAPPER around Apple Mail | domain |
| `business/skills/mm-cli/SKILL.md` | skill | PERSONAL | skill (MoneyMoney personal finance app CLI) | skill — correct | Move to sussdorff/library-core; WRAPPER around MoneyMoney | project |
| `business/skills/op-credentials/SKILL.md` | skill | ORIGINAL | skill (1Password credentials read/create) | skill — correct | Keep in cognovis/library-core; WRAPPER around 1Password CLI | domain |

**Marketplace candidates**: `collmex-cli` (Collmex users), `mail-send` (macOS mail automation), `op-credentials` (1Password users).

---

## Section 3: content Category

### Skills

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `content/skills/brand-forge/SKILL.md` | skill | ORIGINAL | skill (brand/voice profile creation) | skill — correct | Keep in cognovis/library-core | domain |
| `content/skills/cmux-browser/SKILL.md` | skill | ORIGINAL | skill (cmux browser pane automation) | skill — correct; WRAPPER around cmux | Keep in cognovis/library-core | domain |
| `content/skills/cmux-markdown/SKILL.md` | skill | ORIGINAL | skill (cmux markdown viewer pane) | skill — correct; WRAPPER around cmux | Keep in cognovis/library-core | domain |
| `content/skills/linkedin/SKILL.md` | skill | PERSONAL | skill (personal LinkedIn automation) | skill — correct; WRAPPER around playwright-cli | Move to sussdorff/library-core | project |
| `content/skills/pencil/SKILL.md` | skill | ORIGINAL | skill (Pencil design tool via MCP) | skill — correct; WRAPPER around pencil MCP | Keep in cognovis/library-core | domain |
| `content/skills/transcribe/SKILL.md` | skill | PERSONAL | skill (personal audio transcription via AssemblyAI + Plaud) | skill — correct; WRAPPER around AssemblyAI | Move to sussdorff/library-core | project |

---

## Section 4: core Category

### Skills

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `core/skills/beads/SKILL.md` | skill | ORIGINAL | skill (dispatches bead implementation — auto-trigger on bead context) | skill — correct; orchestrator of agents | Keep in cognovis/library-core | core |
| `core/skills/cmux/SKILL.md` | skill | ORIGINAL | skill (cmux topology control) | skill — correct; WRAPPER around cmux | Keep in cognovis/library-core | domain |
| `core/skills/daily-brief/SKILL.md` | skill | ORIGINAL | skill (generate daily briefs from open-brain) | skill — correct | Keep in cognovis/library-core | domain |
| `core/skills/dolt/SKILL.md` | skill | ORIGINAL | skill (troubleshoot Dolt failures) | skill — correct; WRAPPER around Dolt CLI | Keep in cognovis/library-core | domain |
| `core/skills/event-log/SKILL.md` | skill | ORIGINAL | skill (query event log database) | skill — correct | Keep in cognovis/library-core | domain |
| `core/skills/inject-standards/SKILL.md` | skill | ORIGINAL | skill (loads standards into context) | skill — correct | Keep in cognovis/library-core | core |
| `core/skills/prompt-refiner/SKILL.md` | skill | ORIGINAL | skill (refine dictated input via HeyPresto MCP) | skill — correct; WRAPPER around HeyPresto MCP | Keep in cognovis/library-core | domain |
| `core/skills/standards/SKILL.md` | skill | ORIGINAL | skill (manage standards lifecycle) | skill — correct | Keep in cognovis/library-core | domain |
| `core/skills/summarize/SKILL.md` | skill | ORIGINAL | skill (content extraction/summarization) | skill — correct; WRAPPER around summarize CLI + Crawl4AI | Keep in cognovis/library-core | domain |
| `core/skills/vision/SKILL.md` | skill | ORIGINAL | skill (creative brainstorming mode) | skill — correct; NOTE: name "vision" conflicts with standard "vision" semantics — consider rename | Keep in cognovis/library-core | domain |

### Agents

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `core/agents/branch-synchronizer.md` | agent | ORIGINAL | agent (git branch sync operations, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `core/agents/ci-monitor.md` | agent | ORIGINAL | agent (monitors CI pipelines, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `core/agents/git-operations.md` | agent | ORIGINAL | agent (git operations, isolated context) | agent — correct | Keep in cognovis/library-core | domain |
| `core/agents/researcher.md` | agent | ORIGINAL | agent (research tasks, isolated context) | agent — correct | Keep in cognovis/library-core | domain |
| `core/agents/session-close.md` | agent | ORIGINAL | agent (multi-phase close pipeline, isolated) | agent — correct | Keep in cognovis/library-core; Codex bridge via `dev-tools/codex-agents/session-close.toml` | core |
| `core/agents/session-close-handlers/` | script | ORIGINAL | scripts (implementation substrate for session-close phases) | scripts — correct (not a primitive per PRIMITIVES.md §9) | Keep alongside session-close agent | core |

### Hooks

| Path | Current Type | Origin | Hook Event | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|-----------|--------|-------------|-----------------|------|
| `core/hooks/read-before-edit.py` | guardrail | ORIGINAL | PreToolUse(Edit, Write, MultiEdit) | guardrail (read-before-edit safety constraint) | guardrail — correct | Keep in core plugin | core |
| `core/hooks/rules-loader.py` | guardrail | ORIGINAL | SessionStart | guardrail (loads rules.d at session start) | guardrail — correct | Keep in core plugin | core |
| `core/hooks/worktree-create.sh` | guardrail | ORIGINAL | WorktreeCreate | guardrail (configures worktree at creation) | guardrail — correct | Keep in core plugin | core |

---

## Section 5: dev-tools Category

### Skills

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `dev-tools/skills/binary-explorer/SKILL.md` | skill | ORIGINAL | skill (reverse-engineer desktop apps) | skill — correct | Keep in cognovis/library-core; broad marketplace candidate | domain |
| `dev-tools/skills/bug-triage/SKILL.md` | skill | ORIGINAL | skill (4-phase bug investigation) | skill — correct | Keep in cognovis/library-core | domain |
| `dev-tools/skills/codex/SKILL.md` | skill | ORIGINAL | skill (OpenAI Codex CLI wrapper) | skill — correct; WRAPPER around Codex CLI | Keep in cognovis/library-core | domain |
| `dev-tools/skills/playwright-cli/SKILL.md` | skill | ORIGINAL | skill (playwright-cli browser automation) | skill — correct; WRAPPER around playwright-cli | Keep in cognovis/library-core | domain |
| `dev-tools/skills/project-context/SKILL.md` | skill | ORIGINAL | skill (generates project-context.md) | skill — correct | Keep in cognovis/library-core; marketplace candidate | domain |
| `dev-tools/skills/project-health/SKILL.md` | skill | ORIGINAL | skill (project quality assessment) | skill — correct | Keep in cognovis/library-core | domain |
| `dev-tools/skills/project-setup/SKILL.md` | skill | ORIGINAL | skill (scaffolds new projects) | skill — correct | Keep in cognovis/library-core | domain |
| `dev-tools/skills/spec-developer/SKILL.md` | skill | ORIGINAL | skill (feature spec via Q&A dialogue) | skill — correct | Keep in cognovis/library-core | domain |
| `dev-tools/skills/vision-author/SKILL.md` | skill | ORIGINAL | skill (guided vision.md dialogue) | skill — correct | Keep in cognovis/library-core | domain |

### Agents

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `dev-tools/agents/chrome-devtools-tester.md` | agent | ORIGINAL | agent (Chrome DevTools browser testing, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/codex-guide.md` | agent | ORIGINAL | agent (Codex CLI guidance, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/constraint-checker.md` | agent | ORIGINAL | agent (read-only constraint checking, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/feedback-extractor.md` | agent | ORIGINAL | agent (extracts structured feedback, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/file-analyzer.md` | agent | ORIGINAL | agent (file analysis, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/gui-review.md` | agent | ORIGINAL | agent (GUI review via screenshots, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/holdout-validator.md` | agent | ORIGINAL | agent (holdout test validation, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/implementer.md` | agent | ORIGINAL | agent (code implementation, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/integration-test-runner.md` | agent | ORIGINAL | agent (integration test execution, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/pester-test-engineer.md` | agent | ORIGINAL | agent (Pester test authoring, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/playwright-tester.md` | agent | ORIGINAL | agent (playwright browser testing, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/prd-generator.md` | agent | ORIGINAL | agent (PRD generation, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/scenario-generator.md` | agent | ORIGINAL | agent (scenario generation, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/spellcheck-test-engineer.md` | agent | ORIGINAL | agent (spellcheck test authoring, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/test-author.md` | agent | ORIGINAL | agent (test authoring, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/test-engineer.md` | agent | ORIGINAL | agent (test engineering, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `dev-tools/agents/uat-validator.md` | agent | ORIGINAL | agent (UAT from external-user perspective, isolated, information barrier) | agent — correct | Keep in cognovis/library-core | domain |

### Hooks

| Path | Current Type | Origin | Hook Event | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|-----------|--------|-------------|-----------------|------|
| `dev-tools/hooks/anatomy-index.py` | guardrail | ORIGINAL | PreToolUse(Read), PostToolUse | guardrail (tracks file-read anatomy for indexing) | guardrail — correct | Keep in dev-tools plugin | domain |
| `dev-tools/hooks/buglog.py` | guardrail | ORIGINAL | PreToolUse(Bash), PostToolUse(Bash) | guardrail (logs bash commands for bug investigation) | guardrail — correct | Keep in dev-tools plugin | domain |

### Codex Agent Bridges (dev-tools/codex-agents/)

| Path | Current Type | Origin | Source | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `dev-tools/codex-agents/bead-orchestrator.toml` | agent (Codex TOML bridge) | ORIGINAL | Source: `beads-workflow/agents/bead-orchestrator.md` | agent — correct (Codex translation of Claude agent) | Maintain parity with source; sync via sync-codex-agents | domain |
| `dev-tools/codex-agents/session-close.toml` | agent (Codex TOML bridge) | ORIGINAL | Source: `core/agents/session-close.md` | agent — correct | Maintain parity with source | domain |
| `dev-tools/codex-agents/wave-orchestrator.toml` | agent (Codex TOML bridge) | ORIGINAL | Source: `beads-workflow/agents/wave-orchestrator.md` | agent — correct | Maintain parity with source | domain |

---

## Section 6: infra Category

### Skills

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `infra/skills/hetzner-cloud/SKILL.md` | skill | PERSONAL | skill (personal Hetzner Cloud infra management) | skill — correct; WRAPPER around hcloud CLI | Move to sussdorff/library-core | project |
| `infra/skills/home-infra/SKILL.md` | skill | PERSONAL | skill (personal home infrastructure — Proxmox, UniFi, HA) | skill — correct | Move to sussdorff/library-core | project |
| `infra/skills/infra-principles/SKILL.md` | skill | ORIGINAL | skill (Cognovis infrastructure principles) | RECLASSIFY: evaluate if purely principles/context → reclassify as standard | Evaluate: if content is purely factual guidance → reclassify as standard (not invokable). If contains workflow steps → keep as skill. Keep in cognovis/library-core | domain |
| `infra/skills/local-vm/SKILL.md` | skill | PERSONAL | skill (personal local VM management) | skill — correct | Move to sussdorff/library-core | project |
| `infra/skills/paperless-cli/SKILL.md` | skill | PERSONAL | skill (personal Paperless-ngx document management) | skill — correct; WRAPPER around Paperless CLI | Move to sussdorff/library-core | project |
| `infra/skills/piler-cli/SKILL.md` | skill | PERSONAL | skill (personal Piler email archive CLI) | skill — correct; WRAPPER around Piler CLI | Move to sussdorff/library-core | project |
| `infra/skills/portless/SKILL.md` | skill | ORIGINAL | skill (portless proxy dev URL setup) | skill — correct; WRAPPER around portless proxy | Keep in cognovis/library-core; broad utility | domain |
| `infra/skills/ui-cli/SKILL.md` | skill | ORIGINAL | skill (UI automation CLI) | skill — correct | Keep in cognovis/library-core | domain |

### Agents

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `infra/agents/home.md` | agent | PERSONAL | agent (home infrastructure management, isolated, baked-in topology) | agent — correct; PERSONAL because it has baked-in personal infra topology | Move to sussdorff/library-core | project |

---

## Section 7: medical Category

### Skills

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `medical/skills/billing-reviewer/SKILL.md` | skill | ORIGINAL | skill (MIRA billing UI review) | skill — correct; project-specific | Keep in cognovis/library-core (project: mira) | project |
| `medical/skills/mira-aidbox/SKILL.md` | skill | ORIGINAL | skill (mira-specific Aidbox configuration) | skill — correct; WRAPPER around samurai-skills Aidbox + project overlay | Keep in cognovis/library-core (project: mira) | project |

### Agents

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `medical/agents/compliance-reviewer.md` | agent | ORIGINAL | agent (medical compliance review, isolated) | agent — correct | Keep in cognovis/library-core (project: mira) | project |
| `medical/agents/human-factors-reviewer.md` | agent | ORIGINAL | agent (human factors review, isolated) | agent — correct | Keep in cognovis/library-core (project: mira) | project |

---

## Section 8: meta Category

### Skills

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `meta/skills/agent-forge/SKILL.md` | skill | ORIGINAL | skill (create/review agents; auto-trigger on agent context) | skill — correct | Keep in cognovis/library-core; strong marketplace candidate | core |
| `meta/skills/claude-md-pruner/SKILL.md` | skill | ORIGINAL | skill (review CLAUDE.md for outdated instructions) | skill — correct | Keep in cognovis/library-core | domain |
| `meta/skills/entropy-scan/SKILL.md` | skill | ORIGINAL | skill (scan agent harness for invariant violations) | skill — correct | Keep in cognovis/library-core | domain |
| `meta/skills/hook-creator/SKILL.md` | skill | ORIGINAL | skill (create/configure Claude Code hooks) | skill — correct | Keep in cognovis/library-core; marketplace candidate | domain |
| `meta/skills/nbj-audit/SKILL.md` | skill | ORIGINAL | skill (audit codebase against Nate's 12 NBJ primitives) | skill — correct; ADOPTED pattern (NBJ from Nate's Newsletter) — ensure attribution | Confirm license with Nate; if permissive → keep; if proprietary → convert to marketplace reference | domain |
| `meta/skills/plugin-management/SKILL.md` | skill | ORIGINAL | skill (create/test/distribute Claude Code plugins) | skill — correct | Keep in cognovis/library-core; marketplace candidate | domain |
| `meta/skills/skill-auditor/SKILL.md` | skill | ORIGINAL | skill (audit skills for quality) | skill — correct | Keep in cognovis/library-core | domain |
| `meta/skills/sync-standards/SKILL.md` | skill | ORIGINAL | skill (sync global standards to project) | skill — correct | Keep in cognovis/library-core | domain |
| `meta/skills/system-prompt-audit/SKILL.md` | skill | ORIGINAL | skill (audit Anthropic system prompt changes) | skill — correct | Keep in cognovis/library-core | domain |
| `meta/skills/token-cost/SKILL.md` | skill | ORIGINAL | skill (measure static context token overhead) | skill — correct | Keep in cognovis/library-core | domain |
| `meta/skills/vision-review/SKILL.md` | skill | ORIGINAL | skill (architecture trinity enforcer reactive role) | skill — correct; uses `trinity_role: enforcer-reactive` — part of architecture-trinity plugin | Keep in meta/plugins/architecture-trinity | domain |

### Agents

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `meta/agents/convention-reviewer.md` | agent | ORIGINAL | agent (convention review, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `meta/agents/learning-extractor.md` | agent | ORIGINAL | agent (extract learnings from sessions, isolated) | agent — correct | Keep in cognovis/library-core | domain |
| `meta/agents/skill-auditor.md` | agent | ORIGINAL | agent (skill auditing, isolated context) | agent — correct | Keep in cognovis/library-core | domain |

### Plugins

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `meta/plugins/architecture-trinity/` | plugin | ORIGINAL | plugin (bundles architecture scout agent + related skills) | plugin — correct | Keep in cognovis/library-core; marketplace candidate | domain |
| `meta/plugins/workflow/` | plugin | ORIGINAL | plugin (workflow bundle) | plugin — correct | Keep in cognovis/library-core | domain |
| `meta/plugins/bead-orchestrator.toml` | miscfile | ORIGINAL | Codex agent bridge file (misplaced in plugins/) | should be in dev-tools/codex-agents/ | Move to dev-tools/codex-agents/ | domain |
| `meta/plugins/session-close.toml` | miscfile | ORIGINAL | Codex agent bridge file (misplaced in plugins/) | should be in dev-tools/codex-agents/ | Move to dev-tools/codex-agents/ (already synced to ~/.codex/agents/) | domain |
| `meta/plugins/wave-orchestrator.toml` | miscfile | ORIGINAL | Codex agent bridge file (misplaced in plugins/) | should be in dev-tools/codex-agents/ | Move to dev-tools/codex-agents/ (already synced to ~/.codex/agents/) | domain |

---

## Section 9: .claude/skills (in claude-code-plugins — gitignored, local install copies)

These are **gitignored local install copies** (`.claude/*` is in `.gitignore`; `.claude/skills/` has no git exception). They are NOT the canonical source. The canonical sources are in the category directories.

| Installed Name | Canonical Source | Origin | Intent | Correct Type | Migration Action | Tier |
|---------------|-----------------|--------|--------|-------------|-----------------|------|
| `agent-forge` | `meta/skills/agent-forge/` | ORIGINAL | skill | skill | Remove local copy; install from cognovis/library-core via /library use | core |
| `bash-best-practices` | Not in category dirs — unique to .claude/skills | ORIGINAL | skill (bash scripting guide) | skill | Add to meta/skills/ as canonical source; commit and track | domain |
| `binary-explorer` | `dev-tools/skills/binary-explorer/` | ORIGINAL | skill | skill | Remove local copy; install from cognovis/library-core | domain |
| `command-creator` | Not in category dirs — unique to .claude/skills | ORIGINAL | skill (guide for creating commands) | skill | Add to meta/skills/ as canonical source; commit and track | domain |
| `git-worktree-tools` | Not in category dirs — unique to .claude/skills | ORIGINAL | skill (git worktree lifecycle) | skill | Add to dev-tools/skills/ or core/skills/ as canonical source | domain |
| `hook-creator` | `meta/skills/hook-creator/` | ORIGINAL | skill | skill | Remove local copy; install from cognovis/library-core | domain |
| `marketplace-manager` | Not in category dirs — unique to .claude/skills | ORIGINAL | skill (plugin marketplace management) | skill | Add to meta/skills/ as canonical source | domain |
| `playwright-mcp-usage` | Not in category dirs | ORIGINAL | skill (Playwright MCP usage guide) | skill — consider merging with `dev-tools/skills/playwright-cli/` | Evaluate merge with playwright-cli skill; if separate — add to dev-tools/skills/ | domain |
| `playwright-usage` | Not in category dirs | ORIGINAL | skill (Playwright MCP usage — older version) | skill — DUPLICATE of playwright-mcp-usage | Merge into one canonical skill; remove duplicate | domain |
| `plugin-creator` | Not in category dirs | ORIGINAL | skill (guide for creating plugins) | skill | Add to meta/skills/ as canonical source | domain |
| `plugin-tester` | Not in category dirs | ORIGINAL | skill (test plugins in local dev) | skill | Add to meta/skills/ as canonical source | domain |
| `powershell-pragmatic` | Not in category dirs | ORIGINAL | skill (PowerShell best practices) | skill | Add to dev-tools/skills/ as canonical source | domain |
| `skill-tester` | Not in category dirs | ORIGINAL | skill (test skills in local dev) | skill | Add to meta/skills/ as canonical source | domain |
| `slash-command-creator` | Not in category dirs | ORIGINAL | skill (guide for creating slash commands) | skill — DUPLICATE functionality with `command-creator` | Consolidate into command-creator; remove slash-command-creator | domain |

---

## Section 9b: ~/.claude/skills/open-brain/people-query (Globally Installed)

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `~/.claude/skills/open-brain/people-query/SKILL.md` | skill | ORIGINAL | skill (query open-brain memory for people/contact context; auto-triggered on social/contact queries) | skill — correct | Add canonical source to core/skills/ or meta/skills/; WRAPPER around open-brain MCP | domain |

---

## Section 10: .claude/commands (in claude-code-plugins — git tracked)

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `.claude/commands/compact-reference.md` | command | ORIGINAL | command (user-explicit compact reference workflow) | command — correct (user deliberate action: choose which file to compact) | Keep in cognovis/library-core | domain |
| `.claude/commands/install-playwright.md` | command | ORIGINAL | command (user-explicit Playwright MCP setup) | command — correct (destructive system install requires user intent) | Keep in cognovis/library-core | domain |
| `.claude/commands/install-plugin.md` | command | ORIGINAL | command (user-explicit plugin install) | command — correct (user picks plugin + project) | Keep in cognovis/library-core | domain |

---

## Section 11: .claude/standards (in claude-code-plugins — git tracked)

| Path | Current Type | Origin | Intent | Correct Type | Migration Action | Tier |
|------|-------------|--------|--------|-------------|-----------------|------|
| `.claude/standards/dev-tools/execution-result-envelope.md` | standard | ORIGINAL | standard (enforces Execution-Result Envelope contract) | standard — correct | Migrate to `.agents/standards/execution-result-envelope.md` per CL-v56 | domain |
| `.claude/standards/dev-tools/python-default-bash-exception.md` | standard | ORIGINAL | standard (Python as default script language rule) | standard — correct | Migrate to `.agents/standards/python-default-bash-exception.md` per CL-v56 | domain |
| `.claude/standards/dev-tools/script-first-rule.md` | standard | ORIGINAL | standard (executable logic in scripts, not prompts) | standard — correct | Migrate to `.agents/standards/script-first-rule.md` per CL-v56 | domain |
| `.claude/standards/integrations/open-brain-http-client.md` | standard | ORIGINAL | standard (open-brain REST vs MCP decision reference) | standard — correct | Migrate to `.agents/standards/open-brain-http-client.md` per CL-v56 | domain |
| `.claude/standards/workflow/adr-location.md` | standard | ORIGINAL | standard (ADR canonical directory location) | standard — correct | Migrate to `.agents/standards/adr-location.md` per CL-v56 | domain |

---

## Section 12: ~/.claude/hooks (Installed Global Hooks)

These are hooks installed to the user's global Claude Code config. Each is classified by origin and whether it should ship with a library plugin.

| Hook File | Origin | Hook Event (from settings.json) | Intent | Correct Type | Migration Action | Tier |
|-----------|--------|--------------------------------|--------|-------------|-----------------|------|
| `anatomy-index.py` | ORIGINAL | PreToolUse(Read), PostToolUse | guardrail (file-read anatomy tracking) | guardrail — correct | Source: `dev-tools/hooks/anatomy-index.py`; ships with dev-tools plugin | domain |
| `auto-capture.py` | ORIGINAL | (PreToolUse — via dcg wrapper) | guardrail (captures tool calls for audit) | guardrail — correct | Unique to global install; add to core/hooks/ as canonical source | core |
| `bd-cache-invalidator.py` | ORIGINAL | PostToolUse(Bash) | guardrail (bd cache invalidation) | guardrail — correct | Source: `beads-workflow/hooks/bd-cache-invalidator.py`; ships with beads-workflow plugin | domain |
| `buglog.py` | ORIGINAL | PreToolUse(Bash), PostToolUse(Bash) | guardrail (bash command history for debugging) | guardrail — correct | Source: `dev-tools/hooks/buglog.py`; ships with dev-tools plugin | domain |
| `caveman-mode.py` | ORIGINAL | (context-dependent) | guardrail (debug/trace mode hook) | guardrail — correct | Unique to global install; add to dev-tools/hooks/ as canonical | domain |
| `context-monitor.sh` | ORIGINAL | (context-dependent) | guardrail (monitors context budget) | guardrail — correct | Unique to global install; add to dev-tools/hooks/ as canonical | domain |
| `enforce-boundaries.sh` | ORIGINAL | (PreToolUse) | guardrail (enforces tool boundary permissions) | guardrail — correct | Unique to global install; add to core/hooks/ as canonical | core |
| `event-log.py` | ORIGINAL | (PostToolUse) | guardrail (logs structured events to DB) | guardrail — correct | Related to `core/skills/event-log/`; add to core/hooks/ as canonical | core |
| `events_db.py` | ORIGINAL | (library — not a hook itself) | script (shared DB library for event-log) | script (implementation substrate) | Keep alongside event-log.py; not a primitive | core |
| `inject-subagent-standards.py` | ORIGINAL | TaskCreated | guardrail (injects standards into subagents at task creation) | guardrail — correct | Unique to global install; add to core/hooks/ as canonical | core |
| `instructions-loaded-logger.py` | ORIGINAL | (SessionStart) | guardrail (logs which instructions were loaded) | guardrail — correct | Unique to global install; add to meta/hooks/ as canonical | domain |
| `load-compaction-recovery.py` | ORIGINAL | (SessionStart) | guardrail (loads compaction recovery state) | guardrail — correct | Related to beads-workflow pre-compact; add to beads-workflow/hooks/ or core/hooks/ | domain |
| `log-adhoc-subagent-metrics.py` | ORIGINAL | SubagentStop | guardrail (logs ad-hoc subagent metrics) | guardrail — correct | Unique to global install; add to beads-workflow/hooks/ as canonical | domain |
| `pre-compact-state.py` | ORIGINAL | PreCompact | guardrail (saves state before compaction) | guardrail — correct | Source: `beads-workflow/hooks/pre-compact-state.py`; ships with beads-workflow plugin | domain |
| `prefetch_beads.py` / `prefetch-beads.py` | ORIGINAL | (SessionStart or PostToolUse) | guardrail (prefetches beads data) — DUPLICATE FILES (underscore vs hyphen) | guardrail — correct; duplicate needs resolution | Deduplicate to single file `prefetch-beads.py`; add to beads-workflow/hooks/ | domain |
| `read-before-edit.py` | ORIGINAL | PreToolUse(Edit, Write, MultiEdit) | guardrail (read-before-edit safety) | guardrail — correct | Source: `core/hooks/read-before-edit.py`; ships with core plugin | core |
| `session-context.py` | ORIGINAL | SessionStart | guardrail (injects beads session context) | guardrail — correct | Source: `beads-workflow/hooks/session-context.py`; ships with beads-workflow plugin | domain |
| `SessionStart-rules-loader.py` | ORIGINAL | SessionStart | guardrail (loads rules.d files) | guardrail — correct | Source: `core/hooks/rules-loader.py` (filename differs — naming inconsistency); ships with core plugin | core |
| `sync-claude-memories.sh` | ORIGINAL | (PostToolUse or Stop) | guardrail (syncs memories to external store) | guardrail — correct | Unique to global install; add to core/hooks/ as canonical | core |

---

## Section 13: ~/.claude/standards (Global User Standards — Legacy Path)

Per CL-v56, the canonical path is `.agents/standards/<name>.md`. These files are at the legacy `~/.claude/standards/<domain>/<name>.md` path and should migrate to `.agents/standards/` during CL-717.

All 63 standards here are classified as ORIGINAL (created by Malte for Cognovis/personal workflows). Below are grouped by domain. Note: `~/.claude/standards/README.md` is included in the count as a documentation file but not a standard artifact — the 62 actionable standards are detailed below.

### agents/ (3 standards)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/agents/debrief-contract.md` | ORIGINAL | standard (subagent debrief return contract) | standard — correct | `.agents/standards/debrief-contract.md` | core |
| `~/.claude/standards/agents/prompt-caching-strategy.md` | ORIGINAL | standard (prompt caching strategy for agent system prompts) | standard — correct | `.agents/standards/prompt-caching-strategy.md` | core |
| `~/.claude/standards/agents/tool-boundaries.md` | ORIGINAL | standard (allowed tools per agent role) | standard — correct | `.agents/standards/tool-boundaries.md` | core |

### dev-tools/ (8 standards)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/dev-tools/ast-grep-reference.md` | ORIGINAL | standard (ast-grep syntax reference) | standard — correct | `.agents/standards/ast-grep-reference.md` | domain |
| `~/.claude/standards/dev-tools/command-substitutions.md` | ORIGINAL | standard (shell command substitution patterns) | standard — correct | `.agents/standards/command-substitutions.md` | domain |
| `~/.claude/standards/dev-tools/dotclaude-access.md` | ORIGINAL | standard (.claude directory access rules) | standard — correct | `.agents/standards/dotclaude-access.md` | domain |
| `~/.claude/standards/dev-tools/hook-exit-codes.md` | ORIGINAL | standard (hook exit code semantics) | standard — correct | `.agents/standards/hook-exit-codes.md` | domain |
| `~/.claude/standards/dev-tools/hooks.md` | ORIGINAL | standard (hooks comprehensive reference) | standard — correct | `.agents/standards/hooks.md` | domain |
| `~/.claude/standards/dev-tools/rare-command-substitutions.md` | ORIGINAL | standard (rare shell command substitution edge cases) | standard — correct | `.agents/standards/rare-command-substitutions.md` | domain |
| `~/.claude/standards/dev-tools/subagent-standards.md` | ORIGINAL | standard (subagent communication standards) | standard — correct | `.agents/standards/subagent-standards.md` | domain |
| `~/.claude/standards/dev-tools/tool-standards.md` | ORIGINAL | standard (tool use standards for agents) | standard — correct | `.agents/standards/tool-standards.md` | domain |

### flet/ (2 standards)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/flet/accessibility.md` | ORIGINAL | standard (Flet accessibility guidelines) | standard — correct | `.agents/standards/flet-accessibility.md` | domain |
| `~/.claude/standards/flet/web-mode.md` | ORIGINAL | standard (Flet web mode patterns) | standard — correct | `.agents/standards/flet-web-mode.md` | domain |

### frontend/ (4 standards)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/frontend/frontend-dev-loop.md` | ORIGINAL | standard (frontend development loop) | standard — correct | `.agents/standards/frontend-dev-loop.md` | domain |
| `~/.claude/standards/frontend/nextjs-app-router.md` | ORIGINAL | standard (Next.js App Router patterns) | standard — correct | `.agents/standards/nextjs-app-router.md` | domain |
| `~/.claude/standards/frontend/sse-first.md` | ORIGINAL | standard (SSE-first streaming patterns) | standard — correct | `.agents/standards/sse-first.md` | domain |
| `~/.claude/standards/frontend/view-impact-check.md` | ORIGINAL | standard (view impact assessment checklist) | standard — correct | `.agents/standards/view-impact-check.md` | domain |

### git/ (1 standard)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/git/conventional-commits.md` | ORIGINAL | standard (conventional commit message format) | standard — correct | `.agents/standards/conventional-commits.md` | core |

### healthcare/ (2 standards)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/healthcare/clinical-ux-style-guide.md` | ORIGINAL | standard (clinical UX style guidelines) | standard — correct | `.agents/standards/clinical-ux-style-guide.md` | project (mira) |
| `~/.claude/standards/healthcare/control-areas.md` | ORIGINAL | standard (healthcare control areas classification) | standard — correct | `.agents/standards/healthcare-control-areas.md` | project (mira) |

### powershell/ (1 standard)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/powershell/style.md` | ORIGINAL | standard (PowerShell style guide) | standard — correct | `.agents/standards/powershell-style.md` | domain |

### project/ (4 standards)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/project/centralized-config.md` | ORIGINAL | standard (centralized config patterns) | standard — correct | `.agents/standards/centralized-config.md` | domain |
| `~/.claude/standards/project/launchd-patterns.md` | ORIGINAL | standard (macOS launchd service patterns) | standard — correct | `.agents/standards/launchd-patterns.md` | domain |
| `~/.claude/standards/project/no-mock-data.md` | ORIGINAL | standard (no mock data in production) | standard — correct | `.agents/standards/no-mock-data.md` | domain |
| `~/.claude/standards/project/team-workflow.md` | ORIGINAL | standard (team collaboration workflow) | standard — correct | `.agents/standards/team-workflow.md` | domain |

### python/ (6 standards)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/python/cli-patterns.md` | ORIGINAL | standard (Python CLI patterns) | standard — correct | `.agents/standards/python-cli-patterns.md` | domain |
| `~/.claude/standards/python/dependency-injection.md` | ORIGINAL | standard (Python DI patterns for testable system calls) | standard — correct | `.agents/standards/python-dependency-injection.md` | domain |
| `~/.claude/standards/python/python314-patterns.md` | ORIGINAL | standard (Python 3.14 best practices) | standard — correct | `.agents/standards/python314-patterns.md` | domain |
| `~/.claude/standards/python/security-defaults.md` | ORIGINAL | standard (Python security defaults) | standard — correct | `.agents/standards/python-security-defaults.md` | domain |
| `~/.claude/standards/python/style.md` | ORIGINAL | standard (Python coding style) | standard — correct | `.agents/standards/python-style.md` | domain |
| `~/.claude/standards/python/third-party-sdk-compat.md` | ORIGINAL | standard (known 3rd-party SDK incompatibilities) | standard — correct | `.agents/standards/python-third-party-sdk-compat.md` | domain |

### release/ (1 standard)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/release/changelog.md` | ORIGINAL | standard (changelog format and conventions) | standard — correct | `.agents/standards/release-changelog.md` | domain |

### security/ (1 standard)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/security/content-isolation.md` | ORIGINAL | standard (content isolation for untrusted external content) | standard — correct | `.agents/standards/content-isolation.md` | core |

### skills/ (4 standards)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/skills/development.md` | ORIGINAL | standard (skill development patterns) | standard — correct | `.agents/standards/skill-development.md` | domain |
| `~/.claude/standards/skills/quality.md` | ORIGINAL | standard (skill quality checklist) | standard — correct | `.agents/standards/skill-quality.md` | domain |
| `~/.claude/standards/skills/token-budget-tiers.md` | ORIGINAL | standard (token budget tier guidance) | standard — correct | `.agents/standards/token-budget-tiers.md` | domain |
| `~/.claude/standards/skills/upstream-watchdog.md` | ORIGINAL | standard (upstream dependency watchdog patterns) | standard — correct | `.agents/standards/upstream-watchdog.md` | domain |

### workflow/ (24 standards)

All workflow standards are ORIGINAL, type=standard, correct type. Migration target: `.agents/standards/<name>.md`. Tier: domain (except noted).

| File | Description | Tier |
|------|-------------|------|
| `agent-patterns.md` | Agent orchestration patterns | domain |
| `agent-quality-gates.md` | Agent quality gate checklist | domain |
| `agent-session-capture.md` | Session capture/summary contract | domain |
| `bead-spec.md` | Bead specification format | domain |
| `code-review.md` | Universal code review patterns | domain |
| `definition-of-done.md` | DoD checklist | domain |
| `english-only.md` | Source code must be English | core |
| `etl-development.md` | ETL development patterns | domain |
| `factory-ready.md` | Factory-ready spec quality gate | domain |
| `generalization-notes.md` | Notes on generalizing project-specific code | domain |
| `git-best-practices.md` | Git workflow best practices | domain |
| `no-emoji.md` | No emoji in agent output | core |
| `planning-personas.md` | Planning persona definitions | domain |
| `pragmatic-development.md` | Pragmatic dev principles | domain |
| `production-feedback-example.md` | Production feedback example template | domain |
| `production-feedback.md` | Production feedback process | domain |
| `scale-adaptive.md` | Scale-adaptive development | domain |
| `systematic-debugging.md` | Systematic debugging methodology | domain |
| `tdd-discipline.md` | TDD RED-GREEN-REFACTOR discipline | domain |
| `test-quality.md` | Test quality checklist | domain |
| `uat-config-schema.md` | UAT configuration schema | domain |
| `verification-discipline.md` | Verification discipline patterns | domain |
| `workflow-guide.md` | Workflow guide reference | domain |
| `workflow-phases.md` | Workflow phases specification | domain |

### writing/ (1 standard)

| Path | Origin | Intent | Correct Type | Migration Target | Tier |
|------|--------|--------|-------------|-----------------|------|
| `~/.claude/standards/writing/brand-usage.md` | ORIGINAL | standard (Cognovis brand usage guidelines) | standard — correct | `.agents/standards/brand-usage.md` | domain |

---

## Section 14: ~/.codex/agents (Installed Codex Agent Bridges)

| Path | Origin | Source of Truth | Correct Type | Notes | Tier |
|------|--------|----------------|-------------|-------|------|
| `~/.codex/agents/bead-orchestrator.toml` | ORIGINAL | `dev-tools/codex-agents/bead-orchestrator.toml` (synced from `beads-workflow/agents/bead-orchestrator.md`) | agent — correct | Installed copy; track drift vs Claude source | domain |
| `~/.codex/agents/session-close.toml` | ORIGINAL | `dev-tools/codex-agents/session-close.toml` (synced from `core/agents/session-close.md`) | agent — correct | Installed copy; track drift vs Claude source | core |
| `~/.codex/agents/wave-orchestrator.toml` | ORIGINAL | `dev-tools/codex-agents/wave-orchestrator.toml` (synced from `beads-workflow/agents/wave-orchestrator.md`) | agent — correct | Installed copy; track drift vs Claude source | domain |

---

## Section 15: content repos (cognovis/library-core, sussdorff/library-core)

Both repos are not cloned locally and are presumed empty pending CL-1rr (library migration bead). No artifacts to classify at this time.

---

## Summary: Marketplace Candidates

These artifacts have broad generalizability and would benefit from marketplace publication:

| Artifact | Path | Reason |
|----------|------|--------|
| `agent-forge` | `meta/skills/agent-forge/SKILL.md` | Universal agent-creation guide; useful for any Claude Code user |
| `hook-creator` | `meta/skills/hook-creator/SKILL.md` | Universal hook creation guide |
| `plugin-management` | `meta/skills/plugin-management/SKILL.md` | Universal plugin authoring guide |
| `project-context` | `dev-tools/skills/project-context/SKILL.md` | Universal project constitution generator |
| `binary-explorer` | `dev-tools/skills/binary-explorer/SKILL.md` | Universal reverse-engineering skill |
| `architecture-trinity` | `meta/plugins/architecture-trinity/` | Plugin bundle; strong architectural governance use case |
| `collmex-cli` | `business/skills/collmex-cli/SKILL.md` | Collmex ERP niche marketplace |
| `mail-send` | `business/skills/mail-send/SKILL.md` | macOS mail automation community |
| `op-credentials` | `business/skills/op-credentials/SKILL.md` | 1Password CLI automation; broad DevOps community |

---

## Summary: Migration Plan by Category

### PERSONAL artifacts — move to sussdorff/library-core

Once CL-1rr creates the `sussdorff/library-core` repo:

| Artifact | Current Path |
|----------|-------------|
| ai-readiness | business/skills/ |
| amazon | business/skills/ |
| career-check | business/skills/ |
| google-invoice | business/skills/ |
| mm-cli | business/skills/ |
| linkedin | content/skills/ |
| transcribe | content/skills/ |
| hetzner-cloud | infra/skills/ |
| home-infra | infra/skills/ |
| local-vm | infra/skills/ |
| paperless-cli | infra/skills/ |
| piler-cli | infra/skills/ |
| home (agent) | infra/agents/ |

### ORIGINAL, ORIGINAL — keep in cognovis/library-core

All beads-workflow, core, dev-tools, meta artifacts not marked PERSONAL stay in `cognovis/library-core`.

### PROJECT — remain in cognovis/library-core, scoped to mira project

| Artifact | Path |
|----------|------|
| billing-reviewer | medical/skills/ |
| mira-aidbox | medical/skills/ |
| compliance-reviewer | medical/agents/ |
| human-factors-reviewer | medical/agents/ |
| angebotserstellung | business/skills/ |
| healthcare/* standards | ~/.claude/standards/healthcare/ |

### Standards — migrate legacy path to .agents/standards/

Per CL-v56 canonical path convention, all standards under `~/.claude/standards/` should migrate to `.agents/standards/<name>.md` during CL-717. The `claude-code-plugins/.claude/standards/` entries should also migrate.

### Orphaned .claude/skills entries — add canonical sources

These skills exist only in the gitignored `.claude/skills/` directory and need canonical sources added to the category dirs:

| Skill | Action |
|-------|--------|
| bash-best-practices | Add to `meta/skills/bash-best-practices/` |
| command-creator | Add to `meta/skills/command-creator/` |
| git-worktree-tools | Add to `dev-tools/skills/git-worktree-tools/` |
| marketplace-manager | Add to `meta/skills/marketplace-manager/` |
| playwright-mcp-usage | Merge with `dev-tools/skills/playwright-cli/` or add as separate |
| playwright-usage | Merge with playwright-mcp-usage (duplicate) |
| plugin-creator | Add to `meta/skills/plugin-creator/` |
| plugin-tester | Add to `meta/skills/plugin-tester/` |
| powershell-pragmatic | Add to `dev-tools/skills/powershell-pragmatic/` |
| skill-tester | Add to `meta/skills/skill-tester/` |
| slash-command-creator | Merge with command-creator (duplicate semantics) |

### Hooks — add missing canonical sources

Several installed global hooks have no corresponding source in the category directories:

| Hook | Action |
|------|--------|
| auto-capture.py | Add to core/hooks/ |
| caveman-mode.py | Add to dev-tools/hooks/ |
| context-monitor.sh | Add to dev-tools/hooks/ |
| enforce-boundaries.sh | Add to core/hooks/ |
| event-log.py | Add to core/hooks/ |
| inject-subagent-standards.py | Add to core/hooks/ |
| instructions-loaded-logger.py | Add to meta/hooks/ (new dir) |
| load-compaction-recovery.py | Add to beads-workflow/hooks/ or core/hooks/ |
| log-adhoc-subagent-metrics.py | Add to beads-workflow/hooks/ |
| sync-claude-memories.sh | Add to core/hooks/ |

### Codex TOML files — move from meta/plugins/ to dev-tools/codex-agents/

| File | Current Location | Target Location |
|------|-----------------|----------------|
| bead-orchestrator.toml | meta/plugins/ | dev-tools/codex-agents/ (already exists there) — remove from plugins/ |
| session-close.toml | meta/plugins/ | dev-tools/codex-agents/ (already exists there) — remove from plugins/ |
| wave-orchestrator.toml | meta/plugins/ | dev-tools/codex-agents/ (already exists there) — remove from plugins/ |

---

## Provenance Fields Per Artifact Group

| Group | Source URL | License | Copy Mode | Last-Verified SHA |
|-------|-----------|---------|-----------|------------------|
| claude-code-plugins (all ORIGINAL) | https://github.com/cognovis/claude-code-plugins | Private | original | `79148b1` (2026-04-30) |
| ~/.claude/standards/ (all ORIGINAL) | https://github.com/malte-sussdorff/.claude | Private | original | (managed via claude-config-handler) |
| ~/.codex/agents/ (TOML bridges) | https://github.com/cognovis/claude-code-plugins | Private | translated/adapted from Claude .md sources | `79148b1` (2026-04-30) |
| hook-creator references disler | https://github.com/disler/claude-code-hooks-mastery | MIT (community examples, linked only, not copied) | reference link only | n/a |
| nbj-audit references NBJ framework | https://github.com/disler (Nate's Newsletter) | To be confirmed | framework interpretation — not direct copy | n/a |
| cognovis/library-core | Not yet created | Private | target repo | n/a |
| sussdorff/library-core | Not yet created | Private | target repo | n/a |

---

## Cross-References

- `docs/PRIMITIVES.md` — taxonomy source of truth used for all Intent and Correct-Type classifications
- `docs/policy/name-collision.md` — Migration Action column references these path rules (canonical/bridge symlink convention)
- `docs/audit/mcp-servers.md` (CL-p91) — MCP server audit, excluded from this document to avoid duplication
- `docs/audit/skills-origin.json` — Machine-readable version of this audit (same data, JSON format)
- CL-v56 (closed) — Standards loader contract; canonical path is `.agents/standards/<name>.md`
- CL-1rr — Library migration bead that will create the content repos
- CL-717 — Standards path migration (legacy `~/.claude/standards/` → `.agents/standards/`)
