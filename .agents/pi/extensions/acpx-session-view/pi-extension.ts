import fs from "node:fs";
import path from "node:path";
import type {
  ExtensionAPI,
  ExtensionCommandContext,
  Theme,
} from "@earendil-works/pi-coding-agent";
import {
  Key,
  matchesKey,
  truncateToWidth,
  wrapTextWithAnsi,
} from "@earendil-works/pi-tui";

import {
  AcpxSessionFollower,
  acpxStreamRecord,
  listAcpxSessions,
  resolveAcpxSession,
  type AcpxAttachEvent,
  type AcpxAttachSnapshot,
  type AcpxSessionRecord,
} from "./session-source.ts";

const MAX_CONTENT_CHARS = 200_000;
const POLL_INTERVAL_MS = 250;

interface DisplayEntry {
  kind: AcpxAttachEvent["kind"];
  text: string;
}

function active(record: AcpxSessionRecord): boolean {
  if (record.closed) return false;
  if (!record.pid) return false;
  try {
    process.kill(record.pid, 0);
    return true;
  } catch {
    return false;
  }
}

function compactIdentifier(record: AcpxSessionRecord): string {
  return record.name || record.acpx_record_id;
}

export class AcpxAttachComponent {
  private entries: DisplayEntry[] = [];
  private snapshot: AcpxAttachSnapshot;
  private scrollFromBottom = 0;
  private follow = true;
  private timer: ReturnType<typeof setInterval> | undefined;
  private lastHeight = 24;

  constructor(
    private readonly follower: AcpxSessionFollower,
    private readonly theme: Theme,
    private readonly requestRender: () => void,
    private readonly done: () => void,
  ) {
    this.snapshot = follower.poll();
    this.apply(this.snapshot.events);
    this.timer = setInterval(() => {
      try {
        const next = follower.poll();
        this.snapshot = next;
        this.apply(next.events);
        if (next.events.length > 0 && this.follow) this.scrollFromBottom = 0;
        this.requestRender();
      } catch (error) {
        this.apply([{ kind: "error", text: error instanceof Error ? error.message : String(error) }]);
        this.requestRender();
      }
    }, POLL_INTERVAL_MS);
  }

  private apply(events: AcpxAttachEvent[]): void {
    for (const event of events) {
      const previous = this.entries.at(-1);
      if ((event.kind === "message" || event.kind === "thought") && previous?.kind === event.kind) {
        previous.text += event.text;
      } else if (event.kind !== "usage" || previous?.text !== event.text) {
        this.entries.push({ ...event });
      }
    }
    let size = this.entries.reduce((total, entry) => total + entry.text.length, 0);
    while (size > MAX_CONTENT_CHARS && this.entries.length > 1) {
      size -= this.entries.shift()!.text.length;
    }
  }

  handleInput(data: string): void {
    if (matchesKey(data, Key.escape) || matchesKey(data, Key.ctrl("c"))) {
      this.done();
      return;
    }
    if (data === "f") {
      this.follow = !this.follow;
      if (this.follow) this.scrollFromBottom = 0;
    } else if (matchesKey(data, Key.up)) {
      this.follow = false;
      this.scrollFromBottom++;
    } else if (matchesKey(data, Key.down)) {
      this.scrollFromBottom = Math.max(0, this.scrollFromBottom - 1);
      if (this.scrollFromBottom === 0) this.follow = true;
    } else if (matchesKey(data, Key.pageUp)) {
      this.follow = false;
      this.scrollFromBottom += Math.max(1, this.lastHeight - 5);
    } else if (matchesKey(data, Key.pageDown)) {
      this.scrollFromBottom = Math.max(0, this.scrollFromBottom - Math.max(1, this.lastHeight - 5));
      if (this.scrollFromBottom === 0) this.follow = true;
    } else if (matchesKey(data, Key.end)) {
      this.follow = true;
      this.scrollFromBottom = 0;
    }
    this.requestRender();
  }

  private entryLines(width: number): string[] {
    const inner = Math.max(10, width - 2);
    const lines: string[] = [];
    for (const entry of this.entries) {
      const prefix = entry.kind === "message" ? "A "
        : entry.kind === "thought" ? "T "
          : entry.kind === "tool" ? "• "
            : entry.kind === "usage" ? "Σ "
              : entry.kind === "error" ? "✗ " : "✓ ";
      const color = entry.kind === "message" ? "text"
        : entry.kind === "thought" ? "dim"
          : entry.kind === "tool" ? "accent"
            : entry.kind === "usage" ? "muted"
              : entry.kind === "error" ? "error" : "success";
      const paragraphs = entry.text.replace(/\r/g, "").split("\n");
      for (let index = 0; index < paragraphs.length; index++) {
        const lead = index === 0 ? prefix : "  ";
        const wrapped = wrapTextWithAnsi(`${lead}${paragraphs[index]}`, inner);
        for (const line of wrapped.length ? wrapped : [lead]) lines.push(this.theme.fg(color as any, line));
      }
    }
    return lines;
  }

  render(width: number): string[] {
    const safeWidth = Math.max(20, width);
    const record = this.snapshot.record;
    const external = record.acpx_record_id.startsWith("file:");
    const terminalKind = [...this.entries].reverse().find((entry) => entry.kind === "terminal" || entry.kind === "error")?.kind;
    const state = terminalKind === "error" ? "FAILED"
      : terminalKind === "terminal" ? "DONE"
        : active(record) ? "LIVE"
          : external ? "FOLLOW"
            : record.closed ? "CLOSED" : "IDLE";
    const stateColor = state === "LIVE" || state === "FOLLOW" || state === "DONE" ? "success"
      : state === "FAILED" ? "error"
        : state === "CLOSED" ? "dim" : "warning";
    const header = [
      this.theme.fg("accent", this.theme.bold(`ACPX ATTACH · ${compactIdentifier(record)}`)),
      this.theme.fg(stateColor, state)
        + this.theme.fg("dim", ` · ${record.agent_command} · ${record.cwd}`),
      this.theme.fg("dim", `ACP ${record.acp_session_id} · record ${record.acpx_record_id}`),
    ];
    const footerParts = [
      this.follow ? "following" : `paused · ${this.scrollFromBottom} lines from tail`,
      "f follow",
      "↑↓/pg scroll",
      "end tail",
      "esc close",
    ];
    if (this.snapshot.malformedLines) footerParts.push(`${this.snapshot.malformedLines} malformed`);
    if (this.snapshot.droppedBytes) footerParts.push(`${this.snapshot.droppedBytes} bytes elided`);
    const footer = this.theme.fg("dim", footerParts.join(" · "));
    const body = this.entryLines(safeWidth);
    this.lastHeight = Math.max(8, Math.min(36, process.stdout.rows ? process.stdout.rows - 8 : 24));
    const available = Math.max(3, this.lastHeight - header.length - 2);
    const end = Math.max(0, body.length - this.scrollFromBottom);
    const start = Math.max(0, end - available);
    return [...header, "", ...body.slice(start, end), "", footer]
      .map((line) => truncateToWidth(line, safeWidth));
  }

  invalidate(): void {}

  dispose(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = undefined;
  }
}

async function chooseRecord(args: string, ctx: ExtensionCommandContext): Promise<AcpxSessionRecord | undefined> {
  const identifier = args.trim();
  if (identifier) {
    const candidate = path.resolve(ctx.cwd, identifier);
    if (fs.existsSync(candidate)) return acpxStreamRecord(candidate, ctx.cwd);
    return resolveAcpxSession(identifier, { cwd: ctx.cwd });
  }
  const records = listAcpxSessions();
  const nearby = records.filter((record) => record.cwd === ctx.cwd);
  const choices = (nearby.length ? [...nearby, ...records.filter((record) => record.cwd !== ctx.cwd)] : records).slice(0, 50);
  if (choices.length === 0) throw new Error("No ACPX sessions found");
  const labels = choices.map((record) => {
    const state = active(record) ? "LIVE" : record.closed ? "CLOSED" : "IDLE";
    const used = record.last_used_at ? new Date(record.last_used_at).toLocaleString() : "unknown time";
    return `${state} · ${compactIdentifier(record)} · ${used} · ${record.cwd}`;
  });
  const selected = await ctx.ui.select("Attach to ACPX session", labels);
  const index = selected ? labels.indexOf(selected) : -1;
  return index >= 0 ? choices[index] : undefined;
}

export function registerAcpxAttachView(pi: ExtensionAPI, commandName = "acpx-attach"): void {
  pi.registerCommand(commandName, {
    description: `Inspect and follow ACPX without prompting it: /${commandName} [record-id|ACP-session-id|name|event-stream-path]`,
    handler: async (args, ctx) => {
      if (ctx.mode !== "tui") {
        ctx.ui.notify(`${commandName} requires interactive TUI mode`, "error");
        return;
      }
      try {
        const record = await chooseRecord(args, ctx);
        if (!record) return;
        await ctx.ui.custom<void>((tui, theme, _keybindings, done) =>
          new AcpxAttachComponent(
            new AcpxSessionFollower(record),
            theme,
            () => tui.requestRender(),
            () => done(undefined),
          ),
        );
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
      }
    },
  });
}

export default function acpxSessionView(pi: ExtensionAPI): void {
  registerAcpxAttachView(pi);
}
