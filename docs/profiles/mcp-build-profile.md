# `mcp` build profile — orchestrator route profile for library-tool-surface MCP work

> **Status:** draft (2026-05-29). Design spec for a new orchestrator *workflow
> type* that builds `library-tool-surface` MCP servers (ADR-0007 / `CL-ugwe`).
> Implementation lands in `cognovis-core` (the orchestrator's home), mirroring
> the `infra` route profile added in `cognovis-core@033a639`.

## Why a dedicated profile

The default `full` workflow is tuned for product features: it assumes a
runnable app, end-user UAT, feature-doc layers, and an adversarial diff
review. Building an MCP server (`bead.*`, `git.*`, `library.exec`, `release.*`
typed tools over `bd`/`git`/Library Scripts) has a *different* verification
primitive — the **MCP handshake against hermetic fixtures** — and no product
UAT surface. `quick` is too thin: it drops verification entirely, which is the
one phase a typed tool surface that dangerous agents will depend on (ADR-0007
Phase 7 / `CL-tpet`) cannot lose.

So `mcp` is a third workflow slot-set, a deliberate sibling of `infra`: lean on
product ceremony, but with a hard, specialized verification gate.

This profile is **not** a new orchestrator and **not** a `Workflow`-tool
script. It is a route profile inside the existing `bead-orchestrator`,
selected the same way `infra` is.

## Phase mapping (vs `full`)

| Bucket | Phases |
|---|---|
| **Keep** | claim, context, MoC, changelog, session-close |
| **Drop** | UAT (no end user), feature-doc layers (the authoring contract is its own bead, `CL-ugwe.9`), break-analysis (no product consumers) |
| **Replace** | implementation prompt (FastMCP scaffold + command-family tool), verification (hermetic handshake, not run-the-app), review (opposite-family pre-push advisory) |

The unit the profile fans over is a **command family** (`bead.*`, `git.*`,
`library.exec`, `release.*`) — one scaffold, per-family tool logic + per-family
test fixture. Not to be confused with **harness family** (the four `bin/`
launchers).

## Slot set (`mcp` workflow)

```yaml
mcp:
  implementation:   # nested implementer (Sonnet tier) — real code, NOT active-context
  verification:     # NEW adapter: hermetic MCP handshake + registration smoke
  advisory_review:  # opposite-family pre-push advisory (reuse infra's adapters)
  session_close:
```

- **`implementation`** — a real implementer slot (unlike `infra`, which uses
  `active-context`; MCP server code is substantial). Specialized prompt pins:
  FastMCP app, one module per command family, `json-envelope` output contract
  per `script.md`, `insert_agent_call` metrics on every path **including error
  paths**, each tool backed by a Library Script or a *closed enum* of CLI
  verbs (never inline shell), server-side `bead-hygiene` for `bead.*`, and the
  closed-`script_id`-enum invariant for `library.exec`.
- **`verification`** — a NEW adapter (`mcp-smoke`, a script under
  `skills/beads/scripts/`) that runs hermetically: start the server
  in-process / subprocess → `initialize` + `tools/list` → call each tool
  against throwaway fixtures (tmpdir bd db via `BEADS_DIR`, `git init` tmp
  repo, registry fixture) → assert envelope shape + side-effect + a metrics
  row was written. **No staging environment** — fixtures only; the hard rail
  is that tests never touch the real `.beads` or `bd dolt push`. For the
  registration bead (`CL-ugwe.3`) this slot also runs a **per-harness-family
  registration smoke** (resolve the registration snippet for each of the four
  launcher families; Cursor at minimum, since it is an active impl surface).
- **`advisory_review`** — reuse the infra opposite-family mechanism: cld-line
  → `codex-exec`, cdx-line → `claude-exec`, reviewing `<pre-impl-sha>...HEAD`
  before push and blocking on findings. MCP tools are high-blast-radius
  (dangerous agents will depend on them), so the adversarial pre-push check is
  the "keep verification" the design requires.
- A bounded fix loop (verification DISPUTED → dispatch fix → re-verify, max N)
  lives in the prompt phase, mirroring `quick`'s `fix_loop`.

## Selection

Operator-driven for v1 (`--route-profile <profile> --force-tier mcp`). The
launcher forwards both values to the typed `bead_claim_prepare` contract, with
`surface:mcp` label inference as an **assist only** — NOT pipeline-blocking
force-routing. Rationale: the infra review (`033a639`) showed
`surface:permissions` over-inference force-routing product beads to INFRA
(finding A4). The build cluster (`CL-ugwe.2/.4/.5`) is small and known, so we
take the operator-driven path and defer force-routing until `surface:mcp`
inference is proven precise (e.g. matches `FastMCP`, `tools/list`,
`library-tool-surface`, `typed tool`, but not generic "tool").

## Implementation file set (in `cognovis-core`)

Mirrors the infra recipe extracted from `033a639`:

1. `skills/beads/lib/orchestrator/route_profiles.py` — add `"mcp"` to
   `VALID_WORKFLOWS`; define `MCP_WORKFLOW_SLOTS` + register in
   `_WORKFLOW_REQUIRED_SLOTS`; add `mcp-smoke` to `VALID_ADAPTERS`.
2. `skills/beads/scripts/resolve_slot_dispatch.py` — mirror `mcp-smoke` into
   its **separate** adapter registry (`VALID_ADAPTERS` + `ADAPTER_SCRIPT` +
   `ADAPTER_HARNESS`). This second registry must stay in sync with #1.
3. `skills/beads/scripts/infer_surface_labels.py` — add a `SurfaceRule` for
   `surface:mcp`. Do **not** add it to `PIPELINE_SURFACES` for v1
   (operator-driven selection).
4. `mcp-servers/cognovis-tools/tools/bead_claim_protocol.py` and
   `bead_tools.py` — accept and persist the `force_tier` override, map `mcp` to
   the `mcp` workflow, and materialize the matching route-profile execution
   plan. `skills/beads/scripts/phase0-claim.py` retains equivalent behavior for
   compatibility launchers only.
5. `.agents/orchestrator-config.yml` — add `model_tiers.mcp`,
   `perspective_policy[cld|cdx].tier_*` for the opposite-family reviewer, and
   an `mcp:` slot block under **each** profile (`cld-default`, `cdx-default`,
   `cdx-composer`). Respect the one-extending-bead-per-section serialization
   rule; `bd dep add` against the active owner.
6. `agents/bead-orchestrator.md` — routing rule + announcement, dispatch-table
   row for `mcp-smoke`, the new specialized phase(s) (handshake verification;
   reuse Phase-15b-style opposite-family advisory), and the Phase-Progress
   `route:` enum.
7. `standards/orchestrator/orchestrator-config.md` + `surface-labels.md` —
   document the `mcp` workflow/tier, the `mcp-smoke` adapter, and the
   `surface:mcp` label (non-blocking for v1).
8. `skills/beads/scripts/mcp-smoke.py` — NEW verification adapter (model on
   `claude-exec.py`/`codex-exec.py` structure); register in
   `skills/beads/SKILL.md`.

## Traps to fix while building (from the infra review of `033a639`)

- **A1 — enforce slot completeness.** `_WORKFLOW_REQUIRED_SLOTS` is defined but
  never checked; a profile missing a slot resolves cleanly at Phase 0 and only
  fails deep in `resolve_slot_dispatch`. Add a `build_execution_plan`
  assertion that `_WORKFLOW_REQUIRED_SLOTS["mcp"]` ⊆ slot keys, with a test —
  do not inherit infra's latent gap.
- **A3 — test the opposite-family invariant.** Add a test asserting the `mcp`
  profile's `advisory_review.harness` differs from its `implementation.harness`
  per line (cld→codex, cdx→claude). Infra encodes this by hand but never
  asserts it.
- **A2 — harden the advisory adapter's read-only guarantee.** `claude-exec.py`
  relies on `--tools ""` + `--permission-mode dontAsk`, weaker than
  `codex-exec.py`'s `--sandbox read-only`. If `mcp` reuses `claude-exec`,
  prefer explicit `--disallowedTools` or assert empty-tools semantics in a
  test.

## Tests to add

`test_route_profiles.py` (workflow constant + slot resolution +
slot-completeness A1), `test_resolve_slot_dispatch.py` (`mcp-smoke` validity +
dispatch), `test_phase0_claim.py` (tier→flags), `test_smoke_matrix.py`
(selection), plus the opposite-family-harness assertion (A3) and a hermetic
`mcp-smoke` self-test against a tmpdir fixture.

## Cross-references

- ADR-0007 `docs/adr/library-tool-surface-mcp.md` — the MCP species + Decision
  4 (4-harness registration, registration ≠ orchestration role).
- `docs/primitives/mcp-server.md` — `library-tool-surface` species.
- Infra sibling: `cognovis-core@033a639` (route profile, `surface:*`
  inference, opposite-family advisory).
- Epic `CL-ugwe`; build cluster `CL-ugwe.2/.3/.4/.5`; L5 graduation `CL-tpet`.
