# Library CLI Invariants

Rules that apply when modifying `scripts/library.py` or `scripts/lib/*.py` in
this repo. These exist because each one was broken at least once and shipped
before the regression was caught.

## 1. Project lockfile lookups require a git root or explicit `--project <path>`

`./.library.lock` lookups must NOT fall back to `cwd().resolve()` blindly.
There are stray `.library.lock` files on real machines (`/Users/<u>/.library.lock`,
system snapshots, scratch dirs) that get silently interpreted as "the project"
when a command is run from a non-project cwd.

**Rule:** any code that reads a project-scoped lockfile must go through
`_resolve_target_root` (or an equivalent helper) and:

- Return the git worktree root when one is found, OR
- Return the explicit `--project <path>` argument when passed, OR
- Skip the project lockfile entirely and emit a warning that names the missing
  precondition (the working scope filter, "not in a git worktree", and how to
  pass `--project`).

Never read `cwd / ".library.lock"` as a fallback. Empty project results +
warning is the correct behaviour for non-project cwd; silent stray-lockfile
inclusion is the bug.

Touchpoint: `scripts/library.py::_resolve_target_root`,
`scripts/lib/installed.py::_load_scope_entries`.

## 2. Catalog-diff math runs against the union of installed entries

When a command produces a "catalog vs installed" diff (e.g.
`installed --diff-catalog`), the comparison set is the **union** of project
and global installed entries — regardless of any `--scope` filter on the
visible table.

Scope filters apply to *display*, never to set arithmetic. Computing the diff
against the visible (scope-filtered) set causes globally-installed entries to
be misclassified as "available but not installed" when the user filtered to
project. On the library/meta machine at CL-uyp time this footgun produced 173
false positives; the fix dropped that to 45.

**Rule:** compute the diff set once from the full installed union; filter
display afterward.

Touchpoint: `scripts/lib/installed.py::build_catalog_diff`.

## 3. Inventory commands need `--offline` and per-process remote-SHA cache

Any command that walks the lockfile and calls `git ls-remote` per entry MUST:

- Accept `--offline` and skip every network call when set (returning
  `upstream: "unknown"` for each entry), AND
- Cache `get_remote_sha(clone_url, ref)` results in-process so two commands
  in the same run (`status` + `installed`, or `installed` + `sync --dry-run`)
  share the result.

139 entries × one `git ls-remote` is slow and flaky on bad networks, and an
"inventory" query is conceptually offline. Network MUST be opt-out, not
mandatory.

Touchpoint: `scripts/lib/status.py::get_remote_sha`,
`scripts/library.py::cmd_installed`.

## 4. Lifecycle commands share a default scope

`status`, `audit`, `sync`, and `installed` all default to **`both`** (project
and global). They are part of the same lifecycle question — "what is
installed and is it current?" — and a mismatch between their defaults produces
contradictory counts (the CL-uyp regression: status=5 behind, sync=124 refresh).

**Rule:** any new lifecycle verb added to `scripts/library.py` defaults to
`--scope=both`. Add a regression test that invokes the new verb together with
`status --dry-run` and asserts they agree on the entry set when both are run
with **no arguments**.

Touchpoint: `scripts/library.py` argparse defaults for any
cross-primitive verb.

## 5. Silently-skipped entries must be counted and surfaced

`sync --dry-run` previously refreshed entries with `upstream: "unknown"` (dead
repo, network down, local-only source). After CL-uyp it skips them — which is
correct, but the user can no longer tell why an entry isn't refreshing.

**Rule:** when a lifecycle command skips an entry for any reason other than
"current", it MUST emit:

- A per-bucket count (`unknown_skipped`, `current_skipped`, etc.) in JSON, AND
- A `warnings:` line in JSON and human output naming the count and the
  escape hatch (`--force`).

`skipped_by_status` is the canonical key when the bucket is upstream-status
derived.

Touchpoint: `scripts/library.py::cmd_sync_all`.

## Standard application

These invariants are platform-internal — they apply only to the library
CLI implementation in this repo, not to projects that consume the library.
Surface them in:

- Any bead that adds or modifies a lifecycle verb in `scripts/library.py`
- Adversarial reviews of changes to `scripts/lib/installed.py`,
  `scripts/lib/status.py`, `scripts/lib/sync_audit.py`
- The factory-check Phase for CLI-touching beads

When extending the CLI, add a test that exercises each relevant invariant.
