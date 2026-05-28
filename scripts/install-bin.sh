#!/usr/bin/env bash
# scripts/install-bin.sh — Idempotently install cognovis-library/bin/ entries to ~/.local/bin/
#
# Purpose: Creates symlinks from ~/.local/bin/<name> → <repo>/bin/<name> for each launcher.
# Prerequisites: ~/.local/bin/ should be in $PATH (add to ~/.zshrc if missing).
# Usage: bash scripts/install-bin.sh
#        Safe to re-run — existing up-to-date symlinks are reported and skipped.
#
# Per ADR-0002 Decision 2: cld and cdx canonical source is cognovis-library/bin/.

set -euo pipefail

# Explicit allow-list — never symlink lib/ or other subdirectories automatically
LAUNCHERS=(cld cdx agr cra)

# Resolve absolute path of bin/ relative to this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN_DIR="$REPO_ROOT/bin"
DEST_DIR="${HOME}/.local/bin"

# Portable realpath (avoid GNU coreutils dependency)
_realpath() {
    python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$1"
}

mkdir -p "$DEST_DIR"

up_to_date=0
installed=0

for name in "${LAUNCHERS[@]}"; do
    src="$BIN_DIR/$name"
    dest="$DEST_DIR/$name"

    if [[ ! -f "$src" ]]; then
        echo "ERROR: $src not found — skipping $name"
        continue
    fi

    target="$(_realpath "$src")"

    if [[ -L "$dest" ]]; then
        current="$(readlink "$dest")"
        if [[ "$current" == "$target" ]]; then
            echo "$name: already up to date ($dest -> $target)"
            (( up_to_date++ )) || true
            continue
        fi
    elif [[ -e "$dest" ]]; then
        # Non-symlink file exists — back up before overwriting
        backup="${dest}.bak"
        echo "WARNING: $dest is a regular file (not a symlink). Backing up to $backup before replacing."
        mv "$dest" "$backup"
    fi

    ln -sfn "$target" "$dest"
    echo "$name: installed ($dest -> $target)"
    (( installed++ )) || true
done

if [[ "$up_to_date" -gt 0 && "$installed" -eq 0 ]]; then
    echo "All binaries already up to date — nothing to do."
fi

# PATH sanity check (warn-only)
case ":${PATH}:" in
    *":${DEST_DIR}:"*) ;;
    *) echo "WARNING: ${DEST_DIR} is not in \$PATH. Add to ~/.zshrc: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
