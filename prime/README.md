# Project-tooling hook sources

This directory contains the canonical Git hook bodies installed by the
`project_tooling` runtime. The Library does not project `.beads/PRIME.md`;
`bd prime` is owned by the upstream Beads CLI.

The surviving sources are `hooks/post-commit.sh` for the Beads export hook
and `hooks/pre-push.sh` for the cooperative gitleaks gate.
