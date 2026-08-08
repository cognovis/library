import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export interface AcpxSessionRecord {
  schema?: string;
  acpx_record_id: string;
  acp_session_id: string;
  agent_command: string;
  cwd: string;
  name?: string | null;
  created_at?: string;
  last_used_at?: string;
  closed?: boolean;
  pid?: number;
  last_agent_exit_code?: number | null;
  last_agent_exit_signal?: string | null;
  last_agent_disconnect_reason?: string | null;
  event_log?: {
    active_path?: string;
    max_segments?: number;
    last_write_at?: string;
    last_write_error?: string | null;
  };
}

export type AcpxAttachEvent =
  | { kind: "message" | "thought"; text: string }
  | { kind: "tool"; text: string }
  | { kind: "usage"; text: string }
  | { kind: "terminal" | "error"; text: string };

export interface AcpxAttachSnapshot {
  record: AcpxSessionRecord;
  events: AcpxAttachEvent[];
  malformedLines: number;
  droppedBytes: number;
}

const DEFAULT_INITIAL_BYTES = 1_048_576;
const DEFAULT_INCREMENT_BYTES = 1_048_576;

export function acpxSessionsDirectory(environment: NodeJS.ProcessEnv = process.env): string {
  return environment.ACPX_SESSIONS_DIR
    ? path.resolve(environment.ACPX_SESSIONS_DIR)
    : path.join(os.homedir(), ".acpx", "sessions");
}

function parseRecord(file: string): AcpxSessionRecord | undefined {
  try {
    const value = JSON.parse(fs.readFileSync(file, "utf8")) as Partial<AcpxSessionRecord>;
    if (
      typeof value.acpx_record_id !== "string"
      || typeof value.acp_session_id !== "string"
      || typeof value.agent_command !== "string"
      || typeof value.cwd !== "string"
    ) return undefined;
    return value as AcpxSessionRecord;
  } catch {
    return undefined;
  }
}

export function listAcpxSessions(directory = acpxSessionsDirectory()): AcpxSessionRecord[] {
  let names: string[];
  try {
    names = fs.readdirSync(directory);
  } catch {
    return [];
  }
  return names
    .filter((name) => name.endsWith(".json") && name !== "index.json")
    .map((name) => parseRecord(path.join(directory, name)))
    .filter((record): record is AcpxSessionRecord => Boolean(record))
    .sort((left, right) => Date.parse(right.last_used_at ?? "") - Date.parse(left.last_used_at ?? ""));
}

export function acpxStreamRecord(streamPath: string, cwd = process.cwd()): AcpxSessionRecord {
  const absolute = path.resolve(cwd, streamPath);
  let stat: fs.Stats;
  try { stat = fs.statSync(absolute); } catch { throw new Error(`ACPX event stream not found: ${absolute}`); }
  if (!stat.isFile()) throw new Error(`ACPX event stream is not a file: ${absolute}`);
  return {
    acpx_record_id: `file:${absolute}`,
    acp_session_id: "external-stream",
    agent_command: "external ACPX event stream",
    cwd: path.dirname(absolute),
    name: path.basename(absolute),
    last_used_at: stat.mtime.toISOString(),
    event_log: { active_path: absolute, max_segments: 0, last_write_at: stat.mtime.toISOString() },
  };
}

export function resolveAcpxSession(
  identifier: string,
  options: { directory?: string; cwd?: string } = {},
): AcpxSessionRecord {
  const records = listAcpxSessions(options.directory);
  const exact = records.filter((record) =>
    record.acpx_record_id === identifier
    || record.acp_session_id === identifier
    || record.name === identifier
  );
  if (exact.length === 0) throw new Error(`ACPX session not found: ${identifier}`);
  if (exact.length === 1) return exact[0]!;
  const cwd = options.cwd ? path.resolve(options.cwd) : undefined;
  const cwdMatches = cwd ? exact.filter((record) => path.resolve(record.cwd) === cwd) : [];
  if (cwdMatches.length === 1) return cwdMatches[0]!;
  throw new Error(`ACPX session identifier is ambiguous: ${identifier}`);
}

function eventPaths(record: AcpxSessionRecord, directory: string): string[] {
  const active = record.event_log?.active_path
    ? path.resolve(record.event_log.active_path)
    : path.join(directory, `${encodeURIComponent(record.acpx_record_id)}.stream.ndjson`);
  const maxSegments = Math.max(0, record.event_log?.max_segments ?? 0);
  const stem = active.endsWith(".stream.ndjson") ? active.slice(0, -".stream.ndjson".length) : undefined;
  const paths: string[] = [];
  if (stem) {
    for (let segment = maxSegments; segment >= 1; segment--) {
      const candidate = `${stem}.stream.${segment}.ndjson`;
      if (fs.existsSync(candidate)) paths.push(candidate);
    }
  }
  if (fs.existsSync(active)) paths.push(active);
  return paths;
}

function parseEventLine(line: string): AcpxAttachEvent | undefined {
  const value = JSON.parse(line) as any;
  if (value?.method === "session/update") {
    const update = value.params?.update;
    const text = update?.content?.type === "text" ? update.content.text : undefined;
    if (update?.sessionUpdate === "agent_message_chunk" && typeof text === "string") return { kind: "message", text };
    if (update?.sessionUpdate === "agent_thought_chunk" && typeof text === "string") return { kind: "thought", text };
    if (update?.sessionUpdate === "tool_call" || update?.sessionUpdate === "tool_call_update") {
      const title = update.title ?? update.kind ?? update.toolCallId ?? "tool";
      const state = update.status ?? update.state;
      return { kind: "tool", text: state ? `${title} · ${state}` : String(title) };
    }
    if (update?.sessionUpdate === "usage_update") {
      const usage = update._meta?.usage ?? update.usage ?? update;
      const used = usage.totalTokens ?? usage.used;
      const size = usage.size;
      const cost = usage.cost?.amount;
      const fields = [used !== undefined ? `tokens ${used}${size ? `/${size}` : ""}` : "usage"];
      if (cost !== undefined) fields.push(`cost ${cost}`);
      return { kind: "usage", text: fields.join(" · ") };
    }
    return undefined;
  }
  if (value?.error) return { kind: "error", text: value.error.message ?? JSON.stringify(value.error) };
  if (value?.result) return { kind: "terminal", text: `completed · ${value.result.stopReason ?? "end"}` };
  return undefined;
}

interface Cursor {
  offset: number;
  buffer: string;
}

export class AcpxSessionFollower {
  private record: AcpxSessionRecord;
  private readonly directory: string;
  private readonly cursors = new Map<string, Cursor>();
  private initialized = false;
  private malformedLines = 0;
  private droppedBytes = 0;

  constructor(
    record: AcpxSessionRecord,
    private readonly limits: { initialBytes?: number; incrementBytes?: number } = {},
    directory = acpxSessionsDirectory(),
  ) {
    this.record = record;
    this.directory = directory;
  }

  private refreshRecord(): void {
    if (this.record.acpx_record_id.startsWith("file:")) {
      try {
        const stat = fs.statSync(this.record.event_log!.active_path!);
        this.record = {
          ...this.record,
          last_used_at: stat.mtime.toISOString(),
          event_log: { ...this.record.event_log, last_write_at: stat.mtime.toISOString() },
        };
      } catch { /* poll reports the retained snapshot when an external stream disappears */ }
      return;
    }
    const refreshed = parseRecord(path.join(this.directory, `${this.record.acpx_record_id}.json`));
    if (refreshed) this.record = refreshed;
  }

  poll(): AcpxAttachSnapshot {
    this.refreshRecord();
    const events: AcpxAttachEvent[] = [];
    const paths = eventPaths(this.record, this.directory);
    const totalInitial = this.limits.initialBytes ?? DEFAULT_INITIAL_BYTES;
    const perInitial = Math.max(1, Math.floor(totalInitial / Math.max(1, paths.length)));
    for (const file of paths) {
      let stat: fs.Stats;
      try { stat = fs.statSync(file); } catch { continue; }
      const identity = `${stat.dev}:${stat.ino}`;
      let cursor = this.cursors.get(identity);
      let discardPartial = false;
      if (!cursor) {
        const start = this.initialized ? 0 : Math.max(0, stat.size - perInitial);
        if (start > 0) {
          this.droppedBytes += start;
          discardPartial = true;
        }
        cursor = { offset: start, buffer: "" };
        this.cursors.set(identity, cursor);
      }
      if (stat.size < cursor.offset) {
        cursor.offset = 0;
        cursor.buffer = "";
      }
      let start = cursor.offset;
      const incrementLimit = this.limits.incrementBytes ?? DEFAULT_INCREMENT_BYTES;
      if (stat.size - start > incrementLimit) {
        const skipped = stat.size - start - incrementLimit;
        start += skipped;
        cursor.buffer = "";
        discardPartial = true;
        this.droppedBytes += skipped;
      }
      if (stat.size <= start) continue;
      const length = stat.size - start;
      const fd = fs.openSync(file, "r");
      const buffer = Buffer.alloc(length);
      try { fs.readSync(fd, buffer, 0, length, start); } finally { fs.closeSync(fd); }
      cursor.offset = stat.size;
      let payload = cursor.buffer + buffer.toString("utf8");
      if (discardPartial) {
        const firstNewline = payload.indexOf("\n");
        payload = firstNewline >= 0 ? payload.slice(firstNewline + 1) : "";
      }
      const lines = payload.split("\n");
      cursor.buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const event = parseEventLine(line);
          if (event) events.push(event);
        } catch {
          this.malformedLines++;
        }
      }
    }
    this.initialized = true;
    return { record: this.record, events, malformedLines: this.malformedLines, droppedBytes: this.droppedBytes };
  }
}
