import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

import { executeBeadsRead } from "./beads-read.ts";

const BEADS_READ_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["operation"],
  properties: {
    operation: {
      type: "string",
      enum: ["ready", "show", "list", "search", "blocked", "children", "dependencies", "status"],
    },
    id: { type: "string", maxLength: 128 },
    query: { type: "string", maxLength: 500 },
    status: { type: "string", enum: ["open", "in_progress", "blocked", "deferred", "closed", "all"] },
    type: { type: "string", enum: ["bug", "feature", "task", "epic", "chore", "decision", "merge-request", "molecule", "gate"] },
    priority: { type: "integer", minimum: 0, maximum: 4 },
    priorityMin: { type: "integer", minimum: 0, maximum: 4 },
    priorityMax: { type: "integer", minimum: 0, maximum: 4 },
    assignee: { type: "string", maxLength: 128 },
    labels: { type: "array", maxItems: 20, uniqueItems: true, items: { type: "string", maxLength: 64 } },
    parent: { type: "string", maxLength: 128 },
    direction: { type: "string", enum: ["up", "down"] },
    sort: { type: "string", enum: ["priority", "created", "updated", "closed", "status", "id", "title", "type", "assignee"] },
    limit: { type: "integer", minimum: 1, maximum: 100 },
  },
} as const;

function required(environment: NodeJS.ProcessEnv, name: string): string {
  const value = environment[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

export async function runBeadsReadonlyMcp(environment: NodeJS.ProcessEnv = process.env): Promise<void> {
  const repositoryRoot = required(environment, "COGNOVIS_PI_REPOSITORY_ROOT");
  const eventLog = required(environment, "COGNOVIS_PI_EVENT_LOG");
  const sessionId = required(environment, "COGNOVIS_PI_SESSION_ID");
  const server = new Server(
    { name: "beads-readonly", version: "1.0.0" },
    { capabilities: { tools: {} } },
  );
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [{
      name: "beads_read",
      title: "Beads Read",
      description: "Read live task state from the managed repository without mutation or shell access.",
      inputSchema: BEADS_READ_SCHEMA,
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    }],
  }));
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    if (request.params.name !== "beads_read") throw new Error("Beads MCP tool is not allowed");
    const result = await executeBeadsRead(request.params.arguments, {
      repositoryRoot,
      eventLog,
      sessionId,
      redactionCanaries: [],
    });
    return { content: [{ type: "text", text: result.output }] };
  });
  await server.connect(new StdioServerTransport());
}

if (import.meta.main) {
  void runBeadsReadonlyMcp().catch(() => {
    process.stderr.write("Beads read-only MCP server failed\n");
    process.exitCode = 1;
  });
}
