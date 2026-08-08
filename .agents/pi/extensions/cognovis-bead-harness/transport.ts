import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import {
  buildAcpxClaudeEnsureInvocation,
  buildAcpxClaudeInvocation,
  parseAcpxJsonEvent,
} from "./acpx-transport.ts";
import type { BeadHarnessProfile, HarnessRole } from "./profile.ts";
import { runProcessTree } from "./process.ts";
import type { ChildInvocation } from "./runner.ts";

export const ROLE_REQUEST_SCHEMA = "cognovis.pi.bead-role-request.v1";
export const ROLE_RESPONSE_SCHEMA = "cognovis.pi.bead-role-response.v1";
const MAX_PROMPT_BYTES = 128 * 1024;

export type RoleRequest = {
  schema: typeof ROLE_REQUEST_SCHEMA;
  requestId: string;
  actor: string;
  sessionId: string;
  prompt: string;
  evidenceFile: string;
  verdictFile: string;
};

export type RoleResponse = {
  schema: typeof ROLE_RESPONSE_SCHEMA;
  requestId: string;
  actor: string;
  status: "complete" | "failed" | "aborted";
  exitCode: number;
  evidenceFile: string;
  verdictFile: string;
  transportSessionId?: string;
  reason?: string;
};

function inside(root: string, candidate: string): boolean {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}

function roleFor(profile: BeadHarnessProfile, actor: string): HarnessRole {
  const reviewer = profile.reviewers.find((item) => item.id === actor);
  if (reviewer) return reviewer;
  if (profile.adjudicator?.id === actor) return profile.adjudicator;
  throw new Error(`Role request has unknown actor: ${actor}`);
}

export function claimRoleArtifacts(request: RoleRequest, claims: Map<string, string>): void {
  const keys = [request.evidenceFile, request.verdictFile].map((artifact) => path.resolve(artifact));
  for (const key of keys) {
    const owner = claims.get(key);
    if (owner && owner !== request.requestId) throw new Error(`Role artifact is already claimed by ${owner}`);
  }
  for (const key of keys) claims.set(key, request.requestId);
}

export function claimRoleSession(
  request: RoleRequest,
  sessionActors: Map<string, string>,
  actorSessions: Map<string, string>,
): void {
  const sessionActor = sessionActors.get(request.sessionId);
  if (sessionActor && sessionActor !== request.actor) throw new Error(`Role session is already claimed by ${sessionActor}`);
  const actorSession = actorSessions.get(request.actor);
  if (actorSession && actorSession !== request.sessionId) throw new Error(`Role actor ${request.actor} changed session`);
  sessionActors.set(request.sessionId, request.actor);
  actorSessions.set(request.actor, request.sessionId);
}

export function parseRoleRequest(value: unknown, profile: BeadHarnessProfile, artifactsDir: string): RoleRequest {
  if (!value || typeof value !== "object") throw new Error("Role request must be an object");
  const item = value as Record<string, unknown>;
  if (item.schema !== ROLE_REQUEST_SCHEMA) throw new Error("Unsupported role request schema");
  for (const key of ["requestId", "actor", "sessionId", "prompt", "evidenceFile", "verdictFile"]) {
    if (typeof item[key] !== "string" || !item[key]) throw new Error(`Role request ${key} is required`);
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(String(item.requestId))) throw new Error("Role request id is invalid");
  const role = roleFor(profile, String(item.actor));
  if (Buffer.byteLength(String(item.prompt), "utf8") > MAX_PROMPT_BYTES) throw new Error("Role request prompt is too large");
  if (!inside(artifactsDir, String(item.evidenceFile)) || !inside(artifactsDir, String(item.verdictFile))) {
    throw new Error("Role request artifacts must stay inside the run artifact directory");
  }
  if (path.resolve(String(item.evidenceFile)) === path.resolve(String(item.verdictFile))) throw new Error("Role request artifacts must be distinct");
  if (role.transport === "direct-acpx" && role.harness !== "claude") throw new Error("Only Claude may use direct ACPX transport");
  return item as RoleRequest;
}

export function physicalRoleSessionName(artifactsDir: string, request: RoleRequest): string {
  const runDigest = createHash("sha256").update(path.basename(path.resolve(artifactsDir))).digest("hex").slice(0, 20);
  const actor = request.actor.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 32);
  const sessionDigest = createHash("sha256").update(request.sessionId).digest("hex").slice(0, 20);
  return `cognovis-${runDigest}-${actor}-${sessionDigest}`;
}

function acpxOptions(input: {
  role: HarnessRole;
  request: RoleRequest;
  systemPrompt: string;
  worktree: string;
  sessionDir: string;
  acpxCommand?: string;
  adapterCommand?: string;
  sessionName?: string;
}) {
  const mcpConfigPath = path.join(input.sessionDir, "mcp.json");
  fs.mkdirSync(input.sessionDir, { recursive: true, mode: 0o700 });
  fs.writeFileSync(mcpConfigPath, '{"mcpServers":[]}\n', { encoding: "utf8", mode: 0o600 });
  return {
    model: input.role.transportModel,
    cwd: input.worktree,
    prompt: input.request.prompt,
    systemPrompt: input.systemPrompt,
    tools: "read,grep,find,ls",
    timeoutMs: 60 * 60 * 1000,
    mcpConfigPath,
    ...(input.acpxCommand ? { acpxCommand: input.acpxCommand } : {}),
    ...(input.adapterCommand ? { adapterCommand: input.adapterCommand } : {}),
    sessionName: input.sessionName ?? input.request.sessionId,
  };
}

export function buildRoleInvocation(input: {
  role: HarnessRole;
  request: RoleRequest;
  systemPrompt: string;
  worktree: string;
  sessionDir: string;
  piCommand: string;
  piCommandPrefix?: string[];
  acpxCommand?: string;
  adapterCommand?: string;
  sessionName?: string;
}): ChildInvocation {
  if (input.role.transport === "direct-acpx") return buildAcpxClaudeInvocation(acpxOptions(input));
  return {
    command: input.piCommand,
    args: [
      ...(input.piCommandPrefix ?? []),
      "--mode", "json", "-p",
      "--session-dir", input.sessionDir,
      "--session-id", input.request.sessionId,
      "--no-skills", "--no-extensions", "--no-context-files", "--no-prompt-templates", "--no-themes",
      "--approve", "--offline",
      "--thinking", input.role.reasoning,
      "--model", input.role.transportModel,
      "--system-prompt", input.systemPrompt,
      "--tools", "read,grep,find,ls",
      input.request.prompt,
    ],
  };
}

function extractNativePiResult(line: string): { text?: string; stopReason?: string; error?: string } {
  try {
    const event = JSON.parse(line) as any;
    if (event.type !== "message_end" || event.message?.role !== "assistant") return {};
    const text = (event.message.content ?? []).filter((part: any) => part.type === "text" && typeof part.text === "string").map((part: any) => part.text).join("");
    return {
      ...(text ? { text } : {}),
      ...(typeof event.message.stopReason === "string" ? { stopReason: event.message.stopReason } : {}),
      ...(typeof event.message.errorMessage === "string" && event.message.errorMessage ? { error: event.message.errorMessage } : {}),
    };
  } catch { return {}; }
}

function atomicWrite(file: string, content: string): void {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.tmp-${process.pid}-${Date.now()}`;
  fs.writeFileSync(temporary, content, { encoding: "utf8", mode: 0o600 });
  fs.renameSync(temporary, file);
}

export async function executeRoleRequest(input: {
  profile: BeadHarnessProfile;
  request: RoleRequest;
  roleSystemPrompt: string;
  worktree: string;
  artifactsDir: string;
  piCommand: string;
  piCommandPrefix?: string[];
  signal: AbortSignal;
  onActivity: (text: string, stream: "stdout" | "stderr") => void;
  runProcess?: typeof runProcessTree;
}): Promise<RoleResponse> {
  const role = roleFor(input.profile, input.request.actor);
  const sessionDir = path.join(input.artifactsDir, "role-sessions", input.request.requestId);
  const localAcpx = path.resolve(process.cwd(), "node_modules/.bin/acpx");
  const localAdapter = path.resolve(process.cwd(), "node_modules/.bin/claude-agent-acp");
  const transportSessionName = physicalRoleSessionName(input.artifactsDir, input.request);
  const invocation = buildRoleInvocation({
    role,
    request: input.request,
    systemPrompt: input.roleSystemPrompt,
    worktree: input.worktree,
    sessionDir,
    piCommand: input.piCommand,
    ...(role.transport === "direct-acpx" ? { sessionName: transportSessionName } : {}),
    ...(input.piCommandPrefix ? { piCommandPrefix: input.piCommandPrefix } : {}),
    ...((process.env.COGNOVIS_PI_ACPX_COMMAND ?? (fs.existsSync(localAcpx) ? localAcpx : undefined))
      ? { acpxCommand: process.env.COGNOVIS_PI_ACPX_COMMAND ?? localAcpx }
      : {}),
    ...((process.env.COGNOVIS_PI_CLAUDE_ADAPTER_COMMAND ?? (fs.existsSync(localAdapter) ? localAdapter : undefined))
      ? { adapterCommand: process.env.COGNOVIS_PI_CLAUDE_ADAPTER_COMMAND ?? localAdapter }
      : {}),
  });
  fs.mkdirSync(path.dirname(input.request.evidenceFile), { recursive: true, mode: 0o700 });
  fs.writeFileSync(input.request.evidenceFile, "", { encoding: "utf8", mode: 0o600 });
  let buffer = "";
  let answer = "";
  let stopReason = "";
  let transportError = "";
  const runProcess = input.runProcess ?? runProcessTree;
  const recordEvidence = (text: string, stream: "stdout" | "stderr") => {
    fs.appendFileSync(input.request.evidenceFile, text, { encoding: "utf8", mode: 0o600 });
    input.onActivity(text.split("\n").map((line) => line ? `${role.harness} > ${line}` : line).join("\n"), stream);
  };
  const consume = (text: string, stream: "stdout" | "stderr") => {
    recordEvidence(text, stream);
    if (stream !== "stdout") return;
    buffer += text;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (role.transport === "direct-acpx") {
        try {
          const mapped = parseAcpxJsonEvent(JSON.parse(line));
          if (mapped.resetAnswer) answer = "";
          answer += mapped.text ?? "";
          if (mapped.stopReason) stopReason = mapped.stopReason;
          if (mapped.error) transportError = mapped.error;
        } catch { /* transport noise */ }
      } else {
        const mapped = extractNativePiResult(line);
        if (mapped.text !== undefined) answer = mapped.text;
        if (mapped.stopReason) stopReason = mapped.stopReason;
        if (mapped.error) transportError = mapped.error;
      }
    }
  };
  const isolatedEnvironment = role.transport === "direct-acpx"
    ? { ...process.env, COGNOVIS_PI_SESSION_ID: transportSessionName }
    : process.env;
  if (role.transport === "direct-acpx") {
    const ensure = buildAcpxClaudeEnsureInvocation(acpxOptions({
      role,
      request: input.request,
      systemPrompt: input.roleSystemPrompt,
      worktree: input.worktree,
      sessionDir,
      sessionName: transportSessionName,
      ...((process.env.COGNOVIS_PI_ACPX_COMMAND ?? (fs.existsSync(localAcpx) ? localAcpx : undefined))
        ? { acpxCommand: process.env.COGNOVIS_PI_ACPX_COMMAND ?? localAcpx }
        : {}),
      ...((process.env.COGNOVIS_PI_CLAUDE_ADAPTER_COMMAND ?? (fs.existsSync(localAdapter) ? localAdapter : undefined))
        ? { adapterCommand: process.env.COGNOVIS_PI_CLAUDE_ADAPTER_COMMAND ?? localAdapter }
        : {}),
    }));
    const ensured = await runProcess(
      ensure.command, ensure.args, input.worktree, input.signal, recordEvidence, 5_000, isolatedEnvironment,
    );
    if (ensured.exitCode !== 0 || ensured.aborted) {
      return {
        schema: ROLE_RESPONSE_SCHEMA, requestId: input.request.requestId, actor: input.request.actor,
        status: ensured.aborted ? "aborted" : "failed", exitCode: ensured.exitCode,
        evidenceFile: input.request.evidenceFile, verdictFile: input.request.verdictFile,
        transportSessionId: transportSessionName,
        reason: "direct ACPX session preflight failed",
      };
    }
  }
  buffer = "";
  answer = "";
  stopReason = "";
  transportError = "";
  const result = await runProcess(
    invocation.command, invocation.args, input.worktree, input.signal, consume, 5_000, isolatedEnvironment,
  );
  if (buffer) {
    if (role.transport === "direct-acpx") {
      try {
        const mapped = parseAcpxJsonEvent(JSON.parse(buffer));
        if (mapped.resetAnswer) answer = "";
        answer += mapped.text ?? "";
        if (mapped.stopReason) stopReason = mapped.stopReason;
        if (mapped.error) transportError = mapped.error;
      } catch { /* trailing transport noise */ }
    } else {
      const mapped = extractNativePiResult(buffer);
      if (mapped.text !== undefined) answer = mapped.text;
      if (mapped.stopReason) stopReason = mapped.stopReason;
      if (mapped.error) transportError = mapped.error;
    }
  }
  const acceptedStop = new Set(["end_turn", "stop", "complete", "completed"]);
  const status = result.aborted
    ? "aborted"
    : result.exitCode === 0 && answer.trim() && !transportError && acceptedStop.has(stopReason)
      ? "complete"
      : "failed";
  if (status === "complete") atomicWrite(input.request.verdictFile, `${answer.trim()}\n`);
  return {
    schema: ROLE_RESPONSE_SCHEMA,
    requestId: input.request.requestId,
    actor: input.request.actor,
    status,
    exitCode: result.exitCode,
    evidenceFile: input.request.evidenceFile,
    verdictFile: input.request.verdictFile,
    transportSessionId: role.transport === "direct-acpx" ? transportSessionName : input.request.sessionId,
    ...(status === "failed" ? { reason: transportError || (stopReason ? `role transport stopped with ${stopReason}` : answer.trim() ? "role transport exited without a terminal stop" : "role transport produced no terminal answer") } : {}),
  };
}
