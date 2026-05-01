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
cognovis-library/prime/PRIME.md          ← canonical (this file's sibling)
                  ↓ SessionStart hook reads
~/.claude/templates/PRIME.md              ← bootstrap cache (refreshed on read)
                  ↓ SessionStart hook copies
<project>/.beads/PRIME.md                 ← per-project (bd prime reads this)
```

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

If `cognovis-library` is not yet checked out, the hooks fall back to
`~/.claude/templates/PRIME.md` (which travels in the `~/.claude` dotfiles
repo). After `cognovis-library` is cloned, the next SessionStart syncs the
cache from the library and the chain resumes.
