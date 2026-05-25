export const meta = {
  "name": "bead-context-pack",
  "description": "Collect a read-only context pack for a bead.",
  "phases": [
    {
      "name": "context"
    }
  ]
};

const pack = await agent(
  "Gather the primary files, tests, symbols, graph neighbors, and blockers for the active bead.",
  {
    "slot": "implementation",
    "agentType": "bead-context",
    "readOnly": true,
    "output": "json"
  }
);

return {
  "pack": pack
};
