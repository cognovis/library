import path from "node:path";
import { readFile } from "node:fs/promises";

import { launchWorkbench, defaultStateRoot } from "./launcher.ts";
import { parseWorkbenchProvider } from "./providers.ts";
import { SessionStore } from "./session-store.ts";

function value(args: string[], name: string): string | undefined {
  const index = args.indexOf(name);
  if (index < 0) return undefined;
  const result = args[index + 1];
  if (!result || result.startsWith("--")) throw new Error(`${name} requires a value`);
  return result;
}

function help(): string {
  return [
    "Usage:",
    "  bun <installed-extension>/cli.ts launch [--provider claude|codex|kimi] [--fusion-profile FILE | --bead-profile FILE] [--prompt TEXT] [--state-dir DIR] [--session-id ID]",
    "  bun <installed-extension>/cli.ts sessions [--state-dir DIR]",
    "  bun <installed-extension>/cli.ts session [current|ID] [--state-dir DIR]",
    "  bun <installed-extension>/cli.ts receipt [current|ID] [--state-dir DIR]",
  ].join("\n");
}

async function main(args = process.argv.slice(2)): Promise<number> {
  const command = args[0];
  const stateRoot = path.resolve(value(args, "--state-dir") ?? defaultStateRoot());
  const store = new SessionStore(stateRoot);
  if (!command || command === "help" || command === "--help") {
    process.stdout.write(`${help()}\n`);
    return 0;
  }
  if (command === "launch") {
    const prompt = value(args, "--prompt");
    const requestedSessionId = value(args, "--session-id");
    const fusionProfile = value(args, "--fusion-profile");
    const beadProfile = value(args, "--bead-profile");
    if (fusionProfile && beadProfile) throw new Error("--fusion-profile and --bead-profile are mutually exclusive");
    const provider = parseWorkbenchProvider(value(args, "--provider"));
    const result = await launchWorkbench({
      repositoryRoot: process.cwd(),
      stateRoot,
      print: Boolean(prompt),
      provider,
      ...(fusionProfile ? { fusionProfile } : {}),
      ...(beadProfile ? { beadProfile } : {}),
      ...(requestedSessionId ? { sessionId: requestedSessionId } : {}),
      ...(prompt ? { prompt } : {}),
    });
    if (result.stdout) process.stdout.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
    process.stderr.write(`workbench session: ${result.sessionId}\n`);
    return result.exitCode;
  }
  if (command === "sessions") {
    const summaries = await Promise.all((await store.listSessionIds()).map((id) => store.summarize(id)));
    process.stdout.write(`${JSON.stringify(summaries, null, 2)}\n`);
    return 0;
  }
  if (command === "session" || command === "receipt") {
    const requested = args[1] && !args[1].startsWith("--") ? args[1] : "current";
    const sessionId = requested === "current" ? await store.currentSessionId() : requested;
    if (!sessionId) throw new Error("No current workbench session");
    if (command === "session") {
      process.stdout.write(`${JSON.stringify(await store.summarize(sessionId), null, 2)}\n`);
    } else {
      const receipt = await readFile(store.receiptPath(sessionId), "utf8");
      process.stdout.write(receipt);
    }
    return 0;
  }
  throw new Error(`Unknown command: ${command}\n${help()}`);
}

void main().then(
  (code) => { process.exitCode = code; },
  (error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  },
);
