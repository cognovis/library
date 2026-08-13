# Rigorous Repository Cleanup Plan (2026-08)

> Premise: the only things this repository must serve today are
> (1) the `library` command (`scripts/library.py` + `bin/library`),
> (2) the `cld` / `cdx` launchers as fast entry points,
> (3) the current library model: `library.yaml` + `.library.lock` at the state
>     of ADR-0010 / ADR-0011, with `docs/PRIMITIVES.md` and the current ADRs.
>
> Everything else must answer one question: **does this accelerate delivery of
> the above, today?** If the answer is "it did once" or "it might again", the
> default verdict is REMOVE — git history is the archive, we never delete
> knowledge, only working-tree presence.

Verdicts used below:

- **REMOVE** — delete from working tree in this cleanup (history keeps it).
- **KEEP** — has a current, demonstrated consumer.
- **DECIDE** — needs one explicit user decision; the plan names the decision.
- **FIX** — keep, but stale content must be corrected as part of cleanup.

---

## Phase 0 — Safety net (before anything is deleted)

1. `git tag pre-cleanup-2026-08` on current `main` and push the tag.
2. `bd export -o /tmp/beads-pre-cleanup.jsonl` snapshot (outside the repo).
3. Every phase below lands as its own branch + merge, so any category can be
   reverted in isolation.
4. CI (`provider-contract.yml`) must be green after every phase — tests are
   pruned together with the feature they cover, never before, never orphaned.

---

## Phase 1 — Mechanical junk (no decision needed)

Untracked runtime droppings in the repo root. Delete; all are ignored or
should be:

| Item | Verdict | Reason |
|---|---|---|
| `.beads.gate.lock`, `.library.lock.lock`, `.library.lock.workspace-lock`, `.session-close.lock`, `.wave-orchestrator.lock` | REMOVE | Stale lock droppings from past runs |
| `.session-close-state.json`, `.worktree-handoff.json` | REMOVE | Transient orchestrator IPC, already gitignored |
| `metrics.db` (0 bytes) | REMOVE | Empty, `*.db` is ignored |
| `.pytest_cache/`, `.ruff_cache/`, `**/__pycache__/` | REMOVE | Tool caches (bulk of the 11 MB under `tests/`) |
| `.antigravitycli/`, `.context/`, `.cursor/` | REMOVE | Harness-private session tracking, gitignored |
| `.intake/` (entire directory) | REMOVE | Session transcripts, review packets, draft bodies from past intake runs. All consumed. Ignored anyway |
| `.session-close-state.json.owned-manifest` | FIX | This one is **tracked** and 0 bytes — untrack and add to `.gitignore` |

---

## Phase 2 — Dead scripts and stale install paths

`scripts/` holds 30 entries; `library.py` and its `lib/` + `checks/` are the
core. The rest, one by one:

| Script | Verdict | Question answered |
|---|---|---|
| `scripts/cdx` | REMOVE | April-era 6.5 KB predecessor of `bin/cdx` (25 KB, current). Nothing legitimate references it — except the stale justfile recipe below |
| `scripts/migrate_missing.py`, `scripts/migrate_originals.py`, `scripts/migrate-lockfile.py`, `scripts/register-bootstrap-receipts.py` | REMOVE | One-shot migration scripts, zero references from bin/tests/catalog/CI. Their migrations ran |
| `scripts/validate-marketplace-agents.sh` | REMOVE | Validates a marketplace layout ADR-0002 abolished |
| `scripts/update-consumers.py` + `consumer-projects.yml` + `docs/consumer-updater.md` | DECIDE | Doc itself says "transitional, closed to expansion; ADR-0010 replaces it after Workspace rollout". Decision: is Workspace rollout far enough to retire the legacy path now? If yes → REMOVE all three + `tests/test_update_consumers.py` + `tests/test_consumer_updater_references.py` |
| `scripts/standards-loader.sh` | FIX | Open bead CL-yt4 already says: retire superseded ops. Execute that bead as part of this phase |
| `scripts/audit-open-brain-mcp.py` | DECIDE | Open-brain MCP audit — is this a library-platform concern or does it belong in the open-brain repo? Default: move or REMOVE |
| `scripts/agent-fleet-audit.py`, `scripts/check-coverage.py`, `scripts/workflow-token-report.py`, `scripts/filter-codex-jsonl.py`, `scripts/cdx-quick-cursor-dispatch.py`, `scripts/compact-bead-context.py`, `scripts/cdx-bead-workflow.py`, `scripts/coordinator_callback.py`, `scripts/worktree-overlays.py` | KEEP/verify | Each has exactly one live consumer (launchers or tests). Verify the consumer is itself surviving cleanup; anything whose only consumer is a removed test goes with it |
| `scripts/build-agent.py`, `scripts/compose-agent.py`, `scripts/install-hook.py`, `scripts/install-mcp.py`, `scripts/sync_project_tooling.py`, `scripts/validate-library.py`, `scripts/validate-gascity-export.py` | KEEP | Installer/validator surface of the library command (gascity validator: see Gas City decision, Phase 6) |

**Install-path consolidation (FIX):** there are three parallel install stories —
`install.sh`, `scripts/install-bin.sh`, and `justfile` recipes. Keep exactly
one documented path (`scripts/install-bin.sh` per ADR-0002 Decision 2 +
`install.sh` if it still does distinct bootstrap work — verify, else fold).
The `justfile` is badly stale: it drives `/library` through
`claude --dangerously-skip-permissions --model opus` (the pre-CLI era) and
`install-cdx` copies the dead `scripts/cdx`. Rewrite the justfile to call the
real CLI, or delete it entirely if nobody runs `just`.

**Root `SKILL.md` + `cookbook/` (DECIDE):** this is the `/library` skill and its
15 cookbook pages — the LLM-facing wrapper around the CLI. Per the
"Python scripts over cookbook" principle, the CLI is the product and the skill
is a thin router. Decision: shrink `SKILL.md` + cookbook to a minimal "call the
CLI" surface, delete cookbook pages that merely paraphrase `library --help`.

---

## Phase 3 — Documentation: current state only, history lives in git

Rule applied: a doc survives only if it describes the **current** system. ADRs
are the one sanctioned history format — but even there, superseded ADRs get a
one-line pointer to their successor, not continued maintenance.

| Doc | Verdict | Reason |
|---|---|---|
| `docs/PRIMITIVES.md`, `docs/ARCHITECTURE.md`, `docs/lockfile-format.md`, `docs/policy/name-collision.md`, `docs/harness-baseline.md`, `docs/project-tooling.md`, `docs/schema/*` | KEEP + FIX | Core reference. FIX: purge historical asides ("used to be called…"), renumber primitives (14 is missing), verify every statement against ADR-0010/0011 |
| `docs/primitives/*.md` | KEEP + FIX | Same pass per primitive. `package.md` ("retired concept") shrinks to a 5-line tombstone or folds into PRIMITIVES.md — it exists only to answer "why is there no package type", which one paragraph covers |
| `docs/adr/` — accepted ADRs | KEEP | 0002, 0003, 0004, 0005, 0006, 0009, 0010, 0011, plane-vocabulary, information-model, per-harness-agent-base |
| `docs/adr/` — superseded (0001, 0007, 0008) | KEEP, frozen | Add explicit "superseded by X" header line where missing; never edit again. Add a tiny `docs/adr/README.md` index with status column so nobody has to open 13 files to find the current ones |
| `docs/audit/*` (11 files: retirement audits, canaries, MCP migration debt) | REMOVE | Point-in-time evidence for completed retirements. The beads and git history carry the evidence. Exception: check `skills-origin.json` for live consumers first |
| `docs/research/*` (11 files) | REMOVE | Pre-decision research inputs; the decisions landed in ADRs. Exception: `pi-workflow-executor-evidence.json` has a consuming test (`test_pi_workflow_executor_evidence.py`) — remove test + evidence together, or keep both, but decide once |
| `docs/reports/legacy-projection-inventory.*` | REMOVE when consumed | Coupled to `test_legacy_projection_*` tests — same verdict as the legacy-projection code path |
| `docs/migration/workspace-legacy-inventory.md` | REMOVE when ADR-0010 rollout done | Same trigger as the consumer-updater decision |
| `docs/gc-pilot/RUNBOOK.md` | DECIDE | Gas City decision (Phase 6) |
| `docs/cognovis-tools-retirement.md` | REMOVE | Retirement is executed; provenance lives on CL-tbsz and in history |
| `docs/dolt-auth-fix.md` | REMOVE | Operational note that belongs in the `dolt` skill, if anywhere |
| `docs/chezmoi-externals.md` | REMOVE | Decided 2026-08-12: chezmoi is no longer part of the deployment story. Remove doc plus the chezmoi path in `scripts/lib/manager_inventory.py` and any tests covering it, in one commit |
| `docs/managed-worker-stack.md` | KEEP/verify | Verify it describes the current worker stack; prune or fix like the other core docs |
| `docs/workspaces/library-authoring.md` + `workspaces/` | KEEP | Current Workspace v2 authoring surface |
| `plans/CL-yum0.md` | REMOVE when CL-yum0 closes | Plans are transient; this file's content belongs in the bead |
| `images/` (120 KB) | REMOVE | Zero references from README or docs |
| `CHANGELOG.md` (119 KB) | KEEP | Generated release history, append-only |
| `prime/`, `templates/`, `guardrails/`, `standards/` | KEEP + verify | Small, each has a live consumer. `prime/PRIME.md`: CL-seho explicitly wants the bd-prime shadowing removed — execute that bead, which may empty `prime/` |

---

## Phase 4 — library.yaml condensation (agent-executed, user signs off batches)

Current catalog volume: 110 skills, 61 standards, 40 agents, 9 scripts,
8 model-standards, 7 MCP servers, 5 workflows, 9 pi_extensions + 6
pi_profiles, plus prompts/guardrails/agent_bases/just_modules/
runtime_configs/workspaces — 287 entries in a 196 KB file.

Execution split — the agent does the work, the user only decides:

**Mechanical (follows from decisions already taken, no sign-off per entry):**

1. `pi_extensions` + `pi_profiles` entries: re-point at their new canonical
   home in `../cognovis-pi` (Phase 6.1 — Library keeps the sync contract,
   sources move).
2. Remove entries whose subject is gone: Gas City projections, `clw`
   workflow entries, the `cognovis-tools` MCP server entry and its
   capability bindings, chezmoi-related tooling.
3. `prompts` (4 entries): CL-jzu already says promote category:standard
   prompts to `library.standards` — execute, then drop the section if empty.
4. Structural conformance pass against ADR-0010/0011 +
   `library-yaml-information-model.md`: any field or section those don't
   sanction is removed.

**Judgment calls (batched for user sign-off, evidence attached):**

5. For skills/agents/standards, build a keep/remove candidate list from
   evidence, not taste: `.library.lock` receipts, Workspace membership,
   `requires:`/`requires_standards:` reverse references, and install status
   across the fleet. Entries nothing installs, no Workspace names, and no
   other entry requires are removal candidates. Present per section
   (skills, agents, standards) as three AskUserQuestion batches; user
   confirms or rescues individual entries.

Rails for every slice:

- Hand-edit only — **never** `catalog sync --write` (regenerates the whole
  file and drops remote-only source entries).
- `scripts/validate-library.py` + `pytest tests/test_library_yaml_*` after
  every slice.
- After the catalog shrinks, one `library sync` so the tracked 122 KB
  `.library.lock` reflects the condensed state; stale lock entries for
  removed primitives are drift.
- Schema serialization rule (AGENTS.md): the whole condensation runs under a
  single bead so no parallel schema bead touches the same sections.

---

## Phase 5 — Tests: every removal takes its tests along

133 test files. Not reviewed one-by-one here; instead three enforced rules:

1. **Coupled removal:** each Phase 2/3/6 removal names its test files
   (`test_update_consumers.py`, `test_personal_migration.py`,
   `test_legacy_projection_*.py`, `test_pi_workflow_executor_evidence.py`,
   provider tests for providers we drop, …) and removes them in the same
   commit. No orphaned tests, no orphaned features kept alive by tests.
2. **Post-cleanup audit:** after Phases 2–4, grep tests for references to
   removed files/entries (CL-1h0p "coverage tests reflect current catalog
   contracts" is exactly this — execute it as the closing step).
3. CI green after every phase; the provider-contract workflow stays untouched.

---

## Phase 6 — Strategic decisions (DECIDED 2026-08-12)

1. **Pi/Hermes cutover — DECIDED: lives in `../cognovis-pi`.** The Pi
   migration happens in the cognovis-pi repo; the canonical (master) Pi files
   move there, and this platform keeps only the sync/projection
   responsibility (Pi assets remain Library-synced primitives per ADR-0011).
   Consequences here: extract `.agents/pi/` extension sources to cognovis-pi
   as their canonical home; re-file the CL-yism.* execution beads in
   cognovis-pi (cross-repo false-close rule: beads live where the fix target
   lives); keep in this repo only beads whose deliverable is the Library
   sync/projection contract for Pi assets. `docs/primitives/project-native-pi-bridge.md`
   stays (it documents the sync contract).
2. **Gas City — DECIDED: no longer pursued, clean up.** Close CL-dnna and
   CL-fxhb; remove `scripts/validate-gascity-export.py`, `docs/gc-pilot/`,
   `tests/test_gascity_export_metadata.py`; strip Gas City packability
   passages from PRIMITIVES.md/ADR references only where they describe
   pending work (accepted ADR text stays frozen as history).
3. **Launchers — DECIDED: only `cld` + `cdx` stay.** Remove `bin/agr`,
   `bin/cra`, `bin/clw`; close CL-sevk, CL-t3hk, CL-jixp as won't-do; remove
   `tests/test_cra_launcher_defaults.py`, `tests/test_clw_launcher.py` and
   the `workflow-launcher` agent surface this repo ships for clw; update
   AGENTS.md "Canonical Launchers" section and `scripts/install-bin.sh`.
4. **Stale non-core beads — DECIDED: close as superseded.** The seven CL-ast
   follow-ups (CL-141, CL-6r4, CL-gak, CL-hcc, CL-q78, CL-ayf, CL-bpt) and
   the side-features (CL-7hp, CL-8dn, CL-7hr, CL-cy6, CL-wzpd) close with a
   superseded rationale. Real needs get re-filed fresh against the
   post-cleanup state, in the repo where the fix target lives.

5. **Public beta (CL-it4h) — DECIDED: yes, stays a goal.** People have asked
   to look at the Library, so the public MIT-licensed beta remains a KEEP bead
   with real value. Consequence: README, `install.sh`, and the single
   consolidated install path (Phase 2) are polished *for an external reader*,
   not just internally. The cleanup itself is the best preparation for the
   beta — a stranger should see only the current system. `images/` stays
   REMOVE (unreferenced); the beta gets fresh screenshots if needed, not the
   old ones.
6. **chezmoi — DECIDED: no longer part of the story.** Remove
   `docs/chezmoi-externals.md` plus the chezmoi path in
   `scripts/lib/manager_inventory.py` and its test coverage together.

---

## Phase 7 — Bead triage (execute via `/workplan`)

After Phase 6 answers, run the `workplan` skill over the remaining backlog with
the single question you set: *"Welchen Mehrwert liefert dieser Bead für die
Beschleunigung der Umsetzung?"* Proposed default dispositions going in:

**KEEP (live defects / current contracts on the core):**
CL-14ob, CL-dyrk, CL-eqiq, CL-gzvu, CL-xjo7, CL-mp9f (launcher correctness);
CL-0blv, CL-92kh, CL-lvue, CL-lojw, CL-gx0x, CL-0yvv, CL-mywn, CL-eu21,
CL-yum0, CL-1les, CL-seho, CL-8wtc (library CLI/lock correctness);
CL-1h0p (closing audit); CL-fgss (Workspace v2 contract).

**FOLD into cleanup phases (they *are* cleanup):**
CL-yt4 (standards-loader), CL-um0 (end golden-prompt window — no references
left in `library.py`; verify and close), CL-7eg (one-line catalog fix),
CL-416 + CL-0qk (ADR-0002 Phase 3/4 drains), CL-jzu (prompts→standards
promotion), CL-us0k, CL-69l, CL-ljg (small CLI hygiene — keep only if they
still bite).

**Resolved by Phase 6 decisions:** CL-yism.* → re-file in cognovis-pi (keep
here only Library-sync-contract beads); CL-dnna, CL-fxhb → close (Gas City);
CL-sevk, CL-t3hk, CL-jixp → close (clw removed); seven CL-ast follow-ups and
CL-7hp, CL-8dn, CL-7hr, CL-cy6, CL-wzpd → close as superseded. CL-it4h
(public beta) is a confirmed KEEP — it is the audience the cleanup serves.

**Resolved 2026-08-12 — cognovis-tools is retired, no remaining use found:**
CL-crn2, CL-tpet, CL-elyk, CL-enim, CL-rx6z, and CL-2840 (typed-tools
migration / bead-grant exposure) close as obsolete — their target no longer
exists. `docs/cognovis-tools-retirement.md` still goes to REMOVE (Phase 3);
the retirement rationale lives on CL-tbsz and in these closes. Also sweep
launcher/config code for dead cognovis-tools references (grants, MCP
registration, capability bindings) and remove them with test coverage.

**Epics kept after value re-check:** CL-i9uj (context-budgeted cdx output —
directly accelerates cdx -b), CL-khyy (release workflow — keep while releases
continue).

**Auto-scrub:** every `[DISCOVERED]`/`[REFACTOR]` P3-4 bead older than the
subsystem it refers to gets re-checked against the post-cleanup tree; those
pointing at removed code close as obsolete.

---

## Execution order and gates

| Phase | Gate before merge |
|---|---|
| 0 Safety net | tag pushed, bead snapshot exists |
| 1 Junk | `git status` clean of droppings; nothing tracked was lost |
| 2 Scripts/install | CI green; `bin/cld`, `bin/cdx`, `library` smoke-run |
| 3 Docs | AGENTS.md "Where to look first" table still resolves; ADR index added |
| 4 Catalog | validator + yaml tests green; one bead owns the schema sections |
| 5 Tests | full `uv run --extra dev pytest` green |
| 6 Decisions | answered 2026-08-12 (see Phase 6); only CL-it4h + chezmoi open |
| 7 Beads | workplan receipts; closes carry rationale, no silent closes |

Phases 1–3 can start immediately. The Phase 6 decisions of 2026-08-12 already
unblock the Gas City, launcher, and Pi-related removals in Phases 2/3 and the
bulk closes in Phase 7.
