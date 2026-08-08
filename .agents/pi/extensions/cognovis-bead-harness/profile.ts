import fs from "node:fs";

export type HarnessMode = "standard" | "high-assurance";
export type HarnessRole = {
  id?: string;
  perspective?: "adversarial" | "depth-failure" | "boundary-operator" | "adjudication";
  role: string;
  harness: "claude" | "codex" | "kimi";
  family: "anthropic" | "openai" | "kimi";
  model: string;
  route: string;
  transport: "direct-acpx" | "native-pi";
  transportModel: string;
  reasoning: string;
};
export type BeadHarnessProfile = {
  schema: "cognovis.pi.bead-harness-profile.v2";
  id: string;
  version: string;
  mode: HarnessMode;
  coreContract: "cognovis.bead-harness-run.v2";
  implementer: HarnessRole;
  reviewers: HarnessRole[];
  adjudicator: HarnessRole | null;
  maxReviewWaves: number;
};

function role(value: unknown, label: string): HarnessRole {
  if (!value || typeof value !== "object") throw new Error(`${label} must be an object`);
  const item = value as Record<string, unknown>;
  for (const key of ["role", "harness", "family", "model", "route", "transport", "transportModel", "reasoning"]) {
    if (typeof item[key] !== "string" || !item[key]) throw new Error(`${label}.${key} is required`);
  }
  if (!["claude", "codex", "kimi"].includes(String(item.harness))) throw new Error(`${label}.harness is unsupported`);
  if (!["anthropic", "openai", "kimi"].includes(String(item.family))) throw new Error(`${label}.family is unsupported`);
  const expectedTransport = item.harness === "claude" ? "direct-acpx" : "native-pi";
  if (item.transport !== expectedTransport) throw new Error(`${label}.transport must be ${expectedTransport}`);
  if (item.transport === "direct-acpx" && !String(item.transportModel).startsWith("acpx-claude/")) {
    throw new Error(`${label}.transportModel must use acpx-claude`);
  }
  if (item.transport === "native-pi" && !String(item.transportModel).includes("/")) {
    throw new Error(`${label}.transportModel must be provider-qualified`);
  }
  return item as HarnessRole;
}

export function parseBeadHarnessProfile(value: unknown): BeadHarnessProfile {
  if (!value || typeof value !== "object") throw new Error("Bead Harness profile must be an object");
  const item = value as Record<string, unknown>;
  if (item.schema !== "cognovis.pi.bead-harness-profile.v2") throw new Error("Unsupported Bead Harness profile schema");
  if (item.mode !== "standard" && item.mode !== "high-assurance") throw new Error("Unsupported Bead Harness mode");
  if (item.coreContract !== "cognovis.bead-harness-run.v2") throw new Error("Incompatible Core Bead Harness contract");
  if (typeof item.id !== "string" || typeof item.version !== "string") throw new Error("Profile identity is required");
  if (!Number.isInteger(item.maxReviewWaves) || Number(item.maxReviewWaves) < 1 || Number(item.maxReviewWaves) > 3) {
    throw new Error("maxReviewWaves must be an integer from 1 to 3");
  }
  const implementer = role(item.implementer, "implementer");
  const reviewers = Array.isArray(item.reviewers)
    ? item.reviewers.map((entry, index) => role(entry, `reviewers[${index}]`))
    : [];
  const reviewerIds = reviewers.map((entry) => entry.id);
  if (reviewerIds.some((id) => typeof id !== "string" || !id) || new Set(reviewerIds).size !== reviewerIds.length) {
    throw new Error("Reviewer ids must be non-empty and unique");
  }
  const expectedPerspectives = item.mode === "standard" ? ["adversarial"] : ["depth-failure", "boundary-operator"];
  if (reviewers.map((entry) => entry.perspective).join(",") !== expectedPerspectives.join(",")) {
    throw new Error(`${item.mode} has invalid reviewer perspectives`);
  }
  if (reviewers.some((entry) => entry.family === implementer.family)) throw new Error("A reviewer uses the implementer family");
  if (new Set(reviewers.map((entry) => entry.family)).size !== reviewers.length) throw new Error("Reviewer families must be distinct");
  const adjudicator = item.adjudicator === null ? null : role(item.adjudicator, "adjudicator");
  if (item.mode === "standard" && adjudicator !== null) throw new Error("standard mode has no adjudicator");
  if (item.mode === "high-assurance" && adjudicator === null) throw new Error("high-assurance requires an adjudicator");
  if (adjudicator) {
    if (typeof adjudicator.id !== "string" || !adjudicator.id || adjudicator.perspective !== "adjudication") {
      throw new Error("adjudicator identity and perspective are required");
    }
    if (reviewerIds.includes(adjudicator.id)) throw new Error("adjudicator must be distinct from both reviewers");
    const boundary = reviewers.find((entry) => entry.perspective === "boundary-operator");
    if (adjudicator.family === implementer.family) throw new Error("adjudicator uses the implementer family");
    if (boundary && (adjudicator.family === boundary.family || adjudicator.route === boundary.route)) {
      throw new Error("adjudicator cannot reuse the boundary reviewer family or route");
    }
  }
  if (item.mode === "standard" && item.maxReviewWaves !== 2) throw new Error("standard requires two review waves");
  if (item.mode === "high-assurance" && item.maxReviewWaves !== 3) throw new Error("high-assurance requires three review waves");
  return { ...item, implementer, reviewers, adjudicator } as BeadHarnessProfile;
}

export function loadBeadHarnessProfile(profilePath = process.env.COGNOVIS_PI_BEAD_HARNESS_PROFILE): BeadHarnessProfile {
  if (!profilePath) throw new Error("COGNOVIS_PI_BEAD_HARNESS_PROFILE is not set");
  return parseBeadHarnessProfile(JSON.parse(fs.readFileSync(profilePath, "utf8")));
}
