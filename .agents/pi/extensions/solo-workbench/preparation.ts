import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import type { BeadInvocation } from "../cognovis-bead-harness/runner.ts";
import { loadNativePackProfile } from "../native-pack/profile.ts";
import type { NativePackPacket } from "../native-pack/types.ts";

const BEAD_ID = /^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*$/;
const LIVE_STATUSES = new Set(["open", "in_progress"]);

type Exec = ExtensionAPI["exec"];
type BeadSummary = { id: string; status: string };

function safeSegment(value: string) {
  return value.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "run";
}

function stateHome(environment: NodeJS.ProcessEnv = process.env) {
  return environment.XDG_STATE_HOME?.trim() || path.join(os.homedir(), ".local", "state");
}

export function soloStateRoot(environment: NodeJS.ProcessEnv = process.env) {
  return path.join(stateHome(environment), "cognovis-pi", "solo-workbench");
}

async function command(exec: Exec, executable: string, args: string[], cwd?: string) {
  const result = await exec(executable, args, cwd ? { cwd } : undefined);
  if (result.code !== 0) {
    throw new Error(`${executable} ${args.join(" ")} failed: ${(result.stderr || result.stdout).trim()}`);
  }
  return result.stdout.trim();
}

async function repositoryRoot(exec: Exec, cwd: string) {
  return path.resolve(await command(exec, "git", ["rev-parse", "--show-toplevel"], cwd));
}

async function worktreeBase(exec: Exec, repository: string) {
  for (const candidate of ["refs/remotes/origin/HEAD", "refs/remotes/origin/main", "HEAD"]) {
    const result = await exec("git", ["rev-parse", "--verify", `${candidate}^{commit}`], { cwd: repository });
    if (result.code === 0 && result.stdout.trim()) return result.stdout.trim();
  }
  throw new Error(`Cannot resolve a committed worktree base for ${repository}`);
}

async function loadBead(
  exec: Exec,
  repository: string,
  beadId: string,
  allowedStatuses: ReadonlySet<string> = LIVE_STATUSES,
): Promise<BeadSummary> {
  if (!BEAD_ID.test(beadId)) throw new Error(`Invalid Bead ID: ${beadId}`);
  const output = await command(exec, "bd", ["-C", repository, "show", beadId, "--json"]);
  const [bead] = JSON.parse(output) as BeadSummary[];
  if (!bead || bead.id !== beadId) throw new Error(`Bead ${beadId} was not returned by bd`);
  if (!allowedStatuses.has(bead.status)) throw new Error(`Bead ${beadId} is not executable (${bead.status})`);
  return bead;
}

export async function ensureSoloWorktree(options: {
  exec: Exec;
  cwd: string;
  key: string;
  beadIds: string[];
  environment?: NodeJS.ProcessEnv;
  allowedStatuses?: ReadonlySet<string>;
}) {
  const repository = await repositoryRoot(options.exec, options.cwd);
  for (const beadId of options.beadIds) {
    await loadBead(options.exec, repository, beadId, options.allowedStatuses ?? LIVE_STATUSES);
  }
  const repoKey = createHash("sha256").update(repository).digest("hex").slice(0, 16);
  const worktree = path.join(soloStateRoot(options.environment), "worktrees", repoKey, safeSegment(options.key));
  const branch = `cognovis/${safeSegment(options.key)}`;
  fs.mkdirSync(path.dirname(worktree), { recursive: true, mode: 0o700 });

  if (fs.existsSync(worktree)) {
    const common = await command(options.exec, "git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], repository);
    const worktreeCommon = await command(options.exec, "git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], worktree);
    if (path.resolve(common) !== path.resolve(worktreeCommon)) throw new Error(`${worktree} belongs to another repository`);
    const actualBranch = await command(options.exec, "git", ["symbolic-ref", "--quiet", "HEAD"], worktree);
    if (actualBranch !== `refs/heads/${branch}`) throw new Error(`${worktree} is on ${actualBranch}, expected ${branch}`);
    const status = await command(options.exec, "git", ["status", "--porcelain"], worktree);
    if (status) throw new Error(`${worktree} has uncommitted or conflicting changes`);
  } else {
    const branchExists = await options.exec("git", ["show-ref", "--verify", "--quiet", `refs/heads/${branch}`], { cwd: repository });
    const args = branchExists.code === 0
      ? ["worktree", "add", worktree, branch]
      : ["worktree", "add", "-b", branch, worktree, await worktreeBase(options.exec, repository)];
    await command(options.exec, "git", args, repository);
  }

  await command(options.exec, "bd", ["-C", worktree, "show", options.beadIds[0]!, "--json"]);
  return { repository, worktree, branch };
}

export async function prepareBeadInvocation(
  exec: Exec,
  cwd: string,
  raw: string,
  environment: NodeJS.ProcessEnv = process.env,
): Promise<BeadInvocation> {
  const parts = raw.trim().split(/\s+/).filter(Boolean);
  if (parts.length !== 1 || !BEAD_ID.test(parts[0]!)) throw new Error("Usage: /bead <live-bead-id>");
  const beadId = parts[0]!;
  const prepared = await ensureSoloWorktree({ exec, cwd, key: `bead-${beadId}`, beadIds: [beadId], environment });
  return { beadId, worktree: prepared.worktree };
}

export async function preparePackPacket(
  exec: Exec,
  cwd: string,
  raw: string,
  environment: NodeJS.ProcessEnv = process.env,
) {
  const beadIds = raw.trim().split(/\s+/).filter(Boolean);
  if (beadIds.length < 2) throw new Error("Usage: /pack <live-bead-id> <live-bead-id> [...]");
  if (beadIds.some((id) => !BEAD_ID.test(id))) throw new Error("Every Pack argument must be a valid explicit Bead ID");
  if (new Set(beadIds).size !== beadIds.length) throw new Error("A Native Pack cannot contain duplicate Bead IDs");
  const profile = loadNativePackProfile(environment.COGNOVIS_PI_NATIVE_PACK_PROFILE);
  if (beadIds.length > profile.maxPackSize) {
    throw new Error(`Native Pack ${profile.id} accepts at most ${profile.maxPackSize} Beads`);
  }
  const digest = createHash("sha256").update(beadIds.join("\0")).digest("hex").slice(0, 12);
  const id = `pack-${digest}`;
  const prepared = await ensureSoloWorktree({
    exec,
    cwd,
    key: id,
    beadIds,
    environment,
    allowedStatuses: new Set(["open", "in_progress"]),
  });
  const packet: NativePackPacket = {
    schema: "cognovis.pi.native-pack-packet.v1",
    id,
    repository: prepared.repository,
    worktree: prepared.worktree,
    beadIds,
  };
  const packetDir = path.join(soloStateRoot(environment), "packets");
  fs.mkdirSync(packetDir, { recursive: true, mode: 0o700 });
  const packetPath = path.join(packetDir, `${id}.json`);
  const temporary = `${packetPath}.tmp-${process.pid}`;
  fs.writeFileSync(temporary, `${JSON.stringify(packet, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  fs.renameSync(temporary, packetPath);
  return packetPath;
}
