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

// extensions/acpx-workbench/cli.ts
import path7 from "path";
import { readFile as readFile5 } from "fs/promises";

// extensions/acpx-workbench/launcher.ts
import { randomUUID as randomUUID2 } from "crypto";
import { spawn } from "child_process";
import { mkdir as mkdir4, readFile as readFile4, stat as stat2 } from "fs/promises";
import os from "os";
import path6 from "path";

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

// extensions/acpx-workbench/profile.ts
import { createHash } from "crypto";
import { readFile, realpath } from "fs/promises";
import path from "path";
function publicModelId(model) {
  return typeof model === "string" ? model : model.id;
}
function validModelRoute(model, provider) {
  if (typeof model === "string")
    return model.startsWith(`${provider}:`);
  return Object.keys(model).length === 2 && typeof model.id === "string" && model.id.startsWith(`${provider}:`) && typeof model.nativeModel === "string" && model.nativeModel.startsWith(`${provider}:`);
}
var ALLOWED_PROFILE_PATHS = {
  "pi-workbench": [
    ".agents/pi/profiles/pi-workbench.json",
    "profiles/pi-workbench.json"
  ]
};
var PROJECT_NATIVE_RESOURCE_PATHS = {
  "project-native:pi-extension/acpx-workbench/index.ts": [
    ".agents/pi/extensions/acpx-workbench/index.ts",
    "extensions/acpx-workbench/index.ts"
  ],
  "project-native:pi-extension/acpx-workbench/dist/provider.js": [
    ".agents/pi/extensions/acpx-workbench/dist/provider.js",
    "extensions/acpx-workbench/dist/provider.js"
  ],
  "project-native:pi-extension/acpx-workbench/dist/acp-cleanroom-proxy.js": [
    ".agents/pi/extensions/acpx-workbench/dist/acp-cleanroom-proxy.js",
    "extensions/acpx-workbench/dist/acp-cleanroom-proxy.js"
  ],
  "project-native:pi-extension/acpx-workbench/dist/open-brain-readonly-proxy.js": [
    ".agents/pi/extensions/acpx-workbench/dist/open-brain-readonly-proxy.js",
    "extensions/acpx-workbench/dist/open-brain-readonly-proxy.js"
  ],
  "project-native:pi-extension/acpx-workbench/dist/beads-readonly-mcp.js": [
    ".agents/pi/extensions/acpx-workbench/dist/beads-readonly-mcp.js",
    "extensions/acpx-workbench/dist/beads-readonly-mcp.js"
  ],
  "project-native:pi-extension/acpx-workbench/system-prompt.md": [
    ".agents/pi/extensions/acpx-workbench/system-prompt.md",
    "extensions/acpx-workbench/system-prompt.md"
  ]
};
function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}
function assertProfile(value) {
  if (!value || typeof value !== "object")
    throw new Error("Profile must be an object");
  const candidate = value;
  if (candidate.schema !== "cognovis.pi.profile.v1")
    throw new Error("Unsupported profile schema");
  if (candidate.id !== "pi-workbench")
    throw new Error("Profile id must be pi-workbench");
  if (candidate.package?.catalog !== "library.yaml" || candidate.package?.dependencyRoot !== "just-module:pi-workbench") {
    throw new Error("Profile must declare the pi-workbench Library dependency root");
  }
  if (!Array.isArray(candidate.resources) || candidate.resources.length === 0) {
    throw new Error("Profile must declare resources");
  }
  if (candidate.provider?.id !== "acpx-workbench") {
    throw new Error("Profile provider must be acpx-workbench");
  }
  if (candidate.provider.default !== "claude") {
    throw new Error("Profile default provider must be claude");
  }
  for (const provider of ["claude", "codex", "kimi"]) {
    const selection = candidate.provider.selections?.[provider];
    const models = candidate.provider.models?.[provider];
    if (selection?.agent !== provider || !selection.model?.startsWith(`${provider}:`) || !Array.isArray(models) || models.length === 0 || !models.some((model) => publicModelId(model) === selection.model) || !models.every((model) => validModelRoute(model, provider)) || new Set(models.map(publicModelId)).size !== models.length || !selection.mode || !Array.isArray(selection.route) || selection.route.length === 0 || !Array.isArray(selection.adapter?.command) || selection.adapter.command.length === 0 || !(selection.adapter.provenance === "repository-package" && /^\d+\.\d+\.\d+$/.test(selection.adapter.version) || selection.adapter.provenance === "host-binary" && !("version" in selection.adapter)) || !["enforced", "adapter-managed", "not-supported"].includes(selection.isolationCapability?.ambientUserSkills) || !(selection.isolationCapability.warning === null || typeof selection.isolationCapability.warning === "string")) {
      throw new Error(`Profile provider selection is invalid: ${provider}`);
    }
  }
  if (candidate.permissions?.id !== "repository-safe-v1") {
    throw new Error("Profile permission policy must be repository-safe-v1");
  }
  if (candidate.permissions.shell !== "disabled" || candidate.permissions.network !== "open-brain-readonly-proxy-only" || candidate.permissions.allowedTools?.includes("Bash") || candidate.permissions.allowedTools?.includes("bash")) {
    throw new Error("Profile permission boundary is invalid");
  }
  if (candidate.isolation?.downstream?.settingSources?.length !== 0 || candidate.isolation?.downstream?.skills?.length !== 0 || candidate.isolation?.downstream?.plugins?.length !== 0) {
    throw new Error("Downstream discovery allowlists must be empty");
  }
  if (candidate.isolation.downstream.managedMcpServers?.length !== 2 || candidate.isolation.downstream.managedMcpServers[0] !== "beads" || candidate.isolation.downstream.managedMcpServers[1] !== "open-brain") {
    throw new Error("Managed MCP boundary must contain only Beads and Open Brain");
  }
}
function providerSelection(resolved, provider) {
  return resolved.profile.provider.selections[provider];
}
async function resolveFirstRepositoryPath(root, candidates, label) {
  for (const candidate of candidates) {
    const absolutePath = path.resolve(root, candidate);
    if (!isWithin(root, absolutePath))
      throw new Error(`${label} leaves repository root`);
    try {
      const realPath = await realpath(absolutePath);
      if (!isWithin(root, realPath))
        throw new Error(`${label} resolves outside repository root`);
      return { absolutePath: realPath, resolvedPath: path.relative(root, realPath) };
    } catch (error) {
      if (error.code !== "ENOENT")
        throw error;
    }
  }
  throw new Error(`${label} is not installed and has no source-checkout fallback`);
}
function isWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === "" || !relative.startsWith("..") && !path.isAbsolute(relative);
}
async function resolveProfile(repositoryRoot, profileId = "pi-workbench") {
  const root = await realpath(repositoryRoot);
  const manifestCandidates = ALLOWED_PROFILE_PATHS[profileId];
  if (!manifestCandidates)
    throw new Error(`Profile is not allowlisted: ${profileId}`);
  const manifest = await resolveFirstRepositoryPath(root, manifestCandidates, "Profile manifest");
  const rawManifest = await readFile(manifest.absolutePath, "utf8");
  const parsed = JSON.parse(rawManifest);
  assertProfile(parsed);
  const seen = new Set;
  const resources = [];
  for (const resource of parsed.resources) {
    if (seen.has(resource.id))
      throw new Error(`Duplicate profile resource: ${resource.id}`);
    seen.add(resource.id);
    if (!/^[a-f0-9]{64}$/.test(resource.sha256)) {
      throw new Error(`Resource ${resource.id} does not have a pinned sha256`);
    }
    const logicalCandidates = PROJECT_NATIVE_RESOURCE_PATHS[resource.path];
    const resolved = await resolveFirstRepositoryPath(root, logicalCandidates ?? [resource.path], `Resource ${resource.id}`);
    const actual = sha256(await readFile(resolved.absolutePath));
    if (actual !== resource.sha256) {
      throw new Error(`Resource hash mismatch for ${resource.id}: expected ${resource.sha256}, got ${actual}`);
    }
    resources.push({ ...resource, ...resolved });
  }
  for (const required of [
    "system-prompt",
    "pi-extension",
    "provider-implementation",
    "runtime-boundary",
    "mcp-boundary"
  ]) {
    if (!resources.some((resource) => resource.kind === required)) {
      throw new Error(`Profile is missing required resource kind: ${required}`);
    }
  }
  return {
    profile: parsed,
    manifestPath: manifest.absolutePath,
    profileHash: sha256(rawManifest),
    resources
  };
}
function resourceByKind(resolved, kind) {
  const resource = resolved.resources.find((entry) => entry.kind === kind);
  if (!resource)
    throw new Error(`Resolved profile has no ${kind} resource`);
  return resource;
}
function resourceById(resolved, id) {
  const resource = resolved.resources.find((entry) => entry.id === id);
  if (!resource)
    throw new Error(`Resolved profile has no ${id} resource`);
  return resource;
}

// extensions/acpx-workbench/providers.ts
import { execFile } from "child_process";
import { constants } from "fs";
import { access, readFile as readFile2 } from "fs/promises";
import path2 from "path";
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
  for (const directory of pathValue.split(path2.delimiter).filter(Boolean)) {
    const candidate = path2.resolve(directory, executable);
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
    const executable2 = path2.resolve(repositoryRoot, configuredExecutable);
    const packageName = REPOSITORY_ADAPTER_PACKAGES[provider];
    if (!packageName) {
      throw new ProviderUnavailableError(provider, "no repository package is registered");
    }
    let runtimeVersion2;
    try {
      await access(executable2, constants.X_OK);
      const manifestPath = path2.join(repositoryRoot, "node_modules", packageName, "package.json");
      const manifest = JSON.parse(await readFile2(manifestPath, "utf8"));
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

// extensions/acpx-workbench/model-switching.ts
function configuredModelRoutes(profile) {
  return WORKBENCH_PROVIDERS.flatMap((provider) => profile.provider.models[provider].map((route) => {
    const model = typeof route === "string" ? route : route.id;
    const adapterModel = typeof route === "string" ? route : route.nativeModel;
    return {
      provider,
      selection: { ...profile.provider.selections[provider], model, adapterModel }
    };
  }));
}
function routeForModel(profile, modelId) {
  const route = configuredModelRoutes(profile).find(({ selection }) => selection.model === modelId);
  if (!route)
    throw new Error(`No managed provider route owns model: ${modelId}`);
  return route;
}
function providerSessionKey(workbenchSessionId, provider, modelId) {
  const normalizedModel = modelId.replace(/[^a-zA-Z0-9.-]/g, "_");
  return `${workbenchSessionId}-${provider}-${normalizedModel}`;
}
function modelContextWindow(selection) {
  return adapterModelId(selection).endsWith("[1m]") ? 1e6 : 200000;
}
function adapterModelId(selection) {
  return selection.adapterModel ?? selection.model;
}
function assertObservableTurn(provider, textObserved, toolObserved) {
  if (!textObserved && !toolObserved) {
    throw new Error(`${provider} provider returned no text or observable tool activity`);
  }
}

class LazyProviderPool {
  create;
  values = new Map;
  constructor(create) {
    this.create = create;
  }
  get(provider) {
    const existing = this.values.get(provider);
    if (existing)
      return existing;
    const created = this.create(provider).catch((error) => {
      if (this.values.get(provider) === created) {
        this.values.delete(provider);
      }
      throw error;
    });
    this.values.set(provider, created);
    return created;
  }
  async fulfilled() {
    const settled = await Promise.allSettled(this.values.values());
    const fulfilled = [];
    for (const result of settled) {
      if (result.status === "fulfilled")
        fulfilled.push(result.value);
    }
    return fulfilled;
  }
}

// extensions/acpx-workbench/provider-runtime.ts
import {
  lstat,
  mkdir,
  readdir,
  realpath as realpath2,
  stat,
  symlink,
  unlink
} from "fs/promises";
import path3 from "path";
var RUNTIME_SCOPE = "@earendil-works";
var REQUIRED_PACKAGES = ["pi-ai", "pi-coding-agent", "pi-tui"];
var PROJECT_NATIVE_PI_ROOT = path3.join(".agents", "pi");
async function isDirectory(target) {
  try {
    return (await stat(target)).isDirectory();
  } catch {
    return false;
  }
}
function* scopeCandidates(fromFile) {
  let directory = path3.dirname(path3.resolve(fromFile));
  for (;; ) {
    yield path3.join(directory, "node_modules", RUNTIME_SCOPE);
    const parent = path3.dirname(directory);
    if (parent === directory)
      return;
    directory = parent;
  }
}
async function providerRuntimeResolves(providerPath) {
  const missing = new Set(REQUIRED_PACKAGES);
  for (const scope of scopeCandidates(providerPath)) {
    for (const name of [...missing]) {
      if (await isDirectory(path3.join(scope, name)))
        missing.delete(name);
    }
    if (missing.size === 0)
      return true;
  }
  return false;
}
async function piRuntimePackages(piCommand, environment = process.env) {
  const packages = new Map;
  const located = piCommand.includes(path3.sep) ? piCommand : await findOnPath(piCommand, environment);
  if (!located)
    return packages;
  let entry;
  try {
    entry = await realpath2(located);
  } catch {
    return packages;
  }
  const scopes = [];
  let directory = path3.dirname(entry);
  for (;; ) {
    if (path3.basename(directory) === RUNTIME_SCOPE)
      scopes.push(directory);
    scopes.push(path3.join(directory, "node_modules", RUNTIME_SCOPE));
    const parent = path3.dirname(directory);
    if (parent === directory)
      break;
    directory = parent;
  }
  for (const scope of scopes) {
    let names;
    try {
      names = await readdir(scope);
    } catch {
      continue;
    }
    for (const name of names) {
      if (packages.has(name))
        continue;
      const candidate = path3.join(scope, name);
      if (await isDirectory(candidate))
        packages.set(name, candidate);
    }
  }
  return packages;
}
async function link(target, linkPath) {
  try {
    await unlink(linkPath);
  } catch {}
  await symlink(target, linkPath, "dir");
}
async function ensureProviderRuntimeResolution(repositoryRoot, providerPath, piCommand, environment = process.env) {
  const root = path3.resolve(repositoryRoot);
  const provider = path3.resolve(providerPath);
  const projectNativeRoot = path3.join(root, PROJECT_NATIVE_PI_ROOT);
  if (!provider.startsWith(projectNativeRoot + path3.sep))
    return null;
  if (await providerRuntimeResolves(provider))
    return null;
  const packages = await piRuntimePackages(piCommand, environment);
  const missing = REQUIRED_PACKAGES.filter((name) => !packages.has(name));
  if (missing.length > 0) {
    throw new Error(`Cannot make the Pi runtime resolvable for ${provider}: ` + `${piCommand} ships no ${missing.map((name) => `${RUNTIME_SCOPE}/${name}`).join(", ")}`);
  }
  const scope = path3.join(projectNativeRoot, "node_modules", RUNTIME_SCOPE);
  try {
    if ((await lstat(scope)).isSymbolicLink())
      await unlink(scope);
  } catch {}
  await mkdir(scope, { recursive: true });
  for (const [name, directory] of packages) {
    await link(directory, path3.join(scope, name));
  }
  return scope;
}

// extensions/acpx-workbench/redaction.ts
var SENSITIVE_KEY = /(?:api[_-]?key|authorization|cookie|credential|password|secret|token)/i;
var INLINE_SECRET_PATTERNS = [
  /\b(?:sk|sk-ant|sk-proj)-[A-Za-z0-9_-]{8,}\b/g,
  /\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b/gi,
  /\b(ANTHROPIC_(?:API_KEY|AUTH_TOKEN|OAUTH_TOKEN)\s*=\s*)[^\s"'`]+/gi,
  /\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)\s*=\s*)[^\s"'`]+/g
];
function redactText(value, options = {}) {
  let redacted = value;
  for (const canary of options.canaries ?? []) {
    if (canary)
      redacted = redacted.replaceAll(canary, "[REDACTED]");
  }
  for (const pattern of INLINE_SECRET_PATTERNS) {
    pattern.lastIndex = 0;
    redacted = redacted.replace(pattern, (match, prefix) => prefix ? `${prefix}[REDACTED]` : "[REDACTED]");
  }
  return redacted;
}
function redactValue(value, options = {}, key = "") {
  const provenanceField = /(?:classification|present|source|stored)$/i.test(key);
  if (key && SENSITIVE_KEY.test(key) && !provenanceField) {
    if (typeof value === "boolean" || value === null)
      return value;
    return "[REDACTED]";
  }
  if (typeof value === "string")
    return redactText(value, options);
  if (Array.isArray(value))
    return value.map((entry) => redactValue(entry, options));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([entryKey, entry]) => [
      entryKey,
      redactValue(entry, options, entryKey)
    ]));
  }
  return value;
}

// extensions/acpx-workbench/session-store.ts
import { randomUUID } from "crypto";
import { mkdir as mkdir3, readFile as readFile3, readdir as readdir2, writeFile as writeFile2 } from "fs/promises";
import path5 from "path";

// extensions/acpx-workbench/evidence.ts
import { appendFile, mkdir as mkdir2, writeFile } from "fs/promises";
import path4 from "path";
async function writeJson(target, value) {
  await mkdir2(path4.dirname(target), { recursive: true });
  await writeFile(target, `${JSON.stringify(value, null, 2)}
`, "utf8");
}
async function appendJsonLine(target, value) {
  await mkdir2(path4.dirname(target), { recursive: true });
  await appendFile(target, `${JSON.stringify(value)}
`, "utf8");
}

// extensions/acpx-workbench/session-store.ts
function createWorkbenchEvent(sessionId, type, data, redaction = {}) {
  return {
    schema: "cognovis.pi.event.v1",
    eventId: randomUUID(),
    sessionId,
    timestamp: new Date().toISOString(),
    type,
    data: redactValue(data, redaction)
  };
}
async function appendWorkbenchEvent(eventLog, sessionId, type, data, redaction = {}) {
  const event = createWorkbenchEvent(sessionId, type, data, redaction);
  await appendJsonLine(eventLog, event);
  return event;
}

class SessionStore {
  stateRoot;
  sessionsRoot;
  constructor(stateRoot) {
    this.stateRoot = stateRoot;
    this.sessionsRoot = path5.join(stateRoot, "sessions");
  }
  sessionDir(sessionId) {
    if (!/^[A-Za-z0-9._-]+$/.test(sessionId))
      throw new Error("Invalid session id");
    return path5.join(this.sessionsRoot, sessionId);
  }
  eventLog(sessionId) {
    return path5.join(this.sessionDir(sessionId), "events.jsonl");
  }
  receiptPath(sessionId) {
    return path5.join(this.sessionDir(sessionId), "boot-receipt.json");
  }
  async initializeSession(sessionId) {
    const directory = this.sessionDir(sessionId);
    await mkdir3(directory, { recursive: true, mode: 448 });
    await mkdir3(this.stateRoot, { recursive: true, mode: 448 });
    await writeJson(path5.join(this.stateRoot, "current.json"), { sessionId });
    return directory;
  }
  async writeReceipt(sessionId, receipt) {
    await writeJson(this.receiptPath(sessionId), receipt);
  }
  async append(sessionId, type, data, redaction = {}) {
    return appendWorkbenchEvent(this.eventLog(sessionId), sessionId, type, data, redaction);
  }
  async currentSessionId() {
    try {
      const parsed = JSON.parse(await readFile3(path5.join(this.stateRoot, "current.json"), "utf8"));
      return typeof parsed.sessionId === "string" ? parsed.sessionId : null;
    } catch (error) {
      if (error.code === "ENOENT")
        return null;
      throw error;
    }
  }
  async readEvents(sessionId) {
    try {
      const raw = await readFile3(this.eventLog(sessionId), "utf8");
      return raw.split(`
`).filter(Boolean).map((line) => JSON.parse(line));
    } catch (error) {
      if (error.code === "ENOENT")
        return [];
      throw error;
    }
  }
  async listSessionIds() {
    try {
      const entries = await readdir2(this.sessionsRoot, { withFileTypes: true });
      return entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort().reverse();
    } catch (error) {
      if (error.code === "ENOENT")
        return [];
      throw error;
    }
  }
  async summarize(sessionId) {
    const [events, current] = await Promise.all([this.readEvents(sessionId), this.currentSessionId()]);
    const byType = (type) => events.filter((event) => event.type === type).map((event) => event.data);
    const provider = byType("provider");
    const tools = byType("tool");
    const toolFailures = tools.filter((tool) => tool && typeof tool === "object" && tool.status === "failed").map((tool) => ({ stage: "tool", ...tool }));
    return {
      schema: "cognovis.pi.session-view.v1",
      sessionId,
      current: current === sessionId,
      startedAt: events[0]?.timestamp ?? null,
      latestAt: events.at(-1)?.timestamp ?? null,
      prompts: byType("prompt"),
      provider: provider.at(-1) ?? null,
      tools,
      failures: [...byType("failure"), ...toolFailures],
      permissions: byType("permission"),
      verification: byType("verification")
    };
  }
  async writeView(target, sessionId) {
    await mkdir3(path5.dirname(target), { recursive: true });
    await writeFile2(target, `${JSON.stringify(await this.summarize(sessionId), null, 2)}
`, "utf8");
  }
}

// extensions/acpx-workbench/launcher.ts
var PI_ISOLATION_FLAGS = [
  "--no-context-files",
  "--no-skills",
  "--no-extensions",
  "--no-prompt-templates",
  "--no-themes",
  "--approve",
  "--offline",
  "--no-tools"
];
function defaultStateRoot(environment = process.env) {
  const base = environment.XDG_STATE_HOME?.trim() || path6.join(os.homedir(), ".local", "state");
  return path6.join(base, "cognovis-pi", "pi-workbench");
}
function createSessionId(now = new Date) {
  return `${now.toISOString().replace(/[:.]/g, "-")}-${randomUUID2().slice(0, 8)}`;
}
function managedEnvironment(ambient, values) {
  const clean = { ...ambient };
  for (const name of Object.keys(clean)) {
    if (name.startsWith("ANTHROPIC_") || name.startsWith("ACPX_AUTH_") || name.startsWith("CODEX_") || name.startsWith("KIMI_") || name.startsWith("MOONSHOT_") || name.startsWith("OPENAI_") || name.startsWith("PI_") || name.startsWith("COGNOVIS_PI_")) {
      delete clean[name];
    }
  }
  for (const name of AUTH_ENVIRONMENT_NAMES)
    delete clean[name];
  for (const name of ["CLAUDE_CONFIG_DIR", "CLAUDE_MODEL_CONFIG", "MAX_THINKING_TOKENS"]) {
    delete clean[name];
  }
  return { ...clean, ...values, PI_OFFLINE: "1" };
}
async function createLaunchPlan(options) {
  const repositoryRoot = path6.resolve(options.repositoryRoot);
  const profile = await resolveProfile(repositoryRoot);
  let provider = parseWorkbenchProvider(options.provider, profile.profile.provider.default);
  let selection = providerSelection(profile, provider);
  if (options.fusionProfile && options.beadProfile) {
    throw new Error("Fusion and Bead Harness profiles are mutually exclusive");
  }
  let fusionExtensionPath = null;
  let fusionProfilePath = null;
  let beadExtensionPath = null;
  let beadProfilePath = null;
  const beadRequiredProviders = new Set;
  if (options.fusionProfile) {
    fusionProfilePath = path6.resolve(repositoryRoot, options.fusionProfile);
    const fusion = JSON.parse(await readFile4(fusionProfilePath, "utf8"));
    if (fusion.schema !== "cognovis.pi.fusion-profile.v1" || typeof fusion.roles?.builder !== "string" || !fusion.roles.builder.startsWith(`${profile.profile.provider.id}/`)) {
      throw new Error("Fusion profile has no managed ACPX builder role");
    }
    const hostModel = fusion.roles.builder.slice(profile.profile.provider.id.length + 1);
    const hostRoute = routeForModel(profile.profile, hostModel);
    provider = hostRoute.provider;
    selection = hostRoute.selection;
    const candidates = [
      path6.join(repositoryRoot, ".agents/pi/extensions/fusion-harness/fusion-harness.ts"),
      path6.join(repositoryRoot, "extensions/fusion-harness/fusion-harness.ts")
    ];
    for (const candidate of candidates) {
      try {
        if ((await stat2(candidate)).isFile()) {
          fusionExtensionPath = candidate;
          break;
        }
      } catch {}
    }
    if (!fusionExtensionPath) {
      throw new Error("Fusion Harness extension is not installed");
    }
  }
  if (options.beadProfile) {
    beadProfilePath = path6.resolve(repositoryRoot, options.beadProfile);
    const bead = JSON.parse(await readFile4(beadProfilePath, "utf8"));
    if (bead.schema !== "cognovis.pi.bead-harness-profile.v2" || typeof bead.implementer?.harness !== "string" || typeof bead.implementer?.model !== "string" || typeof bead.implementer?.route !== "string" || !Array.isArray(bead.reviewers)) {
      throw new Error("Bead Harness profile has no managed implementer route");
    }
    if (bead.mode === "high-assurance") {
      const boundary = bead.reviewers.find((reviewer) => reviewer.perspective === "boundary-operator");
      if (!bead.adjudicator || typeof bead.adjudicator.id !== "string" || bead.reviewers.some((reviewer) => reviewer.id === bead.adjudicator?.id) || bead.adjudicator.family === bead.implementer.family || bead.adjudicator.family === boundary?.family || bead.adjudicator.route === boundary?.route) {
        throw new Error("Bead Harness adjudicator is not distinct from the implementer and boundary reviewer");
      }
    }
    const requiredRoutes = [
      bead.implementer.route,
      ...bead.reviewers.map((reviewer) => reviewer.route),
      ...bead.adjudicator ? [bead.adjudicator.route] : []
    ];
    if (requiredRoutes.some((route) => typeof route !== "string")) {
      throw new Error("Bead Harness profile carries an incomplete managed route");
    }
    for (const route of requiredRoutes) {
      const resolved = routeForModel(profile.profile, route);
      beadRequiredProviders.add(resolved.provider);
    }
    const hostRoute = routeForModel(profile.profile, bead.implementer.route);
    provider = hostRoute.provider;
    selection = hostRoute.selection;
    const candidates = [
      path6.join(repositoryRoot, ".agents/pi/extensions/cognovis-bead-harness/index.ts"),
      path6.join(repositoryRoot, "extensions/cognovis-bead-harness/index.ts")
    ];
    for (const candidate of candidates) {
      try {
        if ((await stat2(candidate)).isFile()) {
          beadExtensionPath = candidate;
          break;
        }
      } catch {}
    }
    if (!beadExtensionPath)
      throw new Error("Cognovis Bead Harness extension is not installed");
  }
  const selections = Object.fromEntries(WORKBENCH_PROVIDERS.map((entry) => [entry, providerSelection(profile, entry)]));
  const ambient = options.environment ?? process.env;
  const providerRuntimes = await resolveProviderRuntimes(repositoryRoot, selections, ambient);
  for (const required of beadRequiredProviders) {
    if (providerRuntimes[required].status !== "available") {
      throw new Error(`Bead Harness required provider is unavailable: ${required}`);
    }
  }
  const stateRoot = path6.resolve(options.stateRoot ?? defaultStateRoot(options.environment));
  const sessionId = options.sessionId ?? createSessionId();
  const store = new SessionStore(stateRoot);
  const sessionDir = await store.initializeSession(sessionId);
  const piConfigDir = path6.join(sessionDir, "pi-config");
  const piSessionsDir = path6.join(sessionDir, "pi-sessions");
  const acpxStateDir = path6.join(sessionDir, "acpx");
  const downstreamCwd = path6.join(sessionDir, "downstream-cwd");
  await Promise.all([
    mkdir4(piConfigDir, { recursive: true, mode: 448 }),
    mkdir4(piSessionsDir, { recursive: true, mode: 448 }),
    mkdir4(acpxStateDir, { recursive: true, mode: 448 }),
    ...WORKBENCH_PROVIDERS.map((entry) => mkdir4(path6.join(acpxStateDir, entry), { recursive: true, mode: 448 })),
    mkdir4(downstreamCwd, { recursive: true, mode: 448 })
  ]);
  const extension = resourceByKind(profile, "pi-extension");
  const providerImplementation = resourceByKind(profile, "provider-implementation");
  const proxy = resourceByKind(profile, "runtime-boundary");
  const openBrainProxy = resourceById(profile, "open-brain-readonly-proxy");
  const beadsMcp = resourceById(profile, "beads-readonly-mcp");
  const systemPrompt = await readFile4(resourceByKind(profile, "system-prompt").absolutePath, "utf8");
  const bunCommand = process.execPath;
  const repositoryPi = path6.join(repositoryRoot, "node_modules", ".bin", "pi");
  let piCommand = options.piCommand ?? repositoryPi;
  if (!options.piCommand) {
    try {
      if (!(await stat2(repositoryPi)).isFile())
        piCommand = "pi";
    } catch {
      piCommand = "pi";
    }
  }
  await ensureProviderRuntimeResolution(repositoryRoot, providerImplementation.absolutePath, piCommand, ambient);
  const canaries = options.redactionCanaries ?? [];
  const eventLog = store.eventLog(sessionId);
  const environment = managedEnvironment(ambient, {
    COGNOVIS_PI_ACPX_ADAPTER_COMMAND: `${bunCommand} ${proxy.absolutePath}`,
    COGNOVIS_PI_ACPX_STATE_DIR: acpxStateDir,
    COGNOVIS_PI_BEADS_MCP_PATH: beadsMcp.absolutePath,
    COGNOVIS_PI_BUN_COMMAND: bunCommand,
    COGNOVIS_PI_ALLOWED_TOOLS: profile.profile.permissions.allowedTools.join(","),
    COGNOVIS_PI_DOWNSTREAM_CWD: downstreamCwd,
    COGNOVIS_PI_EVENT_LOG: eventLog,
    COGNOVIS_PI_OPEN_BRAIN_PROXY_PATH: openBrainProxy.absolutePath,
    COGNOVIS_PI_PROFILE_ID: profile.profile.id,
    COGNOVIS_PI_PROVIDER_IMPLEMENTATION_PATH: providerImplementation.absolutePath,
    COGNOVIS_PI_PROVIDER_RUNTIMES_JSON: JSON.stringify(providerRuntimes),
    COGNOVIS_PI_REDACTION_CANARIES_JSON: JSON.stringify(canaries),
    COGNOVIS_PI_REPOSITORY_ROOT: repositoryRoot,
    COGNOVIS_PI_SESSION_ID: sessionId,
    COGNOVIS_PI_WORKBENCH_EXTENSION_PATH: extension.absolutePath,
    ...fusionProfilePath ? { COGNOVIS_PI_FUSION_PROFILE: fusionProfilePath } : {},
    ...beadProfilePath ? { COGNOVIS_PI_BEAD_HARNESS_PROFILE: beadProfilePath } : {},
    PI_CODING_AGENT_DIR: piConfigDir
  });
  const args = [
    ...PI_ISOLATION_FLAGS,
    "--extension",
    extension.absolutePath,
    ...fusionExtensionPath ? ["--extension", fusionExtensionPath] : [],
    ...beadExtensionPath ? ["--extension", beadExtensionPath] : [],
    "--provider",
    profile.profile.provider.id,
    "--model",
    selection.model,
    "--system-prompt",
    `${systemPrompt}

Managed repository root: ${repositoryRoot}`,
    "--session-dir",
    piSessionsDir,
    "--session-id",
    sessionId
  ];
  if (options.print || options.prompt)
    args.push("--print");
  if (options.prompt)
    args.push(options.prompt);
  const receipt = {
    schema: "cognovis.pi.boot-receipt.v1",
    sessionId,
    createdAt: new Date().toISOString(),
    profile: {
      id: profile.profile.id,
      version: profile.profile.version,
      sha256: profile.profileHash,
      resolvedPath: path6.relative(repositoryRoot, profile.manifestPath),
      dependencyRoot: profile.profile.package.dependencyRoot
    },
    resources: profile.resources.map((resource) => ({
      id: resource.id,
      kind: resource.kind,
      path: resource.path,
      resolvedPath: resource.resolvedPath,
      sha256: resource.sha256,
      source: resource.source
    })),
    provider: {
      id: profile.profile.provider.id,
      initialSelection: provider,
      initialModel: selection.model,
      models: configuredModelRoutes(profile.profile).map(({ provider: entry, selection: route }) => {
        const runtime = providerRuntimes[entry];
        return {
          selection: entry,
          agent: route.agent,
          model: route.model,
          mode: route.mode,
          route: route.route,
          availability: runtime.status,
          adapter: runtime.status === "available" ? runtime.commandProvenance : null,
          unavailableReason: runtime.status === "unavailable" ? runtime.reason : null,
          isolationCapability: route.isolationCapability
        };
      })
    },
    authProvenance: {
      classification: "per-provider-default-context",
      routes: Object.fromEntries(WORKBENCH_PROVIDERS.map((entry) => [
        entry,
        {
          source: selections[entry].authContext,
          apiKeySource: null,
          configMode: "default",
          credentialProjection: false
        }
      ])),
      apiKeySource: null,
      configMode: "default",
      credentialProjection: false,
      environment: snapshotEnvironment(environment),
      credentialValuesStored: false
    },
    permissionPolicy: {
      ...profile.profile.permissions,
      downstreamMode: selection.mode,
      acpxPermissionMode: "deny-all",
      hostCallbackScope: "adapter-emitted permission requests",
      providerNativeReads: "observable but not host-decided",
      verifiedBoundary: "ACPX deny-all fallback plus fail-closed host callback"
    },
    isolation: profile.profile.isolation
  };
  await store.writeReceipt(sessionId, receipt);
  await store.append(sessionId, "boot", receipt, { canaries });
  return {
    command: piCommand,
    args,
    environment,
    profile,
    provider,
    receipt,
    sessionId,
    sessionDir,
    stateRoot
  };
}
async function launchWorkbench(options) {
  const plan = await createLaunchPlan(options);
  const store = new SessionStore(plan.stateRoot);
  const capture = Boolean(options.print || options.prompt);
  const child = spawn(plan.command, plan.args, {
    cwd: path6.resolve(options.repositoryRoot),
    env: plan.environment,
    stdio: capture ? ["ignore", "pipe", "pipe"] : "inherit"
  });
  let stdout = "";
  let stderr = "";
  if (capture) {
    child.stdout?.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr?.on("data", (chunk) => {
      stderr += String(chunk);
    });
  }
  const exitCode = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolve(code ?? 1));
  });
  const redaction = options.redactionCanaries ? { canaries: options.redactionCanaries } : {};
  stdout = redactText(stdout, redaction);
  stderr = redactText(stderr, redaction);
  await store.append(plan.sessionId, "verification", {
    check: "managed-launch",
    state: exitCode === 0 ? "pass" : "fail",
    exitCode
  });
  if (exitCode !== 0) {
    await store.append(plan.sessionId, "failure", {
      stage: "managed-launch",
      message: stderr || `Pi exited with code ${exitCode}`
    }, redaction);
  }
  return { sessionId: plan.sessionId, exitCode, stdout, stderr, receipt: plan.receipt };
}

// extensions/acpx-workbench/cli.ts
function value(args, name) {
  const index = args.indexOf(name);
  if (index < 0)
    return;
  const result = args[index + 1];
  if (!result || result.startsWith("--"))
    throw new Error(`${name} requires a value`);
  return result;
}
function help() {
  return [
    "Usage:",
    "  bun <installed-extension>/cli.ts launch [--provider claude|codex|kimi] [--fusion-profile FILE | --bead-profile FILE] [--prompt TEXT] [--state-dir DIR] [--session-id ID]",
    "  bun <installed-extension>/cli.ts sessions [--state-dir DIR]",
    "  bun <installed-extension>/cli.ts session [current|ID] [--state-dir DIR]",
    "  bun <installed-extension>/cli.ts receipt [current|ID] [--state-dir DIR]"
  ].join(`
`);
}
async function main(args = process.argv.slice(2)) {
  const command = args[0];
  const stateRoot = path7.resolve(value(args, "--state-dir") ?? defaultStateRoot());
  const store = new SessionStore(stateRoot);
  if (!command || command === "help" || command === "--help") {
    process.stdout.write(`${help()}
`);
    return 0;
  }
  if (command === "launch") {
    const prompt = value(args, "--prompt");
    const requestedSessionId = value(args, "--session-id");
    const fusionProfile = value(args, "--fusion-profile");
    const beadProfile = value(args, "--bead-profile");
    if (fusionProfile && beadProfile)
      throw new Error("--fusion-profile and --bead-profile are mutually exclusive");
    const provider = parseWorkbenchProvider(value(args, "--provider"));
    const result = await launchWorkbench({
      repositoryRoot: process.cwd(),
      stateRoot,
      print: Boolean(prompt),
      provider,
      ...fusionProfile ? { fusionProfile } : {},
      ...beadProfile ? { beadProfile } : {},
      ...requestedSessionId ? { sessionId: requestedSessionId } : {},
      ...prompt ? { prompt } : {}
    });
    if (result.stdout)
      process.stdout.write(result.stdout);
    if (result.stderr)
      process.stderr.write(result.stderr);
    process.stderr.write(`workbench session: ${result.sessionId}
`);
    return result.exitCode;
  }
  if (command === "sessions") {
    const summaries = await Promise.all((await store.listSessionIds()).map((id) => store.summarize(id)));
    process.stdout.write(`${JSON.stringify(summaries, null, 2)}
`);
    return 0;
  }
  if (command === "session" || command === "receipt") {
    const requested = args[1] && !args[1].startsWith("--") ? args[1] : "current";
    const sessionId = requested === "current" ? await store.currentSessionId() : requested;
    if (!sessionId)
      throw new Error("No current workbench session");
    if (command === "session") {
      process.stdout.write(`${JSON.stringify(await store.summarize(sessionId), null, 2)}
`);
    } else {
      const receipt = await readFile5(store.receiptPath(sessionId), "utf8");
      process.stdout.write(receipt);
    }
    return 0;
  }
  throw new Error(`Unknown command: ${command}
${help()}`);
}
main().then((code) => {
  process.exitCode = code;
}, (error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}
`);
  process.exitCode = 1;
});
