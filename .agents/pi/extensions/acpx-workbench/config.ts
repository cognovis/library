import path from "node:path";
import {
  WORKBENCH_PROVIDERS,
  type ProviderRuntimeManifest,
} from "./providers.ts";

export interface ExtensionConfig {
  acpxStateDir: string;
  adapterCommand: string;
  beadsMcpPath: string;
  bunCommand: string;
  eventLog: string;
  openBrainProxyPath: string;
  profileId: "pi-workbench";
  providerRuntimes: ProviderRuntimeManifest;
  redactionCanaries: string[];
  repositoryRoot: string;
  sessionId: string;
}

function providerRuntimeManifest(value: string): ProviderRuntimeManifest {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("COGNOVIS_PI_PROVIDER_RUNTIMES_JSON must be an object");
  }
  const manifest = parsed as Record<string, any>;
  for (const provider of WORKBENCH_PROVIDERS) {
    const entry = manifest[provider];
    if (!entry || typeof entry !== "object") {
      throw new Error(`Missing provider runtime entry: ${provider}`);
    }
    if (entry.status === "unavailable") {
      if (typeof entry.reason !== "string" || !entry.reason) {
        throw new Error(`Unavailable provider runtime requires a reason: ${provider}`);
      }
      continue;
    }
    if (
      entry.status !== "available" ||
      !Array.isArray(entry.adapterArgv) ||
      entry.adapterArgv.length === 0 ||
      !entry.adapterArgv.every((item: unknown) => typeof item === "string" && item) ||
      !entry.adapterEnvironment ||
      typeof entry.adapterEnvironment !== "object" ||
      Array.isArray(entry.adapterEnvironment) ||
      Object.values(entry.adapterEnvironment).some((item) => typeof item !== "string") ||
      !entry.commandProvenance ||
      typeof entry.commandProvenance !== "object"
    ) {
      throw new Error(`Invalid available provider runtime entry: ${provider}`);
    }
  }
  return manifest as ProviderRuntimeManifest;
}

function required(environment: NodeJS.ProcessEnv, name: string): string {
  const value = environment[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

export function loadExtensionConfig(
  environment: NodeJS.ProcessEnv = process.env,
): ExtensionConfig {
  const adapterCommand = required(environment, "COGNOVIS_PI_ACPX_ADAPTER_COMMAND");
  if (!path.isAbsolute(adapterCommand)) {
    const executable = adapterCommand.trim().split(/\s+/, 1)[0] ?? "";
    if (!path.isAbsolute(executable)) {
      throw new Error("COGNOVIS_PI_ACPX_ADAPTER_COMMAND must start with an absolute path");
    }
  }
  const profileId = required(environment, "COGNOVIS_PI_PROFILE_ID");
  if (profileId !== "pi-workbench") throw new Error("Only pi-workbench is supported");
  const canariesRaw = environment.COGNOVIS_PI_REDACTION_CANARIES_JSON ?? "[]";
  const canaries: unknown = JSON.parse(canariesRaw);
  if (!Array.isArray(canaries) || !canaries.every((entry) => typeof entry === "string")) {
    throw new Error("COGNOVIS_PI_REDACTION_CANARIES_JSON must be a string array");
  }
  return {
    acpxStateDir: path.resolve(required(environment, "COGNOVIS_PI_ACPX_STATE_DIR")),
    adapterCommand,
    beadsMcpPath: path.resolve(required(environment, "COGNOVIS_PI_BEADS_MCP_PATH")),
    bunCommand: path.resolve(required(environment, "COGNOVIS_PI_BUN_COMMAND")),
    eventLog: path.resolve(required(environment, "COGNOVIS_PI_EVENT_LOG")),
    openBrainProxyPath: path.resolve(required(environment, "COGNOVIS_PI_OPEN_BRAIN_PROXY_PATH")),
    profileId,
    providerRuntimes: providerRuntimeManifest(
      required(environment, "COGNOVIS_PI_PROVIDER_RUNTIMES_JSON"),
    ),
    redactionCanaries: canaries,
    repositoryRoot: path.resolve(required(environment, "COGNOVIS_PI_REPOSITORY_ROOT")),
    sessionId: required(environment, "COGNOVIS_PI_SESSION_ID"),
  };
}
