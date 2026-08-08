// @bun
var __create = Object.create;
var __getProtoOf = Object.getPrototypeOf;
var __defProp = Object.defineProperty;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
function __accessProp(key) {
  return this[key];
}
var __toESMCache_node;
var __toESMCache_esm;
var __toESM = (mod, isNodeMode, target) => {
  var canCache = mod != null && typeof mod === "object";
  if (canCache) {
    var cache = isNodeMode ? __toESMCache_node ??= new WeakMap : __toESMCache_esm ??= new WeakMap;
    var cached = cache.get(mod);
    if (cached)
      return cached;
  }
  target = mod != null ? __create(__getProtoOf(mod)) : {};
  const to = isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target;
  for (let key of __getOwnPropNames(mod))
    if (!__hasOwnProp.call(to, key))
      __defProp(to, key, {
        get: __accessProp.bind(mod, key),
        enumerable: true
      });
  if (canCache)
    cache.set(mod, to);
  return to;
};
var __commonJS = (cb, mod) => () => (mod || cb((mod = { exports: {} }).exports, mod), mod.exports);
var __returnValue = (v) => v;
function __exportSetter(name, newValue) {
  this[name] = __returnValue.bind(null, newValue);
}
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, {
      get: all[name],
      enumerable: true,
      configurable: true,
      set: __exportSetter.bind(all, name)
    });
};
var __require = import.meta.require;

// extensions/acpx-workbench/acp-cleanroom-proxy.ts
import { spawn } from "child_process";
import readline from "readline";

// extensions/acpx-workbench/auth-provenance.ts
var AUTH_ENVIRONMENT_NAMES = [
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_AUTH_TOKEN",
  "ANTHROPIC_OAUTH_TOKEN",
  "CODEX_API_KEY",
  "KIMI_API_KEY",
  "MOONSHOT_API_KEY",
  "OPENAI_API_KEY"
];
function snapshotEnvironment(environment) {
  return Object.fromEntries(AUTH_ENVIRONMENT_NAMES.map((name) => [name, Boolean(environment[name])]));
}

// extensions/acpx-workbench/providers.ts
import { execFile } from "child_process";
import { constants } from "fs";
import { access, readFile } from "fs/promises";
import path from "path";
import { promisify } from "util";
var WORKBENCH_PROVIDERS = ["claude", "codex", "kimi"];

class UnknownWorkbenchProviderError extends Error {
  code = "UNKNOWN_WORKBENCH_PROVIDER";
  constructor(value) {
    super(`Unknown workbench provider: ${value}. Expected one of: ${WORKBENCH_PROVIDERS.join(", ")}`);
    this.name = "UnknownWorkbenchProviderError";
  }
}

class ProviderUnavailableError extends Error {
  code = "WORKBENCH_PROVIDER_UNAVAILABLE";
  provider;
  constructor(provider, message) {
    super(`${provider} provider is unavailable: ${message}`);
    this.name = "ProviderUnavailableError";
    this.provider = provider;
  }
}
var execFileAsync = promisify(execFile);
var REPOSITORY_ADAPTER_PACKAGES = {
  claude: "@agentclientprotocol/claude-agent-acp",
  codex: "@agentclientprotocol/codex-acp"
};
function parseWorkbenchProvider(value, defaultProvider = "claude") {
  const selected = value?.trim() || defaultProvider;
  if (!WORKBENCH_PROVIDERS.includes(selected)) {
    throw new UnknownWorkbenchProviderError(selected);
  }
  return selected;
}
async function findOnPath(executable, environment) {
  const pathValue = environment.PATH ?? "";
  for (const directory of pathValue.split(path.delimiter).filter(Boolean)) {
    const candidate = path.resolve(directory, executable);
    try {
      await access(candidate, constants.X_OK);
      return candidate;
    } catch {}
  }
  return null;
}
async function probeHostVersion(provider, executable, arguments_, environment) {
  try {
    const result = await execFileAsync(executable, [...arguments_, "--version"], {
      env: environment,
      timeout: 5000
    });
    const observed = `${result.stdout}${result.stderr}`.trim();
    const match = observed.match(/\d+\.\d+\.\d+/);
    if (!match) {
      throw new Error(`version command returned an unrecognized value: ${observed || "<empty>"}`);
    }
    return match[0];
  } catch (error) {
    if (error instanceof ProviderUnavailableError)
      throw error;
    throw new ProviderUnavailableError(provider, error instanceof Error ? error.message : "version probe failed");
  }
}
async function resolveProviderRuntime(repositoryRoot, provider, selection, environment) {
  if (selection.agent !== provider) {
    throw new ProviderUnavailableError(provider, "profile agent does not match selection");
  }
  const [configuredExecutable, ...arguments_] = selection.adapter.command;
  if (!configuredExecutable) {
    throw new ProviderUnavailableError(provider, "profile adapter command is empty");
  }
  if (selection.adapter.provenance === "repository-package") {
    const executable2 = path.resolve(repositoryRoot, configuredExecutable);
    const packageName = REPOSITORY_ADAPTER_PACKAGES[provider];
    if (!packageName) {
      throw new ProviderUnavailableError(provider, "no repository package is registered");
    }
    let runtimeVersion2;
    try {
      await access(executable2, constants.X_OK);
      const manifestPath = path.join(repositoryRoot, "node_modules", packageName, "package.json");
      const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
      if (manifest.name !== packageName || typeof manifest.version !== "string") {
        throw new Error(`${packageName} package metadata is invalid`);
      }
      runtimeVersion2 = manifest.version;
    } catch {
      const bunx = await findOnPath("bunx", environment);
      if (!bunx) {
        throw new ProviderUnavailableError(provider, `${configuredExecutable} is missing and bunx was not found on PATH`);
      }
      const portableArguments = [`${packageName}@${selection.adapter.version}`];
      const portableVersion = await probeHostVersion(provider, bunx, portableArguments, environment);
      if (portableVersion !== selection.adapter.version) {
        throw new ProviderUnavailableError(provider, `profile requires adapter ${selection.adapter.version}, resolved package is ${portableVersion}`);
      }
      return {
        adapterArgv: [bunx, ...portableArguments],
        adapterEnvironment: provider === "codex" ? {
          CODEX_CONFIG: JSON.stringify({
            mcp_servers: {},
            project_doc_max_bytes: 0
          })
        } : {},
        commandProvenance: {
          kind: "host-binary",
          executable: bunx,
          arguments: portableArguments,
          configuredVersion: selection.adapter.version,
          runtimeVersion: portableVersion,
          managedEnvironmentNames: provider === "codex" ? ["CODEX_CONFIG"] : []
        }
      };
    }
    if (runtimeVersion2 !== selection.adapter.version) {
      throw new ProviderUnavailableError(provider, `profile requires adapter ${selection.adapter.version}, installed package is ${runtimeVersion2}`);
    }
    return {
      adapterArgv: [executable2, ...arguments_],
      adapterEnvironment: provider === "codex" ? {
        CODEX_CONFIG: JSON.stringify({
          mcp_servers: {},
          project_doc_max_bytes: 0
        })
      } : {},
      commandProvenance: {
        kind: selection.adapter.provenance,
        executable: executable2,
        arguments: arguments_,
        configuredVersion: selection.adapter.version,
        runtimeVersion: runtimeVersion2,
        managedEnvironmentNames: provider === "codex" ? ["CODEX_CONFIG"] : []
      }
    };
  }
  const executable = await findOnPath(configuredExecutable, environment);
  if (!executable) {
    throw new ProviderUnavailableError(provider, `${configuredExecutable} was not found on PATH`);
  }
  const runtimeVersion = await probeHostVersion(provider, executable, arguments_, environment);
  return {
    adapterArgv: [executable, ...arguments_],
    adapterEnvironment: {},
    commandProvenance: {
      kind: selection.adapter.provenance,
      executable,
      arguments: arguments_,
      runtimeVersion,
      managedEnvironmentNames: []
    }
  };
}
async function resolveProviderRuntimes(repositoryRoot, selections, environment) {
  const entries = await Promise.all(WORKBENCH_PROVIDERS.map(async (provider) => {
    try {
      const runtime = await resolveProviderRuntime(repositoryRoot, provider, selections[provider], environment);
      return [
        provider,
        {
          status: "available",
          adapterArgv: runtime.adapterArgv,
          adapterEnvironment: runtime.adapterEnvironment,
          commandProvenance: runtime.commandProvenance
        }
      ];
    } catch (error) {
      return [
        provider,
        {
          status: "unavailable",
          reason: error instanceof Error ? error.message : `${provider} provider is unavailable`
        }
      ];
    }
  }));
  return Object.fromEntries(entries);
}

// extensions/acpx-workbench/acp-cleanroom-proxy.ts
function managedMcpServers(options) {
  return [{
    name: "beads",
    command: options.mcpCommand,
    args: [options.beadsMcpPath],
    env: [
      { name: "COGNOVIS_PI_REPOSITORY_ROOT", value: options.repositoryRoot },
      { name: "COGNOVIS_PI_EVENT_LOG", value: process.env.COGNOVIS_PI_EVENT_LOG ?? "" },
      { name: "COGNOVIS_PI_SESSION_ID", value: process.env.COGNOVIS_PI_SESSION_ID ?? "" }
    ]
  }, {
    name: "open-brain",
    command: options.mcpCommand,
    args: [options.openBrainProxyPath],
    env: []
  }];
}
function object(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? { ...value } : {};
}
function managedSystemPrompt(meta) {
  const prompt = meta.systemPrompt;
  if (typeof prompt === "string" && prompt.length > 0)
    return prompt;
  const append = stringAt(object(prompt), "append");
  return append ? { append } : null;
}
function stringAt(value, key) {
  const entry = value[key];
  return typeof entry === "string" && entry.length > 0 ? entry : null;
}
function rewriteSessionNewMessage(value, options) {
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
    mcpServers: managedMcpServers(options)
  };
  if (options.provider !== "claude") {
    const systemPrompt = managedSystemPrompt(meta);
    return {
      ...message,
      params: {
        ...sharedParams,
        _meta: systemPrompt ? { systemPrompt } : {}
      }
    };
  }
  const claudeCode = object(meta.claudeCode);
  const requested = object(claudeCode.options);
  const forcedOptions = {
    ...typeof requested.model === "string" ? { model: requested.model } : {},
    settingSources: [],
    settings: {
      disableAllHooks: true,
      enabledPlugins: {},
      permissions: {
        defaultMode: "default",
        allow: [],
        ask: [...options.allowedTools],
        deny: ["Bash", "WebFetch", "WebSearch"]
      }
    },
    skills: [],
    plugins: [],
    tools: [...options.allowedTools],
    allowedTools: [],
    disallowedTools: ["Bash", "WebFetch", "WebSearch", "Task", "Skill"],
    strictMcpConfig: true,
    mcpServers: {},
    additionalDirectories: []
  };
  return {
    ...message,
    params: {
      ...sharedParams,
      _meta: {
        ...meta,
        claudeCode: { ...claudeCode, options: forcedOptions }
      }
    }
  };
}
function cleanAdapterEnvironment(environment) {
  const clean = { ...environment };
  for (const name of AUTH_ENVIRONMENT_NAMES)
    delete clean[name];
  for (const name of [
    "ACPX_CLAUDE_INCLUDE_USER_SETTINGS",
    "BASH_ENV",
    "CDPATH",
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_CODE_EXECUTABLE",
    "CLAUDE_MODEL_CONFIG",
    "ENV",
    "MAX_THINKING_TOKENS",
    "NODE_OPTIONS"
  ]) {
    delete clean[name];
  }
  for (const name of Object.keys(clean)) {
    if (name.startsWith("ACPX_AUTH_") || name.startsWith("ANTHROPIC_") || name.startsWith("CLAUDE_CODE_") || name.startsWith("CODEX_") || name.startsWith("COGNOVIS_PI_") || name.startsWith("KIMI_") || name.startsWith("MCP_") || name.startsWith("MOONSHOT_") || name.startsWith("OPENAI_")) {
      delete clean[name];
    }
  }
  return clean;
}
function providerRuntimeLaunch(manifestRaw, provider) {
  const manifest = JSON.parse(manifestRaw);
  const entry = manifest[provider];
  if (!entry || entry.status === "unavailable") {
    const reason = entry?.status === "unavailable" ? entry.reason : "runtime manifest entry is missing";
    throw new Error(`${provider} provider is unavailable: ${reason}`);
  }
  const allowedAdapterEnvironment = new Set(["CODEX_CONFIG"]);
  if (entry.adapterArgv.length === 0 || !entry.adapterArgv.every((item) => typeof item === "string" && item.length > 0) || Object.entries(entry.adapterEnvironment).some(([key, value]) => !allowedAdapterEnvironment.has(key) || typeof value !== "string")) {
    throw new Error(`${provider} provider runtime manifest is invalid`);
  }
  return {
    adapter: entry.adapterArgv,
    environment: entry.adapterEnvironment
  };
}
async function main() {
  const providerIndex = process.argv.indexOf("--provider");
  const providerValue = providerIndex >= 0 ? process.argv[providerIndex + 1] : undefined;
  if (!providerValue)
    throw new Error("Clean-room ACP proxy requires --provider");
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
  if (!executable)
    throw new Error("Clean-room ACP proxy adapter executable is missing");
  const child = spawn(executable, adapterArgs, {
    cwd: downstreamCwd,
    env: {
      ...cleanAdapterEnvironment(process.env),
      ...launch.environment
    },
    stdio: ["pipe", "pipe", "pipe"]
  });
  child.stdout.pipe(process.stdout);
  child.stderr.pipe(process.stderr);
  const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of lines) {
    let output = line;
    try {
      output = JSON.stringify(rewriteSessionNewMessage(JSON.parse(line), {
        repositoryRoot,
        downstreamCwd,
        allowedTools,
        beadsMcpPath,
        mcpCommand,
        provider,
        openBrainProxyPath
      }));
    } catch {}
    child.stdin.write(`${output}
`);
  }
  child.stdin.end();
  const exitCode = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolve(code ?? 1));
  });
  process.exitCode = exitCode;
}
if (import.meta.main) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}
`);
    process.exitCode = 1;
  });
}
export {
  rewriteSessionNewMessage,
  providerRuntimeLaunch,
  cleanAdapterEnvironment
};
