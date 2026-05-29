# MCP Migration Debt Audit — 2026-05-29

## Scope

- Audited installed skill and agent surfaces under `~/.agents/skills/` and `~/.claude/agents/`.
- This worktree can report on those installed files, but their owning source files are outside the writable roots of this run.
- Doctor wrapper: `scripts/check-mcp-migration-debt.sh` runs the audit in fail-on-A mode via `uv run --no-project python`.
- Top five remediation targets by A+B hit count: ~/.claude/agents/bead-orchestrator.md, ~/.claude/agents/quick-fix.md, ~/.claude/agents/wave-orchestrator.md, ~/.agents/skills/bead-reviewer/SKILL.md, ~/.agents/skills/beads/SKILL.md

## Summary

| File | Hits | A+B Hits | Classification | Notes |
|------|------|----------|----------------|-------|
| `~/.claude/agents/bead-orchestrator.md` | 97 | 90 | A | Explicit bead read recipe should route to the typed bead.show tool. |
| `~/.claude/agents/quick-fix.md` | 33 | 30 | A | Explicit bead close recipe should route to the typed bead.close tool. |
| `~/.claude/agents/wave-orchestrator.md` | 19 | 18 | A | Explicit bead read recipe should route to the typed bead.show tool. |
| `~/.agents/skills/bead-reviewer/SKILL.md` | 15 | 15 | A | Explicit bead read recipe should route to the typed bead.show tool. |
| `~/.agents/skills/beads/SKILL.md` | 9 | 8 | A | Explicit bead mutation recipe should route to the typed bead.update tool. |
| `~/.claude/agents/session-close.md` | 9 | 6 | A | Explicit bead list recipe should route to the typed bead.list tool. |
| `~/.agents/skills/session-close/SKILL.md` | 1 | 1 | A | Explicit bead list recipe should route to the typed bead.list tool. |
| `~/.agents/skills/wave-dispatch/SKILL.md` | 1 | 1 | A | Explicit bead read recipe should route to the typed bead.show tool. |

## Classification Key

- A = Must Migrate (typed tool exists, anti-pattern violation)
- B = Should Migrate (candidate for Phase 6 or `library.exec`)
- C = Can Migrate (contextual, low priority)
- D = No Migration (informational or prohibitive mention)

## Detailed Findings

### `~/.claude/agents/bead-orchestrator.md`

- Summary classification: **A**
- Total hits: **97**
- A+B hits: **90**

- L60 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `> **Anti-precedent rule:** `OPERATIONAL DEVIATION` notes from prior runs visible in `bd show``
- L256 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `bd show <id>`
- L271 [A] `bd create` → `mcp__cognovis-tools__bead.create`. Explicit bead creation recipe should route to the typed bead.create tool. Snippet: `1. Create child beads: `bd create --title="..." --type=task``
- L325 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `EFFORT=$(bd show <id> --json | jq -r '.metadata.effort // ""')`
- L326 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `TYPE=$(bd show <id> --json | jq -r '.type // ""')`
- L336 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `<bd show output>`
- L352 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --metadata='{"effort": "<estimated>"}'`
- L404 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `LIVE_NETWORK_JSON=$(bd show "<bead-id>" --json | uv run python "$LIVE_NETWORK_SCRIPT")`
- L453 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `bead_type='<type from bd show>',`
- L454 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `priority=<priority from bd show, default 2>,`
- L466 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: ``bd update <id> --append-notes="WARNING: routing.py unavailable, fell back to prose-rule interpretation. Risk: rule drift between prose and code."``
- L492 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: ``bd update <id> --append-notes="PAUL routing selected but no uat-config.yml found; Phase 13 cannot run until project UAT config exists."``
- L514 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: ``bd update <id> --append-notes="TIER_CONFIG_ERROR: config validation failed, unknown models: <names>"``
- L548 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `- `diff_loc_estimate` < 50; read from `metadata.diff_loc_estimate` via `bd show <id> --json` if available;`
- L608 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="BLOCKED: bead-reviewer helper missing at $COMPUTE_SHA. Run '/library use bead-reviewer' to install."`
- L623 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `BEAD_JSON=$(bd show <id> --json)`
- L657 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `OPEN_BLOCKERS=$(bd show <id> --json | python3 -c "`
- L674 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Bead-reviewer gate blocked dispatch: cached spec verdict=$EFFECTIVE_SPEC_VERDICT findings=$CACHED_FINDINGS. Fix the spec issues and re-run."`
- L682 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Bead-reviewer gate: spec clean but blocked by: $OPEN_BLOCKERS. Close blockers and re-run."`
- L695 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `FRESH_SPEC_VERDICT=$(bd show <id> --json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0].get('metadata',{}).get('review',{}).get('spec_verdict',''))")`
- L698 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `OPEN_BLOCKERS=$(bd show <id> --json | python3 -c "`
- L712 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Bead-reviewer gate: spec clean but blocked by: $OPEN_BLOCKERS. Close blockers and re-run."`
- L715 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `FINDINGS=$(bd show <id> --json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0].get('metadata',{}).get('review',{}).get('findings_summary',''))")`
- L718 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Bead-reviewer gate blocked dispatch: fresh spec verdict=$FRESH_SPEC_VERDICT findings=$FINDINGS. Fix the spec issues and re-run."`
- L825 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="BLOCKED: inject-standards runner missing"`
- L831 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="BLOCKED: context provider runner missing"`
- L858 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `( bd show <bead-id> --json > "$TMPDIR_P1/bd_show_json" 2>/dev/null ) &`
- L869 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="BLOCKED: inject-standards failed (exit=$INJECT_RC)"`
- L876 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="BLOCKED: context provider failed (exit=$CONTEXT_PROVIDER_RC)"`
- L891 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `SKILLS_REFERENCED=$(bd show <bead-id> 2>/dev/null | grep -oE '/[a-z][a-z0-9-]+' | sort -u)`
- L930 [C] `bd show` → `mcp__cognovis-tools__bead.show`. Contextual bead CLI mention; lower-priority migration. Snippet: `is also unavailable, extract paths manually from `bd show` output and mark confidence low.`
- L967 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead-id> --append-notes="Provenance logged: standards=[<path1>] skills=[<list>] adrs=[<list or none>] docs=[<list or none>]"`
- L979 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `bd show "<bead-id>" 2>/dev/null | python3 "$CHECK_SCRIPT" --stdin --quiet`
- L982 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `bd show "<bead-id>" 2>/dev/null | grep -qE 'cmux|wave-dispatch|wave-poll' \`
- L1046 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="BLOCKED: resource lock $_LR busy after ${LOCK_WAIT_TIMEOUT}s wait at Phase 1. Bead left in_progress; re-run when the holder releases."`
- L1052 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `[ -n "$BEAD_LOCK_FILE" ] && bd update <id> --append-notes="Resource lock acquired: $_LR at $BEAD_LOCK_FILE"`
- L1088 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Pre-mortem: level=<GREEN|YELLOW|RED>; technical=<...>; blast_radius=<...>; reversibility=<...>; data_integrity=<...>; security=<...>; mitigations=<...>; hardest_ak=<...>"`
- L1367 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `| anything else | ABORT with `bd update <id> --append-notes="ABORT: unknown adapter: <value>."` |`
- L1375 [D] `bd update` → `mcp__cognovis-tools__bead.update`. Informational or prohibitive mention; not teaching an invocation. Snippet: `| anything else | ABORT with `bd update <id> --append-notes="ABORT: unknown impl_model family: <value>. Fix route_decision before retrying."` | Fail loud, do not improvise |`
- L1385 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Phase 5 ABORT: codex binary not on PATH. ABORT_REASON: codex_binary_missing"`
- L1395 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Phase 5 ABORT: codex exec rejected AK1 flags. Update codex CLI. ABORT_REASON: ak1_flags_rejected"`
- L1413 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Phase 5 ABORT: live network preflight failed for $LIVE_TCP_ENDPOINT. ABORT_REASON: live_network_preflight_failed"`
- L1420 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Phase 5 ABORT: live network required but no TCP endpoint or project-specific live probe was available. ABORT_REASON: missing_live_network_probe"`
- L1434 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Phase 5 ABORT: codex dry-run failed (exit=$_PROBE_EXIT). ABORT_REASON: dry_run_failed"`
- L1461 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `{AK_LIST from bd show}`
- L1529 [A] `bd list` → `mcp__cognovis-tools__bead.list`. Explicit bead list recipe should route to the typed bead.list tool. Snippet: `2. **Existing bead fit check**: Search `bd search <keywords>`, `bd list --status=open --json`, and `bd list --status=in_progress --json` for same-repo open/in-progress beads with matching intent, release artifact, version bump, publish action, review path, or UAT target. If found, append to or update that bead.`
- L1529 [A] `bd search` → `mcp__cognovis-tools__bead.search`. Explicit bead search recipe should route to the typed bead.search tool. Snippet: `2. **Existing bead fit check**: Search `bd search <keywords>`, `bd list --status=open --json`, and `bd list --status=in_progress --json` for same-repo open/in-progress beads with matching intent, release artifact, version bump, publish action, review path, or UAT target. If found, append to or update that bead.`
- L1530 [A] `bd create` → `mcp__cognovis-tools__bead.create`. Explicit bead creation recipe should route to the typed bead.create tool. Snippet: `3. **New bead only after failing 1 and 2**: `bd create --title="[DISCOVERED] <short title>" -t task -p 2 --deps discovered-from:<BEAD_ID>` — record why the current bead does not fit, which candidate IDs were checked, and why none matched.`
- L1540 [B] `git add` → `mcp__cognovis-tools__git.stage_paths or mcp__cognovis-tools__library.exec`. Git staging instructions are a migration candidate for typed git tools or library.exec. Snippet: `3. Commit: `git add <test-files> && git commit -m "test(<bead-id>): red — <what>"``
- L1540 [B] `git commit` → `mcp__cognovis-tools__git.commit or mcp__cognovis-tools__library.exec`. Git commit recipes are a migration candidate for typed git tools or library.exec. Snippet: `3. Commit: `git add <test-files> && git commit -m "test(<bead-id>): red — <what>"``
- L1544 [B] `git add` → `mcp__cognovis-tools__git.stage_paths or mcp__cognovis-tools__library.exec`. Git staging instructions are a migration candidate for typed git tools or library.exec. Snippet: `7. Commit: `git add <specific-files> && git commit -m "feat(<bead-id>): green — <summary>"``
- L1544 [B] `git commit` → `mcp__cognovis-tools__git.commit or mcp__cognovis-tools__library.exec`. Git commit recipes are a migration candidate for typed git tools or library.exec. Snippet: `7. Commit: `git add <specific-files> && git commit -m "feat(<bead-id>): green — <summary>"``
- L1586 [A] `bd create` → `mcp__cognovis-tools__bead.create`. Explicit bead creation recipe should route to the typed bead.create tool. Snippet: `- If you discover out-of-scope work, run the fit-first decision routine first. Only create `bd create --title="[DISCOVERED] <title>" -t task -p 3 --deps discovered-from:<BEAD_ID>` after the current bead and existing-bead checks both fail, and include the no-fit rationale plus checked candidate IDs in the new bead body.`
- L1618 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead-id> --append-notes="ABORT: codex-impl.py not found at $CODEX_IMPL. Run '/library use beads' to reinstall."`
- L1672 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead-id> --append-notes="PARTIAL: codex-impl.py exit 4 ($PARTIAL_REASON). commits=$COMMITS, worktree_dirty=$WORKTREE_DIRTY"`
- L1675 [D] `bd update` → `mcp__cognovis-tools__bead.update`. Informational or prohibitive mention; not teaching an invocation. Snippet: `bd update <bead-id> --append-notes="ABORT: codex-impl.py failed for <bead-id> (exit=$IMPL_EXIT). Surface to user; do NOT substitute Claude."`
- L1686 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead-id> --append-notes="ABORT: cursor-impl.py not found at $CURSOR_IMPL. Run '/library use beads' to reinstall."`
- L1708 [D] `bd update` → `mcp__cognovis-tools__bead.update`. Informational or prohibitive mention; not teaching an invocation. Snippet: `bd update <bead-id> --append-notes="ABORT: cursor-impl.py failed for <bead-id> (exit=$IMPL_EXIT). Surface to user; do NOT substitute Claude/Codex."`
- L1731 [B] `git status` → `mcp__cognovis-tools__git.status or mcp__cognovis-tools__library.exec`. Git status probes are a migration candidate for typed git tools or library.exec. Snippet: `1. Check `git status --porcelain``
- L1734 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="WARNING: impl subagent returned without committing. Orchestrator auto-committed."`
- L1735 [B] `git add` → `mcp__cognovis-tools__git.stage_paths or mcp__cognovis-tools__library.exec`. Git staging instructions are a migration candidate for typed git tools or library.exec. Snippet: `git add <changed-files>`
- L1736 [B] `git commit` → `mcp__cognovis-tools__git.commit or mcp__cognovis-tools__library.exec`. Git commit recipes are a migration candidate for typed git tools or library.exec. Snippet: `git commit -m "feat(<bead-id>): auto-commit orphaned implementation changes"`
- L1750 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Phase 5 artifact validation failed; repair implementation_manifest.json/evidence_ledger.json before review."`
- L1835 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="DECISION: auto-accept review at iter <N>, max_iters=<MAX_ITERS> exhausted"`
- L1990 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="P5 state machine: DONE. iterations=<N>, final_verdict=<CLEAN|FINDINGS-FIXED>, verdicts=<json>"`
- L2157 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Codex adversarial: SKIPPED (exit=${CODEX_EXIT}, reason=${CODEX_REASON}). Adversarial coverage gap on this bead. Risk: undetected regressions in ${DIFF_SCOPE}."`
- L2216 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead-id> --append-notes="ABORT: cursor-impl.py not found at $CURSOR_IMPL. Run '/library use beads' to reinstall."`
- L2233 [D] `bd update` → `mcp__cognovis-tools__bead.update`. Informational or prohibitive mention; not teaching an invocation. Snippet: `bd update <bead-id> --append-notes="ABORT: cursor-impl.py regression fix failed (exit=$FIX_EXIT). Surface to user; do NOT substitute Claude."`
- L2313 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Codex re-check: SKIPPED (exit=${RECHECK_EXIT}, reason=${RECHECK_REASON}). Cannot confirm fixes. Applying Axis B auto-accept."`
- L2323 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="DECISION: auto-accept codex at iter 1, still-broken after fix"`
- L2376 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `<AK list from bd show>`
- L2432 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="VETO: verification DISPUTED with fixability=human. Human review required before proceeding."`
- L2437 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="VETO: e2e-heavy PARTIAL — bead's primary deliverable is e2e verification; routing-layer substitutes are not acceptable evidence. Either deliver the e2e harness or revise the AC's MoC to match what was tested."`
- L2450 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead_id> --append-notes="Skill Application Advisory:`
- L2497 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update "$BEAD_ID" --set-metadata "implementation_impact=$IMPACT_METADATA"`
- L2516 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update "$BEAD_ID" --append-notes "$IMPACT_NOTE"`
- L2565 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead-id> --append-notes="ABORT: cursor-impl.py not found at $CURSOR_IMPL. Run '/library use beads' to reinstall."`
- L2583 [D] `bd update` → `mcp__cognovis-tools__bead.update`. Informational or prohibitive mention; not teaching an invocation. Snippet: `bd update <bead-id> --append-notes="ABORT: cursor-impl.py verification fix failed (exit=$VERFIX_EXIT). Surface to user; do NOT substitute Claude."`
- L2628 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `| Still `DISPUTED` | Hard VETO. Log and escalate: `bd update <id> --append-notes="Verification re-run still DISPUTED after auto-fix — hard VETO."` Report to user. |`
- L2790 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `<full bead description + acceptance criteria from bd show>`
- L2931 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <id> --append-notes="Run complete: run_id=<run_id> pre_impl_sha=<sha> phase9=<verified|disputed>"`
- L2932 [B] `bd dolt` → `mcp__cognovis-tools__library.exec`. Dolt workflow recipes are a migration candidate for library.exec until a typed surface exists. Snippet: `bd dolt commit`
- L3034 [B] `git push` → `mcp__cognovis-tools__git.push or mcp__cognovis-tools__library.exec`. Git push recipes are a migration candidate for typed git tools or library.exec. Snippet: `4. Merge feature → main + git push + bd dolt commit && bd dolt pull && bd dolt push --force`
- L3034 [B] `bd dolt` → `mcp__cognovis-tools__library.exec`. Dolt workflow recipes are a migration candidate for library.exec until a typed surface exists. Snippet: `4. Merge feature → main + git push + bd dolt commit && bd dolt pull && bd dolt push --force`
- L3035 [A] `bd close` → `mcp__cognovis-tools__bead.close`. Explicit bead close recipe should route to the typed bead.close tool. Snippet: `5. Close the bead: bd close {BEAD_ID}`
- L3050 [B] `git merge` → `mcp__cognovis-tools__git.merge_from_main or mcp__cognovis-tools__library.exec`. Git merge recipes are a migration candidate for typed git tools or library.exec. Snippet: `>   cd <repo-root> && git checkout main && git merge worktree-bead-{BEAD_ID} --no-ff`
- L3051 [B] `git push` → `mcp__cognovis-tools__git.push or mcp__cognovis-tools__library.exec`. Git push recipes are a migration candidate for typed git tools or library.exec. Snippet: `>   git push && bd dolt commit && bd dolt pull && bd dolt push --force`
- L3051 [B] `bd dolt` → `mcp__cognovis-tools__library.exec`. Dolt workflow recipes are a migration candidate for library.exec until a typed surface exists. Snippet: `>   git push && bd dolt commit && bd dolt pull && bd dolt push --force`
- L3052 [A] `bd close` → `mcp__cognovis-tools__bead.close`. Explicit bead close recipe should route to the typed bead.close tool. Snippet: `>   bd close {BEAD_ID}"`
- L3067 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead_id> --append-notes="[VALIDATION] run_id=<run_id> commits stay on worktree. NO merge/push/tag."`
- L3098 [D] `bd show` → `mcp__cognovis-tools__bead.show`. Informational or prohibitive mention; not teaching an invocation. Snippet: `- Do NOT run `bd prime` or `bd onboard` yourself. The SessionStart hook (`~/.claude/scripts/beads-session-start.zsh`) already emits `bd prime` output, so PRIME.md content is in the agent's context. The bead context (`bd show <id>`) is also injected into your prompt. Running `bd prime` again only duplicates context. (The `beads` skill that previously did routing has been removed — PRIME.md's Entrypoints table replaces it.)`
- L3103 [A] `bd list` → `mcp__cognovis-tools__bead.list`. Explicit bead list recipe should route to the typed bead.list tool. Snippet: ``bd search <keywords>`, `bd list --status=open --json`, and`
- L3103 [A] `bd search` → `mcp__cognovis-tools__bead.search`. Explicit bead search recipe should route to the typed bead.search tool. Snippet: ``bd search <keywords>`, `bd list --status=open --json`, and`
- L3104 [A] `bd list` → `mcp__cognovis-tools__bead.list`. Explicit bead list recipe should route to the typed bead.list tool. Snippet: ``bd list --status=in_progress --json` for an existing home. Create a new`
- L3110 [A] `bd create` → `mcp__cognovis-tools__bead.create`. Explicit bead creation recipe should route to the typed bead.create tool. Snippet: `via the scope-creep escape hatch), is a legitimate follow-up (then `bd create`), or is`
- L3126 [B] `bd dolt` → `mcp__cognovis-tools__library.exec`. Dolt workflow recipes are a migration candidate for library.exec until a typed surface exists. Snippet: `by `brew services`, NOT by `bd` — never `bd dolt start`, never `bd dolt stop`,`
- L3128 [B] `bd dolt` → `mcp__cognovis-tools__library.exec`. Dolt workflow recipes are a migration candidate for library.exec until a typed surface exists. Snippet: `1. Run `bd dolt status` ONCE to confirm reality.`

### `~/.claude/agents/quick-fix.md`

- Summary classification: **A**
- Total hits: **33**
- A+B hits: **30**

- L66 [A] `bd close` → `mcp__cognovis-tools__bead.close`. Explicit bead close recipe should route to the typed bead.close tool. Snippet: `recover with `bd close` if session-close returned without closing it.`
- L210 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `LIVE_NETWORK_JSON=$(bd show "<id>" --json | uv run python "$LIVE_NETWORK_SCRIPT")`
- L324 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update {BEAD_ID} --append-notes="WARNING: codex-impl.py not found at $CODEX_IMPL; falling back to general-purpose Agent (haiku). IMPL_MODEL={ROUTE_DECISION_IMPL_MODEL}. Install clc-f1b.2 to enable cld-line dispatch."`
- L358 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `{AK_LIST from bd show}`
- L373 [A] `bd list` → `mcp__cognovis-tools__bead.list`. Explicit bead list recipe should route to the typed bead.list tool. Snippet: `2. **Existing bead fit check**: Search `bd search <keywords>`, `bd list --status=open --json`, and `bd list --status=in_progress --json` for same-repo open/in-progress beads with matching intent, release artifact, version bump, publish action, review path, or UAT target. If found, append to or update that bead.`
- L373 [A] `bd search` → `mcp__cognovis-tools__bead.search`. Explicit bead search recipe should route to the typed bead.search tool. Snippet: `2. **Existing bead fit check**: Search `bd search <keywords>`, `bd list --status=open --json`, and `bd list --status=in_progress --json` for same-repo open/in-progress beads with matching intent, release artifact, version bump, publish action, review path, or UAT target. If found, append to or update that bead.`
- L374 [A] `bd create` → `mcp__cognovis-tools__bead.create`. Explicit bead creation recipe should route to the typed bead.create tool. Snippet: `3. **New bead only after failing 1 and 2**: `bd create --title="[DISCOVERED] <short title>" -t task -p 2 --deps discovered-from:{BEAD_ID}` — record why the current bead does not fit, which candidate IDs were checked, and why none matched.`
- L378 [B] `git add` → `mcp__cognovis-tools__git.stage_paths or mcp__cognovis-tools__library.exec`. Git staging instructions are a migration candidate for typed git tools or library.exec. Snippet: `git add <files> && git commit -m "{type}({BEAD_ID}): {short description}"`
- L378 [B] `git commit` → `mcp__cognovis-tools__git.commit or mcp__cognovis-tools__library.exec`. Git commit recipes are a migration candidate for typed git tools or library.exec. Snippet: `git add <files> && git commit -m "{type}({BEAD_ID}): {short description}"`
- L555 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update {BEAD_ID} --append-notes="Codex adversarial: SKIPPED (exit=${CODEX_EXIT}, reason=${CODEX_REASON}). Adversarial coverage gap on this bead. Risk: undetected regressions in ${DIFF_SCOPE}."`
- L644 [B] `git add` → `mcp__cognovis-tools__git.stage_paths or mcp__cognovis-tools__library.exec`. Git staging instructions are a migration candidate for typed git tools or library.exec. Snippet: `- COMMIT your changes: git add <files> && git commit -m 'fix({BEAD_ID}): <summary>'`
- L644 [B] `git commit` → `mcp__cognovis-tools__git.commit or mcp__cognovis-tools__library.exec`. Git commit recipes are a migration candidate for typed git tools or library.exec. Snippet: `- COMMIT your changes: git add <files> && git commit -m 'fix({BEAD_ID}): <summary>'`
- L722 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update {BEAD_ID} --append-notes="Codex re-check: SKIPPED (exit=${RECHECK_EXIT}, reason=${RECHECK_REASON}). Cannot confirm fixes resolved. Treating as STILL-BROKEN for safety."`
- L748 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update {BEAD_ID} --append-notes="MoC evidence:`
- L754 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `If `bd update` fails, log a warning and proceed to Phase 5. MoC evidence failure does NOT block close.`
- L769 [A] `bd close` → `mcp__cognovis-tools__bead.close`. Explicit bead close recipe should route to the typed bead.close tool. Snippet: `>      git/tag/`bd close`/learnings work yourself instead of spawning `session-close`.`
- L774 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `> - Writing `Close reason: ...` to notes and claiming CLOSED without verifying `bd show --json`.`
- L808 [D] `bd close` → `mcp__cognovis-tools__bead.close`. Informational or prohibitive mention; not teaching an invocation. Snippet: `- Do NOT ask the parent quick-fix agent to manually run versioning, push, `bd close`, or`
- L856 [B] `git push` → `mcp__cognovis-tools__git.push or mcp__cognovis-tools__library.exec`. Git push recipes are a migration candidate for typed git tools or library.exec. Snippet: `> In both cases: git push && bd dolt commit && bd dolt pull && bd dolt push --force`
- L856 [B] `bd dolt` → `mcp__cognovis-tools__library.exec`. Dolt workflow recipes are a migration candidate for library.exec until a typed surface exists. Snippet: `> In both cases: git push && bd dolt commit && bd dolt pull && bd dolt push --force`
- L857 [A] `bd close` → `mcp__cognovis-tools__bead.close`. Explicit bead close recipe should route to the typed bead.close tool. Snippet: `> Then: bd close {BEAD_ID}`
- L863 [C] `bd close` → `mcp__cognovis-tools__bead.close`. Contextual bead CLI mention; lower-priority migration. Snippet: `#### Step 5c: Verify `bd close` State (MANDATORY)`
- L869 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `bd show "{BEAD_ID}" --json | jq -e '.[0].status == "closed" and ((.[0].closed_at // "") | length > 0) and ((.[0].close_reason // "") | length > 0)'`
- L877 [A] `bd close` → `mcp__cognovis-tools__bead.close`. Explicit bead close recipe should route to the typed bead.close tool. Snippet: `bd close "{BEAD_ID}" --reason="Quick-fix completed — {TITLE}"`
- L878 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `bd show "{BEAD_ID}" --json | jq -e '.[0].status == "closed" and ((.[0].closed_at // "") | length > 0) and ((.[0].close_reason // "") | length > 0)'`
- L881 [A] `bd close` → `mcp__cognovis-tools__bead.close`. Explicit bead close recipe should route to the typed bead.close tool. Snippet: `If `bd close` fails, or if the second `bd show --json` verification still fails, HARD STOP:`
- L881 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `If `bd close` fails, or if the second `bd show --json` verification still fails, HARD STOP:`
- L886 [A] `bd close` → `mcp__cognovis-tools__bead.close`. Explicit bead close recipe should route to the typed bead.close tool. Snippet: `Surface the `bd close` and `bd show --json` outputs to the caller.`
- L886 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `Surface the `bd close` and `bd show --json` outputs to the caller.`
- L890 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: ``closed_at`, and top-level `close_reason` in `bd show --json`.`
- L904 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `- Close verification: `bd show --json` has status=closed, closed_at, and close_reason`
- L970 [D] `bd close` → `mcp__cognovis-tools__bead.close`. Informational or prohibitive mention; not teaching an invocation. Snippet: `it skip non-applicable merge steps. Do NOT manually do versioning, push, `bd close`, or`
- L972 [A] `bd close` → `mcp__cognovis-tools__bead.close`. Explicit bead close recipe should route to the typed bead.close tool. Snippet: ``bd close` only as the explicit Step 5c recovery path when the bead is still not closed.`

### `~/.claude/agents/wave-orchestrator.md`

- Summary classification: **A**
- Total hits: **19**
- A+B hits: **18**

- L164 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `The preflight gate delegates all deterministic checks to `wave-preflight.py`: `bd show`
- L212 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `**A `bd show` load error is terminal here.** If any bead reports `review: "unknown"` (a`
- L213 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: ``bd show failed` reason — the bead cannot be read), refuse dispatch and stop:`
- L236 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `**Specific IDs given** — validate each exists: `bd show <id>`.`
- L241 [A] `bd list` → `mcp__cognovis-tools__bead.list`. Explicit bead list recipe should route to the typed bead.list tool. Snippet: `bd list --status=open`
- L242 [A] `bd list` → `mcp__cognovis-tools__bead.list`. Explicit bead list recipe should route to the typed bead.list tool. Snippet: `bd list --status=in_progress`
- L243 [A] `bd search` → `mcp__cognovis-tools__bead.search`. Explicit bead search recipe should route to the typed bead.search tool. Snippet: `bd search "<topic>"`
- L244 [A] `bd search` → `mcp__cognovis-tools__bead.search`. Explicit bead search recipe should route to the typed bead.search tool. Snippet: `bd search "<alternate-spelling>"   # e.g. "ueberweisung" AND "Überweisung"`
- L263 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `Build a dependency graph from `bd show <id>` for each selected bead. Extract `blocked_by``
- L358 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update "$bead_id" --append-notes="Phase 1.25: cross-bead review skipped (--skip-wave-review)."`
- L396 [D] `bd update` → `mcp__cognovis-tools__bead.update`. Informational or prohibitive mention; not teaching an invocation. Snippet: `# we do not bd update it.`
- L434 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: ``bd update <id> --append-notes="Architecture review skipped (--skip-review). ..."`.`
- L446 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `Agent(model="haiku", prompt="Bead: <bd show output>. Signal score <score> (threshold 6).`
- L490 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `For each feature bead, run `bd show <id>` and check for the section. For each one missing`
- L715 [B] `git pull` → `mcp__cognovis-tools__git.pull or mcp__cognovis-tools__library.exec`. Git pull recipes are a migration candidate for typed git tools or library.exec. Snippet: `git pull --no-rebase    # verify merges landed on main`
- L716 [B] `bd dolt` → `mcp__cognovis-tools__library.exec`. Dolt workflow recipes are a migration candidate for library.exec until a typed surface exists. Snippet: `bd dolt pull`
- L821 [B] `git pull` → `mcp__cognovis-tools__git.pull or mcp__cognovis-tools__library.exec`. Git pull recipes are a migration candidate for typed git tools or library.exec. Snippet: `- **Pull between waves**: `git pull --no-rebase` + `bd dolt pull`.`
- L821 [B] `bd dolt` → `mcp__cognovis-tools__library.exec`. Dolt workflow recipes are a migration candidate for library.exec until a typed surface exists. Snippet: `- **Pull between waves**: `git pull --no-rebase` + `bd dolt pull`.`
- L833 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `**sequentially** (one at a time), and checks completion with `bd show` after each —`

### `~/.agents/skills/bead-reviewer/SKILL.md`

- Summary classification: **A**
- Total hits: **15**
- A+B hits: **15**

- L26 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `bd show <bead-id> --json`
- L32 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `- `acceptance_criteria` (string — newline-separated text from bd show)`
- L42 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `pipe `bd show <bead-id> --json` into it with `--repo-root <REPO_ROOT>`, where`
- L78 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `Check `metadata.routing.routed_effort` from the `bd show <bead-id> --json``
- L82 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `BEAD_JSON=$(bd show <bead-id> --json)`
- L119 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: ``classify_effort.py` persists the derived result with `bd update <bead-id>`
- L122 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: ``metadata.routing.routed_effort` result via `bd update --metadata` before Step 2.`
- L159 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `bd show <blocker-id> --json | jq -r '.[0].status'`
- L264 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead-id> --body-file /tmp/<bead-id>-reviewer-remediation.md`
- L265 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead-id> --acceptance "<newline-separated AC list>"`
- L270 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead-id> --append-notes="bead-reviewer self-remediation: added <sections>; re-running review."`
- L272 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `5. Reload the bead with `bd show <bead-id> --json` and restart Steps 1-4 once on the`
- L431 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `SHAS=$(bd show <bead-id> --json | python3 "$COMPUTE_SHA")`
- L440 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `bd update <bead-id> --metadata="{\"review\":$REVIEW_JSON}"`
- L616 [A] `bd list` → `mcp__cognovis-tools__bead.list`. Explicit bead list recipe should route to the typed bead.list tool. Snippet: ``bd list --status=open --json` and `bd list --status=in_progress --json` candidates before`

### `~/.agents/skills/beads/SKILL.md`

- Summary classification: **A**
- Total hits: **9**
- A+B hits: **8**

- L15 [D] `bd show` → `mcp__cognovis-tools__bead.show`. Informational or prohibitive mention; not teaching an invocation. Snippet: `**Rules:** Never use `bd edit`. Never guess bead ID prefixes — `bd show 9yt` works with the hash only.`
- L24 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `| `scripts/claim-bead.py` | Claim gate wrapper around `bd update` status/assignee/metadata writes |`
- L89 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `bd show <id> --json | jq -r '.type, .metadata.effort // ""'`
- L118 [A] `bd list` → `mcp__cognovis-tools__bead.list`. Explicit bead list recipe should route to the typed bead.list tool. Snippet: `2. **Existing bead fit check**: Search `bd search <keywords>`, `bd list --status=open --json`, and `bd list --status=in_progress --json` for same-repo open/in-progress beads with matching intent, release artifact, version bump, publish action, review path, or UAT target. If found, append to or update that bead.`
- L118 [A] `bd search` → `mcp__cognovis-tools__bead.search`. Explicit bead search recipe should route to the typed bead.search tool. Snippet: `2. **Existing bead fit check**: Search `bd search <keywords>`, `bd list --status=open --json`, and `bd list --status=in_progress --json` for same-repo open/in-progress beads with matching intent, release artifact, version bump, publish action, review path, or UAT target. If found, append to or update that bead.`
- L119 [A] `bd create` → `mcp__cognovis-tools__bead.create`. Explicit bead creation recipe should route to the typed bead.create tool. Snippet: `3. **New bead only after failing 1 and 2**: `bd create --title="[DISCOVERED] <short title>" -t task -p 2 --deps discovered-from:<bead-id>` — record why the current bead does not fit, which candidate IDs were checked, and why none matched.`
- L144 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `This operation is **explicit invocation only**. Never auto-trigger it from `bd show`, read-only`
- L145 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `queries, or casual effort lookups. On a cache miss, `classify_effort.py` performs a `bd update``
- L178 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `- Cache hit: instant return, no LLM call, no `bd update``

### `~/.claude/agents/session-close.md`

- Summary classification: **A**
- Total hits: **9**
- A+B hits: **6**

- L180 [B] `git commit` → `mcp__cognovis-tools__git.commit or mcp__cognovis-tools__library.exec`. Git commit recipes are a migration candidate for typed git tools or library.exec. Snippet: ``phase-b-prepare.sh`, git commit, `phase-b-ship.sh`, or`
- L204 [A] `bd list` → `mcp__cognovis-tools__bead.list`. Explicit bead list recipe should route to the typed bead.list tool. Snippet: ``bd list --status=in_progress`.`
- L349 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `(`bd update <id> --append-notes="Security audit: <vulns>"`) and proceed automatically.`
- L574 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `and stamp it into the bead: `bd update <id> --append-notes="Close reason: <reason>"`. Then rerun`
- L581 [A] `bd update` → `mcp__cognovis-tools__bead.update`. Explicit bead mutation recipe should route to the typed bead.update tool. Snippet: `**If `--non-interactive`:** Auto-compose the close reason from bead title + the Step 6 commit subject (format: `<bead-title>: <commit-subject>`). Stamp via `bd update <id> --append-notes='Close reason: <auto-composed>'` then rerun the handler with the same arguments.`
- L744 [D] `git merge` → `mcp__cognovis-tools__git.merge_from_main or mcp__cognovis-tools__library.exec`. Informational or prohibitive mention; not teaching an invocation. Snippet: `- Do NOT use `git rebase` — always `git merge``
- L745 [D] `git push` → `mcp__cognovis-tools__git.push or mcp__cognovis-tools__library.exec`. Informational or prohibitive mention; not teaching an invocation. Snippet: `- Do NOT use `git push --force``
- L746 [D] `git add` → `mcp__cognovis-tools__git.stage_paths or mcp__cognovis-tools__library.exec`. Informational or prohibitive mention; not teaching an invocation. Snippet: `- Do NOT use `git add -A` or `git add .` — always stage specific files`
- L747 [B] `bd dolt` → `mcp__cognovis-tools__library.exec`. Dolt workflow recipes are a migration candidate for library.exec until a typed surface exists. Snippet: `- ALWAYS use `bd dolt pull && bd dolt push --force` (Dolt bug dolthub/dolt#10807)`

### `~/.agents/skills/session-close/SKILL.md`

- Summary classification: **A**
- Total hits: **1**
- A+B hits: **1**

- L109 [A] `bd list` → `mcp__cognovis-tools__bead.list`. Explicit bead list recipe should route to the typed bead.list tool. Snippet: ``bd list --status=in_progress`.`

### `~/.agents/skills/wave-dispatch/SKILL.md`

- Summary classification: **A**
- Total hits: **1**
- A+B hits: **1**

- L64 [A] `bd show` → `mcp__cognovis-tools__bead.show`. Explicit bead read recipe should route to the typed bead.show tool. Snippet: `owning project directory through `bd show --json` probes and records per-bead `project_dir``
