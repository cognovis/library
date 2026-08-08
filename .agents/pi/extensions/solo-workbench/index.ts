import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { prepareBeadInvocation, preparePackPacket } from "./preparation.ts";
import { registerRunsCommand } from "./runs.ts";

function profilePath(name: string) {
  const resolved = path.resolve(import.meta.dirname, "..", "..", "profiles", `${name}.json`);
  if (!fs.existsSync(resolved)) throw new Error(`Solo Workbench profile is missing: ${name}`);
  return resolved;
}

export default async function soloWorkbench(pi: ExtensionAPI) {
  process.env.COGNOVIS_PI_FUSION_PROFILE ||= profilePath("fusion-sota");
  process.env.COGNOVIS_PI_BEAD_HARNESS_PROFILE ||= profilePath("bead-high-assurance");
  process.env.COGNOVIS_PI_NATIVE_PACK_PROFILE ||= profilePath("native-pack-standard");

  const [fusion, bead, pack] = await Promise.all([
    import("../fusion-harness/fusion-harness.ts"),
    import("../cognovis-bead-harness/index.ts"),
    import("../native-pack/index.ts"),
  ]);
  fusion.default(pi);
  bead.default(pi, {
    description: "Run a high-assurance Bead in an automatically prepared worktree: /bead <live-bead-id>",
    resolveInvocation: (raw, ctx) => prepareBeadInvocation(pi.exec.bind(pi), ctx.cwd, raw),
  });
  pack.default(pi, {
    description: "Prepare and preflight a Native Pack from Bead IDs: /pack <live-bead-id> <live-bead-id> [...]",
    resolvePacketPath: (raw, ctx) => preparePackPacket(pi.exec.bind(pi), ctx.cwd, raw),
  });
  registerRunsCommand(pi);
}
