#!/usr/bin/env zsh
# lib/orchestrator-config-sync.zsh — keep ~/.agents/orchestrator-config.yml current.
#
# The global orchestrator routing config (~/.agents/orchestrator-config.yml) is the
# fallback the launchers read when a project has no project-local
# .agents/orchestrator-config.yml. Unlike skills/agents/model-standards it has no
# catalog-managed deploy, so the global copy used to be hand-placed once and then
# silently drift from the canonical source (see CL-0w6e: an opus model bump in the
# source never reached the deployed config).
#
# This pre-flight refreshes the global config idempotently from the installed
# catalog clone (or, on dev machines, the sibling cognovis-core checkout) on every
# `cld`/`cdx` launch — self-healing and non-fatal. Project-local
# .agents/orchestrator-config.yml files are committed per project and are NOT
# touched here.

# _sync_orchestrator_config
#
# Copies the canonical orchestrator-config.yml to ~/.agents/orchestrator-config.yml
# when the global copy is missing or differs. Silent when already current or when
# no source is available. Never fails the launch.
_sync_orchestrator_config() {
    local dst="${HOME}/.agents/orchestrator-config.yml"
    local rel="orchestrator-config.yml"
    local src="" candidate

    # Source priority: installed catalog clone first (what `library sync` keeps
    # current), then the dev sibling checkout for machines that work on the catalog.
    for candidate in \
        "${HOME}/.local/share/library/cognovis-library-core/.agents/${rel}" \
        "${HOME}/code/library/cognovis-core/.agents/${rel}"; do
        if [[ -f "$candidate" ]]; then
            src="$candidate"
            break
        fi
    done

    [[ -n "$src" ]] || return 0                       # no source available — skip
    if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
        return 0                                       # already current
    fi

    mkdir -p "${dst:h}" 2>/dev/null || return 0
    if cp -f "$src" "$dst" 2>/dev/null; then
        print -r -- "[orchestrator-config] refreshed ${dst/#$HOME/~} from ${src/#$HOME/~}" >&2
    fi
    return 0
}
