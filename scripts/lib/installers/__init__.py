"""
installers/ — Primitive-specific install logic for the library CLI.

Each module implements install/remove for one primitive type:
  skill.py     — three-layer cache, vendored .agents install, Claude bridge, lockfile update
  standard.py  — vendored .agents install + lockfile update
"""
