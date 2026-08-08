import { lstat, realpath } from "node:fs/promises";
import path from "node:path";

import type { AcpPermissionDecision, AcpPermissionRequest } from "acpx/runtime";

import type { WorkbenchProfile } from "./profile.ts";

export interface PermissionEvaluation {
  action: "approve" | "deny";
  decision: AcpPermissionDecision;
  policyId: "repository-safe-v1";
  tool: string;
  requestKind: string | null;
  reason: string;
  repositoryPath: string | null;
}

export interface PermissionCallbackFailure {
  stage: "permission-callback";
  code: "PERMISSION_CALLBACK_FAILED";
  state: "denied";
  message: "permission request rejected after evaluation or telemetry failure";
}

type PermissionTelemetryAppend = (
  type: "permission" | "failure",
  data: PermissionEvaluation | PermissionCallbackFailure,
) => Promise<void>;

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringAt(value: unknown, keys: readonly string[]): string | null {
  const candidate = record(value);
  if (!candidate) return null;
  for (const key of keys) {
    const entry = candidate[key];
    if (typeof entry === "string" && entry.trim()) return entry.trim();
  }
  return null;
}

export function permissionToolName(request: AcpPermissionRequest): string {
  const toolCall = request.raw.toolCall;
  const meta = record(toolCall._meta) ?? record((request.raw as { _meta?: unknown })._meta);
  const claude = record(meta?.claudeCode);
  const kind =
    (typeof toolCall.kind === "string" && toolCall.kind.trim()) ||
    request.inferredKind ||
    null;
  if (kind === "read") return "Read";
  if (kind === "search") return "Grep";
  if (kind === "execute") return "Bash";
  if (kind === "fetch") return "WebFetch";
  if (kind === "delete") return "Delete";
  if (kind === "move") return "Move";
  if (kind === "edit") {
    const title = toolCall.title?.trim().toLowerCase() ?? "";
    return title.startsWith("write") ? "Write" : "Edit";
  }
  const title = toolCall.title?.trim().toLowerCase() ?? "";
  const titleTool = [
    ["read", "Read"],
    ["write", "Write"],
    ["edit", "Edit"],
    ["grep", "Grep"],
    ["search", "Grep"],
    ["glob", "Glob"],
    ["bash", "Bash"],
    ["shell", "Bash"],
    ["fetch", "WebFetch"],
  ].find(([prefix]) => title === prefix || title.startsWith(`${prefix} `))?.[1];
  return (
    stringAt(claude, ["toolName"]) ??
    stringAt(toolCall.rawInput, ["name", "tool", "toolName"]) ??
    titleTool ??
    "unknown"
  );
}

export function deniedPermissionEvaluation(
  request: AcpPermissionRequest,
  reason: string,
): PermissionEvaluation {
  const requestKind =
    (typeof request.raw.toolCall.kind === "string" && request.raw.toolCall.kind.trim()) ||
    request.inferredKind ||
    null;
  return {
    action: "deny",
    decision: { outcome: "reject_once" },
    policyId: "repository-safe-v1",
    tool: permissionToolName(request),
    requestKind,
    reason,
    repositoryPath: null,
  };
}

const PATH_KEYS = new Set([
  "file_path",
  "filePath",
  "path",
  "notebook_path",
  "directory",
  "grantRoot",
]);

function collectPaths(value: unknown, paths: string[], depth = 0): void {
  if (depth > 8 || value === null || value === undefined) return;
  if (Array.isArray(value)) {
    for (const entry of value) collectPaths(entry, paths, depth + 1);
    return;
  }
  const candidate = record(value);
  if (!candidate) return;
  for (const [key, entry] of Object.entries(candidate)) {
    if (PATH_KEYS.has(key) && typeof entry === "string" && entry.trim()) {
      paths.push(entry.trim());
      continue;
    }
    collectPaths(entry, paths, depth + 1);
  }
}

function requestedPaths(request: AcpPermissionRequest): string[] {
  const paths: string[] = [];
  const toolCall = request.raw.toolCall;
  collectPaths(toolCall.rawInput, paths);
  collectPaths(toolCall.locations, paths);
  collectPaths(toolCall.content, paths);
  collectPaths((request.raw as { _meta?: unknown })._meta, paths);
  return [...new Set(paths)];
}

function isWithin(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

async function realExistingAncestor(candidate: string): Promise<string> {
  let current = candidate;
  while (true) {
    try {
      await lstat(current);
      return realpath(current);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      const parent = path.dirname(current);
      if (parent === current) throw new Error(`No existing ancestor for ${candidate}`);
      current = parent;
    }
  }
}

async function scopedPath(
  repositoryRoot: string,
  rawPath: string,
): Promise<{ allowed: boolean; relative: string | null }> {
  const lexicalRoot = path.resolve(repositoryRoot);
  const root = await realpath(lexicalRoot);
  const candidate = path.resolve(lexicalRoot, rawPath);
  const existing = await realExistingAncestor(candidate);
  if (!isWithin(root, existing)) return { allowed: false, relative: null };
  return { allowed: true, relative: path.relative(lexicalRoot, candidate) || "." };
}

export async function evaluatePermission(
  request: AcpPermissionRequest,
  repositoryRoot: string,
  policy: WorkbenchProfile["permissions"],
): Promise<PermissionEvaluation> {
  const tool = permissionToolName(request);
  const requestKind =
    (typeof request.raw.toolCall.kind === "string" && request.raw.toolCall.kind.trim()) ||
    request.inferredKind ||
    null;
  const deny = (reason: string): PermissionEvaluation =>
    deniedPermissionEvaluation(request, reason);
  if (!policy.allowedTools.includes(tool)) return deny("tool is not allowlisted");

  const paths = requestedPaths(request);
  if ((tool === "Read" || tool === "Edit" || tool === "Write") && paths.length === 0) {
    return deny("file operation did not identify a path");
  }
  const scopes = await Promise.all(paths.map((entry) => scopedPath(repositoryRoot, entry)));
  if (scopes.some((scope) => !scope.allowed)) return deny("path leaves repository scope");
  return {
    action: "approve",
    decision: { outcome: "allow_once" },
    policyId: "repository-safe-v1",
    tool,
    requestKind,
    reason: "allowlisted tool and repository-scoped path",
    repositoryPath: scopes[0]?.relative ?? ".",
  };
}

export async function decideAndRecordPermission(
  request: AcpPermissionRequest,
  repositoryRoot: string,
  policy: WorkbenchProfile["permissions"],
  append: PermissionTelemetryAppend,
): Promise<AcpPermissionDecision> {
  try {
    const evaluation = await evaluatePermission(request, repositoryRoot, policy);
    await append("permission", evaluation);
    return evaluation.decision;
  } catch {
    const denial = deniedPermissionEvaluation(request, "permission callback failed closed");
    const failure: PermissionCallbackFailure = {
      stage: "permission-callback",
      code: "PERMISSION_CALLBACK_FAILED",
      state: "denied",
      message: "permission request rejected after evaluation or telemetry failure",
    };
    try {
      await append("permission", denial);
    } catch {
      // Telemetry is best effort; the permission decision remains fail-closed.
    }
    try {
      await append("failure", failure);
    } catch {
      // Telemetry is best effort; the permission decision remains fail-closed.
    }
    return { outcome: "reject_once" };
  }
}
