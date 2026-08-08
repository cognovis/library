import fs from "node:fs";
import path from "node:path";

import type { FocusRole, NativePackProfile, NativeRole, ThinkingLevel } from "./types.ts";

const THINKING = new Set<ThinkingLevel>(["off", "minimal", "low", "medium", "high", "xhigh", "max"]);
const EXTERNAL_PROVIDERS = new Set(["acpx", "acpx-claude", "claude-code", "codex-cli"]);

function modelFamily(model: string): string {
  return model.split("/", 1)[0]!;
}

function nativeRole(value: unknown, label: string): NativeRole {
  if (!value || typeof value !== "object") throw new Error(`${label} must be an object`);
  const item = value as Record<string, unknown>;
  if (typeof item.model !== "string" || !/^[^/]+\/.+$/.test(item.model)) {
    throw new Error(`${label}.model must be provider-qualified`);
  }
  if (EXTERNAL_PROVIDERS.has(modelFamily(item.model))) throw new Error(`${label}.model uses an external runner`);
  if (!THINKING.has(item.thinking as ThinkingLevel)) throw new Error(`${label}.thinking is invalid`);
  return { model: item.model, thinking: item.thinking as ThinkingLevel };
}

function focusRoles(value: unknown, label: string): FocusRole[] {
  if (!Array.isArray(value) || value.length === 0) throw new Error(`${label} requires at least one lane`);
  const lanes = value.map((entry, index) => {
    const role = nativeRole(entry, `${label}[${index}]`);
    const item = entry as Record<string, unknown>;
    if (typeof item.id !== "string" || !item.id || typeof item.focus !== "string" || !item.focus) {
      throw new Error(`${label}[${index}] requires id and focus`);
    }
    return { ...role, id: item.id, focus: item.focus } as FocusRole;
  });
  if (new Set(lanes.map((lane) => lane.id)).size !== lanes.length) throw new Error(`${label} ids must be unique`);
  return lanes;
}

function gates(value: unknown, label: string): string[][] {
  if (!Array.isArray(value) || value.length === 0 || value.some((argv) => !Array.isArray(argv) || argv.length === 0 || argv.some((arg) => typeof arg !== "string" || !arg))) {
    throw new Error(`${label} must contain non-empty argv arrays`);
  }
  return value.map((argv) => [...argv]) as string[][];
}

export function parseNativePackProfile(value: unknown): NativePackProfile {
  if (!value || typeof value !== "object") throw new Error("Native Pack profile must be an object");
  const item = value as Record<string, unknown>;
  if (item.schema !== "cognovis.pi.native-pack-profile.v1") throw new Error("Unsupported Native Pack profile schema");
  if (typeof item.id !== "string" || !item.id || typeof item.version !== "string" || !item.version) throw new Error("Native Pack profile identity is required");
  if (!Number.isInteger(item.maxPackSize) || Number(item.maxPackSize) < 2 || Number(item.maxPackSize) > 20) throw new Error("maxPackSize must be an integer from 2 to 20");
  if (!Number.isInteger(item.maxReviewTurns) || Number(item.maxReviewTurns) < 1 || Number(item.maxReviewTurns) > 3) throw new Error("maxReviewTurns must be an integer from 1 to 3");
  const profile: NativePackProfile = {
    schema: item.schema,
    id: item.id,
    version: item.version,
    maxPackSize: Number(item.maxPackSize),
    maxReviewTurns: Number(item.maxReviewTurns),
    implementer: nativeRole(item.implementer, "implementer"),
    preflight: focusRoles(item.preflight, "preflight"),
    beadReviewers: focusRoles(item.beadReviewers, "beadReviewers"),
    aggregateReviewers: focusRoles(item.aggregateReviewers, "aggregateReviewers"),
    beadGates: gates(item.beadGates, "beadGates"),
    packGates: gates(item.packGates, "packGates"),
  };
  if (profile.aggregateReviewers.length < 2) throw new Error("aggregateReviewers requires parallel lanes");
  if (new Set(profile.aggregateReviewers.map((lane) => modelFamily(lane.model))).size !== profile.aggregateReviewers.length) {
    throw new Error("aggregate reviewer families must be distinct");
  }
  return profile;
}

export function loadNativePackProfile(profilePath = process.env.COGNOVIS_PI_NATIVE_PACK_PROFILE): NativePackProfile {
  if (!profilePath) throw new Error("COGNOVIS_PI_NATIVE_PACK_PROFILE is not set");
  return parseNativePackProfile(JSON.parse(fs.readFileSync(path.resolve(profilePath), "utf8")));
}
