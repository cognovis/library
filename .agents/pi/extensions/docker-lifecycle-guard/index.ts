import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { isToolCallEventType, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

export type DockerCleanupReceipt = {
  contract: "ccore_docker_cleanup_v1";
  status: "completed" | "completed_with_warnings" | "not_applicable";
  removed_projects?: string[];
  retained_projects?: Array<{ project: string; reason: string }>;
};

function stringArray(value: unknown, field: string): string[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string")) {
    throw new Error(`ccore Docker cleanup ${field} is invalid`);
  }
  return [...value];
}

export function parseDockerCleanupReceipt(value: unknown): DockerCleanupReceipt {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("ccore Docker cleanup receipt must be an object");
  }
  const candidate = value as Record<string, unknown>;
  if (candidate.contract !== "ccore_docker_cleanup_v1") {
    throw new Error("ccore Docker cleanup contract is invalid");
  }
  if (!["completed", "completed_with_warnings", "not_applicable"].includes(String(candidate.status))) {
    throw new Error("ccore Docker cleanup receipt lacks a successful status");
  }
  const retained = candidate.retained_projects;
  if (
    retained !== undefined
    && (!Array.isArray(retained) || retained.some((entry) => {
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) return true;
      const item = entry as Record<string, unknown>;
      return typeof item.project !== "string" || typeof item.reason !== "string";
    }))
  ) throw new Error("ccore Docker cleanup retained_projects is invalid");
  return {
    contract: "ccore_docker_cleanup_v1",
    status: candidate.status as DockerCleanupReceipt["status"],
    ...(candidate.removed_projects !== undefined
      ? { removed_projects: stringArray(candidate.removed_projects, "removed_projects")! }
      : {}),
    ...(retained !== undefined
      ? { retained_projects: retained.map((entry) => ({ ...(entry as { project: string; reason: string }) })) }
      : {}),
  };
}

export type GuardRunner = (
  command: string,
  cwd: string,
) => Promise<{ exitCode: number; stderr: string }>;

export type DockerLifecycleDecision =
  | { allowed: true }
  | { allowed: false; reason: string };

export async function evaluateDockerLifecycleCommand(
  command: string,
  cwd: string,
  runGuard: GuardRunner,
): Promise<DockerLifecycleDecision> {
  try {
    const result = await runGuard(command, cwd);
    if (result.exitCode === 0) return { allowed: true };
    return {
      allowed: false,
      reason: result.stderr.trim() || `Core Docker ownership guard exited ${result.exitCode}`,
    };
  } catch (error) {
    return {
      allowed: false,
      reason: error instanceof Error ? error.message : String(error),
    };
  }
}

export function resolveCoreDockerGuard(environment: NodeJS.ProcessEnv = process.env): string {
  const candidates = [
    environment.COGNOVIS_DOCKER_GUARD_HOOK,
    environment.COGNOVIS_CORE_ROOT
      ? path.join(environment.COGNOVIS_CORE_ROOT, "hooks", "docker-stack-ownership-guard.py")
      : undefined,
    path.join(os.homedir(), "code", "library", "cognovis-core", "hooks", "docker-stack-ownership-guard.py"),
  ].filter((candidate): candidate is string => Boolean(candidate));
  const resolved = candidates.find((candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
  if (!resolved) {
    throw new Error(
      `Core Docker ownership guard unavailable; checked ${candidates.join(", ") || "no configured paths"}`,
    );
  }
  return resolved;
}

export function runCoreDockerGuard(
  command: string,
  cwd: string,
  environment: NodeJS.ProcessEnv = process.env,
): Promise<{ exitCode: number; stderr: string }> {
  return new Promise((resolve, reject) => {
    let stderr = "";
    const child = spawn(environment.PYTHON ?? "python3", [resolveCoreDockerGuard(environment)], {
      cwd,
      env: environment,
      stdio: ["pipe", "ignore", "pipe"],
    });
    child.stderr.on("data", (chunk: Buffer) => { stderr += chunk.toString(); });
    child.on("error", reject);
    child.on("close", (code) => resolve({ exitCode: code ?? 1, stderr }));
    child.stdin.end(JSON.stringify({ tool_name: "Bash", tool_input: { command } }));
  });
}

export function dockerLifecycleGuard(
  runGuard: GuardRunner = (command, cwd) => runCoreDockerGuard(command, cwd),
) {
  return function registerDockerLifecycleGuard(pi: ExtensionAPI): void {
    pi.on("tool_call", async (event, ctx) => {
      if (!isToolCallEventType("bash", event)) return;
      const decision = await evaluateDockerLifecycleCommand(event.input.command, ctx.cwd, runGuard);
      if (!decision.allowed) return { block: true, reason: decision.reason };
    });
  };
}

export default dockerLifecycleGuard();
