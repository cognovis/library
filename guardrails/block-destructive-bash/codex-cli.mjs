/**
 * block-destructive-bash — Codex CLI SessionStart guardrail
 *
 * Codex CLI has no PreToolUse event (only SessionStart, SessionEnd, Stop).
 * This hook injects a WARNING into the session context at startup to
 * discourage destructive commands. Effectiveness is advisory, not hard-blocking.
 *
 * Installation:
 *   1. Copy this file to your Codex hooks directory
 *   2. Register in hooks.json:
 *      {
 *        "hooks": {
 *          "SessionStart": [
 *            { "matcher": "", "script": ".codex/hooks/block-destructive-bash.mjs" }
 *          ]
 *        }
 *      }
 *
 * Codex CLI hook contract:
 *   - SessionStart hooks run at session initialization
 *   - Hooks can output text that is prepended to the system context
 *   - No exit-code blocking (Codex CLI lacks PreToolUse gate)
 *
 * References:
 *   - docs/research/codex-prompts.md (CL-qzw)
 *   - library.yaml guardrails[block-destructive-bash]
 *
 * CAPABILITY NOTE: This is a reduced-capability installation.
 * Claude Code's PreToolUse hook provides hard blocking; this provides
 * advisory injection only. See docs/research/guardrails-mapping.md for
 * the capability mismatch table.
 */

export default {
  name: "block-destructive-bash",

  async onSessionStart(context) {
    const warningMessage = `
GUARDRAIL ACTIVE: block-destructive-bash
=========================================
The following operations require explicit human approval before execution:
  - Recursive forced deletes (rm -rf)
  - Force-pushes to git remotes (git push --force / git push -f)
  - SQL DDL that destroys data (DROP TABLE, DROP DATABASE, TRUNCATE TABLE)
  - Low-level disk writes (dd if=... of=/dev/...)
  - Drive formatting commands (format C: or equivalent)

If you need to run any of these operations, STOP and ask the user for
explicit permission. The user must confirm and run the command manually.

Rationale: These operations cannot be undone. The model may not have full
context about the consequences — always defer to human judgment.
=========================================
`.trim();

    // Inject the warning into session context
    // Codex CLI will prepend this to the model's system context
    return {
      systemContextAddition: warningMessage,
    };
  },
};
