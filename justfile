set dotenv-load := true

# List available commands
default:
    @just --list

# Install the library (first-time setup)
install:
    claude --dangerously-skip-permissions --model opus "/library install"

# Add a new skill, agent, or prompt to the catalog
add prompt:
    claude --dangerously-skip-permissions --model opus "/library add {{prompt}}"

# Pull a skill from the catalog (install or refresh)
use name:
    claude --dangerously-skip-permissions --model opus "/library use {{name}}"

# Push local changes back to the source
push name:
    claude --dangerously-skip-permissions --model opus "/library push {{name}}"

# Remove a locally installed skill
remove name:
    claude --dangerously-skip-permissions --model opus "/library remove {{name}}"

# Sync all installed items (re-pull from source)
sync:
    claude --dangerously-skip-permissions --model opus "/library sync"

# List all entries in the catalog with install status
list:
    claude --dangerously-skip-permissions --model opus "/library list"

# Search the catalog by keyword
search keyword:
    claude --dangerously-skip-permissions --model opus "/library search {{keyword}}"

# Validate library.yaml against the JSON Schema
validate-library:
    python3 scripts/validate-library.py

# Run cross-harness smoke tests (harness: claude-code | codex | pi | opencode | all)
test-smoke harness="all":
    bash tests/smoke/run-smoke.sh {{harness}}

# ── cdx: Codex launcher with beads workflow integration ──────────

# Install the cdx script to ~/.local/bin/cdx (Codex parallel to cld)
install-cdx:
    #!/usr/bin/env bash
    set -euo pipefail
    INSTALL_DIR="${HOME}/.local/bin"
    mkdir -p "${INSTALL_DIR}"
    cp scripts/cdx "${INSTALL_DIR}/cdx"
    chmod +x "${INSTALL_DIR}/cdx"
    echo "cdx installed to ${INSTALL_DIR}/cdx"
    if ! echo "${PATH}" | grep -q "${INSTALL_DIR}"; then
        echo "NOTE: ${INSTALL_DIR} is not in your PATH. Add it to your shell profile:"
        echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi

# Launch Codex on a specific bead (orchestrator mode, equivalent to cld -b)
cdx bead-id:
    cdx -b {{bead-id}}

# Launch Codex in quick-fix mode for a bead (equivalent to cld -bq)
cdx-quick bead-id:
    cdx -bq {{bead-id}}

# Launch Codex in review mode for a bead (equivalent to cld -br; warns about limitations)
cdx-review bead-id:
    cdx -br {{bead-id}}
