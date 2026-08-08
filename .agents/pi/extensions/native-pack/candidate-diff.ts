import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";

const exec = promisify(execFile);

function safeRelative(value: string): string {
  if (!value || path.isAbsolute(value) || value.split(path.sep).includes("..")) throw new Error("Candidate diff contains an unsafe untracked path");
  return value;
}

async function diffNewFile(cwd: string, relative: string): Promise<string> {
  const absolute = path.resolve(cwd, relative);
  if (!absolute.startsWith(`${path.resolve(cwd)}${path.sep}`) || !fs.statSync(absolute).isFile()) return "";
  try {
    const result = await exec("git", ["diff", "--no-index", "--binary", "--", "/dev/null", relative], {
      cwd,
      encoding: "utf8",
      maxBuffer: 10 * 1024 * 1024,
    });
    return result.stdout;
  } catch (error) {
    const result = error as { code?: number; stdout?: string; stderr?: string };
    if (result.code !== 1 || typeof result.stdout !== "string") {
      throw new Error(`Unable to render untracked candidate file ${relative}: ${result.stderr ?? String(error)}`);
    }
    return result.stdout;
  }
}

export async function readCandidateDiff(cwd: string, diffRange: string, maxBytes = 50_000): Promise<string> {
  const base = diffRange.split("..")[0];
  if (!base || !/^[0-9a-f]{40}$/.test(base)) throw new Error("Candidate diff has an invalid base SHA");
  const args = diffRange.includes("..WORKTREE@")
    ? ["diff", "--binary", base, "--"]
    : ["diff", "--binary", diffRange, "--"];
  const tracked = await exec("git", args, { cwd, encoding: "utf8", maxBuffer: 10 * 1024 * 1024 });
  let output = tracked.stdout;
  if (diffRange.includes("..WORKTREE@")) {
    const untracked = await exec("git", ["ls-files", "--others", "--exclude-standard", "-z"], { cwd, encoding: "utf8", maxBuffer: 10 * 1024 * 1024 });
    for (const raw of untracked.stdout.split("\0").filter(Boolean).sort()) output += await diffNewFile(cwd, safeRelative(raw));
  }
  if (!output) return "(empty diff)";
  const byteCount = Buffer.byteLength(output);
  if (byteCount > maxBytes) {
    throw new Error(`Candidate diff is ${byteCount} bytes and exceeds the fail-closed ${maxBytes}-byte review limit; split the Bead or raise the reviewed profile limit`);
  }
  return output;
}
