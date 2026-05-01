#!/usr/bin/env bash
# post-commit hook — managed by cognovis-library project_tooling (CL-3fh)
# Runs bd export after each commit to keep beads database in sync with git history.
# Do not edit manually — canonical version is in prime/hooks/post-commit.sh.

command -v bd &>/dev/null || exit 0
[[ -d ".beads" ]] || exit 0
bd export 2>/dev/null || true
