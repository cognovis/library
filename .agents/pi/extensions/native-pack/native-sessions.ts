import fs from "node:fs";
import path from "node:path";

import { StringEnum } from "@earendil-works/pi-ai";
import {
  createAgentSession,
  DefaultResourceLoader,
  defineTool,
  getAgentDir,
  ModelRuntime,
  SessionManager,
  SettingsManager,
  type ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { dockerLifecycleGuard } from "../docker-lifecycle-guard/index.ts";
import { readCandidateDiff } from "./candidate-diff.ts";
import type { NativePackSessions } from "./engine.ts";
import type {
  AggregateSubmission,
  Approval,
  BeadRecord,
  BeadSubmission,
  FocusRole,
  NativePackPacket,
  NativePackProfile,
  PreflightSubmission,
  ReviewFinding,
  ReviewSubmission,
} from "./types.ts";

const READ_TOOLS = ["read", "grep", "find", "ls"] as const;
const WRITE_TOOLS = [...READ_TOOLS, "edit", "write", "bash"] as const;

export function nativeRoleTools(kind: "preflight" | "implementer" | "reviewer"): string[] {
  return [...(kind === "implementer" ? WRITE_TOOLS : READ_TOOLS)];
}

interface PiChild {
  prompt(text: string): Promise<void>;
  abort(): Promise<void>;
  dispose(): void;
  subscribe(listener: (event: any) => void): () => void;
}

type Capture<T> = { value: T | undefined };

function promptFile(name: string): string {
  return fs.readFileSync(path.join(import.meta.dirname, "prompts", name), "utf8");
}

function submissionTool<T>(name: string, parameters: any, capture: Capture<T>): ToolDefinition {
  return defineTool({
    name,
    label: name,
    description: `Submit the typed terminal result for this native Pack role. This is the only completion signal.`,
    parameters,
    async execute(_id, params) {
      capture.value = params as T;
      return {
        content: [{ type: "text", text: `${name} accepted` }],
        details: params,
        terminate: true,
      };
    },
  }) as ToolDefinition;
}

const PreflightSchema = Type.Object({
  laneId: Type.String(),
  seams: Type.Array(Type.String()),
  questions: Type.Array(Type.String()),
  risks: Type.Array(Type.String()),
});
const BeadSchema = Type.Object({
  beadId: Type.String(),
  summary: Type.String(),
  evidence: Type.Array(Type.String()),
});
const FindingSchema = Type.Object({
  id: Type.String(),
  severity: StringEnum(["blocking", "advisory"] as const),
  summary: Type.String(),
});
const ReviewSchema = Type.Object({
  laneId: Type.String(),
  decision: StringEnum(["clean", "blocking"] as const),
  candidateSha: Type.String(),
  findings: Type.Array(FindingSchema),
});

function jsonPrompt(kind: string, value: unknown): string {
  return `${kind}\n\n${JSON.stringify(value, null, 2)}`;
}

export function assertSuccessfulDiffRead(diffRead: boolean, kind: string, laneId: string): void {
  if (!diffRead) throw new Error(`${kind}:${laneId} submitted without successfully reading the bound candidate diff`);
}

export class NativePiSessions implements NativePackSessions {
  private readonly profile: NativePackProfile;
  private readonly cwd: string;
  private readonly artifactsDir: string;
  private readonly modelRuntime: ModelRuntime;
  private readonly children = new Set<PiChild>();
  private readonly implementers = new Map<string, { session: PiChild; capture: Capture<BeadSubmission> }>();
  private readonly onActivity: ((role: string, activity: string) => void) | undefined;

  private constructor(
    profile: NativePackProfile,
    cwd: string,
    artifactsDir: string,
    modelRuntime: ModelRuntime,
    onActivity?: (role: string, activity: string) => void,
  ) {
    this.profile = profile;
    this.cwd = cwd;
    this.artifactsDir = artifactsDir;
    this.modelRuntime = modelRuntime;
    this.onActivity = onActivity;
  }

  static async create(
    profile: NativePackProfile,
    cwd: string,
    artifactsDir: string,
    onActivity?: (role: string, activity: string) => void,
  ): Promise<NativePiSessions> {
    const modelRuntime = await ModelRuntime.create();
    const required = [
      profile.implementer,
      ...profile.preflight,
      ...profile.beadReviewers,
      ...profile.aggregateReviewers,
    ];
    const available = new Set((await modelRuntime.getAvailable()).map((model) => `${model.provider}/${model.id}`));
    for (const role of required) {
      if (!available.has(role.model)) throw new Error(`Native Pi model is unavailable or unauthenticated: ${role.model}`);
    }
    return new NativePiSessions(profile, cwd, artifactsDir, modelRuntime, onActivity);
  }

  private async child<T>(
    roleName: string,
    role: { model: string; thinking: NativePackProfile["implementer"]["thinking"] },
    systemPrompt: string,
    tools: string[],
    toolName: string,
    schema: any,
    persistentKey?: string,
    extraTools: ToolDefinition[] = [],
  ): Promise<{ session: PiChild; capture: Capture<T> }> {
    const [provider, ...modelParts] = role.model.split("/");
    const model = this.modelRuntime.getModel(provider!, modelParts.join("/"));
    if (!model) throw new Error(`Native Pi model is not registered: ${role.model}`);
    const capture: Capture<T> = { value: undefined };
    const completion = submissionTool<T>(toolName, schema, capture);
    const agentDir = getAgentDir();
    const settings = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: true, maxRetries: 2 } });
    const loader = new DefaultResourceLoader({
      cwd: this.cwd,
      agentDir,
      settingsManager: settings,
      noExtensions: true,
      noSkills: true,
      noPromptTemplates: true,
      noThemes: true,
      noContextFiles: true,
      systemPrompt,
      extensionFactories: tools.includes("bash")
        ? [{ name: "docker-lifecycle-guard", hidden: true, factory: dockerLifecycleGuard() }]
        : [],
    });
    await loader.reload();
    const sessionDirectory = path.join(this.artifactsDir, "sessions", persistentKey ?? `${roleName}-${crypto.randomUUID()}`);
    fs.mkdirSync(sessionDirectory, { recursive: true, mode: 0o700 });
    const { session } = await createAgentSession({
      cwd: this.cwd,
      agentDir,
      modelRuntime: this.modelRuntime,
      model,
      thinkingLevel: role.thinking,
      tools: [...tools, toolName, ...extraTools.map((tool) => tool.name)],
      customTools: [completion, ...extraTools],
      resourceLoader: loader,
      sessionManager: SessionManager.create(this.cwd, sessionDirectory),
      settingsManager: settings,
    });
    const child = session as PiChild;
    child.subscribe((event) => {
      if (event.type === "tool_execution_start") this.onActivity?.(roleName, `${event.toolName}`);
      if (event.type === "message_update" && event.assistantMessageEvent?.type === "text_delta") {
        const text = String(event.assistantMessageEvent.delta ?? "").trim();
        if (text) this.onActivity?.(roleName, text.slice(-240));
      }
    });
    this.children.add(child);
    return { session: child, capture };
  }

  private async run<T>(roleName: string, child: PiChild, capture: Capture<T>, prompt: string): Promise<T> {
    capture.value = undefined;
    this.onActivity?.(roleName, "starting");
    await child.prompt(prompt);
    if (!capture.value) throw new Error(`${roleName} exited without its typed completion tool`);
    return capture.value;
  }

  async preflight(lane: FocusRole, packet: NativePackPacket, beads: BeadRecord[]): Promise<PreflightSubmission> {
    const child = await this.child<PreflightSubmission>(
      `preflight:${lane.id}`,
      lane,
      promptFile("preflight.system.md"),
      nativeRoleTools("preflight"),
      "submit_preflight",
      PreflightSchema,
    );
    try {
      return await this.run(`preflight:${lane.id}`, child.session, child.capture, jsonPrompt("Analyze this Pack for your assigned focus.", { laneId: lane.id, focus: lane.focus, packet, beads }));
    } finally {
      child.session.dispose();
      this.children.delete(child.session);
    }
  }

  async implement(beadId: string, bead: BeadRecord, approval: Approval): Promise<BeadSubmission> {
    let child = this.implementers.get(beadId);
    if (!child) {
      child = await this.child<BeadSubmission>(
        `implementer:${beadId}`,
        this.profile.implementer,
        promptFile("implementer.system.md"),
        nativeRoleTools("implementer"),
        "submit_bead_result",
        BeadSchema,
        `implementer-${beadId.replace(/[^A-Za-z0-9_.-]/g, "_")}`,
      );
      this.implementers.set(beadId, child);
    }
    return this.run(`implementer:${beadId}`, child.session, child.capture, jsonPrompt("Implement this approved Bead.", { bead, approval }));
  }

  async repair(beadId: string, findings: ReviewSubmission[]): Promise<BeadSubmission> {
    const child = this.implementers.get(beadId);
    if (!child) throw new Error(`No persistent implementer session for ${beadId}`);
    return this.run(`implementer:${beadId}`, child.session, child.capture, jsonPrompt("Repair only these accepted blocking findings, rerun focused evidence, and resubmit.", { beadId, findings }));
  }

  async releaseImplementer(beadId: string): Promise<void> {
    const child = this.implementers.get(beadId);
    if (!child) return;
    try { await child.session.abort(); } catch { /* already idle */ }
    child.session.dispose();
    this.children.delete(child.session);
    this.implementers.delete(beadId);
  }

  async review(lane: FocusRole, beadId: string, candidateSha: string, diffRange: string): Promise<ReviewSubmission> {
    return this.oneShotReview("reviewer", lane, "reviewer.system.md", "submit_review", beadId, candidateSha, diffRange);
  }

  async aggregate(
    lane: FocusRole,
    candidateSha: string,
    diffRange: string,
    commits: Array<{ beadId: string; sha: string }>,
  ): Promise<AggregateSubmission> {
    return this.oneShotReview("aggregate", lane, "aggregate-reviewer.system.md", "submit_aggregate_review", "complete Pack", candidateSha, diffRange, commits);
  }

  private async oneShotReview(
    kind: string,
    lane: FocusRole,
    systemFile: string,
    toolName: string,
    subject: string,
    candidateSha: string,
    diffRange: string,
    commits?: Array<{ beadId: string; sha: string }>,
  ): Promise<ReviewSubmission> {
    let diffRead = false;
    const diffTool = defineTool({
      name: "read_candidate_diff",
      label: "Read candidate diff",
      description: "Read the exact candidate diff bound by the Native Pack harness. The tool takes no caller-selected revision.",
      parameters: Type.Object({}),
      execute: async () => {
        const text = await readCandidateDiff(this.cwd, diffRange);
        diffRead = true;
        return { content: [{ type: "text", text }], details: { candidateSha, diffRange } };
      },
    }) as ToolDefinition;
    const child = await this.child<ReviewSubmission>(`${kind}:${lane.id}`, lane, promptFile(systemFile), nativeRoleTools("reviewer"), toolName, ReviewSchema, undefined, [diffTool]);
    try {
      const result = await this.run(`${kind}:${lane.id}`, child.session, child.capture, jsonPrompt("Review this exact subject for your assigned focus.", {
        laneId: lane.id,
        focus: lane.focus,
        subject,
        candidateSha,
        diffRange,
        commits,
      }));
      assertSuccessfulDiffRead(diffRead, kind, lane.id);
      result.findings = result.findings.map((finding: ReviewFinding) => ({ ...finding }));
      return result;
    } finally {
      child.session.dispose();
      this.children.delete(child.session);
    }
  }

  async dispose(): Promise<void> {
    await Promise.all([...this.children].map(async (child) => {
      try { await child.abort(); } catch { /* already idle */ }
      child.dispose();
    }));
    this.children.clear();
    this.implementers.clear();
  }
}
