import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";

export const OPEN_BRAIN_MCP_URL = "https://open-brain.sussdorff.org/mcp";
export const OPEN_BRAIN_READ_TOOLS = [
  "search",
  "timeline",
  "get_observations",
  "search_by_concept",
  "get_context",
  "stats",
] as const;

const ALLOWED_TOOLS = new Set<string>(OPEN_BRAIN_READ_TOOLS);

export function filterOpenBrainTools(tools: Tool[]): Tool[] {
  const byName = new Map(tools.map((tool) => [tool.name, tool]));
  return OPEN_BRAIN_READ_TOOLS.flatMap((name) => {
    const tool = byName.get(name);
    return tool ? [tool] : [];
  });
}

export async function callOpenBrainReadTool<T>(
  name: string,
  arguments_: Record<string, unknown> | undefined,
  call: (name: string, arguments_: Record<string, unknown> | undefined) => Promise<T>,
): Promise<T> {
  if (!ALLOWED_TOOLS.has(name)) throw new Error("Open Brain tool is not allowed");
  return call(name, arguments_);
}

export function configureOpenBrainReadonlyServer(
  server: Server,
  upstream: {
    listTools(params?: Record<string, unknown>): Promise<{ tools: Tool[]; [key: string]: unknown }>;
    callTool(params: { name: string; arguments?: Record<string, unknown> }): Promise<unknown>;
  },
): void {
  server.setRequestHandler(ListToolsRequestSchema, async (request) => {
    const response = await upstream.listTools(request.params);
    return { ...response, tools: filterOpenBrainTools(response.tools) };
  });
  server.setRequestHandler(CallToolRequestSchema, async (request) =>
    callOpenBrainReadTool(request.params.name, request.params.arguments, (name, arguments_) =>
      upstream.callTool({ name, ...(arguments_ ? { arguments: arguments_ } : {}) }),
    ) as any
  );
}

export function openBrainApiKey(environment: NodeJS.ProcessEnv): string {
  const value = environment.OB_TOKEN?.trim() || environment.OPEN_BRAIN_API_KEY?.trim();
  if (!value) {
    throw new Error(
      "Open Brain authentication is required; set OB_TOKEN or OPEN_BRAIN_API_KEY in the managed runtime environment",
    );
  }
  return value;
}

export async function runOpenBrainReadonlyProxy(
  environment: NodeJS.ProcessEnv = process.env,
): Promise<void> {
  const upstream = new Client(
    { name: "cognovis-pi-open-brain-readonly-proxy", version: "1.0.0" },
    { capabilities: {} },
  );
  const upstreamTransport = new StreamableHTTPClientTransport(new URL(OPEN_BRAIN_MCP_URL), {
    requestInit: { headers: { "x-api-key": openBrainApiKey(environment) } },
  });
  await upstream.connect(upstreamTransport as any);

  const server = new Server(
    { name: "open-brain-readonly", version: "1.0.0" },
    { capabilities: { tools: {} } },
  );
  configureOpenBrainReadonlyServer(server, upstream);
  await server.connect(new StdioServerTransport());
}

if (import.meta.main) {
  void runOpenBrainReadonlyProxy().catch((error) => {
    const message = error instanceof Error && /auth|401|403/i.test(error.message)
      ? "Open Brain authentication failed or is unavailable"
      : "Open Brain read-only proxy failed";
    process.stderr.write(`${message}\n`);
    process.exitCode = 1;
  });
}
