export const meta = {
  "name": "bead-orchestrator",
  "workflow": "full",
  "version": "1",
  "description": "Deterministic cdx bead-orchestrator workflow spine."
};

export async function run(args) {
  await agent("Run the selected full.implementation leaf for the bead.", {
    "slot": "implementation"
  });
}
