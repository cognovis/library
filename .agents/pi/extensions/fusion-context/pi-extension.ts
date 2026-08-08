import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import os from "node:os";
import path from "node:path";
import { Type } from "typebox";

import { registerBeadsReadTool } from "../acpx-workbench/beads-read.ts";
import {
  filterOpenBrainTools,
  openBrainApiKey,
  OPEN_BRAIN_MCP_URL,
  OPEN_BRAIN_READ_TOOLS,
} from "../acpx-workbench/open-brain-readonly-proxy.ts";

export default function registerFusionContext(pi: ExtensionAPI): void {
  registerBeadsReadTool(pi, {
    repositoryRoot: process.cwd(),
    eventLog: path.join(os.tmpdir(), `fusion-context-${process.pid}.jsonl`),
    sessionId: process.env.PI_SESSION_ID ?? `fusion-context-${process.pid}`,
    redactionCanaries: [],
  });

  let client: Client | undefined;
  const registerOpenBrainTool = (tool: {
    name: string;
    title?: string | undefined;
    description?: string | undefined;
    inputSchema?: unknown;
  }) => {
    pi.registerTool({
      name: `mcp__open-brain__${tool.name}`,
      label: tool.title ?? `Open Brain ${tool.name}`,
      description: tool.description ?? `Run the read-only Open Brain ${tool.name} operation.`,
      parameters: tool.inputSchema as any ?? Type.Unsafe({ type: "object", additionalProperties: true }),
      async execute(_toolCallId, params) {
        if (!client) throw new Error("Open Brain read-only context is unavailable");
        const result = await client.callTool({ name: tool.name, arguments: params as any });
        return {
          content: Array.isArray(result.content) ? result.content as any : [{ type: "text", text: JSON.stringify(result) }],
          details: { tool: tool.name },
        };
      },
    });
  };
  for (const name of OPEN_BRAIN_READ_TOOLS) registerOpenBrainTool({ name });

  pi.on("session_start", async (_event, ctx) => {
    let token: string;
    try {
      token = openBrainApiKey(process.env);
    } catch {
      return;
    }
    client = new Client(
      { name: "cognovis-pi-fusion-context", version: "1.0.0" },
      { capabilities: {} },
    );
    const transport = new StreamableHTTPClientTransport(new URL(OPEN_BRAIN_MCP_URL), {
      requestInit: { headers: { "x-api-key": token } },
    });
    await client.connect(transport as any);
    const listed = await client.listTools();
    for (const tool of filterOpenBrainTools(listed.tools)) registerOpenBrainTool(tool);
    const requested = new Set(process.env.COGNOVIS_PI_FUSION_CONTEXT_TOOLS?.split(",").filter(Boolean) ?? []);
    if (requested.size > 0) {
      pi.setActiveTools(pi.getAllTools().map((tool) => tool.name).filter((name) => requested.has(name)));
    }
    ctx.ui.setStatus("fusion-context", "read-only context");
  });

  pi.on("session_shutdown", async () => {
    await client?.close();
    client = undefined;
  });
}
