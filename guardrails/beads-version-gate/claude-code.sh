#!/usr/bin/env bash
# Beads version gate: blocks Claude if local bd version != latest GitHub release.
# Works on macOS, Linux, Windows (Git Bash/WSL/MSYS2).
# Runs at SessionStart - checks once per session.

set -euo pipefail

# Extract semver from a string (portable: tries grep -oE, falls back to python3)
extract_version() {
  echo "$1" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' 2>/dev/null | head -1 ||
  echo "$1" | python3 -c "import re,sys; m=re.search(r'(\d+\.\d+\.\d+)',sys.stdin.read()); print(m.group(1) if m else '')" 2>/dev/null ||
  echo ""
}

# Get installed version
BD_OUTPUT="$(bd version 2>/dev/null)" || BD_OUTPUT=""
LOCAL_VERSION="$(extract_version "$BD_OUTPUT")"

if [ -z "$LOCAL_VERSION" ]; then
  echo "WARNING: Could not determine local beads (bd) version. Is bd installed?"
  exit 1
fi

# Get latest published GitHub release (source of truth, platform-independent)
REMOTE_RAW=""
if command -v gh &>/dev/null; then
  REMOTE_RAW="$(gh release view --repo steveyegge/beads --json tagName -q '.tagName' 2>/dev/null)" || REMOTE_RAW=""
fi
if [ -z "$REMOTE_RAW" ] && command -v curl &>/dev/null; then
  REMOTE_RAW="$(curl -sf 'https://api.github.com/repos/steveyegge/beads/releases/latest' 2>/dev/null |
    python3 -c "import json,sys; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null)" || REMOTE_RAW=""
fi
if [ -z "$REMOTE_RAW" ] && command -v wget &>/dev/null; then
  REMOTE_RAW="$(wget -qO- 'https://api.github.com/repos/steveyegge/beads/releases/latest' 2>/dev/null |
    python3 -c "import json,sys; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null)" || REMOTE_RAW=""
fi

REMOTE_VERSION="$(extract_version "$REMOTE_RAW")"

if [ -z "$REMOTE_VERSION" ]; then
  echo "WARNING: Could not fetch latest beads release from GitHub (network issue?). Continuing with local v${LOCAL_VERSION}."
  exit 0
fi

if [ "$LOCAL_VERSION" != "$REMOTE_VERSION" ]; then
  cat <<EOF
BLOCKED: beads version mismatch.

  Installed: v${LOCAL_VERSION}
  Published: v${REMOTE_VERSION} (github.com/steveyegge/beads)

Update beads before working in this project:

  macOS:   brew update && brew upgrade beads
  Linux:   Download from https://github.com/steveyegge/beads/releases/latest
  Windows: scoop update beads  OR  download from https://github.com/steveyegge/beads/releases/latest

All team members MUST use the same beads version to prevent
Dolt schema conflicts and data loss on the shared remote database.
EOF
  exit 1
fi

echo "beads v${LOCAL_VERSION} (matches latest release)"
