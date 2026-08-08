import { createHash } from "node:crypto";
import { readFile, realpath } from "node:fs/promises";
import path from "node:path";

export type ResourceKind =
  | "system-prompt"
  | "pi-extension"
  | "provider-implementation"
  | "runtime-boundary"
  | "mcp-boundary";

export interface ProfileResource {
  id: string;
  kind: ResourceKind;
  path: string;
  sha256: string;
  source: string;
}

export interface WorkbenchProfile {
  schema: "cognovis.pi.profile.v1";
  id: "pi-workbench";
  version: string;
  package: { catalog: "library.yaml"; dependencyRoot: "just-module:pi-workbench" };
  library: { repository: string; commit: string; allowlist: string[] };
  resources: ProfileResource[];
  provider: {
    id: "acpx-workbench";
    default: "claude";
    selections: Record<"claude" | "codex" | "kimi", ProviderSelection>;
    models: Record<"claude" | "codex" | "kimi", Array<string | ProviderModelRoute>>;
  };
  permissions: {
    id: "repository-safe-v1";
    acpxFallback: "deny-all";
    downstreamMode: "default";
    nonInteractive: "fail";
    allowedTools: string[];
    pathScope: "repository";
    shell: "disabled";
    network: "disabled" | "open-brain-readonly-proxy-only";
  };
  isolation: {
    piDiscovery: Record<string, boolean>;
    downstream: {
      settingSources: [];
      skills: [];
      plugins: [];
      mcpServers: Record<string, never>;
      managedMcpServers: ["beads", "open-brain"];
      hooks: false;
      projectCwd: false;
    };
  };
  observability: { events: "jsonl"; consumer: "workbench session"; retention: "durable" };
}

export type ProviderAdapter =
  | {
      command: string[];
      version: string;
      provenance: "repository-package";
    }
  | {
      command: string[];
      provenance: "host-binary";
    };

export interface ProviderSelection {
  agent: "claude" | "codex" | "kimi";
  model: string;
  adapterModel?: string;
  mode: string;
  route: string[];
  authContext: string;
  isolationCapability: {
    ambientUserSkills: "enforced" | "adapter-managed" | "not-supported";
    warning: string | null;
  };
  adapter: ProviderAdapter;
}

export interface ProviderModelRoute {
  id: string;
  nativeModel: string;
}

function publicModelId(model: string | ProviderModelRoute): string {
  return typeof model === "string" ? model : model.id;
}

function validModelRoute(
  model: string | ProviderModelRoute,
  provider: "claude" | "codex" | "kimi",
): boolean {
  if (typeof model === "string") return model.startsWith(`${provider}:`);
  return (
    Object.keys(model).length === 2 &&
    typeof model.id === "string" &&
    model.id.startsWith(`${provider}:`) &&
    typeof model.nativeModel === "string" &&
    model.nativeModel.startsWith(`${provider}:`)
  );
}

export interface ResolvedResource extends ProfileResource {
  absolutePath: string;
  resolvedPath: string;
}

export interface ResolvedProfile {
  profile: WorkbenchProfile;
  manifestPath: string;
  profileHash: string;
  resources: ResolvedResource[];
}

const ALLOWED_PROFILE_PATHS = {
  "pi-workbench": [
    ".agents/pi/profiles/pi-workbench.json",
    "profiles/pi-workbench.json",
  ],
} as const;

const PROJECT_NATIVE_RESOURCE_PATHS = {
  "project-native:pi-extension/acpx-workbench/index.ts": [
    ".agents/pi/extensions/acpx-workbench/index.ts",
    "extensions/acpx-workbench/index.ts",
  ],
  "project-native:pi-extension/acpx-workbench/dist/provider.js": [
    ".agents/pi/extensions/acpx-workbench/dist/provider.js",
    "extensions/acpx-workbench/dist/provider.js",
  ],
  "project-native:pi-extension/acpx-workbench/dist/acp-cleanroom-proxy.js": [
    ".agents/pi/extensions/acpx-workbench/dist/acp-cleanroom-proxy.js",
    "extensions/acpx-workbench/dist/acp-cleanroom-proxy.js",
  ],
  "project-native:pi-extension/acpx-workbench/dist/open-brain-readonly-proxy.js": [
    ".agents/pi/extensions/acpx-workbench/dist/open-brain-readonly-proxy.js",
    "extensions/acpx-workbench/dist/open-brain-readonly-proxy.js",
  ],
  "project-native:pi-extension/acpx-workbench/dist/beads-readonly-mcp.js": [
    ".agents/pi/extensions/acpx-workbench/dist/beads-readonly-mcp.js",
    "extensions/acpx-workbench/dist/beads-readonly-mcp.js",
  ],
  "project-native:pi-extension/acpx-workbench/system-prompt.md": [
    ".agents/pi/extensions/acpx-workbench/system-prompt.md",
    "extensions/acpx-workbench/system-prompt.md",
  ],
} as const;

export function sha256(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function assertProfile(value: unknown): asserts value is WorkbenchProfile {
  if (!value || typeof value !== "object") throw new Error("Profile must be an object");
  const candidate = value as Partial<WorkbenchProfile>;
  if (candidate.schema !== "cognovis.pi.profile.v1") throw new Error("Unsupported profile schema");
  if (candidate.id !== "pi-workbench") throw new Error("Profile id must be pi-workbench");
  if (
    candidate.package?.catalog !== "library.yaml" ||
    candidate.package?.dependencyRoot !== "just-module:pi-workbench"
  ) {
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
  for (const provider of ["claude", "codex", "kimi"] as const) {
    const selection = candidate.provider.selections?.[provider];
    const models = candidate.provider.models?.[provider];
    if (
      selection?.agent !== provider ||
      !selection.model?.startsWith(`${provider}:`) ||
      !Array.isArray(models) ||
      models.length === 0 ||
      !models.some((model) => publicModelId(model) === selection.model) ||
      !models.every((model) => validModelRoute(model, provider)) ||
      new Set(models.map(publicModelId)).size !== models.length ||
      !selection.mode ||
      !Array.isArray(selection.route) ||
      selection.route.length === 0 ||
      !Array.isArray(selection.adapter?.command) ||
      selection.adapter.command.length === 0 ||
      !(
        (selection.adapter.provenance === "repository-package" &&
          /^\d+\.\d+\.\d+$/.test(selection.adapter.version)) ||
        (selection.adapter.provenance === "host-binary" &&
          !("version" in selection.adapter))
      ) ||
      !["enforced", "adapter-managed", "not-supported"].includes(
        selection.isolationCapability?.ambientUserSkills,
      ) ||
      !(
        selection.isolationCapability.warning === null ||
        typeof selection.isolationCapability.warning === "string"
      )
    ) {
      throw new Error(`Profile provider selection is invalid: ${provider}`);
    }
  }
  if (candidate.permissions?.id !== "repository-safe-v1") {
    throw new Error("Profile permission policy must be repository-safe-v1");
  }
  if (
    candidate.permissions.shell !== "disabled" ||
    candidate.permissions.network !== "open-brain-readonly-proxy-only" ||
    candidate.permissions.allowedTools?.includes("Bash") ||
    candidate.permissions.allowedTools?.includes("bash")
  ) {
    throw new Error("Profile permission boundary is invalid");
  }
  if (
    candidate.isolation?.downstream?.settingSources?.length !== 0 ||
    candidate.isolation?.downstream?.skills?.length !== 0 ||
    candidate.isolation?.downstream?.plugins?.length !== 0
  ) {
    throw new Error("Downstream discovery allowlists must be empty");
  }
  if (
    candidate.isolation.downstream.managedMcpServers?.length !== 2 ||
    candidate.isolation.downstream.managedMcpServers[0] !== "beads" ||
    candidate.isolation.downstream.managedMcpServers[1] !== "open-brain"
  ) {
    throw new Error("Managed MCP boundary must contain only Beads and Open Brain");
  }
}

export function providerSelection(
  resolved: ResolvedProfile,
  provider: "claude" | "codex" | "kimi",
): ProviderSelection {
  return resolved.profile.provider.selections[provider];
}

async function resolveFirstRepositoryPath(
  root: string,
  candidates: readonly string[],
  label: string,
): Promise<{ absolutePath: string; resolvedPath: string }> {
  for (const candidate of candidates) {
    const absolutePath = path.resolve(root, candidate);
    if (!isWithin(root, absolutePath)) throw new Error(`${label} leaves repository root`);
    try {
      const realPath = await realpath(absolutePath);
      if (!isWithin(root, realPath)) throw new Error(`${label} resolves outside repository root`);
      return { absolutePath: realPath, resolvedPath: path.relative(root, realPath) };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
  throw new Error(`${label} is not installed and has no source-checkout fallback`);
}

function isWithin(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

export async function resolveProfile(
  repositoryRoot: string,
  profileId: keyof typeof ALLOWED_PROFILE_PATHS = "pi-workbench",
): Promise<ResolvedProfile> {
  const root = await realpath(repositoryRoot);
  const manifestCandidates = ALLOWED_PROFILE_PATHS[profileId];
  if (!manifestCandidates) throw new Error(`Profile is not allowlisted: ${profileId}`);
  const manifest = await resolveFirstRepositoryPath(root, manifestCandidates, "Profile manifest");
  const rawManifest = await readFile(manifest.absolutePath, "utf8");
  const parsed: unknown = JSON.parse(rawManifest);
  assertProfile(parsed);

  const seen = new Set<string>();
  const resources: ResolvedResource[] = [];
  for (const resource of parsed.resources) {
    if (seen.has(resource.id)) throw new Error(`Duplicate profile resource: ${resource.id}`);
    seen.add(resource.id);
    if (!/^[a-f0-9]{64}$/.test(resource.sha256)) {
      throw new Error(`Resource ${resource.id} does not have a pinned sha256`);
    }
    const logicalCandidates = PROJECT_NATIVE_RESOURCE_PATHS[
      resource.path as keyof typeof PROJECT_NATIVE_RESOURCE_PATHS
    ];
    const resolved = await resolveFirstRepositoryPath(
      root,
      logicalCandidates ?? [resource.path],
      `Resource ${resource.id}`,
    );
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
    "mcp-boundary",
  ] as const) {
    if (!resources.some((resource) => resource.kind === required)) {
      throw new Error(`Profile is missing required resource kind: ${required}`);
    }
  }
  return {
    profile: parsed,
    manifestPath: manifest.absolutePath,
    profileHash: sha256(rawManifest),
    resources,
  };
}

export function resourceByKind(resolved: ResolvedProfile, kind: ResourceKind): ResolvedResource {
  const resource = resolved.resources.find((entry) => entry.kind === kind);
  if (!resource) throw new Error(`Resolved profile has no ${kind} resource`);
  return resource;
}

export function resourceById(resolved: ResolvedProfile, id: string): ResolvedResource {
  const resource = resolved.resources.find((entry) => entry.id === id);
  if (!resource) throw new Error(`Resolved profile has no ${id} resource`);
  return resource;
}
