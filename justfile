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
