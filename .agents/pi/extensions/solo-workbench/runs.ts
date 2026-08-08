import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Key, matchesKey } from "@earendil-works/pi-tui";

export type RunProjection = {
  id: string;
  harness: "fusion" | "bead" | "native-pack";
  profile: string;
  phase: string;
  artifactsDir?: string;
};

const MAX_STATUS_BYTES = 256 * 1024;

function boundedFile(file: string, tail = false): string | undefined {
  try {
    const size = fs.statSync(file).size;
    const length = Math.min(size, MAX_STATUS_BYTES);
    const buffer = Buffer.alloc(length);
    const descriptor = fs.openSync(file, "r");
    try {
      fs.readSync(descriptor, buffer, 0, length, tail ? Math.max(0, size - length) : 0);
    } finally {
      fs.closeSync(descriptor);
    }
    return buffer.toString("utf8");
  } catch {
    return undefined;
  }
}

function lastJsonLine(file: string): Record<string, unknown> | undefined {
  try {
    const lines = boundedFile(file, true)?.split("\n").filter(Boolean) ?? [];
    return lines.length ? JSON.parse(lines.at(-1)!) as Record<string, unknown> : undefined;
  } catch {
    return undefined;
  }
}

function string(value: unknown, fallback: string) {
  return typeof value === "string" && value ? value : fallback;
}

export function collectRunProjections(entries: readonly any[], limit = 20): RunProjection[] {
  const boundedLimit = Math.max(1, Math.min(limit, 100));
  const runs: RunProjection[] = [];
  const seen = new Set<string>();
  for (const entry of [...entries].reverse()) {
    if (runs.length >= boundedLimit) break;
    if (entry.type === "custom" && entry.customType === "cognovis-bead-harness") {
      const data = entry.data as Record<string, unknown>;
      const id = string(data.runId, string(data.beadId, "bead"));
      if (seen.has(`bead:${id}`)) continue;
      seen.add(`bead:${id}`);
      const artifactsDir = string(data.artifactsDir, "");
      const event = artifactsDir ? lastJsonLine(path.join(artifactsDir, "lifecycle.jsonl")) : undefined;
      runs.push({
        id,
        harness: "bead",
        profile: string(data.mode, "unknown"),
        phase: string(event?.phase ?? event?.status ?? event?.type, "started"),
        ...(artifactsDir ? { artifactsDir } : {}),
      });
      continue;
    }
    if (entry.type === "custom" && entry.customType === "cognovis-native-pack") {
      const data = entry.data as Record<string, unknown>;
      const id = string(data.runId, "native-pack");
      if (seen.has(`native-pack:${id}`)) continue;
      seen.add(`native-pack:${id}`);
      const artifactsDir = string(data.artifactsDir, "");
      let state: Record<string, unknown> | undefined;
      try {
        const content = artifactsDir ? boundedFile(path.join(artifactsDir, "state.json")) : undefined;
        if (content) state = JSON.parse(content) as Record<string, unknown>;
      } catch { /* retain the binding-only projection */ }
      runs.push({
        id,
        harness: "native-pack",
        profile: string(state?.profileId, "unknown"),
        phase: string(state?.phase, "preflight"),
        ...(artifactsDir ? { artifactsDir } : {}),
      });
      continue;
    }
    if (entry.type === "custom_message" && entry.customType === "fusion-harness") {
      const details = entry.details as Record<string, unknown> | undefined;
      if (!details?.command || !["fusion", "opinion", "auto-validate"].includes(String(details.command))) continue;
      const artifactsDir = typeof details.artifactsDir === "string" ? details.artifactsDir : undefined;
      const key = `fusion:${artifactsDir ?? entry.id ?? details.command}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const configuredProfile = process.env.COGNOVIS_PI_FUSION_PROFILE;
      runs.push({
        id: `${String(details.command)}-${entry.id ?? runs.length + 1}`,
        harness: "fusion",
        profile: configuredProfile ? path.basename(configuredProfile, ".json") : "unknown",
        phase: details.kind === "error" ? "failed" : details.kind === "banner" ? "running" : string(details.kind, "complete"),
        ...(artifactsDir ? { artifactsDir } : {}),
      });
    }
  }
  return runs;
}

function lines(runs: RunProjection[]) {
  if (!runs.length) return ["No Harness runs are recorded in this Pi session."];
  return runs.flatMap((run) => [
    `${run.harness} · ${run.profile} · ${run.phase} · ${run.id}`,
    ...(run.artifactsDir ? [`  artifacts: ${run.artifactsDir}`] : []),
  ]);
}

export function registerRunsCommand(pi: ExtensionAPI) {
  pi.registerCommand("runs", {
    description: "Inspect bounded read-only status for Harness runs in this Pi session",
    handler: async (_raw, ctx) => {
      const output = lines(collectRunProjections(ctx.sessionManager.getBranch()));
      if (ctx.mode !== "tui") {
        ctx.ui.notify(output.join("\n"), "info");
        return;
      }
      await ctx.ui.custom<void>((_tui, theme, _keybindings, done) => ({
        render: (width) => [
          theme.fg("accent", theme.bold("Cognovis Harness Runs · read-only projection")),
          "",
          ...output.map((line) => theme.fg(line.startsWith("  ") ? "dim" : "text", line.slice(0, Math.max(1, width)))),
          "",
          theme.fg("dim", "Enter or Esc to close · canonical Harness artifacts remain authoritative"),
        ],
        handleInput: (data) => {
          if (matchesKey(data, Key.escape) || matchesKey(data, Key.enter)) done();
        },
        invalidate() {},
      }), { overlay: true, overlayOptions: { width: "80%", maxHeight: "80%", anchor: "center" } });
    },
  });
}
