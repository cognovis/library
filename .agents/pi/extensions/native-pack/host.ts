import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";

import { parseDockerCleanupReceipt } from "../docker-lifecycle-guard/index.ts";
import type { NativePackHost } from "./engine.ts";
import type { BeadRecord, CandidateSubject, DockerCleanupReceipt, GateResult } from "./types.ts";

const exec = promisify(execFile);

async function command(file: string, args: string[], cwd: string): Promise<{ stdout: string; stderr: string; exitCode: number }> {
  try {
    const result = await exec(file, args, { cwd, encoding: "utf8", maxBuffer: 10 * 1024 * 1024 });
    return { stdout: result.stdout, stderr: result.stderr, exitCode: 0 };
  } catch (error) {
    const failure = error as { stdout?: string; stderr?: string; code?: number };
    return { stdout: failure.stdout ?? "", stderr: failure.stderr ?? String(error), exitCode: typeof failure.code === "number" ? failure.code : 1 };
  }
}

async function git(cwd: string, args: string[]): Promise<string> {
  const result = await command("git", args, cwd);
  if (result.exitCode !== 0) throw new Error(`git ${args.join(" ")} failed: ${result.stderr.trim()}`);
  return result.stdout.trim();
}

export class GitBeadsPackHost implements NativePackHost {
  readonly worktree: string;
  private readonly ccoreCommand: string;
  private lastCandidate: { sha: string; baseSha: string } | undefined;

  constructor(worktree: string, ccoreCommand = process.env.COGNOVIS_CCORE_COMMAND ?? "ccore") {
    this.worktree = path.resolve(worktree);
    this.ccoreCommand = ccoreCommand;
  }

  async validateLinkedWorktree(worktree: string, repository?: string): Promise<void> {
    const absolute = path.resolve(worktree);
    if (absolute !== this.worktree) throw new Error("Native Pack worktree binding changed");
    const inside = await git(absolute, ["rev-parse", "--is-inside-work-tree"]);
    if (inside !== "true") throw new Error(`${absolute} is not a Git worktree`);
    const gitDir = path.resolve(await git(absolute, ["rev-parse", "--path-format=absolute", "--git-dir"]));
    const commonDir = path.resolve(await git(absolute, ["rev-parse", "--path-format=absolute", "--git-common-dir"]));
    if (gitDir === commonDir) throw new Error(`${absolute} is the main checkout, not a linked worktree`);
    if (repository) {
      const repositoryCommon = path.resolve(await git(path.resolve(repository), ["rev-parse", "--path-format=absolute", "--git-common-dir"]));
      if (repositoryCommon !== commonDir) throw new Error("Native Pack repository and worktree do not share Git identity");
    }
  }

  async loadBead(beadId: string): Promise<BeadRecord> {
    const result = await command("bd", ["-C", this.worktree, "show", beadId, "--json"], this.worktree);
    if (result.exitCode !== 0) throw new Error(`Unable to load Bead ${beadId}: ${result.stderr.trim()}`);
    const parsed = JSON.parse(result.stdout) as any;
    const item = Array.isArray(parsed) ? parsed[0] : parsed;
    if (!item || item.id !== beadId) throw new Error(`Bead ${beadId} returned an invalid live record`);
    return {
      id: item.id,
      title: String(item.title ?? ""),
      status: String(item.status ?? ""),
      body: String(item.description ?? item.body ?? ""),
    };
  }

  async claimBeads(beadIds: string[]): Promise<void> {
    const result = await command("bd", ["-C", this.worktree, "update", ...beadIds, "--claim", "--json"], this.worktree);
    if (result.exitCode !== 0) throw new Error(`Unable to atomically claim Native Pack Beads: ${result.stderr.trim()}`);
    const claimed = JSON.parse(result.stdout) as Array<{ id?: string; status?: string }>;
    const ids = new Set(claimed.map((item) => item.id));
    if (beadIds.some((id) => !ids.has(id))) throw new Error("Native Pack claim response omitted a Bead");
  }

  currentHead(): Promise<string> {
    return git(this.worktree, ["rev-parse", "HEAD"]);
  }

  async assertClean(): Promise<void> {
    const status = await git(this.worktree, ["status", "--porcelain=v1", "--untracked-files=all"]);
    if (status) throw new Error("Native Pack worktree is not clean after committed Bead delivery");
  }

  private async worktreeDigest(): Promise<string> {
    const status = await git(this.worktree, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]);
    const diff = await git(this.worktree, ["diff", "--binary", "HEAD", "--"]);
    const hash = createHash("sha1").update(status).update("\0").update(diff);
    for (const record of status.split("\0").filter(Boolean).sort()) {
      if (!record.startsWith("?? ")) continue;
      const relative = record.slice(3);
      const absolute = path.resolve(this.worktree, relative);
      if (!absolute.startsWith(`${this.worktree}${path.sep}`)) throw new Error("Untracked candidate path escapes the worktree");
      if (fs.statSync(absolute).isFile()) hash.update(relative).update("\0").update(fs.readFileSync(absolute));
    }
    return hash.digest("hex");
  }

  async candidateSubject(baseSha: string): Promise<CandidateSubject> {
    const candidateSha = await this.worktreeDigest();
    this.lastCandidate = { sha: candidateSha, baseSha };
    return { candidateSha, diffRange: `${baseSha}..WORKTREE@${candidateSha}` };
  }

  async assertCandidate(candidateSha: string): Promise<void> {
    if (!this.lastCandidate || this.lastCandidate.sha !== candidateSha) {
      const head = await this.currentHead();
      if (head === candidateSha) return;
      throw new Error("Native Pack candidate was not bound by this host");
    }
    const current = await this.worktreeDigest();
    if (current !== candidateSha) throw new Error("Native Pack candidate drifted during review");
  }

  async runGate(argv: string[]): Promise<GateResult> {
    const [file, ...args] = argv;
    if (!file) throw new Error("Gate argv is empty");
    const startedAt = performance.now();
    const result = await command(file, args, this.worktree);
    const durationMs = Math.round(performance.now() - startedAt);
    const output = `${result.stdout}${result.stderr ? `\n${result.stderr}` : ""}`.slice(-50_000);
    return { argv: [...argv], exitCode: result.exitCode, output, durationMs };
  }

  async cleanupEphemeralDocker(beadIds: string[]): Promise<DockerCleanupReceipt> {
    if (beadIds.length === 0) throw new Error("Native Pack Docker cleanup requires explicit Bead IDs");
    const args = ["cleanup", "docker", ...beadIds.flatMap((beadId) => ["--bead", beadId])];
    const result = await command(this.ccoreCommand, args, this.worktree);
    let receipt: unknown;
    try {
      receipt = JSON.parse(result.stdout);
    } catch {
      throw new Error(`ccore Docker cleanup returned invalid JSON: ${result.stderr.trim() || result.stdout.trim()}`);
    }
    if (![0, 3].includes(result.exitCode)) {
      const candidate = receipt as { code?: string; message?: string };
      throw new Error(
        `ccore Docker cleanup blocked${candidate.code ? ` (${candidate.code})` : ""}: ${candidate.message || result.stderr.trim() || "unknown failure"}`,
      );
    }
    return parseDockerCleanupReceipt(receipt);
  }

  async commitBead(beadId: string): Promise<string> {
    const status = await git(this.worktree, ["status", "--porcelain=v1", "--untracked-files=all"]);
    if (!status) throw new Error(`Bead ${beadId} produced no worktree changes`);
    await git(this.worktree, ["add", "-A", "--"]);
    await git(this.worktree, ["commit", "-m", `${beadId}: native Pack delivery`]);
    this.lastCandidate = undefined;
    return this.currentHead();
  }
}
