#!/usr/bin/env bash
# install.sh — Bootstrap installer for The Library.
#
# Purpose: Make The Library available as a `library` command across whichever
# coding harnesses (Claude Code, Codex, OpenCode, Pi…) are present on this
# machine. Per ADR-0004 Decision 8, the library is installable software that
# the harnesses use — not a Claude-only skill.
#
# Usage:
#     cd <library-meta-checkout>
#     bash install.sh
#
# Safe to re-run. Idempotent.
#
# Post-install:
#   - `library` works in any shell (when bin/library is provided; today
#     it points at the SKILL.md-based slash-command flow).
#   - `/library <verb>` works in every present harness.
#   - Updates: `library update library` (re-runs this install.sh from the
#     latest remote main of the meta repo).

set -euo pipefail

# Resolve absolute path of this checkout
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
META_ROOT="$SCRIPT_DIR"

# Portable realpath
_realpath() {
    python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$1"
}

# Idempotent symlink helper: ln -sfn with backup of non-symlink targets
_link() {
    local src="$1" dest="$2"
    local target
    target="$(_realpath "$src")"

    if [[ -L "$dest" ]]; then
        local current
        current="$(readlink "$dest")"
        if [[ "$current" == "$target" ]]; then
            echo "  ok    $dest"
            return 0
        fi
    elif [[ -e "$dest" ]]; then
        local backup="${dest}.bak"
        echo "  back  $dest -> $backup (was regular file)"
        mv "$dest" "$backup"
    fi

    mkdir -p "$(dirname "$dest")"
    ln -sfn "$target" "$dest"
    echo "  link  $dest -> $target"
}

echo "Library bootstrap from: $META_ROOT"

# --- Phase 1: bin/library command (if/when provided) -----------------------
# Today: bin/library does not yet exist as a standalone CLI. The library
# logic lives in SKILL.md + cookbook/ and runs via harness slash-commands.
# When bin/library lands in this repo (planned per ADR-0004 Decision 8), the
# block below activates and installs it to ~/.local/bin/library.

if [[ -f "$META_ROOT/bin/library" ]]; then
    echo ""
    echo "Installing CLI:"
    LOCAL_BIN="${HOME}/.local/bin"
    _link "$META_ROOT/bin/library" "$LOCAL_BIN/library"
    case ":${PATH}:" in
        *":${LOCAL_BIN}:"*) ;;
        *) echo "  warn  ${LOCAL_BIN} is not in \$PATH; add to ~/.zshrc:"
           echo "        export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
fi

# --- Phase 2: harness skill/command entries --------------------------------
# Detect each harness by the presence of its global dir. For every present
# harness, create skill entries pointing back at this meta checkout.
# Until the harness has its own protocol-specific surface file (e.g. SKILL.md
# for Claude Code, .toml for Codex), we install SKILL.md directories as the
# universal agentskills.io entry — Codex CLI accepts SKILL.md too.

declare -a PLATFORM_SKILLS=(
    "library:${META_ROOT}"
    "skill-forge:${META_ROOT}/skills/skill-forge"
    "agent-forge:${META_ROOT}/skills/agent-forge"
    "standard-forge:${META_ROOT}/skills/standard-forge"
    "script-forge:${META_ROOT}/skills/script-forge"
    "hook-forge:${META_ROOT}/skills/hook-forge"
)

declare -a HARNESS_SKILL_ROOTS=(
    "claude:${HOME}/.claude/skills"
    "codex:${HOME}/.codex/skills"
    "agents:${HOME}/.agents/skills"
    "opencode:${HOME}/.opencode/skills"
)

echo ""
echo "Installing harness skill entries:"

installed_any=0
for entry in "${HARNESS_SKILL_ROOTS[@]}"; do
    harness="${entry%%:*}"
    skill_root="${entry#*:}"
    parent="$(dirname "$skill_root")"   # e.g. ~/.claude

    if [[ ! -d "$parent" ]]; then
        echo "  skip  $harness (no $parent)"
        continue
    fi

    for platform_skill in "${PLATFORM_SKILLS[@]}"; do
        skill_name="${platform_skill%%:*}"
        src_dir="${platform_skill#*:}"

        if [[ ! -d "$src_dir" ]]; then
            echo "  warn  $skill_name source missing at $src_dir"
            continue
        fi

        _link "$src_dir" "$skill_root/$skill_name"
        (( installed_any++ )) || true
    done
done

if [[ "$installed_any" -eq 0 ]]; then
    echo "  warn  No harnesses detected. Library content installed at $META_ROOT"
    echo "        but no slash-command entry points were created."
fi

# --- Phase 3: library home for cache + state -------------------------------
# Per ADR-0003 Decision 3: the cache lives at ~/.local/share/library/.
# Pre-create so that /library use does not have to bootstrap it lazily.

LIBRARY_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}/library"
mkdir -p "$LIBRARY_HOME/skills" "$LIBRARY_HOME/agents" "$LIBRARY_HOME/prompts" "$LIBRARY_HOME/hooks"
echo ""
echo "Library cache home: $LIBRARY_HOME"

# --- Phase 4: summary ------------------------------------------------------

echo ""
echo "Done."
echo ""
echo "Next steps:"
echo "  - In any harness: /library list"
echo "  - Platform forges are installed globally: skill-forge, agent-forge, standard-forge, script-forge, hook-forge"
echo "  - To install a primitive transitively: /library use <name>"
echo "  - To update the library itself: /library update library"
echo ""
echo "If you wipe ~/.claude/ or ~/.codex/, re-run: cd $META_ROOT && bash install.sh"
