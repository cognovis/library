#!/usr/bin/env bash
# install-bin.sh — Idempotent symlink installer for cognovis-library/bin/
#
# Purpose: Install cld/cdx launchers from cognovis-library/bin/ into ~/.local/bin/
#          via symlinks, so updates to this repo are immediately reflected.
#
# Prerequisites:
#   - Run from the repo root (cognovis-library/) or any subdirectory
#   - ~/.local/bin/ should be in $PATH (add to ~/.zshrc if not)
#
# Usage:
#   bash scripts/install-bin.sh
#
# Idempotent: safe to run multiple times. Existing symlinks are updated with
# ln -sfn (no-op if the target is already correct). Reports status per file.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$REPO_ROOT/bin"
DEST_DIR="$HOME/.local/bin"

if [[ ! -d "$BIN_DIR" ]]; then
  echo "ERROR: bin/ directory not found at $BIN_DIR" >&2
  exit 1
fi

# Ensure destination exists
if [[ ! -d "$DEST_DIR" ]]; then
  mkdir -p "$DEST_DIR"
  echo "Created $DEST_DIR"
fi

any_changed=false

for src in "$BIN_DIR"/*; do
  name="$(basename "$src")"
  dest="$DEST_DIR/$name"
  target="$(realpath "$src")"

  if [[ -L "$dest" && "$(readlink "$dest")" == "$target" ]]; then
    echo "$name: already up to date ($dest -> $target)"
  else
    ln -sfn "$target" "$dest"
    any_changed=true
    echo "$name: installed ($dest -> $target)"
  fi
done

if [[ "$any_changed" == false ]]; then
  echo "All binaries already up to date — nothing to do."
fi

exit 0
