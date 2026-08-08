export { runBeadsReadonlyMcp } from "../acpx-workbench/beads-readonly-mcp.ts";
import { runBeadsReadonlyMcp } from "../acpx-workbench/beads-readonly-mcp.ts";

if (import.meta.main) {
  void runBeadsReadonlyMcp().catch(() => {
    process.stderr.write("Beads read-only MCP server failed\n");
    process.exitCode = 1;
  });
}
