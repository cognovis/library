import fs from "node:fs";
import path from "node:path";

export const ACPX_VERSION = "0.12.1";
export const CLAUDE_ADAPTER_VERSION = "0.62.0";

export type FusionChildKind = "acpx-claude" | "native-pi";

export function fusionChildKind(model: string): FusionChildKind {
  if (model.startsWith("acpx-claude/")) return "acpx-claude";
  if (model.includes("/")) return "native-pi";
  throw new Error(`Fusion model must be provider-qualified: ${model}`);
}

export function claudeModelId(model: string): string {
  if (fusionChildKind(model) !== "acpx-claude") {
    throw new Error(`Not an ACPX Claude model: ${model}`);
  }
  return model.slice("acpx-claude/".length);
}

const CLAUDE_TOOL_NAMES: Record<string, string> = {
  read: "Read",
  grep: "Grep",
  find: "Glob",
  ls: "Glob",
  edit: "Edit",
  write: "Write",
  beads_read: "mcp__beads__beads_read",
};

export function claudeAllowedTools(tools: string | "none"): string[] {
  if (tools === "none") return [];
  return tools.split(",").map((tool) => CLAUDE_TOOL_NAMES[tool] ?? tool);
}

export function claudePermissionPolicy(tools: string | "none") {
  const allowed = claudeAllowedTools(tools);
  return {
    autoApprove: allowed,
    autoDeny: ["Bash", "WebFetch", "WebSearch"],
    defaultAction: "deny" as const,
  };
}

export interface AcpxClaudeInvocationOptions {
  model: string;
  cwd: string;
  prompt: string;
  systemPrompt?: string;
  tools: string | "none";
  timeoutMs: number;
  mcpConfigPath: string;
  acpxCommand?: string;
  adapterCommand?: string;
  sessionName?: string;
}

function executable(options: { acpxCommand?: string }, args: string[]) {
  if (options.acpxCommand) return { command: options.acpxCommand, args };
  return { command: "bunx", args: [`acpx@${ACPX_VERSION}`, ...args] };
}

function sessionArgs(options: AcpxClaudeInvocationOptions): string[] {
  const args = [
    "--cwd", options.cwd,
    "--agent", options.adapterCommand ?? `bunx @agentclientprotocol/claude-agent-acp@${CLAUDE_ADAPTER_VERSION}`,
    "--model", claudeModelId(options.model),
    "--allowed-tools", claudeAllowedTools(options.tools).join(","),
    "--permission-policy", JSON.stringify(claudePermissionPolicy(options.tools)),
    "--non-interactive-permissions", "deny",
    "--mcp-config", options.mcpConfigPath,
    "--format", "json",
    "--json-strict",
    "--timeout", String(Math.ceil(options.timeoutMs / 1000)),
  ];
  if (options.systemPrompt) args.push("--system-prompt", options.systemPrompt);
  return args;
}

export function buildAcpxClaudeInvocation(options: AcpxClaudeInvocationOptions) {
  const args = sessionArgs(options);
  if (options.sessionName) {
    args.push("prompt", "-s", options.sessionName, options.prompt);
  } else {
    args.push("exec", options.prompt);
  }
  return executable(options, args);
}

export function buildAcpxClaudeEnsureInvocation(options: AcpxClaudeInvocationOptions) {
  if (!options.sessionName) throw new Error("Persistent ACPX Claude session requires a name");
  const args = sessionArgs(options);
  args.push("sessions", "ensure", "--name", options.sessionName);
  return executable(options, args);
}

export function buildAcpxClaudeCloseInvocation(options: {
  cwd: string;
  sessionName: string;
  acpxCommand?: string;
  adapterCommand?: string;
}) {
  const args = [
    "--cwd", options.cwd,
    "--agent", options.adapterCommand ?? `bunx @agentclientprotocol/claude-agent-acp@${CLAUDE_ADAPTER_VERSION}`,
    "--format", "json",
    "--json-strict",
    "sessions", "close", options.sessionName,
  ];
  return executable(options, args);
}

export function writeReadonlyMcpConfig(options: {
  directory: string;
  repositoryRoot: string;
  sessionId: string;
  beadsServerPath: string;
  openBrainServerPath: string;
  bunCommand?: string;
}): string {
  fs.mkdirSync(options.directory, { recursive: true });
  const configPath = path.join(options.directory, "readonly-context.json");
  const bun = options.bunCommand ?? "bun";
  const mcpServers = [
    {
      name: "beads",
      command: bun,
      args: [options.beadsServerPath],
      env: [
        { name: "COGNOVIS_PI_REPOSITORY_ROOT", value: options.repositoryRoot },
        { name: "COGNOVIS_PI_EVENT_LOG", value: path.join(options.directory, "beads-events.jsonl") },
        { name: "COGNOVIS_PI_SESSION_ID", value: options.sessionId },
      ],
    },
    {
      name: "open-brain",
      command: bun,
      args: [options.openBrainServerPath],
      env: [],
    },
  ];
  fs.writeFileSync(configPath, `${JSON.stringify({ mcpServers }, null, 2)}\n`, "utf8");
  return configPath;
}

export interface ParsedAcpxEvent {
  text?: string;
  thinking?: string;
  tool?: { name: string; input?: unknown };
  usage?: {
    input?: number;
    output?: number;
    cacheRead?: number;
    cacheWrite?: number;
    totalTokens?: number;
  };
  stopReason?: string;
  error?: string;
}

export function parseAcpxJsonEvent(value: unknown): ParsedAcpxEvent {
  if (!value || typeof value !== "object") return {};
  const message = value as any;
  if (message.method === "session/update") {
    const update = message.params?.update;
    if (update?.sessionUpdate === "agent_message_chunk" && update.content?.type === "text") {
      return { text: update.content.text };
    }
    if (update?.sessionUpdate === "agent_thought_chunk" && update.content?.type === "text") {
      return { thinking: update.content.text };
    }
    if (update?.sessionUpdate === "tool_call" || update?.sessionUpdate === "tool_call_update") {
      return { tool: { name: update.title ?? update.kind ?? "tool", input: update.rawInput } };
    }
    if (update?.sessionUpdate === "usage_update") {
      const usage = update._meta?.usage ?? update.usage ?? {};
      return {
        usage: {
          input: usage.inputTokens,
          output: usage.outputTokens,
          cacheRead: usage.cachedReadTokens,
          cacheWrite: usage.cachedWriteTokens,
          totalTokens: usage.totalTokens,
        },
      };
    }
  }
  if (typeof message.result?.stopReason === "string") return { stopReason: message.result.stopReason };
  if (message.error) return { error: message.error.message ?? "ACPX Claude failed" };
  return {};
}
