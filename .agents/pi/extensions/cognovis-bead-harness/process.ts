import { spawn } from "node:child_process";

export type ProcessTreeResult = { exitCode: number; aborted: boolean };

function signalTree(pid: number, signal: NodeJS.Signals): void {
  try {
    if (process.platform === "win32") process.kill(pid, signal);
    else process.kill(-pid, signal);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== "ESRCH") throw error;
  }
}

export function runProcessTree(
  command: string,
  args: string[],
  cwd: string,
  signal: AbortSignal,
  onData: (text: string, stream: "stdout" | "stderr") => void,
  killGraceMs = 5_000,
  environment: NodeJS.ProcessEnv = process.env,
): Promise<ProcessTreeResult> {
  if (signal.aborted) return Promise.resolve({ exitCode: 130, aborted: true });
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      detached: process.platform !== "win32",
      env: environment,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let aborted = false;
    let closedCode: number | null | undefined;
    let killTimer: ReturnType<typeof setTimeout> | undefined;
    const finishAbort = () => {
      if (child.pid) signalTree(child.pid, "SIGKILL");
      resolve({ exitCode: closedCode ?? 130, aborted: true });
    };
    const abort = () => {
      aborted = true;
      if (child.pid) {
        signalTree(child.pid, "SIGTERM");
        killTimer = setTimeout(finishAbort, killGraceMs);
      } else {
        resolve({ exitCode: 130, aborted: true });
      }
    };
    signal.addEventListener("abort", abort, { once: true });
    child.stdout.on("data", (chunk) => onData(chunk.toString(), "stdout"));
    child.stderr.on("data", (chunk) => onData(chunk.toString(), "stderr"));
    child.once("error", (error) => {
      signal.removeEventListener("abort", abort);
      if (killTimer) clearTimeout(killTimer);
      if (aborted) resolve({ exitCode: 130, aborted: true });
      else reject(error);
    });
    child.once("close", (code) => {
      signal.removeEventListener("abort", abort);
      closedCode = code;
      if (aborted && killTimer) return;
      if (killTimer) clearTimeout(killTimer);
      resolve({ exitCode: code ?? (aborted ? 130 : 1), aborted });
    });
  });
}
