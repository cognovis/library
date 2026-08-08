import { readFileSync } from "node:fs";
import path from "node:path";

export type FusionRole = "architect" | "builder" | "reviewer" | "validator";
export type ThinkingLevel =
  | "off"
  | "minimal"
  | "low"
  | "medium"
  | "high"
  | "xhigh"
  | "max";

export interface FusionProfile {
  schema: "cognovis.pi.fusion-profile.v1";
  id: string;
  version: string;
  roles: Record<FusionRole, string>;
  thinking: Record<FusionRole, ThinkingLevel>;
}

const DEFAULT_PROFILE: FusionProfile = {
  schema: "cognovis.pi.fusion-profile.v1",
  id: "fusion-default",
  version: "1.0.0",
  roles: {
    architect: "acpx-claude/opus[1m]",
    builder: "openai-codex/gpt-5.6-sol",
    reviewer: "acpx-claude/claude-fable-5[1m]",
    validator: "acpx-claude/opus[1m]",
  },
  thinking: {
    architect: "xhigh",
    builder: "xhigh",
    reviewer: "xhigh",
    validator: "xhigh",
  },
};

const THINKING_LEVELS = new Set<ThinkingLevel>([
  "off",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
]);

function assertProfile(value: unknown): asserts value is FusionProfile {
  if (!value || typeof value !== "object") {
    throw new Error("Fusion profile must be an object");
  }
  const candidate = value as Partial<FusionProfile>;
  if (candidate.schema !== "cognovis.pi.fusion-profile.v1") {
    throw new Error("Unsupported Fusion profile schema");
  }
  if (!candidate.id || !candidate.version) {
    throw new Error("Fusion profile requires id and version");
  }
  for (const role of ["architect", "builder", "reviewer", "validator"] as const) {
    const model = candidate.roles?.[role];
    if (typeof model !== "string" || !model.includes("/")) {
      throw new Error(`Fusion role ${role} must use a provider-qualified model`);
    }
    if (role === "reviewer" && !model.startsWith("acpx-claude/")) {
      throw new Error("Fusion reviewer must use the ACPX Claude adapter");
    }
    if (role === "builder" && model.startsWith("acpx-claude/")) {
      throw new Error("Fusion builder must use a native Pi provider");
    }
    if (!THINKING_LEVELS.has(candidate.thinking?.[role] as ThinkingLevel)) {
      throw new Error(`Fusion role ${role} has an invalid thinking level`);
    }
  }
}

export function loadFusionProfile(
  environment: NodeJS.ProcessEnv = process.env,
): FusionProfile {
  const configuredPath = environment.COGNOVIS_PI_FUSION_PROFILE?.trim();
  if (!configuredPath) return DEFAULT_PROFILE;
  const absolutePath = path.resolve(configuredPath);
  const parsed: unknown = JSON.parse(readFileSync(absolutePath, "utf8"));
  assertProfile(parsed);
  return parsed;
}
