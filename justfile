set dotenv-load := true

# List available commands
default:
    @just --list

# Install the library (first-time setup)
install:
    bash install.sh

# Add a new skill, agent, or prompt to the catalog
add prompt:
    library add {{prompt}}

# Pull a skill from the catalog (install or refresh)
use name:
    library use {{name}}

# Push local changes back to the source
push name:
    library push {{name}}

# Remove a locally installed skill
remove name:
    library remove {{name}}

# Sync all installed items (re-pull from source)
sync:
    library sync

# List all entries in the catalog with install status
list:
    library list

# Search the catalog by keyword
search keyword:
    library search {{keyword}}

# Validate library.yaml against the JSON Schema
validate-library:
    uv run scripts/validate-library.py

# Run cross-harness smoke tests (harness: claude-code | codex | pi | opencode | all)
test-smoke harness="all":
    bash tests/smoke/run-smoke.sh {{harness}}

# Launch Codex on a specific bead (orchestrator mode, equivalent to cld -b)
cdx bead-id:
    cdx -b {{bead-id}}

# Launch Codex in quick-fix mode for a bead (equivalent to cld -bq)
cdx-quick bead-id:
    cdx -bq {{bead-id}}

# Launch the shared Bead review path with a Codex reviewer
cdx-review bead-id:
    cdx -br {{bead-id}}
