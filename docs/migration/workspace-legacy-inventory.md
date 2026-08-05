# Workspace legacy-writer inventory and cutover register

**Status:** normative migration register for ADR-0010

No legacy writer in this table may be disabled until its row's replacement is
receipt-backed or its project-owned/retired disposition is verified in every
consumer. Workspace reconciliation treats every unresolved row as externally
managed and therefore non-adoptable and non-prunable.

## Bootstrap links

| Target class | Current disposition | Cutover gate |
|---|---|---|
| Harness links for `library` | Library-owned bootstrap receipt | `install.sh` creates only this conversational entrypoint and `register-bootstrap-receipts.py` records every exact symlink target. |
| Historical harness links for `skill-forge`, `agent-forge`, `standard-forge`, `script-forge`, and `hook-forge` | Library-owned direct roots awaiting `library-authoring` | Bootstrap no longer creates them. Exact surviving links are adopted into receipts; a later `library-authoring` registration may demote those direct roots without deleting files. Missing or foreign links are not recreated or claimed. |

## `project_tooling` writer

| Entry and target | Disposition | Writer-disable evidence |
|---|---|---|
| `beads-prime` -> `.beads/PRIME.md` | Retire distribution after the installed `bd prime` command is verified as the sole upstream source | Fleet inventory shows no consumer still reads the copied file. |
| `beads-server-mode` -> `.beads/metadata.json` fields | Project-owned Beads state | The Beads setup path enforces server mode; Workspace never owns or prunes the database metadata file. |
| `beads-post-commit-hook` -> `.git/hooks/post-commit` | Become a Guardrail/Hook primitive | Exact composed-hook receipts exist and preserve any foreign hook chain. |
| `gitleaks-pre-push-hook` -> `.git/hooks/pre-push` | Become a Guardrail/Hook primitive | Exact composed-hook receipts exist and preserve any foreign hook chain. |
| consumer/marketplace profiles -> `.gitignore` | Project-owned bootstrap policy | Each repository commits the intended lines; no Workspace receipt claims `.gitignore`. |

The `project_tooling` section and `sync_project_tooling.py` remain read-only for
new capability design and active only for these rows. Each row is removed in the
same reviewed repository change that proves its cutover gate, so no target has
two writers.

## Consumer updater writer

| Consumers | Target | Disposition | Cutover gate |
|---|---|---|---|
| `polaris`, `mira` | `scripts/refinement/check-seed-data-parity.py` | Become a first-class Script primitive required by the seed-data parity entrypoint | Both project locks contain a verified receipt and the target digest matches. |
| `polaris`, `mira` | `scripts/refinement/bead_status.py` | Become a first-class Script primitive required by the seed-data parity entrypoint | Both project locks contain a verified receipt and the target digest matches. |
| `polaris`, `mira` | `standard:seed-data-parity` refresh entry | Become a direct root or member of an admitted Workspace | Each project registers its replacement root before its consumer entry is removed. |

`update-consumers.py` stays dry-run by default during this transition. A consumer
entry is deleted only in the same reviewed change that installs and verifies all
three replacement receipts.

## External-manager inventory contract

An adapter returns canonical absolute destination paths together with one stable
manager name. `manager_inventory.py` provides the reference `chezmoi` adapter
using its read-only JSON inventory. Global Workspace first contact and prune
block on every overlap. An installed supported manager whose inventory command
fails is an operation failure, never an empty inventory.

This register is intentionally per target. A new wildcard, arbitrary copy rule,
or repository exception must not be added as a Workspace root.
