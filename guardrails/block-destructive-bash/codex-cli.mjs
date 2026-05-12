#!/usr/bin/env node
/**
 * block-destructive-bash -- Codex CLI PreToolUse guardrail.
 *
 * Codex runs command hooks with a JSON payload on stdin. For PreToolUse, a
 * hook may block by exiting 0 and printing {"decision":"block","reason":"..."}
 * to stdout.
 */

import process from "node:process";

const input = await new Promise((resolve) => {
  let data = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    data += chunk;
  });
  process.stdin.on("end", () => resolve(data));
});

if (!input.trim()) {
  process.exit(0);
}

let payload;
try {
  payload = JSON.parse(input);
} catch {
  process.exit(0);
}

if (payload.tool_name !== "Bash") {
  process.exit(0);
}

const command = payload.tool_input?.command;
if (typeof command !== "string" || !command.trim()) {
  process.exit(0);
}

const checks = [
  {
    pattern: /(^|[\s;]|\|\||&&|\|)rm\s+(-[a-z]*r[a-z]*f[a-z]*|--recursive\s+--force|--force\s+--recursive)(\s|$)/i,
    reason: "Recursive forced delete (rm -rf) detected. This irreversibly deletes files.",
  },
  {
    pattern: /git\s+push(\s+\S+)*\s+(--force|-f)(\s|$)/i,
    reason: "Force push to git remote detected. This can overwrite remote history irreversibly.",
  },
  {
    pattern: /DROP\s+(TABLE|DATABASE|SCHEMA)\s/i,
    reason: "SQL DROP TABLE/DATABASE/SCHEMA detected. This irreversibly destroys data.",
  },
  {
    pattern: /TRUNCATE\s+(TABLE\s+)?[a-zA-Z]/i,
    reason: "SQL TRUNCATE TABLE detected. This irreversibly removes all rows from a table.",
  },
  {
    pattern: /(^|[\s;]|\|\||&&|\|)dd\s+.*of=\/dev\//i,
    reason: "dd writing to a block device detected. This can irreversibly overwrite disk data.",
  },
  {
    pattern: /(^|[\s;]|\|\||&&|\|)format\s+[a-zA-Z]:/i,
    reason: "Windows drive format command detected. This irreversibly destroys all data on the drive.",
  },
];

const match = checks.find((check) => check.pattern.test(command));
if (!match) {
  process.exit(0);
}

console.log(
  JSON.stringify({
    decision: "block",
    reason: `${match.reason}\n\nIf this operation is truly needed, ask the user for explicit permission and have them run the command manually.`,
  }),
);
