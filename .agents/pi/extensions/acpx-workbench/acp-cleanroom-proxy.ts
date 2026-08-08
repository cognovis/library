import { spawn } from "node:child_process";
import readline from "node:readline";

import { AUTH_ENVIRONMENT_NAMES } from "./auth-provenance.ts";
import {
  parseWorkbenchProvider,
  type ProviderRuntimeManifest,
  type WorkbenchProvider,
} from "./providers.ts";

export interface CleanroomProxyOptions {
  repositoryRoot: string;
  downstreamCwd: string;
  allowedTools: string[];
  beadsMcpPath: string;
  mcpCommand: string;
  provider: WorkbenchProvider;
  openBrainProxyPath: string;
}

function managedMcpServers(options: CleanroomProxyOptions) {
  return [{
    name: "beads",
    command: options.mcpCommand,
    args: [options.beadsMcpPath],
    env: [
      { name: "COGNOVIS_PI_REPOSITORY_ROOT", value: options.repositoryRoot },
      { name: "COGNOVIS_PI_EVENT_LOG", value: process.env.COGNOVIS_PI_EVENT_LOG ?? "" },
      { name: "COGNOVIS_PI_SESSION_ID", value: process.env.COGNOVIS_PI_SESSION_ID ?? "" },
    ],
  }, {
    name: "open-brain",
    command: options.mcpCommand,
    args: [options.openBrainProxyPath],
    env: [],
  }];
}

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

function managedSystemPrompt(meta: Record<string, unknown>): string | { append: string } | null {
  const prompt = meta.systemPrompt;
  if (typeof prompt === "string" && prompt.length > 0) return prompt;
  const append = stringAt(object(prompt), "append");
  return append ? { append } : null;
}

function stringAt(value: Record<string, unknown>, key: string): string | null {
  const entry = value[key];
  return typeof entry === "string" && entry.length > 0 ? entry : null;
}

export function rewriteSessionNewMessage(
  value: unknown,
  options: CleanroomProxyOptions,
): unknown {
  const message = object(value);
  if (!new Set(["session/new", "session/load", "session/resume"]).has(String(message.method))) {
    return value;
  }
  const params = object(message.params);
  const meta = object(params._meta);
  const sharedParams = {
    ...params,
    cwd: options.downstreamCwd,
    additionalDirectories: [options.repositoryRoot],
    mcpServers: managedMcpServers(options),
  };
  if (options.provider !== "claude") {
    const systemPrompt = managedSystemPrompt(meta);
    return {
      ...message,
      params: {
        ...sharedParams,
        _meta: systemPrompt ? { systemPrompt } : {},
      },
    };
  }
  const claudeCode = object(meta.claudeCode);
  const requested = object(claudeCode.options);
  const forcedOptions = {
    ...(typeof requested.model === "string" ? { model: requested.model } : {}),
    settingSources: [],
    settings: {
      disableAllHooks: true,
      enabledPlugins: {},
      permissions: {
        defaultMode: "default",
        allow: [],
        ask: [...options.allowedTools],
        deny: ["Bash", "WebFetch", "WebSearch"],
      },
    },
    skills: [],
    plugins: [],
    tools: [...options.allowedTools],
    allowedTools: [],
    disallowedTools: ["Bash", "WebFetch", "WebSearch", "Task", "Skill"],
    strictMcpConfig: true,
    mcpServers: {},
    additionalDirectories: [],
  };
  return {
    ...message,
    params: {
      ...sharedParams,
      _meta: {
        ...meta,
        claudeCode: { ...claudeCode, options: forcedOptions },
      },
    },
  };
}

export function cleanAdapterEnvironment(
  environment: NodeJS.ProcessEnv,
): NodeJS.ProcessEnv {
  const clean: NodeJS.ProcessEnv = { ...environment };
  for (const name of AUTH_ENVIRONMENT_NAMES) delete clean[name];
  for (const name of [
    "ACPX_CLAUDE_INCLUDE_USER_SETTINGS",
    "BASH_ENV",
    "CDPATH",
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_CODE_EXECUTABLE",
    "CLAUDE_MODEL_CONFIG",
    "ENV",
    "MAX_THINKING_TOKENS",
    "NODE_OPTIONS",
  ]) {
    delete clean[name];
  }
  for (const name of Object.keys(clean)) {
    if (
      name.startsWith("ACPX_AUTH_") ||
      name.startsWith("ANTHROPIC_") ||
      name.startsWith("CLAUDE_CODE_") ||
      name.startsWith("CODEX_") ||
      name.startsWith("COGNOVIS_PI_") ||
      name.startsWith("KIMI_") ||
      name.startsWith("MCP_") ||
      name.startsWith("MOONSHOT_") ||
      name.startsWith("OPENAI_")
    ) {
      delete clean[name];
    }
  }
  return clean;
}

export function providerRuntimeLaunch(
  manifestRaw: string,
  provider: WorkbenchProvider,
): { adapter: string[]; environment: Record<string, string> } {
  const manifest = JSON.parse(manifestRaw) as ProviderRuntimeManifest;
  const entry = manifest[provider];
  if (!entry || entry.status === "unavailable") {
    const reason = entry?.status === "unavailable"
      ? entry.reason
      : "runtime manifest entry is missing";
    throw new Error(`${provider} provider is unavailable: ${reason}`);
  }
  const allowedAdapterEnvironment = new Set(["CODEX_CONFIG"]);
  if (
    entry.adapterArgv.length === 0 ||
    !entry.adapterArgv.every((item) => typeof item === "string" && item.length > 0) ||
    Object.entries(entry.adapterEnvironment).some(
      ([key, value]) => !allowedAdapterEnvironment.has(key) || typeof value !== "string",
    )
  ) {
    throw new Error(`${provider} provider runtime manifest is invalid`);
  }
  return {
    adapter: entry.adapterArgv,
    environment: entry.adapterEnvironment,
  };
}

async function main(): Promise<void> {
  const providerIndex = process.argv.indexOf("--provider");
  const providerValue = providerIndex >= 0 ? process.argv[providerIndex + 1] : undefined;
  if (!providerValue) throw new Error("Clean-room ACP proxy requires --provider");
  const provider = parseWorkbenchProvider(providerValue);
  const runtimesRaw = process.env.COGNOVIS_PI_PROVIDER_RUNTIMES_JSON;
  const repositoryRoot = process.env.COGNOVIS_PI_REPOSITORY_ROOT;
  const downstreamCwd = process.env.COGNOVIS_PI_DOWNSTREAM_CWD;
  const allowedTools = process.env.COGNOVIS_PI_ALLOWED_TOOLS?.split(",").filter(Boolean) ?? [];
  const openBrainProxyPath = process.env.COGNOVIS_PI_OPEN_BRAIN_PROXY_PATH;
  const beadsMcpPath = process.env.COGNOVIS_PI_BEADS_MCP_PATH;
  const mcpCommand = process.env.COGNOVIS_PI_BUN_COMMAND;
  if (!runtimesRaw || !repositoryRoot || !downstreamCwd || !openBrainProxyPath || !beadsMcpPath || !mcpCommand) {
    throw new Error("Clean-room ACP proxy configuration is incomplete");
  }
  const launch = providerRuntimeLaunch(runtimesRaw, provider);
  const adapter = launch.adapter;
  const [executable, ...adapterArgs] = adapter;
  if (!executable) throw new Error("Clean-room ACP proxy adapter executable is missing");
  const child = spawn(executable, adapterArgs, {
    cwd: downstreamCwd,
    env: {
      ...cleanAdapterEnvironment(process.env),
      ...launch.environment,
    },
    stdio: ["pipe", "pipe", "pipe"],
  });
  child.stdout.pipe(process.stdout);
  child.stderr.pipe(process.stderr);
  const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of lines) {
    let output = line;
    try {
      output = JSON.stringify(
        rewriteSessionNewMessage(JSON.parse(line), {
          repositoryRoot,
          downstreamCwd,
          allowedTools,
          beadsMcpPath,
          mcpCommand,
          provider,
          openBrainProxyPath,
        }),
      );
    } catch {
      // Preserve protocol diagnostics that are not JSON-RPC messages.
    }
    child.stdin.write(`${output}\n`);
  }
  child.stdin.end();
  const exitCode = await new Promise<number>((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolve(code ?? 1));
  });
  process.exitCode = exitCode;
}

if (import.meta.main) {
  void main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
