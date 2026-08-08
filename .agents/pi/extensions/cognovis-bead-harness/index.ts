import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";

import { registerAcpxAttachView } from "../acpx-session-view/pi-extension.ts";
import { parseDockerCleanupReceipt } from "../docker-lifecycle-guard/index.ts";
import { loadBeadHarnessProfile } from "./profile.ts";
import { runProcessTree } from "./process.ts";
import { buildOwnerInvocation, parseBeadInvocation } from "./runner.ts";
import { claimRoleArtifacts, claimRoleSession, executeRoleRequest, parseRoleRequest, ROLE_RESPONSE_SCHEMA, type RoleRequest, type RoleResponse } from "./transport.ts";
import {
  applyLifecycleEvent,
  BEAD_HARNESS_UI_LENS_SCHEMA,
  createHarnessView,
  parseLifecycleEvent,
  renderHarnessLines,
  replayLifecycle,
  recordOwnerActivity,
  validateCompletedRun,
  type HarnessView,
} from "./state.ts";

const CUSTOM_TYPE = "cognovis-bead-harness";
const RUNTIME_SCHEMA = "cognovis.pi.bead-harness-runtime-event.v1";

export type Binding = {
  schema: "cognovis.pi.bead-harness-binding.v2";
  uiLensSchema: typeof BEAD_HARNESS_UI_LENS_SCHEMA;
  runId: string;
  beadId: string;
  mode: string;
  artifactsDir: string;
};

function firstFile(candidates: string[]): string | undefined {
  return candidates.find((candidate) => {
    try { return fs.statSync(candidate).isFile(); } catch { return false; }
  });
}

export function resolveRoleSystemPrompt(worktree: string, role: string): string {
  if (!/^[A-Za-z0-9_-]+$/.test(role)) throw new Error(`Invalid role name: ${role}`);
  const candidates = [
    process.env.COGNOVIS_CORE_ROOT ? path.join(process.env.COGNOVIS_CORE_ROOT, "agents", `${role}.md`) : undefined,
    path.join(worktree, ".agents", "agents", `${role}.md`),
    path.join(worktree, ".claude", "agents", `${role}.md`),
    path.join(os.homedir(), ".agents", "agents", `${role}.md`),
    path.join(os.homedir(), ".claude", "agents", `${role}.md`),
  ].filter((value): value is string => Boolean(value));
  const resolved = firstFile(candidates);
  if (!resolved) throw new Error(`${role}.md not found; probed: ${candidates.join(", ")}`);
  return fs.readFileSync(resolved, "utf8");
}

export function resolveOwnerSystemPrompt(worktree: string): string {
  return resolveRoleSystemPrompt(worktree, "bead-loop-implementer");
}

export function preflightRoleSystemPrompts(
  worktree: string,
  profile: ReturnType<typeof loadBeadHarnessProfile>,
): Map<string, string> {
  const prompts = new Map<string, string>();
  const requiredRoles = [profile.implementer, ...profile.reviewers, ...(profile.adjudicator ? [profile.adjudicator] : [])];
  for (const role of requiredRoles) {
    if (!prompts.has(role.role)) prompts.set(role.role, resolveRoleSystemPrompt(worktree, role.role));
  }
  return prompts;
}

export function validateCanonicalRoleBinding(
  request: RoleRequest,
  profile: ReturnType<typeof loadBeadHarnessProfile>,
  canonical: any,
): void {
  const reviewer = profile.reviewers.find((item) => item.id === request.actor);
  if (reviewer) {
    const expected = canonical.review_artifacts?.[request.actor];
    if (!expected || typeof expected.evidence_file !== "string" || typeof expected.verdict_file !== "string") {
      throw new Error("Canonical state lacks the reviewer artifact binding");
    }
    if (
      path.resolve(expected.evidence_file) !== path.resolve(request.evidenceFile)
      || path.resolve(expected.verdict_file) !== path.resolve(request.verdictFile)
    ) throw new Error("Reviewer request does not use the exact Core-bound artifacts");
    const identity = canonical.reviewers?.find((item: any) => item.id === request.actor);
    if (!identity || identity.session !== request.sessionId) {
      throw new Error("Reviewer request does not use the exact Core-bound session");
    }
    return;
  }
  if (profile.adjudicator?.id !== request.actor) throw new Error(`Role request has unknown actor: ${request.actor}`);
  if (typeof canonical.adjudication_artifact !== "string") {
    throw new Error("Canonical state lacks the adjudicator artifact binding");
  }
  if (path.resolve(canonical.adjudication_artifact) !== path.resolve(request.verdictFile)) {
    throw new Error("Adjudicator request does not use the exact Core-bound verdict artifact");
  }
  if (!canonical.adjudicator || canonical.adjudicator.session !== request.sessionId) {
    throw new Error("Adjudicator request does not use the exact Core-bound session");
  }
  const reports = Object.values(canonical.review_results ?? {}) as any[];
  const findingCount = reports.reduce(
    (total, report) => total + (report?.blocking_findings?.length ?? 0) + (report?.advisory_findings?.length ?? 0),
    0,
  );
  if (findingCount === 0) throw new Error("Adjudicator request is forbidden when validated reviews contain no findings");
}

/** Locate the active Pi executable exactly as the Fusion Harness does. */
export function piInvocationCommand(): { command: string; prefix: string[] } {
  const override = process.env.COGNOVIS_PI_COMMAND;
  if (override) return { command: override, prefix: [] };
  const script = process.argv[1];
  const bunVirtual = script?.startsWith("/$bunfs/root/");
  if (script && !bunVirtual && fs.existsSync(script)) return { command: process.execPath, prefix: [script] };
  const executable = path.basename(process.execPath).toLowerCase();
  if (!/^(node|bun)(\.exe)?$/.test(executable)) return { command: process.execPath, prefix: [] };
  return { command: "pi", prefix: [] };
}

async function validateLinkedWorktree(pi: ExtensionAPI, worktree: string, beadId: string): Promise<string> {
  const absolute = path.resolve(worktree);
  const [inside, gitDir, commonDir, bead] = await Promise.all([
    pi.exec("git", ["-C", absolute, "rev-parse", "--is-inside-work-tree"]),
    pi.exec("git", ["-C", absolute, "rev-parse", "--path-format=absolute", "--git-dir"]),
    pi.exec("git", ["-C", absolute, "rev-parse", "--path-format=absolute", "--git-common-dir"]),
    pi.exec("bd", ["-C", absolute, "show", beadId, "--json"]),
  ]);
  if (inside.code !== 0 || inside.stdout.trim() !== "true") throw new Error(`${absolute} is not a Git worktree`);
  if (gitDir.code !== 0 || commonDir.code !== 0 || path.resolve(gitDir.stdout.trim()) === path.resolve(commonDir.stdout.trim())) {
    throw new Error(`${absolute} is the main checkout, not a linked task worktree`);
  }
  if (bead.code !== 0) throw new Error(`Bead ${beadId} is not available from ${absolute}: ${bead.stderr.trim()}`);
  return absolute;
}

function appendRuntimeEvent(artifactsDir: string, event: Record<string, unknown>): void {
  fs.appendFileSync(
    path.join(artifactsDir, "runtime.jsonl"),
    `${JSON.stringify({ schema: RUNTIME_SCHEMA, timestamp: new Date().toISOString(), ...event })}\n`,
    { encoding: "utf8", mode: 0o600 },
  );
}

export function restoreView(binding: Binding, profile = loadBeadHarnessProfile()): HarnessView {
  if (binding.schema !== "cognovis.pi.bead-harness-binding.v2") throw new Error("Restored binding schema is unsupported");
  if (binding.uiLensSchema !== BEAD_HARNESS_UI_LENS_SCHEMA) throw new Error("Restored binding uses an unsupported UI lens schema");
  if (profile.mode !== binding.mode) throw new Error("Restored binding belongs to another Bead Harness mode");
  const lifecycle = path.join(binding.artifactsDir, "lifecycle.jsonl");
  const view = replayLifecycle(
    profile,
    binding.beadId,
    binding.artifactsDir,
    fs.existsSync(lifecycle) ? fs.readFileSync(lifecycle, "utf8") : "",
    binding.runId,
  );
  if (view.sessionClose === "complete") {
    const statePath = path.join(binding.artifactsDir, "harness-state.json");
    const gatePath = path.join(binding.artifactsDir, "aggregate-review-gate.json");
    if (!fs.existsSync(statePath) || !fs.existsSync(gatePath)) {
      throw new Error("Restored completed run lacks canonical state or aggregate review evidence");
    }
    validateCompletedRun(
      view,
      JSON.parse(fs.readFileSync(statePath, "utf8")),
      JSON.parse(fs.readFileSync(gatePath, "utf8")),
    );
  }
  return view;
}

export type BeadHarnessRegistrationOptions = {
  description?: string;
  resolveInvocation?: (raw: string, ctx: any) => Promise<ReturnType<typeof parseBeadInvocation>>;
};

export function resolveBeadHarnessInvocation(
  raw: string,
  ctx: any,
  options: BeadHarnessRegistrationOptions,
) {
  return options.resolveInvocation
    ? options.resolveInvocation(raw, ctx)
    : Promise.resolve(parseBeadInvocation(raw));
}

async function executeHarness(
  pi: ExtensionAPI,
  ctx: any,
  raw: string,
  controller: AbortController,
  options: BeadHarnessRegistrationOptions,
): Promise<void> {
  const profile = loadBeadHarnessProfile();
  const invocation = await resolveBeadHarnessInvocation(raw, ctx, options);
  const worktree = await validateLinkedWorktree(pi, invocation.worktree, invocation.beadId);
  const runId = `${invocation.beadId}-${Date.now()}`;
  const artifactsDir = path.join(worktree, ".beads", "harness", runId);
  fs.mkdirSync(artifactsDir, { recursive: true, mode: 0o700 });
  const lifecyclePath = path.join(artifactsDir, "lifecycle.jsonl");
  let view = createHarnessView(profile, invocation.beadId, artifactsDir, runId);
  let offset = 0;
  let buffered = "";
  let fatalError: Error | undefined;
  let runtimeTerminalWritten = false;
  const render = () => {
    if (ctx.mode !== "tui") return;
    ctx.ui.setWidget(CUSTOM_TYPE, (_tui: any, theme: any) => ({
      render: (width: number) => renderHarnessLines(view, width).map((line) => theme.fg("muted", line)),
      invalidate() {},
    }), { placement: "aboveEditor" });
  };
  const consumeLifecycle = (final = false) => {
    if (!fs.existsSync(lifecyclePath)) return;
    const file = fs.readFileSync(lifecyclePath, "utf8");
    if (file.length < offset) throw new Error("Lifecycle journal was truncated during the run");
    const fresh = buffered + file.slice(offset);
    const lines = fresh.split("\n");
    const nextBuffered = final ? "" : (lines.pop() ?? "");
    let candidate = view;
    for (const line of lines) if (line.trim()) candidate = applyLifecycleEvent(candidate, parseLifecycleEvent(line));
    view = candidate;
    buffered = nextBuffered;
    offset = file.length;
    render();
  };
  const failRuntime = (error: unknown) => {
    if (fatalError) return;
    fatalError = error instanceof Error ? error : new Error(String(error));
    controller.abort();
  };

  let releaseInput = () => {};
  let ticker: ReturnType<typeof setInterval> | undefined;
  let outputTail = "";
  let activityBuffered = "";
  const roleRequestDir = path.join(artifactsDir, "role-requests");
  fs.mkdirSync(roleRequestDir, { recursive: true, mode: 0o700 });
  const roleTasks = new Map<string, Promise<RoleResponse>>();
  const claimedRoleArtifacts = new Map<string, string>();
  const claimedSessionActors = new Map<string, string>();
  const claimedActorSessions = new Map<string, string>();
  const rolePrompts = new Map<string, string>();
  const consumeActivity = (final = false) => {
    const lines = activityBuffered.split("\n");
    activityBuffered = final ? "" : (lines.pop() ?? "");
    for (const line of lines) if (line.trim()) view = recordOwnerActivity(view, line);
    render();
  };
  const writeRoleResponse = (file: string, response: RoleResponse) => {
    const temporary = `${file}.tmp-${process.pid}`;
    fs.writeFileSync(temporary, `${JSON.stringify(response)}\n`, { encoding: "utf8", mode: 0o600 });
    fs.renameSync(temporary, file);
  };
  const scanRoleRequests = () => {
    const piCommand = piInvocationCommand();
    for (const name of fs.readdirSync(roleRequestDir)) {
      if (!name.endsWith(".json") || name.endsWith(".response.json") || roleTasks.has(name)) continue;
      const requestPath = path.join(roleRequestDir, name);
      const responsePath = path.join(roleRequestDir, `${name.slice(0, -5)}.response.json`);
      const task = (async () => {
        try {
          const request = parseRoleRequest(JSON.parse(fs.readFileSync(requestPath, "utf8")), profile, artifactsDir);
          if (`${request.requestId}.json` !== name) throw new Error("Role request filename does not match requestId");
          const configured = profile.reviewers.find((item) => item.id === request.actor)
            ?? (profile.adjudicator?.id === request.actor ? profile.adjudicator : undefined);
          if (!configured) throw new Error(`Role request has unknown actor: ${request.actor}`);
          const statePath = path.join(artifactsDir, "harness-state.json");
          if (!fs.existsSync(statePath)) throw new Error("Role request arrived before canonical harness state");
          const canonical = JSON.parse(fs.readFileSync(statePath, "utf8")) as any;
          validateCanonicalRoleBinding(request, profile, canonical);
          const nextArtifacts = new Map(claimedRoleArtifacts);
          const nextSessionActors = new Map(claimedSessionActors);
          const nextActorSessions = new Map(claimedActorSessions);
          claimRoleSession(request, nextSessionActors, nextActorSessions);
          claimRoleArtifacts(request, nextArtifacts);
          for (const artifact of [request.evidenceFile, request.verdictFile]) {
            claimedRoleArtifacts.set(path.resolve(artifact), request.requestId);
          }
          claimedSessionActors.set(request.sessionId, request.actor);
          claimedActorSessions.set(request.actor, request.sessionId);
          const response = await executeRoleRequest({
            profile,
            request,
            roleSystemPrompt: rolePrompts.get(configured.role) ?? (() => { throw new Error(`Role prompt was not preflighted: ${configured.role}`); })(),
            worktree,
            artifactsDir,
            piCommand: piCommand.command,
            piCommandPrefix: piCommand.prefix,
            signal: controller.signal,
            onActivity: (text) => {
              outputTail = `${outputTail}${text}`.slice(-16_384);
              activityBuffered = `${activityBuffered}${text}`.slice(-16_384);
            },
          });
          writeRoleResponse(responsePath, response);
          return response;
        } catch (error) {
          const response: RoleResponse = {
            schema: ROLE_RESPONSE_SCHEMA,
            requestId: name.slice(0, -5),
            actor: "unknown",
            status: controller.signal.aborted ? "aborted" : "failed",
            exitCode: controller.signal.aborted ? 130 : 1,
            evidenceFile: "",
            verdictFile: "",
            reason: error instanceof Error ? error.message : String(error),
          };
          try { writeRoleResponse(responsePath, response); } catch { /* terminal response path is unavailable */ }
          return response;
        }
      })();
      roleTasks.set(name, task);
    }
  };
  const stopTicker = () => {
    if (ticker) clearInterval(ticker);
    ticker = undefined;
  };
  const settleRoleTasks = async (abort: boolean) => {
    stopTicker();
    if (abort && !controller.signal.aborted) controller.abort();
    await Promise.allSettled([...roleTasks.values()]);
  };
  render();
  ctx.ui.setStatus(CUSTOM_TYPE, `${profile.id}: ${invocation.beadId} starting`);
  const binding: Binding = {
    schema: "cognovis.pi.bead-harness-binding.v2",
    uiLensSchema: BEAD_HARNESS_UI_LENS_SCHEMA,
    runId,
    beadId: invocation.beadId,
    mode: profile.mode,
    artifactsDir,
  };
  pi.appendEntry(CUSTOM_TYPE, binding);
  appendRuntimeEvent(artifactsDir, { runId, beadId: invocation.beadId, status: "started", mode: profile.mode });
  try {
    const piCommand = piInvocationCommand();
    for (const [role, prompt] of preflightRoleSystemPrompts(worktree, profile)) rolePrompts.set(role, prompt);
    const ownerPrompt = rolePrompts.get(profile.implementer.role);
    if (!ownerPrompt) throw new Error("Implementer role prompt preflight failed");
    const owner = buildOwnerInvocation({
      piCommand: piCommand.command,
      piCommandPrefix: piCommand.prefix,
      systemPrompt: ownerPrompt,
      profile,
      beadId: invocation.beadId,
      worktree,
      artifactsDir,
      runId,
      guardExtension: path.resolve(import.meta.dirname, "..", "docker-lifecycle-guard", "index.ts"),
    });
    releaseInput = ctx.mode === "tui" && ctx.ui.onTerminalInput
      ? ctx.ui.onTerminalInput((data: string) => {
          if (data === "\x1b") {
            controller.abort();
            ctx.ui.setStatus(CUSTOM_TYPE, `${profile.id}: stopping`);
            return { consume: true };
          }
          return undefined;
        })
      : () => {};
    ticker = setInterval(() => {
      try {
        scanRoleRequests();
        consumeLifecycle();
        consumeActivity();
      } catch (error) { failRuntime(error); }
    }, 250);
    const result = await runProcessTree(
      owner.command,
      owner.args,
      worktree,
      controller.signal,
      (text, _stream) => {
        outputTail = `${outputTail}${text}`.slice(-16_384);
        activityBuffered = `${activityBuffered}${text}`.slice(-16_384);
        ctx.ui.setStatus(CUSTOM_TYPE, `${profile.id}: ${invocation.beadId} running`);
      },
    );
    if (result.aborted || controller.signal.aborted) {
      throw fatalError ?? new Error("Bead Harness aborted");
    }
    if (result.exitCode !== 0) {
      if (outputTail) fs.writeFileSync(path.join(artifactsDir, "transport.log"), outputTail, { encoding: "utf8", mode: 0o600 });
      throw new Error(`Bead Harness owner exited ${result.exitCode}; see ${artifactsDir}/transport.log`);
    }
    await settleRoleTasks(false);
    const cleanupPath = path.join(artifactsDir, "runtime-cleanup.json");
    if (!fs.existsSync(cleanupPath)) throw new Error("Bead Harness owner exited without runtime-cleanup.json");
    parseDockerCleanupReceipt(JSON.parse(fs.readFileSync(cleanupPath, "utf8")));
    consumeLifecycle(true);
    consumeActivity(true);
    const statePath = path.join(artifactsDir, "harness-state.json");
    if (!fs.existsSync(statePath)) throw new Error("Owner exited without canonical harness-state.json");
    const gatePath = path.join(artifactsDir, "aggregate-review-gate.json");
    if (!fs.existsSync(gatePath)) throw new Error("Owner exited without aggregate-review-gate.json");
    const state = JSON.parse(fs.readFileSync(statePath, "utf8")) as Record<string, unknown>;
    const gate = JSON.parse(fs.readFileSync(gatePath, "utf8")) as Record<string, unknown>;
    validateCompletedRun(view, state, gate);
    appendRuntimeEvent(artifactsDir, { runId, beadId: invocation.beadId, status: "complete", exitCode: result.exitCode });
    runtimeTerminalWritten = true;
    ctx.ui.notify(`${profile.id} completed for ${invocation.beadId}`, "info");
  } catch (error) {
    const wasAborted = controller.signal.aborted && !fatalError;
    await settleRoleTasks(true);
    if (outputTail && !fs.existsSync(path.join(artifactsDir, "transport.log"))) {
      fs.writeFileSync(path.join(artifactsDir, "transport.log"), outputTail, { encoding: "utf8", mode: 0o600 });
    }
    if (!runtimeTerminalWritten) {
      appendRuntimeEvent(artifactsDir, { runId, beadId: invocation.beadId, status: wasAborted ? "aborted" : "failed", reason: error instanceof Error ? error.message : String(error) });
      runtimeTerminalWritten = true;
    }
    throw error;
  } finally {
    stopTicker();
    releaseInput();
    ctx.ui.setStatus(CUSTOM_TYPE, undefined);
    if (ctx.mode === "tui") ctx.ui.setWidget(CUSTOM_TYPE, undefined);
  }
}

export default function cognovisBeadHarness(
  pi: ExtensionAPI,
  options: BeadHarnessRegistrationOptions = {},
) {
  registerAcpxAttachView(pi);
  let activeController: AbortController | undefined;
  let activeRun: Promise<void> | undefined;
  pi.registerEntryRenderer(CUSTOM_TYPE, (entry, _options, theme) => {
    const data = entry.data as Binding;
    return new Text(theme.fg("dim", `Bead Harness ${data.mode ?? "?"} · ${data.beadId ?? "?"} · ${data.artifactsDir ?? ""}`), 0, 0);
  });
  pi.on("session_start", (_event, ctx) => {
    const bindings = ctx.sessionManager.getBranch().filter((entry: any) => entry.type === "custom" && entry.customType === CUSTOM_TYPE);
    const latest = (bindings.at(-1) as any)?.data as Binding | undefined;
    if (!latest) return;
    try {
      const view = restoreView(latest);
      ctx.ui.setStatus(CUSTOM_TYPE, `restored ${view.beadId} · wave ${view.wave}/${view.profile.maxReviewWaves} · Session Close ${view.sessionClose}`);
    } catch (error) {
      ctx.ui.notify(`Bead Harness restore failed: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  });
  pi.on("session_shutdown", async () => {
    activeController?.abort();
    try { await activeRun; } catch { /* executeHarness records the terminal outcome */ }
  });
  pi.registerCommand("bead", {
    description: options.description ?? "Run the selected Cognovis Bead Harness preset: /bead <id> --worktree <linked-worktree>",
    handler: async (raw, ctx) => {
      if (activeRun) throw new Error("A Bead Harness run is already active in this session");
      const controller = new AbortController();
      activeController = controller;
      const run = executeHarness(pi, ctx, raw, controller, options);
      activeRun = run;
      try { await run; }
      catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
        throw error;
      } finally {
        if (activeRun === run) {
          activeRun = undefined;
          activeController = undefined;
        }
      }
    },
  });
}
