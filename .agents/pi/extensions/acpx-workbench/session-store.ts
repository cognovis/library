import { randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";

import { appendJsonLine, writeJson } from "./evidence.ts";
import { redactValue, type RedactionOptions } from "./redaction.ts";

export type WorkbenchEventType =
  | "boot"
  | "prompt"
  | "provider"
  | "tool"
  | "failure"
  | "permission"
  | "verification";

export interface WorkbenchEvent {
  schema: "cognovis.pi.event.v1";
  eventId: string;
  sessionId: string;
  timestamp: string;
  type: WorkbenchEventType;
  data: unknown;
}

export interface SessionSummary {
  schema: "cognovis.pi.session-view.v1";
  sessionId: string;
  current: boolean;
  startedAt: string | null;
  latestAt: string | null;
  prompts: unknown[];
  provider: unknown | null;
  tools: unknown[];
  failures: unknown[];
  permissions: unknown[];
  verification: unknown[];
}

export function createWorkbenchEvent(
  sessionId: string,
  type: WorkbenchEventType,
  data: unknown,
  redaction: RedactionOptions = {},
): WorkbenchEvent {
  return {
    schema: "cognovis.pi.event.v1",
    eventId: randomUUID(),
    sessionId,
    timestamp: new Date().toISOString(),
    type,
    data: redactValue(data, redaction),
  };
}

export async function appendWorkbenchEvent(
  eventLog: string,
  sessionId: string,
  type: WorkbenchEventType,
  data: unknown,
  redaction: RedactionOptions = {},
): Promise<WorkbenchEvent> {
  const event = createWorkbenchEvent(sessionId, type, data, redaction);
  await appendJsonLine(eventLog, event);
  return event;
}

export class SessionStore {
  readonly sessionsRoot: string;

  constructor(readonly stateRoot: string) {
    this.sessionsRoot = path.join(stateRoot, "sessions");
  }

  sessionDir(sessionId: string): string {
    if (!/^[A-Za-z0-9._-]+$/.test(sessionId)) throw new Error("Invalid session id");
    return path.join(this.sessionsRoot, sessionId);
  }

  eventLog(sessionId: string): string {
    return path.join(this.sessionDir(sessionId), "events.jsonl");
  }

  receiptPath(sessionId: string): string {
    return path.join(this.sessionDir(sessionId), "boot-receipt.json");
  }

  async initializeSession(sessionId: string): Promise<string> {
    const directory = this.sessionDir(sessionId);
    await mkdir(directory, { recursive: true, mode: 0o700 });
    await mkdir(this.stateRoot, { recursive: true, mode: 0o700 });
    await writeJson(path.join(this.stateRoot, "current.json"), { sessionId });
    return directory;
  }

  async writeReceipt(sessionId: string, receipt: unknown): Promise<void> {
    await writeJson(this.receiptPath(sessionId), receipt);
  }

  async append(
    sessionId: string,
    type: WorkbenchEventType,
    data: unknown,
    redaction: RedactionOptions = {},
  ): Promise<WorkbenchEvent> {
    return appendWorkbenchEvent(this.eventLog(sessionId), sessionId, type, data, redaction);
  }

  async currentSessionId(): Promise<string | null> {
    try {
      const parsed = JSON.parse(await readFile(path.join(this.stateRoot, "current.json"), "utf8")) as {
        sessionId?: unknown;
      };
      return typeof parsed.sessionId === "string" ? parsed.sessionId : null;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw error;
    }
  }

  async readEvents(sessionId: string): Promise<WorkbenchEvent[]> {
    try {
      const raw = await readFile(this.eventLog(sessionId), "utf8");
      return raw
        .split("\n")
        .filter(Boolean)
        .map((line) => JSON.parse(line) as WorkbenchEvent);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
      throw error;
    }
  }

  async listSessionIds(): Promise<string[]> {
    try {
      const entries = await readdir(this.sessionsRoot, { withFileTypes: true });
      return entries
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
        .sort()
        .reverse();
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
      throw error;
    }
  }

  async summarize(sessionId: string): Promise<SessionSummary> {
    const [events, current] = await Promise.all([this.readEvents(sessionId), this.currentSessionId()]);
    const byType = (type: WorkbenchEventType) =>
      events.filter((event) => event.type === type).map((event) => event.data);
    const provider = byType("provider");
    const tools = byType("tool");
    const toolFailures = tools
      .filter((tool) => tool && typeof tool === "object" && (tool as { status?: unknown }).status === "failed")
      .map((tool) => ({ stage: "tool", ...(tool as Record<string, unknown>) }));
    return {
      schema: "cognovis.pi.session-view.v1",
      sessionId,
      current: current === sessionId,
      startedAt: events[0]?.timestamp ?? null,
      latestAt: events.at(-1)?.timestamp ?? null,
      prompts: byType("prompt"),
      provider: provider.at(-1) ?? null,
      tools,
      failures: [...byType("failure"), ...toolFailures],
      permissions: byType("permission"),
      verification: byType("verification"),
    };
  }

  async writeView(target: string, sessionId: string): Promise<void> {
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, `${JSON.stringify(await this.summarize(sessionId), null, 2)}\n`, "utf8");
  }
}
