import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { appendWorkbenchEvent } from "./session-store.ts";

const execFileAsync = promisify(execFile);
const OPERATIONS = [
  "ready",
  "show",
  "list",
  "search",
  "blocked",
  "children",
  "dependencies",
  "status",
] as const;
const ISSUE_TYPES = [
  "bug",
  "feature",
  "task",
  "epic",
  "chore",
  "decision",
  "merge-request",
  "molecule",
  "gate",
] as const;
const ISSUE_STATUSES = ["open", "in_progress", "blocked", "deferred", "closed", "all"] as const;
const SORT_FIELDS = ["priority", "created", "updated", "closed", "status", "id", "title", "type", "assignee"] as const;
const BEADS_CONNECTION_ENVIRONMENT = [
  "BEADS_DOLT_SERVER_HOST",
  "BEADS_DOLT_SERVER_PORT",
  "BEADS_DOLT_SERVER_USER",
  "BEADS_DOLT_SERVER_DATABASE",
  "BEADS_DOLT_SERVER_SOCKET",
  "BEADS_DOLT_SERVER_TLS",
  "BEADS_DOLT_SHARED_SERVER",
] as const;
const PROCESS_ENVIRONMENT = ["PATH", "HOME", "TMPDIR", "USER", "LOGNAME", "LANG"] as const;

type Operation = (typeof OPERATIONS)[number];
type BeadsReadInput = {
  operation: Operation;
  id?: string;
  query?: string;
  status?: (typeof ISSUE_STATUSES)[number];
  type?: (typeof ISSUE_TYPES)[number];
  priority?: number;
  priorityMin?: number;
  priorityMax?: number;
  assignee?: string;
  labels?: string[];
  parent?: string;
  direction?: "up" | "down";
  sort?: (typeof SORT_FIELDS)[number];
  limit?: number;
};

const PARAMETERS = Type.Object(
  {
    operation: StringEnum(OPERATIONS),
    id: Type.Optional(Type.String({ maxLength: 128 })),
    query: Type.Optional(Type.String({ maxLength: 500 })),
    status: Type.Optional(StringEnum(ISSUE_STATUSES)),
    type: Type.Optional(StringEnum(ISSUE_TYPES)),
    priority: Type.Optional(Type.Integer({ minimum: 0, maximum: 4 })),
    priorityMin: Type.Optional(Type.Integer({ minimum: 0, maximum: 4 })),
    priorityMax: Type.Optional(Type.Integer({ minimum: 0, maximum: 4 })),
    assignee: Type.Optional(Type.String({ maxLength: 128 })),
    labels: Type.Optional(Type.Array(Type.String({ maxLength: 64 }), { maxItems: 20, uniqueItems: true })),
    parent: Type.Optional(Type.String({ maxLength: 128 })),
    direction: Type.Optional(StringEnum(["up", "down"] as const)),
    sort: Type.Optional(StringEnum(SORT_FIELDS)),
    limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
  },
  { additionalProperties: false },
);

const ALLOWED_FIELDS: Record<Operation, ReadonlySet<string>> = {
  ready: new Set(["operation", "assignee", "labels", "parent", "priority", "type", "sort", "limit"]),
  show: new Set(["operation", "id"]),
  list: new Set(["operation", "assignee", "labels", "parent", "priority", "status", "type", "sort", "limit"]),
  search: new Set(["operation", "query", "assignee", "labels", "priorityMin", "priorityMax", "status", "type", "sort", "limit"]),
  blocked: new Set(["operation", "parent"]),
  children: new Set(["operation", "id"]),
  dependencies: new Set(["operation", "id", "direction"]),
  status: new Set(["operation"]),
};

function safeToken(value: string, label: string, maxLength = 128): string {
  const normalized = value.trim();
  if (
    normalized.length === 0 ||
    normalized.length > maxLength ||
    /[\u0000-\u001f\u007f]/.test(normalized) ||
    normalized.startsWith("-") ||
    normalized.includes("/") ||
    normalized.includes("\\") ||
    normalized === "." ||
    normalized === ".."
  ) {
    throw new Error(`Invalid ${label}`);
  }
  return normalized;
}

function issueId(value: unknown, label = "issue id"): string {
  if (typeof value !== "string") throw new Error(`${label} is required`);
  const normalized = safeToken(value, label);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(normalized)) throw new Error(`Invalid ${label}`);
  return normalized;
}

function textValue(value: unknown, label: string, maxLength: number): string {
  if (typeof value !== "string") throw new Error(`${label} is required`);
  const normalized = value.trim();
  if (!normalized || normalized.length > maxLength || /[\u0000-\u001f\u007f]/.test(normalized)) {
    throw new Error(`Invalid ${label}`);
  }
  return normalized;
}

function integer(value: unknown, label: string, minimum: number, maximum: number): number {
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw new Error(`Invalid ${label}`);
  }
  return value as number;
}

function enumValue<const T extends readonly string[]>(
  value: unknown,
  values: T,
  label: string,
): T[number] {
  if (typeof value !== "string" || !values.includes(value)) throw new Error(`Invalid ${label}`);
  return value as T[number];
}

function addCommonFilters(argv: string[], input: BeadsReadInput): void {
  if (input.assignee !== undefined) argv.push("--assignee", safeToken(input.assignee, "assignee"));
  if (input.parent !== undefined) argv.push("--parent", issueId(input.parent, "parent id"));
  if (input.priority !== undefined) argv.push("--priority", String(integer(input.priority, "priority", 0, 4)));
  if (input.status !== undefined) argv.push("--status", enumValue(input.status, ISSUE_STATUSES, "status"));
  if (input.type !== undefined) argv.push("--type", enumValue(input.type, ISSUE_TYPES, "type"));
  if (input.sort !== undefined) argv.push("--sort", enumValue(input.sort, SORT_FIELDS, "sort"));
  if (input.limit !== undefined) argv.push("--limit", String(integer(input.limit, "limit", 1, 100)));
  if (input.labels !== undefined) {
    if (!Array.isArray(input.labels) || input.labels.length > 20) throw new Error("Invalid labels");
    const labels = input.labels.map((label) => safeToken(label, "label", 64));
    if (new Set(labels).size !== labels.length) throw new Error("Duplicate label values are not allowed");
    for (const label of labels) argv.push("--label", label);
  }
}

export function beadsReadArgv(value: unknown): string[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("beads_read input must be an object");
  }
  const input = value as BeadsReadInput;
  if (!OPERATIONS.includes(input.operation)) throw new Error("Unsupported Beads read operation");
  const allowed = ALLOWED_FIELDS[input.operation];
  for (const key of Object.keys(input)) {
    if (!allowed.has(key)) throw new Error(`Field ${key} is not allowed for ${input.operation}`);
  }
  const argv = ["--readonly", "--json"];
  switch (input.operation) {
    case "ready":
      argv.push("ready");
      addCommonFilters(argv, input);
      break;
    case "show":
      argv.push("show", issueId(input.id));
      break;
    case "list":
      argv.push("list");
      addCommonFilters(argv, input);
      break;
    case "search":
      argv.push("search", textValue(input.query, "search query", 500));
      addCommonFilters(argv, input);
      if (input.priorityMin !== undefined) {
        argv.push("--priority-min", String(integer(input.priorityMin, "priorityMin", 0, 4)));
      }
      if (input.priorityMax !== undefined) {
        argv.push("--priority-max", String(integer(input.priorityMax, "priorityMax", 0, 4)));
      }
      if (
        input.priorityMin !== undefined &&
        input.priorityMax !== undefined &&
        input.priorityMin > input.priorityMax
      ) {
        throw new Error("priorityMin cannot exceed priorityMax");
      }
      break;
    case "blocked":
      argv.push("blocked");
      if (input.parent !== undefined) argv.push("--parent", issueId(input.parent, "parent id"));
      break;
    case "children":
      argv.push("children", issueId(input.id));
      break;
    case "dependencies":
      argv.push("dep", "list", issueId(input.id));
      if (input.direction !== undefined) {
        argv.push("--direction", enumValue(input.direction, ["up", "down"] as const, "direction"));
      }
      break;
    case "status":
      argv.push("status", "--no-activity");
      break;
  }
  return argv;
}

export interface BeadsReadOptions {
  repositoryRoot: string;
  eventLog: string;
  sessionId: string;
  redactionCanaries: string[];
  executable?: string;
}

export function beadsReadEnvironment(
  environment: NodeJS.ProcessEnv,
): Record<string, string> {
  return Object.fromEntries(
    [...PROCESS_ENVIRONMENT, ...BEADS_CONNECTION_ENVIRONMENT].flatMap((name) =>
      environment[name] ? [[name, environment[name] as string]] : [],
    ),
  );
}

export function beadsReadFailureMessage(error: unknown): string {
  const candidate = error as NodeJS.ErrnoException & { stderr?: unknown; killed?: unknown };
  const stderr = typeof candidate?.stderr === "string" ? candidate.stderr : "";
  if (candidate?.code === "ENOENT") {
    return "Beads read failed because the managed bd executable is unavailable";
  }
  if (
    /server unreachable|connection refused|failed to open database/i.test(stderr)
  ) {
    return "Beads backend is unavailable; verify the managed shared Dolt server connection and BEADS_DOLT_SERVER_PORT";
  }
  if (candidate?.killed || /timed out|timeout/i.test(stderr)) {
    return "Beads read timed out while contacting the managed backend";
  }
  return "Beads read failed before a result was available";
}

export async function executeBeadsRead(
  input: unknown,
  options: BeadsReadOptions,
): Promise<{ output: string; operation: Operation }> {
  const argv = beadsReadArgv(input);
  const operation = (input as BeadsReadInput).operation;
  const environment = beadsReadEnvironment(process.env);
  try {
    const { stdout } = await execFileAsync(options.executable ?? "bd", argv, {
      cwd: options.repositoryRoot,
      env: environment,
      encoding: "utf8",
      timeout: 15_000,
      maxBuffer: 2 * 1024 * 1024,
      windowsHide: true,
    });
    await appendWorkbenchEvent(
      options.eventLog,
      options.sessionId,
      "tool",
      { tool: "beads_read", operation, state: "completed", outputBytes: Buffer.byteLength(stdout) },
      { canaries: options.redactionCanaries },
    );
    return { output: stdout, operation };
  } catch (error) {
    const message = beadsReadFailureMessage(error);
    await appendWorkbenchEvent(
      options.eventLog,
      options.sessionId,
      "tool",
      { tool: "beads_read", operation, state: "failed", message },
      { canaries: options.redactionCanaries },
    );
    throw new Error(message, { cause: error });
  }
}

export function registerBeadsReadTool(pi: ExtensionAPI, options: BeadsReadOptions): void {
  pi.registerTool({
    name: "beads_read",
    label: "Beads Read",
    description: "Read live repository Beads state through a fixed, non-mutating operation schema.",
    promptSnippet: "Inspect live repository task state without shell access",
    promptGuidelines: [
      "Use beads_read for live Beads status, issue, dependency, blocker, child, and search queries.",
    ],
    parameters: PARAMETERS,
    async execute(_toolCallId, params) {
      const result = await executeBeadsRead(params, options);
      return {
        content: [{ type: "text", text: result.output }],
        details: { operation: result.operation },
      };
    },
  });
}
