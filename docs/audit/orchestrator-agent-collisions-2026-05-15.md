# Orchestrator-Family Agent Collision Audit (2026-05-15)

Bead: CL-9tb

## Scope

Audited the Decision 8 informational agent set:

- `bead-orchestrator`
- `wave-orchestrator`
- `session-close`
- `review-agent`
- `verification-agent`
- `quick-fix`
- `doc-changelog-updater`
- `feature-doc-updater`
- `wave-monitor`
- `judge-default`

## Findings

| Surface | Finding |
|---|---|
| `library.yaml` catalog | All ten names resolve to `https://github.com/cognovis/library-core/blob/main/agents/...`; `bead-orchestrator`, `wave-orchestrator`, and `session-close` also declare Codex `.toml` siblings. |
| `../cognovis-core/agents/` | Owns all ten Claude `.md` agents. It also owns Codex `.toml` siblings for `bead-orchestrator`, `wave-orchestrator`, and `session-close`. |
| `../sussdorff-core/` | No same-named `.md` or `.toml` agent files found for the audited names. |
| Installed Claude agents | `~/.claude/agents/` currently contains `bead-orchestrator`, `wave-orchestrator`, `session-close`, `review-agent`, `verification-agent`, `quick-fix`, `doc-changelog-updater`, and `feature-doc-updater`. `wave-monitor` and `judge-default` were not installed there. |
| Installed Codex agents | `~/.codex/agents/` currently contains `bead-orchestrator.toml`, `wave-orchestrator.toml`, and `session-close.toml`. |
| Archived plugin paths | No matching agent `.md` or `.toml` files found under `~/.codex/plugins/cache` or `~/.claude/plugins` for the audited names. |

## Conclusion

No cross-marketplace collision was found. The current convention is consistent
with Decision 8: cognovis-core is the canonical home for the orchestrator-family
agents, and sussdorff-core does not ship same-named alternatives.
