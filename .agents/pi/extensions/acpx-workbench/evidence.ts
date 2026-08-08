import { createHash } from "node:crypto";
import { appendFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

export async function writeJson(target: string, value: unknown): Promise<void> {
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

export async function appendJsonLine(target: string, value: unknown): Promise<void> {
  await mkdir(path.dirname(target), { recursive: true });
  await appendFile(target, `${JSON.stringify(value)}\n`, "utf8");
}

export function identityHash(value: string | undefined): string | null {
  return value
    ? createHash("sha256").update(value).digest("hex").slice(0, 16)
    : null;
}
