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

This is a throwaway pilot. The original managed-Dolt variant touches NO
production repo and NO `dolt.cognovis.de` bead state. For real local rigs, use
the verified shared-server bootstrap below so Gas City talks to the existing
Homebrew Dolt on `127.0.0.1:3306` instead of starting another managed server.

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

## Phase 1A — Shared-server Dolt bootstrap (verified 2026-07-03)

Use this path for cities that should share the existing local Homebrew Dolt
server. It was verified with `python-den` and an adopted `ui-cli` rig against
`bd version 1.0.5 (Homebrew)`.

Write a small city template so the external endpoint is present from the start:

```toml
[workspace]
provider = "codex"

[dolt]
host = "127.0.0.1"
port = 3306

[providers]
[providers.claude]
base = "builtin:claude"
ready_delay_ms = 0

[providers.codex]
base = "builtin:codex"
ready_delay_ms = 0

[providers."cursor-agent"]
base = "builtin:cursor"
ready_delay_ms = 0
```

Then initialize the city from that file:

```bash
gc init --file /path/to/city-template.toml \
  --skip-provider-readiness \
  --no-start \
  ~/code/python-den
```

Current Gas City behavior: if the city HQ database does not exist yet, this may
exit after writing the scaffold with `database "hq" not found`, and may briefly
start a managed Dolt server. Stop that server through the generated lifecycle
script; do not kill the process:

```bash
GC_CITY_PATH=~/code/python-den \
GC_BEADS_DIR=~/code/python-den/.beads \
  ~/code/python-den/.gc/scripts/gc-beads-bd.sh stop
```

Normalize the generic HQ database name to a city-specific database, then create
that database on the central Dolt server:

```bash
gc dolt-config normalize-scope \
  --city ~/code/python-den \
  --dir ~/code/python-den \
  --prefix hq \
  --dolt-database gc_python_den_hq

bd -C ~/code/python-den init \
  --reinit-local \
  --server \
  --external \
  --non-interactive \
  --quiet \
  -p hq \
  --database gc_python_den_hq \
  --server-host 127.0.0.1 \
  --server-port 3306 \
  --server-user root \
  --skip-hooks \
  --skip-agents
```

The `bd -C` is intentional. With `bd 1.0.5`, a trailing path argument is not a
safe way to select the target directory for `bd init`; it can run against the
current repository instead.

Mark the city endpoint as external and let Gas City register custom types:

```bash
cd ~/code/python-den
gc beads city use-external --host 127.0.0.1 --port 3306 --user root --adopt-unverified
gc doctor --fix
gc config show --validate
gc bd list --json --limit 1
```

Adopt existing rigs only after the City HQ store is healthy:

```bash
gc rig add ~/code/cli-tools/ui-cli \
  --adopt \
  --name ui-cli \
  --prefix ui-cli \
  --default-branch main

gc bd --rig ui-cli context --json
gc bd --rig ui-cli ready --json --limit 1
gc start --dry-run
```

Install the stock Gas City methodology pack and role pack with durable git
subpath sources, not GitHub tree URLs:

```bash
gc import add --name gc \
  https://github.com/gastownhall/gascity-packs.git//gascity \
  --version sha:3b3b89f2011e06d84459aa7bea1552382f13930a
```

Then add the rig role import under the existing `[[rigs]]` entry:

```toml
[rigs.imports.gc]
source = "https://github.com/gastownhall/gascity-packs.git//gascity/roles"
version = "sha:3b3b89f2011e06d84459aa7bea1552382f13930a"

[[rigs.patches]]
agent = "implementation-worker"
provider = "codex"
```

Note the patch target: under a rig-scoped import, `[[rigs.patches]].agent`
expects the local agent name (`implementation-worker`), not the expanded runtime
name (`gc.implementation-worker`).

Finish with:

```bash
gc import install
gc config show --validate
gc formula list
gc agent list
gc formula show do-work --json
gc doctor --json
```

Verified result on 2026-07-03: `gc formula list` exposed `do-work`,
`build-basic`, `build-basic-review`, `build-from-*`, `review`, and related
formulas; `gc agent list` exposed `ui-cli/gc.implementation-worker` and the
review/planning role agents; `gc doctor --json` returned `ok=true`,
`failed=0`, `blocking_failed=0`. Remaining warnings were non-blocking: local
Gemini alias not explicit, no sessions until `gc start`, no local Dolt backup
for the adopted rig, and deprecated `contract = "graph.v2"` declarations inside
the imported pack.

Verified Proof 1 smoke on 2026-07-03 with `python-den` + `ui-cli`:

```bash
gc sling ui-cli/gc.implementation-worker ui-cli-otk --on do-work --json --nudge
```

Result:

- Source smoke bead: `ui-cli-otk`, closed with `gc.outcome=pass`.
- Workflow root: `ui-cli-kwg`, closed with `gc.outcome=pass`.
- Finalize step: `ui-cli-v89`, closed with `gc.outcome=pass`.
- Implementation attempt: `ui-cli-9f4`, closed with `gc.outcome=pass`.
- Source anchor convoy: `ui-cli-gun`, closed with `gc.outcome=pass`.
- Commit in isolated worktree:
  `ad79d8e6590962c15336edf1e4c18082f9233f49`.
- Marker proof:
  `/Users/malte/code/cli-tools/ui-cli/worktrees/ui-cli-gun/.gc-smoke/python-den-do-work.txt`
  contains exactly `gas city python-den smoke ok`.
- Summary artifact:
  `/Users/malte/code/cli-tools/ui-cli/.gc/artifacts/do-work/ui-cli-kwg/task-ui-cli-gun-summary.md`.

The adopted rig uses the real `ui-cli` bead database (`beads_ui-cli`) through
`gc bd --rig ui-cli ...`; those beads are not copied into the City HQ database.
The City HQ database remains `gc_python_den_hq`.

Operational findings from that smoke:

- Keep `bd 1.0.5`. Do not upgrade bd to fix GC warnings unless this is a
  deliberate team-wide decision.
- `gc start` under launchd can pick a stale `/Users/malte/bin/bd` through the
  `~/.local/bin/bd` wrapper if `~/bin` appears before `/opt/homebrew/bin`.
  Symptom: `bd list: unknown flag: --include-infra`. Start or install the
  supervisor with `/opt/homebrew/bin` before `~/bin`.
- Gas City `1.3.3` emitted
  `native_store_unavailable gate=version_compat reason="bd version differs from linked beads library version"`
  against Homebrew `bd 1.0.5`. The CLI path still worked through `gc bd`; treat
  this as a GC/native-store compatibility warning, not as a reason to change bd.
- Provider sessions did work, but global Codex startup context was heavy. New
  Codex sessions spent noticeable time in SessionStart/open-brain/skills context
  before running the GC claim protocol. This supports keeping GC rigs isolated
  from globally installed hooks/skills where possible.
- The workflow materialized local rig artifacts under `.gc/` and `worktrees/`.
  Keep these local and ignored in adopted source repos:
  `.gc/artifacts/`, `.gc/scripts/`, `.gc/settings.json`, `.gc/tmp/`, and
  `worktrees/`.

Optional off-box archive for the City JSONL export:

- The `jsonl-archive` pack is supplemental observability/export state, not the
  primary beads source of truth. Beads sync remains Dolt-backed through `bd dolt
  push` / `bd dolt pull`.
- On 2026-07-03, `python-den` was configured to push that archive to
  `elysium:/tank/personal/agent-archives/gascity/python-den-jsonl-archive.git`.
  `/tank/personal` is the Elysium ZFS dataset used for personal off-box backup.
- Recreate the remote with:

```bash
ssh -o BatchMode=yes elysium 'set -euo pipefail
base=/tank/personal/agent-archives/gascity
repo=$base/python-den-jsonl-archive.git
install -d -m 700 "$base"
if [ ! -d "$repo" ]; then
  git init --bare "$repo" >/dev/null
  git -C "$repo" symbolic-ref HEAD refs/heads/main
  git -C "$repo" config receive.denyNonFastforwards true
fi'

git -C ~/code/python-den/.gc/runtime/packs/core/jsonl-archive \
  remote add origin elysium:/tank/personal/agent-archives/gascity/python-den-jsonl-archive.git

git -C ~/code/python-den/.gc/runtime/packs/core/jsonl-archive push -u origin main
```

- If running the pack export script manually outside an active City supervisor,
  pass the central Dolt endpoint explicitly:

```bash
GC_CITY=~/code/python-den \
GC_CITY_RUNTIME_DIR=~/code/python-den/.gc/runtime \
GC_DOLT_HOST=127.0.0.1 \
GC_DOLT_PORT=3306 \
PATH="$HOME/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  bash ~/.gc/cache/repos/1d2f032da8cdb758b607f9047362f5779933e41bb913a0d6449e6b4fbdf5ef04/internal/bootstrap/packs/core/assets/scripts/jsonl-export.sh
```

- Verified 2026-07-03: export state reported `last_logged_mode=push`, the
  archive pushed successfully, and local `HEAD`, `origin/main`, and Elysium
  `refs/heads/main` all resolved to
  `beb24cf8bb4fe960f95adcd33d5954c4f9c00f5c`.

Do not use
`https://github.com/gastownhall/gascity-packs/tree/main/gascity/roles` directly.
Use the `.git//gascity/roles` subpath form above.

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

In the managed-Dolt throwaway variant, the rig's beads live in the pilot city's
own managed Dolt (scoped by prefix) — you do NOT run `bd init` here, and nothing
touches dolt.cognovis.de. For existing local rigs, use Phase 1A instead.

> RISK FLAG: the managed-Dolt variant starts its own local Dolt sql-server.
> That did collide conceptually with the existing bd/Dolt topology during the
> 2026-07-03 smoke. Prefer Phase 1A for real rigs.

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
agent    = "implementation-worker"
provider = "codex"
```

The verified current target is the local role name `implementation-worker`.
If a future Gas City release changes patch addressing, `gc config show
--validate` is the authority.

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

## Caveats and resolved checks

- Exact `[[rigs.patches]]` vs `[rigs.imports.gc]` nesting under `[[rigs]]` — the
  validator (Phase 5) is the authority; adjust to what it accepts.
- Whether `build-basic-review` runs cleanly standalone vs only via a build-*
  entrypoint — `gc formula show` (Phase 7) resolves this.
- Resolved 2026-07-03: for real local rigs, use the shared-server bootstrap in
  Phase 1A. It was verified with City HQ database `gc_python_den_hq` and rig
  database `beads_ui-cli` on `127.0.0.1:3306`.
- Resolved 2026-07-03: `ui-cli` beads are available inside `python-den` through
  the adopted rig (`gc bd --rig ui-cli ...`), backed by the existing
  `beads_ui-cli` database. They are not duplicated into City HQ.
- Open follow-up: reduce global Codex/Claude hook and skill injection for GC
  sessions. The smoke passed, but startup/claim latency and queued nudges show
  that global context can make Gas City sessions slower and harder to observe.
