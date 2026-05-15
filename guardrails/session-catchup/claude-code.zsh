#!/usr/bin/env zsh
# session-catchup.zsh - SessionStart hook: pull + show what changed since last session
# Stores timestamp per project in ~/.claude/session-state/<project>.timestamp

set -euo pipefail

# Config
STATE_DIR="${HOME}/.claude/session-state"
mkdir -p "$STATE_DIR"

# Derive project name from git toplevel (fallback: directory name)
if git rev-parse --show-toplevel &>/dev/null; then
    PROJECT_NAME=$(basename "$(git rev-parse --show-toplevel)")
else
    PROJECT_NAME=$(basename "$PWD")
fi

TIMESTAMP_FILE="${STATE_DIR}/${PROJECT_NAME}.timestamp"

# Read last session timestamp
LAST_TS=""
LAST_TS_HUMAN=""
if [[ -f "$TIMESTAMP_FILE" ]]; then
    LAST_TS=$(cat "$TIMESTAMP_FILE")
    # Convert epoch to human-readable
    LAST_TS_HUMAN=$(date -r "$LAST_TS" "+%Y-%m-%d %H:%M" 2>/dev/null || date -d "@$LAST_TS" "+%Y-%m-%d %H:%M" 2>/dev/null || echo "$LAST_TS")
fi

# Git pull (safe, fast-forward only)
if git rev-parse --is-inside-work-tree &>/dev/null; then
    git_pull_output=$(git pull --ff-only -q 2>&1) || true
    if [[ -n "$git_pull_output" && "$git_pull_output" != *"Already up to date"* ]]; then
        echo "$git_pull_output"
    fi
fi

# Beads dolt pull
if [[ -d ".beads" ]] && command -v bd &>/dev/null; then
    bd dolt pull 2>/dev/null || true
fi

# Show changes since last session
if [[ -z "$LAST_TS" ]]; then
    echo ""
    echo "## Session Catchup"
    echo ""
    echo "First session tracked for **${PROJECT_NAME}**. Changes will be shown next time."
else
    SINCE_DATE=$(date -r "$LAST_TS" "+%Y-%m-%dT%H:%M:%S" 2>/dev/null || date -d "@$LAST_TS" --iso-8601=seconds 2>/dev/null || echo "")

    has_output=false

    if [[ -n "$SINCE_DATE" ]] && git rev-parse --is-inside-work-tree &>/dev/null; then
        # All commits since last session - no author filtering
        all_commits=$(git log --since="$SINCE_DATE" --format="%h %s - %an <%ar>" 2>/dev/null || true)

        if [[ -n "$all_commits" ]]; then
            commit_count=$(echo "$all_commits" | wc -l | tr -d ' ')
            echo ""
            echo "## Session Catchup (since ${LAST_TS_HUMAN})"
            echo "<!-- last_session_ts:${LAST_TS} -->"
            echo ""
            has_output=true

            echo "### Commits (${commit_count})"
            echo "$all_commits" | head -30
            if (( commit_count > 30 )); then
                echo "  ... and $(( commit_count - 30 )) more"
            fi
            echo ""
        fi
    fi

    # Beads changes
    if [[ -d ".beads" ]] && command -v bd &>/dev/null; then
        since_date_ymd=$(date -r "$LAST_TS" "+%Y-%m-%d" 2>/dev/null || date -d "@$LAST_TS" "+%Y-%m-%d" 2>/dev/null || echo "")

        if [[ -n "$since_date_ymd" ]]; then
            new_beads=$(bd list --created-after "$since_date_ymd" --flat 2>/dev/null || true)
            updated_beads=$(bd list --updated-after "$since_date_ymd" --flat --all 2>/dev/null || true)

            if [[ -n "$new_beads" || -n "$updated_beads" ]]; then
                if [[ "$has_output" == false ]]; then
                    echo ""
                    echo "## Session Catchup (since ${LAST_TS_HUMAN})"
                    echo "<!-- last_session_ts:${LAST_TS} -->"
                    echo ""
                    has_output=true
                fi
                echo "### Beads activity"

                if [[ -n "$new_beads" ]]; then
                    echo "**New:**"
                    echo "$new_beads" | head -15
                    echo ""
                fi

                if [[ -n "$updated_beads" ]]; then
                    echo "**Updated:**"
                    echo "$updated_beads" | head -15
                    echo ""
                fi
            fi
        fi
    fi

    if [[ "$has_output" == false ]]; then
        echo ""
        echo "## Session Catchup (since ${LAST_TS_HUMAN})"
        echo "<!-- last_session_ts:${LAST_TS} -->"
        echo ""
        echo "No changes since last session."
    fi
fi

# Generate spinner tips from catchup data
# Tips show in the spinner while Claude works - one random tip per spin
LOCAL_SETTINGS=".claude/settings.local.json"
if [[ -f "$LOCAL_SETTINGS" ]] && command -v jq &>/dev/null; then
    tips=()

    # Add today's date as context
    tips+=("$(date '+%A, %d. %B %Y') - ${PROJECT_NAME}")

    if [[ -n "$LAST_TS" ]]; then
        SINCE_DATE_TIPS=$(date -r "$LAST_TS" "+%Y-%m-%dT%H:%M:%S" 2>/dev/null || echo "")

        # Commit subjects as tips (last 10, one-liners)
        if [[ -n "$SINCE_DATE_TIPS" ]] && git rev-parse --is-inside-work-tree &>/dev/null; then
            while IFS= read -r line; do
                [[ -n "$line" ]] && tips+=("$line")
            done < <(git log --since="$SINCE_DATE_TIPS" --format="Commit: %s - %an" 2>/dev/null | head -10)
        fi

        # Bead activity as tips
        if [[ -d ".beads" ]] && command -v bd &>/dev/null; then
            since_ymd=$(date -r "$LAST_TS" "+%Y-%m-%d" 2>/dev/null || echo "")
            if [[ -n "$since_ymd" ]]; then
                while IFS= read -r line; do
                    [[ -n "$line" ]] && tips+=("New: $line")
                done < <(bd list --created-after "$since_ymd" --flat 2>/dev/null | head -5)
                while IFS= read -r line; do
                    [[ -n "$line" ]] && tips+=("Updated: $line")
                done < <(bd list --updated-after "$since_ymd" --flat --all 2>/dev/null | head -5)
            fi
        fi
    fi

    # Also add today's commits (even if session-start was today - gives "what happened today" view)
    today_ymd=$(date "+%Y-%m-%d")
    if git rev-parse --is-inside-work-tree &>/dev/null; then
        while IFS= read -r line; do
            # Deduplicate: skip if already in tips from session delta
            local already=false
            for t in "${tips[@]}"; do
                [[ "$t" == *"$line"* ]] && already=true && break
            done
            [[ "$already" == false && -n "$line" ]] && tips+=("Today: $line")
        done < <(git log --since="$today_ymd" --format="%s - %an" 2>/dev/null | head -5)
    fi

    # Write tips to settings.local.json via jq (merge, don't overwrite)
    if (( ${#tips[@]} > 1 )); then
        tips_json=$(printf '%s\n' "${tips[@]}" | jq -R . | jq -s .)
        tmp=$(mktemp)
        jq --argjson tips "$tips_json" '.spinnerTipsOverride = {"excludeDefault": false, "tips": $tips}' "$LOCAL_SETTINGS" > "$tmp" 2>/dev/null && mv "$tmp" "$LOCAL_SETTINGS"
    else
        # No interesting tips - remove override if present
        tmp=$(mktemp)
        jq 'del(.spinnerTipsOverride)' "$LOCAL_SETTINGS" > "$tmp" 2>/dev/null && mv "$tmp" "$LOCAL_SETTINGS"
    fi
fi

# Write new timestamp
date +%s > "$TIMESTAMP_FILE"
