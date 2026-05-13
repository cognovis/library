"""
scripts/lib — deterministic library engine for cognovis-library.

Modules:
  catalog    — load/validate library.yaml, primitive section mapping, entry lookup
  primitives — primitive registry and metadata
  paths      — resolve default_dirs, project/global scope, AGENTS.md targets
  source     — local/GitHub source parsing, temp clone, tree-SHA/source provenance
  cache      — Layer-B cache path calculation and materialization
  lockfile   — project .library.lock and global ~/.config/library/global.lock
  installers — primitive-specific installers (skill, standard, agent, mcp, etc.)
  output     — human and JSON result envelopes
  errors     — typed exceptions and exit codes
"""
