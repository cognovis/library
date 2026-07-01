# Gas City Pilot — Quick-Loop (cld -bq shape), login-based

> Provenance: authored 2026-07-01 during a Gas City vs. library-platform
> research/advisory session. Background + rationale live in open-brain memories
> `#25948` (Gas City architecture), `#25949` (library+Gas City convergence),
> `#25951` (pilot decision), `#25889` (session summary). Prior evaluation:
> `cognovis-core/docs/research/gascity-migration-plan.md` +
> `gascity-vs-archon-orchestration-comparison.md` (2026-05-14) — cross-check
> before starting, it predates the current Gas City (v2 formulas, ~16 providers,
> upstream/exec-provider abstractions, registry+packs.lock).

Goal: prove that a bead is worked **end-to-end by Gas City, natively, with a
self-healing loop, without a human dispatching it** — reproducing the *shape* of
`cld -bq` (implement -> review -> fix-loop -> close), using the shipped `gascity`
methodology pack. Implementation runs on **Codex (gpt-5.5)**, review on **Claude
(opus)**, both via your existing **login** (no API keys, no `[upstreams]`).

This is a throwaway pilot. It touches NO production repo and NO
`dolt.cognovis.de` bead state — the pilot city runs its own local managed Dolt.

---

## What proves what (two staged proofs)

- **Proof 1 — native drive + self-heal (simplest, run this first).**
  Sling `do-work` at one bead: `prepare-worktree -> implement (check-loop, max 3)
  -> close`. Proves Gas City drives Codex to do a real bead with a retry loop,
  no `cld` wrapper.
- **Proof 2 — the review/fix loop (the "yours" part).**
  Run the review-loop entrypoint so `build-basic-review` engages: 3 review lanes
  (acceptance / test-evidence / simplicity) -> synthesize -> apply-fixes, wrapped
  in a `check` loop `max_attempts = 6` until `implementation-review-approved.sh`
  passes. Proves the implement->review->fix->re-review loop runs and self-heals.
- **Proof 3 — hands-off dispatch (the actual goal).**
  Add an Order so a newly created bead is auto-picked. Then `bd create` a bead
  and watch it get worked with zero human dispatch.

---

## Prerequisites (verify before Phase 0)

- `claude` logged in and working in your terminal (Claude Code).
- `codex` logged in and working in your terminal (Codex CLI).
- `tmux`, `git`, `jq` on PATH (you have these).
- `gc` is NOT yet installed — that is Phase 0. It was never installed before, so
  the whole 2026-05 migration plan is doc-derived; installing + `gc doctor` is
  the single validation gate that was always missing.

---

## Phase 0 — Install gc + doctor (change nothing else)

Gas City is a Go binary. Install per the project's current instructions
(release download or `go install`), then:

```bash
gc version
gc doctor           # reports missing deps / provider readiness; fix nothing else yet
```

`gc doctor` probes provider readiness — it should see `claude` and `codex` as
configured (login-based). If it flags them, fix the login (run `claude` /
`codex` once interactively) before proceeding. STOP here if doctor is unhappy.

---

## Phase 1 — Create the pilot city

```bash
gc init ~/code/gc-pilot --template minimal --default-provider claude
cd ~/code/gc-pilot
```

`gc init` writes `.gc/`, `pack.toml`, `city.toml`, and the **pinned** `core` + `bd`
imports (+ `packs.lock`) for *your* installed binary. Do not hand-write those pins.

---

## Phase 2 — A sandbox rig (fresh git repo, no production beads)

```bash
mkdir -p ~/code/gc-pilot-sandbox && cd ~/code/gc-pilot-sandbox
git init
printf '# sandbox\n' > README.md
git add -A && git commit -m "chore: sandbox init"
cd ~/code/gc-pilot
gc rig add ~/code/gc-pilot-sandbox
gc rig list        # note the assigned prefix, e.g. "gp"
```

The rig's beads live in the pilot city's own managed Dolt (scoped by prefix) —
you do NOT run `bd init` here, and nothing touches dolt.cognovis.de.

> RISK FLAG (validate, don't assume): the pilot city starts its own local Dolt
> sql-server. Watch for port/service collisions with your existing bd/dolt setup.
> This is the deferred Open Question #1 (binding real rigs to the shared server).

---

## Phase 3 — Import the shipped methodology pack (formulas + roles)

Two imports, per the pack README: formulas+skill at city scope, role agents per rig.

```bash
# City scope: formulas + mayor skill
gc import add --name gc "https://github.com/gastownhall/gascity-packs.git//gascity"
```

Then add the rig-scoped role import + the provider patch to `city.toml` (Phase 4),
and run:

```bash
gc import install
```

The `gascity/roles` pack ships these providerless role agents (they become
`gc.<name>` under the `gc` binding): `implementation-worker`,
`implementation-reviewer`, `review-synthesizer`, `gap-analyst`,
`design-implementation-reviewer`, `design-test-risk-reviewer`, `design-author`,
`requirements-planner`, `task-decomposer`, `publisher`, `run-operator`,
`issue-triager`. They **inherit the workspace provider** unless patched.

---

## Phase 4 — Config: providers (login-based) + role bindings

Edit `~/code/gc-pilot/city.toml`. The blocks below are the pilot-specific
additions; `gc init` already wrote `[workspace]` and the pinned `[imports.core]` /
`[imports.bd]`. Keep those.

```toml
# --- providers: login-based, NO upstream blocks (ambient login passed through) ---
[providers.claude]
base            = "builtin:claude"
option_defaults = { model = "opus" }      # review roles -> Claude Opus (your login)

[providers.codex]
base            = "builtin:codex"
option_defaults = { model = "gpt-5.5" }   # impl role -> Codex gpt-5.5 (your login)

# workspace.provider (written by gc init) should be "claude" so review/planner
# roles default to Claude Opus. If gc init set something else, set:
#   [workspace] provider = "claude"

# --- rig: register the roles pack + override the implementation role to Codex ---
# NOTE: model this on examples/t3bridge-gastown/city.toml. gc rig add (Phase 2)
# may already have written a [[rigs]] entry; if so, ADD the [rigs.imports.gc]
# subtable under it rather than duplicating the rig.
[[rigs]]
name = "gc-pilot-sandbox"
path = "/ABSOLUTE/PATH/TO/gc-pilot-sandbox"

[rigs.imports.gc]
source = "https://github.com/gastownhall/gascity-packs.git//gascity/roles"

# Override ONLY the implementation role to Codex; everything else stays Claude Opus.
[[rigs.patches]]
agent    = "gc.implementation-worker"
provider = "codex"
```

Login model: because no `upstream` is set on any agent, Gas City injects no
`ANTHROPIC_*` / `OPENAI_*` and each harness uses its own login (source:
`template_resolve.go:442` — upstream env only renders when `upstream != ""`).

---

## Phase 5 — Validate BEFORE starting (this is the safety gate)

```bash
gc import install
gc config show --validate      # must pass; catches TOML nesting / unknown-field errors
gc doctor                      # provider catalog + builtin-pack-imports; run --fix if it suggests
gc config explain --provenance # optional: confirm impl=codex, reviewers=claude opus
```

If `gc config show --validate` errors on the `[[rigs.patches]]` / `[rigs.imports.gc]`
nesting, move those under the `[[rigs]]` entry as the validator directs (the
t3bridge example is the reference shape). Do not `gc start` until validate passes.

---

## Phase 6 — Start + Proof 1 (native drive + self-heal)

```bash
gc start ~/code/gc-pilot

# Seed one real-ish bead in the sandbox rig (replace <prefix> from gc rig list):
gc bd create --title "Add a hello() function to README-driven demo" \
  --description "Create hello.txt containing the line 'hello from gas city'. Verify the file exists."

# Watch the fleet (three windows / tabs):
gc events --follow           # the event stream (bead.created, session.woke, bead.closed, ...)
gc dashboard                 # the embedded SPA (sessions, beads, formula runs, health)
gc session list              # what's running

# Dispatch the quick native formula at the bead:
gc sling gc-pilot-sandbox/gc.implementation-worker do-work --formula
# -> prepare-worktree -> implement (Codex, check-loop max 3) -> close-source-anchor

# Peek at the live Codex session:
gc session attach <session-name-from-gc-session-list>
```

**Proof 1 passes when:** the bead goes open -> in_progress -> closed, driven by
Codex in a tmux pane, with the implement check-loop visible if the first attempt's
artifact check fails. No `cld` was involved.

---

## Phase 7 — Proof 2 (the review/fix loop)

Run the review-loop entrypoint so `build-basic-review` engages (3 lanes ->
synthesize -> apply-fixes, `check max_attempts = 6` until approved). Confirm the
exact entrypoint + inputs first:

```bash
gc formula list
gc formula show build-from-decompose --json   # inspect inputs (implement -> review -> finalize)
gc formula show build-basic --json            # the full lifecycle (cld -b analog), for later
```

Then sling the review-bearing entrypoint at the bead/convoy (exact target/vars
per `gc formula show`). Reviewers run on Claude Opus; the loop re-reviews until
`implementation-review-approved.sh` passes or the attempt budget is hit.

**Proof 2 passes when:** a review lane finds something, `apply-review-findings`
runs (Codex), and `re-review` flips to approved — all without you dispatching.

> This is where "yours vs stock" shows: the stock lanes are acceptance /
> test-evidence / simplicity. Your Codex-adversarial + verification-VETO + MoC +
> session-close-double-merge are NOT here yet — those are lane-prompt / check-script
> swaps you layer on later. The LOOP is free; the gate CONTENT is your config.

---

## Phase 8 — Proof 3 (hands-off dispatch, the actual goal)

Add an Order so a new bead is auto-worked. Create `orders/auto-quick.toml` in the
city (model on the shipped `mol-dog-stale-db` order shape):

```toml
[order]
description = "Auto-run the quick loop on the next ready unassigned bead"
formula     = "do-work"            # swap to the review entrypoint once Proof 2 is green
trigger     = "cooldown"
interval    = "30s"
pool        = "gc.implementation-worker"
```

Then:

```bash
gc order list
gc order check                     # is it due?
# Hands-off test: just create a bead and walk away.
gc bd create --title "Auto-dispatch smoke: create ping.txt" --description "Create ping.txt with 'pong'."
gc events --follow                 # watch it get picked up and closed with no sling
```

**Proof 3 passes when:** `bd create` alone -> Gas City fires the order -> Codex
works it -> bead closes, and you dispatched nothing. That is "less human
orchestration."

---

## Acceptance (pilot is proven)

- [ ] `gc doctor` green; claude + codex login-ready under gc.
- [ ] Proof 1: one bead open->closed via Codex, native, self-heal loop seen.
- [ ] Proof 2: review lane finds -> fix applied (Codex) -> re-review approved (Opus).
- [ ] Proof 3: `bd create` alone results in a closed bead, no human dispatch.
- [ ] Observability: `gc events` + `gc dashboard` show it as well as cmux did.

## Then (out of scope for the first throw)

- Bind a REAL rig (meta / mira / polaris) — solve the shared-Dolt topology (OQ#1).
- Swap stock review lanes for your gates: add a Codex-adversarial lane, a
  verification-VETO check script, MoC-evidence gate; map session-close
  (double-merge/push) to `finalize`/`publish` or an Order.
- Per-workflow packs: `superpowers` for Mira frontend, a custom Polaris FHIR
  formula — each is just a different pack/formula the order routes to.
- Wire the Library `gascity_export` machinery so your primitives project into
  these packs (the schema + validator already exist in meta/).

## Caveats I could not verify without a running gc

- Exact `[[rigs.patches]]` vs `[rigs.imports.gc]` nesting under `[[rigs]]` — the
  validator (Phase 5) is the authority; adjust to what it accepts.
- Whether `build-basic-review` runs cleanly standalone vs only via a build-*
  entrypoint — `gc formula show` (Phase 7) resolves this.
- Whether the pilot's managed Dolt collides with your existing bd/dolt services.
