# prime/

Canonical source for `.beads/PRIME.md` — the bd workflow primer that gets
auto-injected at session start by the SessionStart hooks (Claude + Codex).

## Status: PROVISIONAL

This directory exists outside `library.yaml`. It is the agreed-upon home
for the workflow primer until the schema-based generalization lands.

The schema work is tracked in **`CL-3fh`**:
> [LIBRARY] project_tooling: fleet-wide → per-project file/hook distribution

Once `CL-3fh` is implemented, `prime/PRIME.md` will become a registered
`project_tooling` entry — same content, accessed via the schema runtime
instead of the hardcoded fallback chain in the hook scripts.

## How the distribution chain works today

```
cognovis-library/prime/PRIME.md            ← canonical (this file's sibling)
                  ↓ SessionStart hook reads
$XDG_CACHE_HOME/cognovis-prime/PRIME.md    ← per-machine bootstrap cache (~/.cache/cognovis-prime/)
                  ↓ SessionStart hook copies
<project>/.beads/PRIME.md                   ← per-project (bd prime reads this)
```

The cache lives under `$XDG_CACHE_HOME` (default `~/.cache/`) — explicitly NOT in
`~/.claude/templates/`. With `~/.claude/` managed as a chezmoi external
(`sussdorff/claude`), writing to it would dirty the working tree on every cache
refresh and stop chezmoi from pulling cleanly. XDG cache is per-machine and
outside chezmoi's scope.

Hooks involved:
- `~/.claude/scripts/beads-session-start.zsh` (Claude SessionStart)
- `~/.codex/scripts/beads-session-start.zsh` (Codex SessionStart)

Both: try library first → fall back to templates cache → copy to
`.beads/PRIME.md` → refresh cache if library was the source.

## Editing PRIME.md

Edit `prime/PRIME.md` here. On the next SessionStart in any
`.beads/`-bearing project, the hook picks up the change:
1. Reads the new content from the library
2. Refreshes `~/.claude/templates/PRIME.md` (cache)
3. Copies into `<project>/.beads/PRIME.md`

`bd prime` then emits the new content per project.

## Bootstrap on a fresh machine

The XDG cache (`~/.cache/cognovis-prime/PRIME.md`) is per-machine and starts
empty. On a fresh machine without `cognovis-library` checked out yet, the
hook chain has no source — the per-project `.beads/PRIME.md` falls back to
whatever `bd onboard` last wrote (or the bd default).

For a clean bootstrap, clone `cognovis-library` before running anything in
beads-managed projects. The first SessionStart afterwards seeds the XDG
cache and per-project `.beads/PRIME.md`.

(The previous design used `~/.claude/templates/PRIME.md` as a chezmoi-synced
bootstrap cache, but that conflicts with chezmoi externals — the cache
needed to be writable by automation, which dirties the chezmoi-managed
working tree. Moved to XDG.)
