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
  await agent("Run the selected full.adversarial_review leaf for the bead.", {
    "slot": "adversarial_review"
  });
  await agent("Run the selected full.verification leaf for the bead.", {
    "slot": "verification"
  });
  await agent("Run the selected full.session_close leaf for the bead.", {
    "slot": "session_close"
  });
}
