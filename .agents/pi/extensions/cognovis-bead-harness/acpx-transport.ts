export const ACPX_VERSION = "0.12.1";
export const CLAUDE_ADAPTER_VERSION = "0.62.0";

const CLAUDE_TOOL_NAMES: Record<string, string> = {
  read: "Read",
  grep: "Grep",
  find: "Glob",
  ls: "Glob",
};

function claudeModelId(model: string): string {
  if (!model.startsWith("acpx-claude/")) throw new Error(`Not an ACPX Claude model: ${model}`);
  return model.slice("acpx-claude/".length);
}

function allowedTools(tools: string): string[] {
  return tools.split(",").map((tool) => CLAUDE_TOOL_NAMES[tool] ?? tool);
}

export interface AcpxClaudeOptions {
  model: string;
  cwd: string;
  prompt: string;
  systemPrompt: string;
  tools: string;
  timeoutMs: number;
  mcpConfigPath: string;
  acpxCommand?: string;
  adapterCommand?: string;
  sessionName: string;
}

function executable(options: AcpxClaudeOptions, args: string[]) {
  return options.acpxCommand
    ? { command: options.acpxCommand, args }
    : { command: "bunx", args: [`acpx@${ACPX_VERSION}`, ...args] };
}

function sessionArgs(options: AcpxClaudeOptions): string[] {
  const permitted = allowedTools(options.tools);
  return [
    "--cwd", options.cwd,
    "--agent", options.adapterCommand ?? `bunx @agentclientprotocol/claude-agent-acp@${CLAUDE_ADAPTER_VERSION}`,
    "--model", claudeModelId(options.model),
    "--allowed-tools", permitted.join(","),
    "--permission-policy", JSON.stringify({
      autoApprove: permitted,
      autoDeny: ["Bash", "WebFetch", "WebSearch"],
      defaultAction: "deny",
    }),
    "--non-interactive-permissions", "deny",
    "--mcp-config", options.mcpConfigPath,
    "--format", "json",
    "--json-strict",
    "--timeout", String(Math.ceil(options.timeoutMs / 1000)),
    "--system-prompt", options.systemPrompt,
  ];
}

export function buildAcpxClaudeInvocation(options: AcpxClaudeOptions) {
  return executable(options, [...sessionArgs(options), "prompt", "-s", options.sessionName, options.prompt]);
}

export function buildAcpxClaudeEnsureInvocation(options: AcpxClaudeOptions) {
  return executable(options, [...sessionArgs(options), "sessions", "ensure", "--name", options.sessionName]);
}

export type ParsedAcpxEvent = {
  text?: string;
  resetAnswer?: boolean;
  stopReason?: string;
  error?: string;
};

export function parseAcpxJsonEvent(value: unknown): ParsedAcpxEvent {
  if (!value || typeof value !== "object") return {};
  const message = value as any;
  if (message.method === "session/update") {
    const update = message.params?.update;
    if (update?.sessionUpdate === "agent_message_chunk" && update.content?.type === "text") {
      return { text: update.content.text };
    }
    if (update?.sessionUpdate === "tool_call" || update?.sessionUpdate === "tool_call_update") {
      return { resetAnswer: true };
    }
  }
  if (typeof message.result?.stopReason === "string") return { stopReason: message.result.stopReason };
  if (message.error) return { error: message.error.message ?? "ACPX Claude failed" };
  return {};
}
