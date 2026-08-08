import { execFile } from "node:child_process";
import { constants } from "node:fs";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

import type { ProviderSelection } from "./profile.ts";

export const WORKBENCH_PROVIDERS = ["claude", "codex", "kimi"] as const;
export type WorkbenchProvider = (typeof WORKBENCH_PROVIDERS)[number];

export class UnknownWorkbenchProviderError extends Error {
  readonly code = "UNKNOWN_WORKBENCH_PROVIDER";

  constructor(value: string) {
    super(
      `Unknown workbench provider: ${value}. Expected one of: ${WORKBENCH_PROVIDERS.join(", ")}`,
    );
    this.name = "UnknownWorkbenchProviderError";
  }
}

export class ProviderUnavailableError extends Error {
  readonly code = "WORKBENCH_PROVIDER_UNAVAILABLE";
  readonly provider: WorkbenchProvider;

  constructor(provider: WorkbenchProvider, message: string) {
    super(`${provider} provider is unavailable: ${message}`);
    this.name = "ProviderUnavailableError";
    this.provider = provider;
  }
}

export interface ResolvedProviderRuntime {
  adapterArgv: string[];
  adapterEnvironment: Record<string, string>;
  commandProvenance: {
    kind: ProviderSelection["adapter"]["provenance"];
    executable: string;
    arguments: string[];
    configuredVersion?: string;
    runtimeVersion: string;
    managedEnvironmentNames: string[];
  };
}

export type ProviderRuntimeManifestEntry =
  | {
      status: "available";
      adapterArgv: string[];
      adapterEnvironment: Record<string, string>;
      commandProvenance: ResolvedProviderRuntime["commandProvenance"];
    }
  | {
      status: "unavailable";
      reason: string;
    };

export type ProviderRuntimeManifest = Record<
  WorkbenchProvider,
  ProviderRuntimeManifestEntry
>;

const execFileAsync = promisify(execFile);
const REPOSITORY_ADAPTER_PACKAGES = {
  claude: "@agentclientprotocol/claude-agent-acp",
  codex: "@agentclientprotocol/codex-acp",
} as const;

export function parseWorkbenchProvider(
  value: string | undefined,
  defaultProvider: WorkbenchProvider = "claude",
): WorkbenchProvider {
  const selected = value?.trim() || defaultProvider;
  if (!WORKBENCH_PROVIDERS.includes(selected as WorkbenchProvider)) {
    throw new UnknownWorkbenchProviderError(selected);
  }
  return selected as WorkbenchProvider;
}

export async function findOnPath(
  executable: string,
  environment: NodeJS.ProcessEnv,
): Promise<string | null> {
  const pathValue = environment.PATH ?? "";
  for (const directory of pathValue.split(path.delimiter).filter(Boolean)) {
    const candidate = path.resolve(directory, executable);
    try {
      await access(candidate, constants.X_OK);
      return candidate;
    } catch {
      // Continue through the caller-provided PATH.
    }
  }
  return null;
}

async function probeHostVersion(
  provider: WorkbenchProvider,
  executable: string,
  arguments_: string[],
  environment: NodeJS.ProcessEnv,
): Promise<string> {
  try {
    const result = await execFileAsync(executable, [...arguments_, "--version"], {
      env: environment,
      timeout: 5_000,
    });
    const observed = `${result.stdout}${result.stderr}`.trim();
    const match = observed.match(/\d+\.\d+\.\d+/);
    if (!match) {
      throw new Error(`version command returned an unrecognized value: ${observed || "<empty>"}`);
    }
    return match[0];
  } catch (error) {
    if (error instanceof ProviderUnavailableError) throw error;
    throw new ProviderUnavailableError(
      provider,
      error instanceof Error ? error.message : "version probe failed",
    );
  }
}

export async function resolveProviderRuntime(
  repositoryRoot: string,
  provider: WorkbenchProvider,
  selection: ProviderSelection,
  environment: NodeJS.ProcessEnv,
): Promise<ResolvedProviderRuntime> {
  if (selection.agent !== provider) {
    throw new ProviderUnavailableError(provider, "profile agent does not match selection");
  }
  const [configuredExecutable, ...arguments_] = selection.adapter.command;
  if (!configuredExecutable) {
    throw new ProviderUnavailableError(provider, "profile adapter command is empty");
  }

  if (selection.adapter.provenance === "repository-package") {
    const executable = path.resolve(repositoryRoot, configuredExecutable);
    const packageName = REPOSITORY_ADAPTER_PACKAGES[
      provider as keyof typeof REPOSITORY_ADAPTER_PACKAGES
    ];
    if (!packageName) {
      throw new ProviderUnavailableError(provider, "no repository package is registered");
    }
    let runtimeVersion: string;
    try {
      await access(executable, constants.X_OK);
      const manifestPath = path.join(repositoryRoot, "node_modules", packageName, "package.json");
      const manifest = JSON.parse(await readFile(manifestPath, "utf8")) as {
        name?: unknown;
        version?: unknown;
      };
      if (manifest.name !== packageName || typeof manifest.version !== "string") {
        throw new Error(`${packageName} package metadata is invalid`);
      }
      runtimeVersion = manifest.version;
    } catch {
      const bunx = await findOnPath("bunx", environment);
      if (!bunx) {
        throw new ProviderUnavailableError(
          provider,
          `${configuredExecutable} is missing and bunx was not found on PATH`,
        );
      }
      const portableArguments = [`${packageName}@${selection.adapter.version}`];
      const portableVersion = await probeHostVersion(
        provider,
        bunx,
        portableArguments,
        environment,
      );
      if (portableVersion !== selection.adapter.version) {
        throw new ProviderUnavailableError(
          provider,
          `profile requires adapter ${selection.adapter.version}, resolved package is ${portableVersion}`,
        );
      }
      return {
        adapterArgv: [bunx, ...portableArguments],
        adapterEnvironment: provider === "codex"
          ? {
              CODEX_CONFIG: JSON.stringify({
                mcp_servers: {},
                project_doc_max_bytes: 0,
              }),
            }
          : {},
        commandProvenance: {
          kind: "host-binary",
          executable: bunx,
          arguments: portableArguments,
          configuredVersion: selection.adapter.version,
          runtimeVersion: portableVersion,
          managedEnvironmentNames: provider === "codex" ? ["CODEX_CONFIG"] : [],
        },
      };
    }
    if (runtimeVersion !== selection.adapter.version) {
      throw new ProviderUnavailableError(
        provider,
        `profile requires adapter ${selection.adapter.version}, installed package is ${runtimeVersion}`,
      );
    }
    return {
      adapterArgv: [executable, ...arguments_],
      adapterEnvironment: provider === "codex"
        ? {
            CODEX_CONFIG: JSON.stringify({
              mcp_servers: {},
              project_doc_max_bytes: 0,
            }),
          }
        : {},
      commandProvenance: {
        kind: selection.adapter.provenance,
        executable,
        arguments: arguments_,
        configuredVersion: selection.adapter.version,
        runtimeVersion,
        managedEnvironmentNames: provider === "codex" ? ["CODEX_CONFIG"] : [],
      },
    };
  }

  const executable = await findOnPath(configuredExecutable, environment);
  if (!executable) {
    throw new ProviderUnavailableError(provider, `${configuredExecutable} was not found on PATH`);
  }
  const runtimeVersion = await probeHostVersion(
    provider,
    executable,
    arguments_,
    environment,
  );
  return {
    adapterArgv: [executable, ...arguments_],
    adapterEnvironment: {},
    commandProvenance: {
      kind: selection.adapter.provenance,
      executable,
      arguments: arguments_,
      runtimeVersion,
      managedEnvironmentNames: [],
    },
  };
}

export async function resolveProviderRuntimes(
  repositoryRoot: string,
  selections: Record<WorkbenchProvider, ProviderSelection>,
  environment: NodeJS.ProcessEnv,
): Promise<ProviderRuntimeManifest> {
  const entries = await Promise.all(
    WORKBENCH_PROVIDERS.map(async (provider) => {
      try {
        const runtime = await resolveProviderRuntime(
          repositoryRoot,
          provider,
          selections[provider],
          environment,
        );
        return [
          provider,
          {
            status: "available",
            adapterArgv: runtime.adapterArgv,
            adapterEnvironment: runtime.adapterEnvironment,
            commandProvenance: runtime.commandProvenance,
          },
        ] as const;
      } catch (error) {
        return [
          provider,
          {
            status: "unavailable",
            reason: error instanceof Error ? error.message : `${provider} provider is unavailable`,
          },
        ] as const;
      }
    }),
  );
  return Object.fromEntries(entries) as ProviderRuntimeManifest;
}
