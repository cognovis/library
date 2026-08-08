import path from "node:path";

import type { BeadHarnessProfile } from "./profile.ts";

export type BeadInvocation = { beadId: string; worktree: string };
export type ChildInvocation = { command: string; args: string[] };

function tokens(input: string): string[] {
  return Array.from(input.matchAll(/"([^"]*)"|'([^']*)'|(\S+)/g), (match) => (match[1] ?? match[2] ?? match[3])!);
}

export function parseBeadInvocation(input: string): BeadInvocation {
  const parts = tokens(input.trim());
  const worktreeIndex = parts.indexOf("--worktree");
  if (worktreeIndex < 0 || !parts[worktreeIndex + 1]) throw new Error("--worktree PATH is required");
  const beadId = parts.find((part, index) => index !== worktreeIndex && index !== worktreeIndex + 1 && !part.startsWith("--"));
  if (!beadId || !/^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*$/.test(beadId)) throw new Error("A valid explicit Bead ID is required (hierarchical IDs such as cpi-123.1 are supported)");
  return { beadId, worktree: parts[worktreeIndex + 1]! };
}

export function ownerPrompt(profile: BeadHarnessProfile, beadId: string, worktree: string, artifactsDir: string, runId: string): string {
  const reviewers = profile.reviewers.map((reviewer) => `${reviewer.id}:${reviewer.role}:${reviewer.transport}/${reviewer.transportModel}:${reviewer.family}:${reviewer.perspective}`).join(", ");
  return [
    `Deliver exactly Bead ${beadId} in linked worktree ${worktree}.`,
    `Use execution mode auto and the validated ${profile.mode} Bead Harness preset.`,
    `Implementer route: ${profile.implementer.transport}/${profile.implementer.transportModel}.`,
    `Reviewer routes: ${reviewers}.`,
    profile.adjudicator ? `Registered adjudicator: ${profile.adjudicator.id}:${profile.adjudicator.role}:${profile.adjudicator.transport}/${profile.adjudicator.transportModel}:${profile.adjudicator.family}; use a session and artifacts distinct from both reviewers, and never reuse the boundary reviewer.` : "No adjudicator is permitted in standard mode.",
    `Maximum review waves: ${profile.maxReviewWaves}.`,
    `Bind the canonical cognovis.bead-harness-run.v2 run and every cognovis.bead-harness-event.v2 event to run_id ${runId}; pass --run-id ${runId}, reviewer route/model fields, and the profile adjudicator through --adjudicator-json when starting harness_contract.py.`,
    `Use execution_contract.py as the canonical TDD/MoC/commit owner and harness_contract.py only as the deterministic review contract. Persist harness state to ${artifactsDir}/harness-state.json and execution state to ${artifactsDir}/execution-state.json after every transition.`,
    `Each reviewer must write exactly one cognovis.bead-review-verdict.v1 to its bound per-wave verdict path. Call review-result with only the reviewer ID; never transcribe result or findings.`,
    `If Core reports adjudication_not_required, do not launch the adjudicator. Otherwise dispatch the registered adjudicator to its bound path for one cognovis.bead-review-adjudication.v1 and call adjudicate without typed dispositions.`,
    `At convergence export ${artifactsDir}/aggregate-review-gate.json with review_evidence_receipt_v1, advance execution review-clean exactly once, then pass execution state into harness MoC and commit transitions before Session Close.`,
    `Also append each new cognovis.bead-harness-event.v2 object to ${artifactsDir}/lifecycle.jsonl in sequence order.`,
    `Do not invoke any dispatch wrapper or launch reviewer processes yourself. Request each reviewer/adjudicator from the parent Pi extension by atomically writing ${artifactsDir}/role-requests/<requestId>.json with exactly {schema:"cognovis.pi.bead-role-request.v1",requestId,actor,sessionId,prompt,evidenceFile,verdictFile}; actor must be the registered profile id and both artifact paths must be the exact Core-bound paths inside ${artifactsDir}. Wait for the matching <requestId>.response.json and proceed only when its status is complete. The extension directly launches Claude through ACPX/claude-agent-acp and Codex/Kimi as native Pi children. Submit depth and boundary requests before waiting so they run as parallel siblings.`,

    `After focused verification and the clean commit, run ccore cleanup docker --bead ${beadId} > ${artifactsDir}/runtime-cleanup.json and require its typed successful result before delivery_pending.`,
    "Run exactly one Session Close only after the canonical contract reaches delivery_pending; its idempotent Docker cleanup remains the final fallback.",
  ].join("\n");
}

/** Build the clean native-Pi owner invocation. Claude children are direct ACPX
 * roles and Codex/Kimi children are native Pi roles; no skill wrapper owns
 * transport. */
export function buildOwnerInvocation(input: {
  piCommand: string;
  piCommandPrefix?: string[];
  systemPrompt: string;
  profile: BeadHarnessProfile;
  beadId: string;
  worktree: string;
  artifactsDir: string;
  runId: string;
  guardExtension: string;
}): ChildInvocation {
  const sessionDir = path.join(input.artifactsDir, "owner-session");
  const args = [
    ...(input.piCommandPrefix ?? []),
    "--mode", "json", "-p",
    "--session-dir", sessionDir,
    "--session-id", `${input.beadId}-cognovis-bead-${input.profile.mode}-${input.runId}`,
    "--no-extensions", "--extension", input.guardExtension,
    "--no-context-files", "--no-prompt-templates", "--no-themes",
    "--approve", "--offline",
    "--thinking", input.profile.implementer.reasoning,
    "--model", input.profile.implementer.transportModel,
    "--system-prompt", input.systemPrompt,
    ownerPrompt(input.profile, input.beadId, input.worktree, input.artifactsDir, input.runId),
  ];
  return { command: input.piCommand, args };
}
