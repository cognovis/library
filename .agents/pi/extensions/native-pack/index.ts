import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Key, matchesKey, Text } from "@earendil-works/pi-tui";

import { NativePackEngine } from "./engine.ts";
import { GitBeadsPackHost } from "./host.ts";
import { NativePiSessions } from "./native-sessions.ts";
import { loadNativePackProfile } from "./profile.ts";
import { applyPackEvent, renderPackLines } from "./state.ts";
import type { NativePackPacket, PackEvent, PackState } from "./types.ts";

const CUSTOM_TYPE = "cognovis-native-pack";
type Binding = { schema: "cognovis.pi.native-pack-binding.v1"; runId: string; artifactsDir: string; packetPath: string };

function tokens(input: string): string[] {
  return Array.from(input.matchAll(/"([^"]*)"|'([^']*)'|(\S+)/g), (match) => (match[1] ?? match[2] ?? match[3])!);
}

export function parsePackInvocation(input: string): string {
  const parts = tokens(input.trim());
  if (parts.length !== 1) throw new Error("Usage: /pack <packet.json>");
  return path.resolve(parts[0]!);
}

export function defaultNativePackStateRoot(environment: NodeJS.ProcessEnv = process.env): string {
  const base = environment.XDG_STATE_HOME?.trim() || path.join(os.homedir(), ".local", "state");
  return path.join(base, "cognovis-pi", "native-pack");
}

function readPacket(packetPath: string): NativePackPacket {
  const parsed = JSON.parse(fs.readFileSync(packetPath, "utf8")) as NativePackPacket;
  if (parsed.schema !== "cognovis.pi.native-pack-packet.v1") throw new Error("Unsupported Native Pack packet schema");
  return parsed;
}

function writeState(artifactsDir: string, state: PackState): void {
  const target = path.join(artifactsDir, "state.json");
  const temporary = `${target}.tmp-${process.pid}`;
  fs.writeFileSync(temporary, `${JSON.stringify(state, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  fs.renameSync(temporary, target);
}

export function readNativePackState(artifactsDir: string): PackState {
  let state = JSON.parse(fs.readFileSync(path.join(artifactsDir, "state.json"), "utf8")) as PackState;
  const journalPath = path.join(artifactsDir, "lifecycle.jsonl");
  if (!fs.existsSync(journalPath)) return state;
  const lines = fs.readFileSync(journalPath, "utf8").split("\n").filter(Boolean);
  for (const [index, line] of lines.entries()) {
    let event: PackEvent;
    try {
      event = JSON.parse(line) as PackEvent;
    } catch (error) {
      if (index === lines.length - 1) {
        fs.writeFileSync(journalPath, lines.slice(0, index).map((entry) => `${entry}\n`).join(""), { encoding: "utf8", mode: 0o600 });
        break;
      }
      throw error;
    }
    if (event.sequence > state.lastSequence) state = applyPackEvent(state, event);
  }
  return state;
}

export function abortRestoredPackState(state: PackState): PackState {
  const event: PackEvent = {
    schema: "cognovis.pi.native-pack-event.v1",
    sequence: state.lastSequence + 1,
    runId: state.runId,
    type: "phase",
    phase: "aborted",
  };
  fs.appendFileSync(path.join(state.artifactsDir, "lifecycle.jsonl"), `${JSON.stringify(event)}\n`, { encoding: "utf8", mode: 0o600 });
  const aborted = applyPackEvent(state, event);
  writeState(aborted.artifactsDir, aborted);
  return aborted;
}

export type NativePackRegistrationOptions = {
  description?: string;
  resolvePacketPath?: (raw: string, ctx: any) => Promise<string>;
};

export function resolveNativePackPacketPath(
  raw: string,
  ctx: any,
  options: NativePackRegistrationOptions,
) {
  return options.resolvePacketPath
    ? options.resolvePacketPath(raw, ctx)
    : Promise.resolve(parsePackInvocation(raw));
}

export default function nativePack(
  pi: ExtensionAPI,
  options: NativePackRegistrationOptions = {},
) {
  let engine: NativePackEngine | undefined;
  let visibleState: PackState | undefined;
  let activeRun: Promise<PackState> | undefined;
  let activeCtx: any;
  let restoreBlocked = false;

  const render = (ctx = activeCtx) => {
    if (!ctx || ctx.mode !== "tui" || !visibleState) return;
    ctx.ui.setWidget(CUSTOM_TYPE, (_tui: any, theme: any) => ({
      render: (width: number) => renderPackLines(visibleState!, width).map((line) => theme.fg("muted", line)),
      invalidate() {},
    }), { placement: "aboveEditor" });
    ctx.ui.setStatus(CUSTOM_TYPE, `${visibleState.packId} · ${visibleState.phase}`);
  };

  pi.registerEntryRenderer(CUSTOM_TYPE, (entry, _options, theme) => {
    const data = entry.data as Binding;
    return new Text(theme.fg("dim", `Native Pack ${data.runId} · ${data.artifactsDir}`), 0, 0);
  });

  pi.on("session_start", (_event, ctx) => {
    activeCtx = ctx;
    restoreBlocked = false;
    const bindings = ctx.sessionManager.getBranch().filter((entry: any) => entry.type === "custom" && entry.customType === CUSTOM_TYPE);
    const binding = (bindings.at(-1) as any)?.data as Binding | undefined;
    if (!binding) return;
    if (!fs.existsSync(path.join(binding.artifactsDir, "state.json"))) return;
    try {
      visibleState = readNativePackState(binding.artifactsDir);
      render(ctx);
    } catch (error) {
      restoreBlocked = true;
      ctx.ui.notify(`Native Pack restore failed: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  });

  pi.on("session_shutdown", async () => {
    try { await engine?.abort(); } catch { /* terminal state already recorded */ }
    if (activeRun) try { await activeRun; } catch { /* command reports the failure */ }
  });

  pi.registerCommand("pack", {
    description: options.description ?? "Preflight a native Pack: /pack <packet.json>",
    handler: async (raw, ctx) => {
      if (restoreBlocked) throw new Error("Native Pack restore is corrupt; refusing to start another Pack until the artifacts are repaired");
      if (visibleState && !["delivery_ready", "failed", "aborted"].includes(visibleState.phase)) {
        throw new Error(`Native Pack ${visibleState.packId} is already active`);
      }
      activeCtx = ctx;
      const packetPath = await resolveNativePackPacketPath(raw, ctx, options);
      const packet = readPacket(packetPath);
      const profile = loadNativePackProfile();
      const runId = `${packet.id}-${Date.now()}`;
      const repositoryKey = createHash("sha256").update(path.resolve(packet.repository)).digest("hex").slice(0, 16);
      const artifactsDir = path.join(defaultNativePackStateRoot(), repositoryKey, runId);
      let nextEngine: NativePackEngine;
      const sessions = await NativePiSessions.create(profile, path.resolve(packet.worktree), artifactsDir, (role, activity) => {
        nextEngine?.recordActivity(role, activity);
        visibleState = nextEngine?.state ?? visibleState;
        render(ctx);
      });
      nextEngine = new NativePackEngine(profile, new GitBeadsPackHost(packet.worktree), sessions, artifactsDir, runId);
      engine = nextEngine;
      const releaseInput = ctx.mode === "tui" && ctx.ui.onTerminalInput
        ? ctx.ui.onTerminalInput((data: string) => {
            if (matchesKey(data, Key.escape)) {
              void engine?.abort();
              return { consume: true };
            }
            return undefined;
          })
        : () => {};
      try {
        pi.appendEntry(CUSTOM_TYPE, { schema: "cognovis.pi.native-pack-binding.v1", runId, artifactsDir, packetPath } satisfies Binding);
        visibleState = await engine.preflight(packet);
        render(ctx);
        ctx.ui.notify(`Native Pack ${packet.id} awaits approval. Run /pack-approve [operator].`, "info");
      } finally {
        releaseInput();
      }
    },
  });

  pi.registerCommand("pack-approve", {
    description: "Approve the active preflight and run the Pack: /pack-approve [operator]",
    handler: async (raw, ctx) => {
      if (!engine || !visibleState || visibleState.phase !== "awaiting_approval") throw new Error("No Native Pack is awaiting approval");
      const approvedBy = raw.trim() || process.env.USER || "operator";
      const releaseInput = ctx.mode === "tui" && ctx.ui.onTerminalInput
        ? ctx.ui.onTerminalInput((data: string) => {
            if (matchesKey(data, Key.escape)) {
              void engine?.abort();
              return { consume: true };
            }
            return undefined;
          })
        : () => {};
      const ticker = setInterval(() => {
        visibleState = engine?.state ?? visibleState;
        render(ctx);
      }, 250);
      const run = engine.approveAndRun({ approvedBy, decisions: [] });
      activeRun = run;
      try {
        visibleState = await run;
        render(ctx);
        ctx.ui.notify(`Native Pack ${visibleState.packId} is delivery-ready locally.`, "info");
      } catch (error) {
        visibleState = engine.state;
        render(ctx);
        ctx.ui.notify(`${error instanceof Error ? error.message : String(error)} Artifacts were retained for diagnosis; Pack Beads may remain claimed in bd.`, "error");
        throw error;
      } finally {
        clearInterval(ticker);
        releaseInput();
        activeRun = undefined;
      }
    },
  });

  pi.registerCommand("pack-abort", {
    description: "Abort the active or restored Native Pack",
    handler: async (_raw, ctx) => {
      if (!visibleState || ["delivery_ready", "failed", "aborted"].includes(visibleState.phase)) throw new Error("No active Native Pack can be aborted");
      if (engine) {
        await engine.abort();
        visibleState = engine.state;
      } else {
        visibleState = abortRestoredPackState(visibleState);
      }
      render(ctx);
      const claimNote = visibleState.approval ? " Pack Beads may remain claimed in bd." : "";
      ctx.ui.notify(`Native Pack ${visibleState.packId} aborted.${claimNote}`, "info");
    },
  });

  pi.registerCommand("pack-details", {
    description: "Show details for the active or restored Native Pack",
    handler: async (_raw, ctx) => {
      if (!visibleState) throw new Error("No Native Pack state is visible");
      const state = visibleState;
      if (ctx.mode !== "tui") {
        ctx.ui.notify(`${state.packId}: ${state.phase} · ${state.artifactsDir}`, "info");
        return;
      }
      await ctx.ui.custom<void>((_tui, theme, _keybindings, done) => ({
        render: (width: number) => [
          ...renderPackLines(state, width, state.beads.length),
          "",
          `artifacts: ${state.artifactsDir}`,
          ...(state.error ? ["error:", ...state.error.split("\n")] : ["Esc to close"]),
        ].map((line) => theme.fg(line.startsWith("error:") ? "error" : "text", line.slice(0, Math.max(1, width)))),
        handleInput: (data: string) => { if (matchesKey(data, Key.escape) || matchesKey(data, Key.enter)) done(); },
        invalidate() {},
      }), { overlay: true, overlayOptions: { width: "80%", maxHeight: "80%", anchor: "center" } });
    },
  });
}
