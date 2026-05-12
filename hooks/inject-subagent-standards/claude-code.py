#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pyyaml>=6.0"
# ]
# ///
"""
inject-subagent-standards.py — TaskCreated hook for conditional standards injection.

DEPRECATED (CL-717): This hook is scheduled for removal in Phase 3 of the standards-loading
migration (post-CL-717). Standards are now declared via `requires_standards:` frontmatter in
SKILL.md files and loaded via `standards-loader.sh`. This hook remains active during the
transition period to ensure no regressions in existing agent spawning.

Migration status: CL-717 complete — all skills have requires_standards frontmatter.
Removal target: Phase 3 (see docs/research/standards-loading.md#compatibility).

Fires before agent spawn. Reads the agent_label from the TaskCreated event,
looks up the matching pattern in ~/.claude/agent-standards.yml, and injects
standard file paths into the agent's system prompt when a match is found.

Behavior:
- CCP_NO_SUBAGENT_STANDARDS=1 → skip injection entirely (off-switch)
- No match or empty mapping → exit 0 silently (no injection)
- CCP_ORCHESTRATOR_RUN_ID set AND pattern in orchestrator_handled → skip (orchestrator pre-injected)
- Otherwise → output hookSpecificOutput.additionalSystemPrompt with paths

Exit codes:
- 0: always (fail-open — never block a spawn due to hook errors)
- 2: never used (TaskCreated is a blocking-capable hook, but we don't block on errors)

Performance: <100ms at p95. perf_counter_ns captured at module load.

Note: If `uv` is not installed, this script will fail to start (exit 1 from the launcher).
Exit 1 from a non-blocking hook is treated as a hook-error (non-blocking) — spawns proceed.
This is an acceptable trade-off: uv is a required tool in this workflow.
"""

import fnmatch
import json
import os
import sys
from pathlib import Path


def get_standards_file() -> Path:
    """Return path to agent-standards.yml. AGENT_STANDARDS_YML env var overrides default."""
    override = os.environ.get("AGENT_STANDARDS_YML")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "agent-standards.yml"


def load_standards_config(path: Path) -> dict | None:
    """
    Load and parse the agent-standards.yml file.

    Returns parsed dict on success, None on failure (logs warning to stderr).
    """
    import yaml  # noqa: PLC0415 — imported here to keep startup fast when yaml fails

    if not path.exists():
        print(
            f"inject-subagent-standards: warning: agent-standards.yml not found at {path}",
            file=sys.stderr,
        )
        return None

    try:
        content = path.read_text(encoding="utf-8")
        config = yaml.safe_load(content)
        if not isinstance(config, dict):
            print(
                f"inject-subagent-standards: warning: agent-standards.yml is not a YAML mapping at {path}",
                file=sys.stderr,
            )
            return None
        return config
    except Exception as e:
        print(
            f"inject-subagent-standards: warning: failed to parse agent-standards.yml: {e}",
            file=sys.stderr,
        )
        return None


def match_agent_label(label: str, mappings: dict) -> tuple[str | None, list[str]]:
    """
    Match agent_label against mapping keys using fnmatch glob.

    Agent labels use ':' as namespace separator (e.g. 'dev-tools:implementer'),
    while patterns use '/' (e.g. 'dev-tools/*'). Labels are normalized by
    replacing ':' with '/' before matching so patterns work naturally.

    Exact matches (no glob) are tried first against the raw label for backwards
    compatibility with labels like 'Explore', 'researcher', 'general-purpose'.

    Returns (matched_pattern, paths_list). If no match, returns (None, []).
    Keys are tried in definition order; first match wins.
    """
    normalized_label = label.replace(":", "/")
    for pattern, paths in mappings.items():
        # Try exact match on raw label first (for bare names like 'Explore')
        if fnmatch.fnmatch(label, pattern):
            return pattern, list(paths) if paths else []
        # Try normalized match (colon → slash) for namespaced labels
        if fnmatch.fnmatch(normalized_label, pattern):
            return pattern, list(paths) if paths else []
    return None, []


def main() -> None:
    # Read stdin event (fail-open on parse errors)
    try:
        raw = sys.stdin.read()
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"inject-subagent-standards: warning: invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(0)
    except OSError as e:
        print(f"inject-subagent-standards: warning: stdin read error: {e}", file=sys.stderr)
        sys.exit(0)

    # Off-switch: CCP_NO_SUBAGENT_STANDARDS=1 disables all injection
    if os.environ.get("CCP_NO_SUBAGENT_STANDARDS") == "1":
        sys.exit(0)

    # Extract agent label
    agent_label: str = event.get("agent_label", "")
    if not agent_label:
        sys.exit(0)

    # Load config
    standards_path = get_standards_file()
    config = load_standards_config(standards_path)
    if config is None:
        sys.exit(0)

    mappings: dict = config.get("mappings", {})
    orchestrator_handled: list[str] = config.get("orchestrator_handled", [])

    # Match agent label against patterns
    matched_pattern, paths = match_agent_label(agent_label, mappings)

    if matched_pattern is None:
        # No match → no injection
        sys.exit(0)

    if not paths:
        # Empty list → explicitly configured as no-injection
        sys.exit(0)

    # Check orchestrator bypass: if CCP_ORCHESTRATOR_RUN_ID is set AND the matched
    # pattern is listed in orchestrator_handled → orchestrator pre-injected, skip
    orchestrator_run_id = os.environ.get("CCP_ORCHESTRATOR_RUN_ID")
    if orchestrator_run_id:
        if matched_pattern in orchestrator_handled:
            # Orchestrator already handled this agent's standards
            sys.exit(0)

    # Build injection prompt with absolute paths.
    # Resolution order (project-local wins over user-global):
    #   1. <cwd>/.agents/standards/<path>
    #   2. ~/.agents/standards/<path>
    # Falls back to ~/.agents/standards/<path> when no project-local file exists,
    # so the agent gets a usable absolute path even if the file is missing on disk.
    proj_base = Path.cwd() / ".agents" / "standards"
    global_base = Path.home() / ".agents" / "standards"

    def resolve(rel: str) -> str:
        local = proj_base / rel
        if local.is_file():
            return str(local)
        return str(global_base / rel)

    abs_paths = [resolve(p) for p in paths]
    path_list = "\n".join(f"- {p}" for p in abs_paths)
    prompt = f"Load these standards before implementing:\n{path_list}"

    output = {"hookSpecificOutput": {"additionalSystemPrompt": prompt}}
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"inject-subagent-standards: unexpected error: {e}", file=sys.stderr)
        sys.exit(0)
