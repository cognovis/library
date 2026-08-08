# Cognovis Solo Workbench

The Solo Workbench is the daily-driver Pi package for a single developer. It
registers the existing Fusion, Cognovis Bead Harness, and Native Pack extensions
in one ordinary Pi session while preserving their child sessions, profiles,
worktrees, approvals, and evidence contracts. Bead and Native Pack runs inherit
their explicit Docker lifecycle guard and exact-Bead runtime cleanup automatically;
Fusion remains outside that lifecycle because it owns no Docker stack.

Install it project-locally through the Library Platform:

```bash
cd /path/to/consumer-project
library pi-extension use solo-workbench --json
```

Or target the project explicitly:

```bash
library pi-extension use solo-workbench --target-project /path/to/consumer-project --json
```

A subsequent plain `pi` session exposes:

```text
/fusion <prompt>
/opinion <prompt>
/bead <live-bead-id>
/pack <live-bead-id> <live-bead-id> [...]
/runs
```

The integrated defaults are Fusion SOTA, Bead High Assurance, and Native Pack
Standard. Existing `COGNOVIS_PI_FUSION_PROFILE`,
`COGNOVIS_PI_BEAD_HARNESS_PROFILE`, and `COGNOVIS_PI_NATIVE_PACK_PROFILE`
environment variables override those defaults explicitly. Fusion also contributes its auxiliary `/auto-validate`, `/thinking`,
`/system-prompt`, and `/fh-reset` commands. Native Pack contributes
`/pack-approve`, `/pack-abort`, and `/pack-details`; the shared ACPX viewer is
available as `/acpx-attach`. Standalone `just` launchers remain available for
isolated runs, diagnostics, and verification.

`/bead` and `/pack` create deterministic linked worktrees below
`${XDG_STATE_HOME:-~/.local/state}/cognovis-pi/solo-workbench/worktrees/`. They
reuse only clean worktrees on their expected branch and verify that `bd` resolves
the repository's Beads workspace from the new checkout. They intentionally do not
run a project package manager; the selected Harness remains responsible for any
repository-specific bootstrap required by its gates. `/pack` writes its generated
typed packet to the adjacent private `packets/` directory before entering Native
Pack preflight.

`/runs` is a bounded read-only projection over Harness bindings and messages in
the current Pi session. Canonical Harness state and evidence remain authoritative.
