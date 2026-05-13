"""
installers/ — Primitive-specific install logic for the library CLI.

Each module implements install/remove for one primitive type:
  skill.py     — three-layer cache, .agents symlink, Claude bridge, lockfile update
  standard.py  — AGENTS.md block injection + lockfile update
"""
