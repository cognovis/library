export const OPEN_BRAIN_READ_TOOLS = [
  "mcp__open-brain__search",
  "mcp__open-brain__timeline",
  "mcp__open-brain__get_observations",
  "mcp__open-brain__search_by_concept",
  "mcp__open-brain__get_context",
  "mcp__open-brain__stats",
] as const;

const READ_CONTEXT_TOOLS = ["read", "grep", "find", "ls", "beads_read", ...OPEN_BRAIN_READ_TOOLS];

export const FUSION_TOOL_MATRICES = {
  readonly: READ_CONTEXT_TOOLS.join(","),
  opinion: READ_CONTEXT_TOOLS.join(","),
  full: [...READ_CONTEXT_TOOLS, "edit", "write"].join(","),
  validator: [...READ_CONTEXT_TOOLS, "write"].join(","),
} as const;
