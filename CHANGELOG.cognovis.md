# Cognovis Library Changelog

This changelog tracks changes made by Cognovis on top of the upstream fork.
Upstream: https://github.com/disler/the-library (forked at commit `47f455c`)

---

## [v2026.04.1] - 2026-04-16

### Added

- Forked from `disler/the-library` at commit `47f455c` as the basis for Cognovis
  multi-harness distribution (Claude Code + Codex + marketplaces).
- `docs/ARCHITECTURE.md`: Captures the fork rationale and design decisions:
  - Catalog + content-repo split (one catalog, many content repos)
  - Per-repo on-demand distribution over BMAD deploy-all
  - Codex subagents as first-class citizens alongside Claude Code
  - Open agent-skills standard shared by both harnesses
  - IndyDevDan's original pattern as the foundation
- `AGENTS.md`: Agent instructions for this repo (non-interactive shell, beads workflow)
- `CLAUDE.md`: Claude Code project instructions (beads integration, session close protocol)
- `.claude/settings.json`: Project hooks (SessionStart/PreCompact run `bd prime`)
- `.claude/anatomy.json`: Open-brain anatomy config
- `.gitignore`: Added beads/Dolt entries (`.dolt/`, `*.db`, `.beads-credential-key`)
- Seeded 11 beads for multi-harness extension work:
  - Epic `CL-36o`: Multi-harness library (parent of all sub-beads)
  - `CL-nvp`: Document architecture
  - `CL-6hg`: Add Codex paths to default_dirs in library.yaml
  - `CL-06x`: Extend /library use cookbook with tool-awareness
  - `CL-7ii`: Add marketplaces: category to library.yaml schema
  - `CL-xcm`: Add hooks as fourth artifact type
  - `CL-tap`: Build cdx wrapper script
  - `CL-qzw`: Research Codex layer-3 format and install path
  - `CL-11p`: Layer 2 agents format translation spec
  - `CL-23z`: Third-party origin audit
  - `CL-1rr`: Bootstrap content repos
  - Dependency graph wired: epic depends on all subs; inter-sub deps correctly set
