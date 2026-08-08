import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { mkdir, readFile, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { AUTH_ENVIRONMENT_NAMES, snapshotEnvironment } from "./auth-provenance.ts";
import { resolveProfile, resourceById, resourceByKind, type ResolvedProfile } from "./profile.ts";
import { providerSelection } from "./profile.ts";
import { configuredModelRoutes, routeForModel } from "./model-switching.ts";
import {
  parseWorkbenchProvider,
  resolveProviderRuntimes,
  WORKBENCH_PROVIDERS,
  type WorkbenchProvider,
} from "./providers.ts";
import { ensureProviderRuntimeResolution } from "./provider-runtime.ts";
import { redactText } from "./redaction.ts";
import { SessionStore } from "./session-store.ts";

export const PI_ISOLATION_FLAGS = [
  "--no-context-files",
  "--no-skills",
  "--no-extensions",
  "--no-prompt-templates",
  "--no-themes",
  "--approve",
  "--offline",
  "--no-tools",
] as const;

export interface LaunchOptions {
  repositoryRoot: string;
  stateRoot?: string;
  sessionId?: string;
  prompt?: string;
  print?: boolean;
  piCommand?: string;
  environment?: NodeJS.ProcessEnv;
  redactionCanaries?: string[];
  provider?: string;
  fusionProfile?: string;
  beadProfile?: string;
}

export interface LaunchPlan {
  command: string;
  args: string[];
  environment: NodeJS.ProcessEnv;
  profile: ResolvedProfile;
  receipt: Record<string, unknown>;
  sessionId: string;
  sessionDir: string;
  stateRoot: string;
  provider: WorkbenchProvider;
}

export interface LaunchResult {
  sessionId: string;
  exitCode: number;
  stdout: string;
  stderr: string;
  receipt: Record<string, unknown>;
}

export function defaultStateRoot(environment: NodeJS.ProcessEnv = process.env): string {
  const base = environment.XDG_STATE_HOME?.trim() || path.join(os.homedir(), ".local", "state");
  return path.join(base, "cognovis-pi", "pi-workbench");
}

export function createSessionId(now = new Date()): string {
  return `${now.toISOString().replace(/[:.]/g, "-")}-${randomUUID().slice(0, 8)}`;
}

export function managedEnvironment(
  ambient: NodeJS.ProcessEnv,
  values: Record<string, string>,
): NodeJS.ProcessEnv {
  const clean = { ...ambient };
  for (const name of Object.keys(clean)) {
    if (
      name.startsWith("ANTHROPIC_") ||
      name.startsWith("ACPX_AUTH_") ||
      name.startsWith("CODEX_") ||
      name.startsWith("KIMI_") ||
      name.startsWith("MOONSHOT_") ||
      name.startsWith("OPENAI_") ||
      name.startsWith("PI_") ||
      name.startsWith("COGNOVIS_PI_")
    ) {
      delete clean[name];
    }
  }
  for (const name of AUTH_ENVIRONMENT_NAMES) delete clean[name];
  for (const name of ["CLAUDE_CONFIG_DIR", "CLAUDE_MODEL_CONFIG", "MAX_THINKING_TOKENS"]) {
    delete clean[name];
  }
  return { ...clean, ...values, PI_OFFLINE: "1" };
}

export async function createLaunchPlan(options: LaunchOptions): Promise<LaunchPlan> {
  const repositoryRoot = path.resolve(options.repositoryRoot);
  const profile = await resolveProfile(repositoryRoot);
  let provider = parseWorkbenchProvider(options.provider, profile.profile.provider.default);
  let selection = providerSelection(profile, provider);
  if (options.fusionProfile && options.beadProfile) {
    throw new Error("Fusion and Bead Harness profiles are mutually exclusive");
  }
  let fusionExtensionPath: string | null = null;
  let fusionProfilePath: string | null = null;
  let beadExtensionPath: string | null = null;
  let beadProfilePath: string | null = null;
  const beadRequiredProviders = new Set<WorkbenchProvider>();
  if (options.fusionProfile) {
    fusionProfilePath = path.resolve(repositoryRoot, options.fusionProfile);
    const fusion = JSON.parse(await readFile(fusionProfilePath, "utf8")) as {
      schema?: unknown;
      roles?: { builder?: unknown };
    };
    if (
      fusion.schema !== "cognovis.pi.fusion-profile.v1" ||
      typeof fusion.roles?.builder !== "string" ||
      !fusion.roles.builder.startsWith(`${profile.profile.provider.id}/`)
    ) {
      throw new Error("Fusion profile has no managed ACPX builder role");
    }
    const hostModel = fusion.roles.builder.slice(profile.profile.provider.id.length + 1);
    const hostRoute = routeForModel(profile.profile, hostModel);
    provider = hostRoute.provider;
    selection = hostRoute.selection;
    const candidates = [
      path.join(repositoryRoot, ".agents/pi/extensions/fusion-harness/fusion-harness.ts"),
      path.join(repositoryRoot, "extensions/fusion-harness/fusion-harness.ts"),
    ];
    for (const candidate of candidates) {
      try {
        if ((await stat(candidate)).isFile()) {
          fusionExtensionPath = candidate;
          break;
        }
      } catch {
        // Continue to the source-checkout fallback.
      }
    }
    if (!fusionExtensionPath) {
      throw new Error("Fusion Harness extension is not installed");
    }
  }
  if (options.beadProfile) {
    beadProfilePath = path.resolve(repositoryRoot, options.beadProfile);
    const bead = JSON.parse(await readFile(beadProfilePath, "utf8")) as {
      schema?: unknown;
      mode?: unknown;
      implementer?: { harness?: unknown; family?: unknown; model?: unknown; route?: unknown };
      reviewers?: Array<{ id?: unknown; perspective?: unknown; family?: unknown; route?: unknown }>;
      adjudicator?: { id?: unknown; family?: unknown; route?: unknown } | null;
    };
    if (
      bead.schema !== "cognovis.pi.bead-harness-profile.v2" ||
      typeof bead.implementer?.harness !== "string" ||
      typeof bead.implementer?.model !== "string" ||
      typeof bead.implementer?.route !== "string" ||
      !Array.isArray(bead.reviewers)
    ) {
      throw new Error("Bead Harness profile has no managed implementer route");
    }
    if (bead.mode === "high-assurance") {
      const boundary = bead.reviewers.find((reviewer) => reviewer.perspective === "boundary-operator");
      if (
        !bead.adjudicator
        || typeof bead.adjudicator.id !== "string"
        || bead.reviewers.some((reviewer) => reviewer.id === bead.adjudicator?.id)
        || bead.adjudicator.family === bead.implementer.family
        || bead.adjudicator.family === boundary?.family
        || bead.adjudicator.route === boundary?.route
      ) {
        throw new Error("Bead Harness adjudicator is not distinct from the implementer and boundary reviewer");
      }
    }
    const requiredRoutes = [
      bead.implementer.route,
      ...bead.reviewers.map((reviewer) => reviewer.route),
      ...(bead.adjudicator ? [bead.adjudicator.route] : []),
    ];
    if (requiredRoutes.some((route) => typeof route !== "string")) {
      throw new Error("Bead Harness profile carries an incomplete managed route");
    }
    for (const route of requiredRoutes as string[]) {
      const resolved = routeForModel(profile.profile, route);
      beadRequiredProviders.add(resolved.provider);
    }
    const hostRoute = routeForModel(profile.profile, bead.implementer.route);
    provider = hostRoute.provider;
    selection = hostRoute.selection;
    const candidates = [
      path.join(repositoryRoot, ".agents/pi/extensions/cognovis-bead-harness/index.ts"),
      path.join(repositoryRoot, "extensions/cognovis-bead-harness/index.ts"),
    ];
    for (const candidate of candidates) {
      try {
        if ((await stat(candidate)).isFile()) {
          beadExtensionPath = candidate;
          break;
        }
      } catch {
        // Continue to the source-checkout fallback.
      }
    }
    if (!beadExtensionPath) throw new Error("Cognovis Bead Harness extension is not installed");
  }
  const selections = Object.fromEntries(
    WORKBENCH_PROVIDERS.map((entry) => [entry, providerSelection(profile, entry)]),
  ) as Record<WorkbenchProvider, ReturnType<typeof providerSelection>>;
  const ambient = options.environment ?? process.env;
  const providerRuntimes = await resolveProviderRuntimes(
    repositoryRoot,
    selections,
    ambient,
  );
  for (const required of beadRequiredProviders) {
    if (providerRuntimes[required].status !== "available") {
      throw new Error(`Bead Harness required provider is unavailable: ${required}`);
    }
  }
  const stateRoot = path.resolve(options.stateRoot ?? defaultStateRoot(options.environment));
  const sessionId = options.sessionId ?? createSessionId();
  const store = new SessionStore(stateRoot);
  const sessionDir = await store.initializeSession(sessionId);
  const piConfigDir = path.join(sessionDir, "pi-config");
  const piSessionsDir = path.join(sessionDir, "pi-sessions");
  const acpxStateDir = path.join(sessionDir, "acpx");
  const downstreamCwd = path.join(sessionDir, "downstream-cwd");
  await Promise.all([
    mkdir(piConfigDir, { recursive: true, mode: 0o700 }),
    mkdir(piSessionsDir, { recursive: true, mode: 0o700 }),
    mkdir(acpxStateDir, { recursive: true, mode: 0o700 }),
    ...WORKBENCH_PROVIDERS.map((entry) =>
      mkdir(path.join(acpxStateDir, entry), { recursive: true, mode: 0o700 })
    ),
    mkdir(downstreamCwd, { recursive: true, mode: 0o700 }),
  ]);
  const extension = resourceByKind(profile, "pi-extension");
  const providerImplementation = resourceByKind(profile, "provider-implementation");
  const proxy = resourceByKind(profile, "runtime-boundary");
  const openBrainProxy = resourceById(profile, "open-brain-readonly-proxy");
  const beadsMcp = resourceById(profile, "beads-readonly-mcp");
  const systemPrompt = await readFile(resourceByKind(profile, "system-prompt").absolutePath, "utf8");
  const bunCommand = process.execPath;
  const repositoryPi = path.join(repositoryRoot, "node_modules", ".bin", "pi");
  let piCommand = options.piCommand ?? repositoryPi;
  if (!options.piCommand) {
    try {
      if (!(await stat(repositoryPi)).isFile()) piCommand = "pi";
    } catch {
      piCommand = "pi";
    }
  }
  // A vendored provider bundle carries bare imports of the external Pi runtime
  // packages and has no node_modules of its own; link the runtime of the Pi we
  // are about to spawn onto its resolution path.
  await ensureProviderRuntimeResolution(
    repositoryRoot,
    providerImplementation.absolutePath,
    piCommand,
    ambient,
  );
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
    ...(fusionProfilePath ? { COGNOVIS_PI_FUSION_PROFILE: fusionProfilePath } : {}),
    ...(beadProfilePath ? { COGNOVIS_PI_BEAD_HARNESS_PROFILE: beadProfilePath } : {}),
    PI_CODING_AGENT_DIR: piConfigDir,
  });
  const args = [
    ...PI_ISOLATION_FLAGS,
    "--extension",
    extension.absolutePath,
    ...(fusionExtensionPath ? ["--extension", fusionExtensionPath] : []),
    ...(beadExtensionPath ? ["--extension", beadExtensionPath] : []),
    "--provider",
    profile.profile.provider.id,
    "--model",
    selection.model,
    "--system-prompt",
    `${systemPrompt}\n\nManaged repository root: ${repositoryRoot}`,
    "--session-dir",
    piSessionsDir,
    "--session-id",
    sessionId,
  ];
  if (options.print || options.prompt) args.push("--print");
  if (options.prompt) args.push(options.prompt);

  const receipt = {
    schema: "cognovis.pi.boot-receipt.v1",
    sessionId,
    createdAt: new Date().toISOString(),
    profile: {
      id: profile.profile.id,
      version: profile.profile.version,
      sha256: profile.profileHash,
      resolvedPath: path.relative(repositoryRoot, profile.manifestPath),
      dependencyRoot: profile.profile.package.dependencyRoot,
    },
    resources: profile.resources.map((resource) => ({
      id: resource.id,
      kind: resource.kind,
      path: resource.path,
      resolvedPath: resource.resolvedPath,
      sha256: resource.sha256,
      source: resource.source,
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
          isolationCapability: route.isolationCapability,
        };
      }),
    },
    authProvenance: {
      classification: "per-provider-default-context",
      routes: Object.fromEntries(
        WORKBENCH_PROVIDERS.map((entry) => [
          entry,
          {
            source: selections[entry].authContext,
            apiKeySource: null,
            configMode: "default",
            credentialProjection: false,
          },
        ]),
      ),
      apiKeySource: null,
      configMode: "default",
      credentialProjection: false,
      environment: snapshotEnvironment(environment),
      credentialValuesStored: false,
    },
    permissionPolicy: {
      ...profile.profile.permissions,
      downstreamMode: selection.mode,
      acpxPermissionMode: "deny-all",
      hostCallbackScope: "adapter-emitted permission requests",
      providerNativeReads: "observable but not host-decided",
      verifiedBoundary: "ACPX deny-all fallback plus fail-closed host callback",
    },
    isolation: profile.profile.isolation,
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
    stateRoot,
  };
}

export async function launchWorkbench(options: LaunchOptions): Promise<LaunchResult> {
  const plan = await createLaunchPlan(options);
  const store = new SessionStore(plan.stateRoot);
  const capture = Boolean(options.print || options.prompt);
  const child = spawn(plan.command, plan.args, {
    cwd: path.resolve(options.repositoryRoot),
    env: plan.environment,
    stdio: capture ? ["ignore", "pipe", "pipe"] : "inherit",
  });
  let stdout = "";
  let stderr = "";
  if (capture) {
    child.stdout?.on("data", (chunk) => { stdout += String(chunk); });
    child.stderr?.on("data", (chunk) => { stderr += String(chunk); });
  }
  const exitCode = await new Promise<number>((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolve(code ?? 1));
  });
  const redaction = options.redactionCanaries ? { canaries: options.redactionCanaries } : {};
  stdout = redactText(stdout, redaction);
  stderr = redactText(stderr, redaction);
  await store.append(plan.sessionId, "verification", {
    check: "managed-launch",
    state: exitCode === 0 ? "pass" : "fail",
    exitCode,
  });
  if (exitCode !== 0) {
    await store.append(plan.sessionId, "failure", {
      stage: "managed-launch",
      message: stderr || `Pi exited with code ${exitCode}`,
    }, redaction);
  }
  return { sessionId: plan.sessionId, exitCode, stdout, stderr, receipt: plan.receipt };
}
