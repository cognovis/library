export {
  callOpenBrainReadTool,
  configureOpenBrainReadonlyServer,
  filterOpenBrainTools,
  openBrainApiKey,
  OPEN_BRAIN_MCP_URL,
  OPEN_BRAIN_READ_TOOLS,
  runOpenBrainReadonlyProxy,
} from "../acpx-workbench/open-brain-readonly-proxy.ts";
import { runOpenBrainReadonlyProxy } from "../acpx-workbench/open-brain-readonly-proxy.ts";

if (import.meta.main) {
  void runOpenBrainReadonlyProxy().catch(() => {
    process.stderr.write("Open Brain read-only proxy failed\n");
    process.exitCode = 1;
  });
}
