/**
 * Cognovis ACPX workbench provider.
 *
 * Selectively adapted from myk-org/pi-config at
 * c43b2a84e11f9de1426535291ddd8325340c7e4e (MIT): provider registration,
 * model discovery, persistent runtime sessions, and latest-user-message routing.
 */
import type {
  AssistantMessage,
  Context,
  Model,
  SimpleStreamOptions,
  StreamOptions,
} from "@earendil-works/pi-ai";
import { createAssistantMessageEventStream, createProvider } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  createAcpRuntime,
  createAgentRegistry,
  createFileSessionStore,
  type AcpRuntimeHandle,
} from "acpx/runtime";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { loadExtensionConfig } from "./config.ts";
import {
  assertObservableTurn,
  adapterModelId,
  configuredModelRoutes,
  LazyProviderPool,
  modelContextWindow,
  providerSessionKey,
  routeForModel,
} from "./model-switching.ts";
import { decideAndRecordPermission } from "./permission-policy.ts";
import {
  resolveProfile,
  resourceByKind,
  type ProviderSelection,
} from "./profile.ts";
import type { WorkbenchProvider } from "./providers.ts";
import { mapRuntimeEvent, type MutableUsage } from "./runtime-events.ts";
import { appendWorkbenchEvent } from "./session-store.ts";
import { registerBeadsReadTool } from "./beads-read.ts";

const config = loadExtensionConfig();
const resolvedProfile = await resolveProfile(config.repositoryRoot, config.profileId);
const systemPrompt = await readFile(resourceByKind(resolvedProfile, "system-prompt").absolutePath, "utf8");
const projectCwd = process.cwd();

function managedMcpServers() {
  return [{
    name: "beads",
    command: config.bunCommand,
    args: [config.beadsMcpPath],
    env: [
      { name: "COGNOVIS_PI_REPOSITORY_ROOT", value: config.repositoryRoot },
      { name: "COGNOVIS_PI_EVENT_LOG", value: config.eventLog },
      { name: "COGNOVIS_PI_SESSION_ID", value: config.sessionId },
    ],
  }, {
    name: "open-brain",
    command: config.bunCommand,
    args: [config.openBrainProxyPath],
    env: [],
  }];
}

interface ActiveProviderRoute {
  provider: WorkbenchProvider;
  selection: ProviderSelection;
  runtime: ReturnType<typeof createAcpRuntime>;
  handles: Map<string, AcpRuntimeHandle>;
}

const providerPool = new LazyProviderPool<ActiveProviderRoute>(async (provider) => {
  const manifest = config.providerRuntimes[provider];
  if (manifest.status === "unavailable") {
    throw new Error(manifest.reason);
  }
  const selection = resolvedProfile.profile.provider.selections[provider];
  const runtime = createAcpRuntime({
    cwd: projectCwd,
    sessionStore: createFileSessionStore({
      stateDir: path.join(config.acpxStateDir, provider),
    }),
    agentRegistry: createAgentRegistry({
      overrides: {
        [provider]: `${config.adapterCommand} --provider ${provider}`,
      },
    }),
    permissionMode: "deny-all",
    nonInteractivePermissions: "fail",
    mcpServers: managedMcpServers(),
    async onPermissionRequest(request) {
      return decideAndRecordPermission(
        request,
        config.repositoryRoot,
        resolvedProfile.profile.permissions,
        async (type, data) => {
          await appendWorkbenchEvent(
            config.eventLog,
            config.sessionId,
            type,
            { provider, ...data },
            { canaries: config.redactionCanaries },
          );
        },
      );
    },
  });
  return { provider, selection, runtime, handles: new Map() };
});

function latestUserText(context: Context): string {
  for (let index = context.messages.length - 1; index >= 0; index -= 1) {
    const message = context.messages[index];
    if (message?.role !== "user") continue;
    if (typeof message.content === "string") return message.content;
    return message.content
      .filter((block) => "text" in block)
      .map((block) => ("text" in block ? block.text : ""))
      .join("\n");
  }
  throw new Error("ACPX provider requires a user message");
}

async function ensureHandle(
  route: ActiveProviderRoute,
  modelId: string,
  adapterModelId: string,
  requestedSystemPrompt: string | undefined,
): Promise<AcpRuntimeHandle> {
  const existing = route.handles.get(modelId);
  if (existing) return existing;
  const providerModelId = adapterModelId.replace(new RegExp(`^${route.provider}:`), "");
  const handle = await route.runtime.ensureSession({
    sessionKey: providerSessionKey(config.sessionId, route.provider, modelId),
    agent: route.provider,
    mode: "oneshot",
    cwd: projectCwd,
    sessionOptions: {
      ...(providerModelId === "default" ? {} : { model: providerModelId }),
      allowedTools: [...resolvedProfile.profile.permissions.allowedTools],
      systemPrompt: requestedSystemPrompt || systemPrompt,
    },
  });
  await route.runtime.setMode({ handle, mode: route.selection.mode });
  route.handles.set(modelId, handle);
  return handle;
}

function piUsage(usage: MutableUsage): AssistantMessage["usage"] {
  return {
    input: usage.input ?? 0,
    output: usage.output ?? 0,
    cacheRead: usage.cacheRead ?? 0,
    cacheWrite: usage.cacheWrite ?? 0,
    totalTokens: usage.totalTokens ?? 0,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  };
}

function streamAcpx(
  model: Model<any>,
  context: Context,
  options?: SimpleStreamOptions | StreamOptions,
) {
  const stream = createAssistantMessageEventStream();
  void (async () => {
    const usage: MutableUsage = {};
    let selectedProvider: WorkbenchProvider | null = null;
    const output: AssistantMessage = {
      role: "assistant",
      content: [],
      api: model.api,
      provider: model.provider,
      model: model.id,
      usage: piUsage(usage),
      stopReason: "stop",
      timestamp: Date.now(),
    };
    try {
      const modelRoute = routeForModel(resolvedProfile.profile, model.id);
      selectedProvider = modelRoute.provider;
      await appendWorkbenchEvent(
        config.eventLog,
        config.sessionId,
        "prompt",
        {
          text: latestUserText(context),
          state: "submitted",
          provider: modelRoute.provider,
          model: model.id,
        },
        { canaries: config.redactionCanaries },
      );
      stream.push({ type: "start", partial: output });
      const runtimeManifest = config.providerRuntimes[modelRoute.provider];
      if (runtimeManifest.status === "unavailable") {
        await appendWorkbenchEvent(config.eventLog, config.sessionId, "provider", {
          id: model.provider,
          model: model.id,
          agent: modelRoute.provider,
          route: modelRoute.selection.route,
          state: "unavailable",
          message: runtimeManifest.reason,
        });
        throw new Error(runtimeManifest.reason);
      }
      const activeRoute = await providerPool.get(modelRoute.provider);
      const handle = await ensureHandle(
        activeRoute,
        model.id,
        adapterModelId(modelRoute.selection),
        context.systemPrompt,
      );
      const providerStatus = await activeRoute.runtime.getStatus({ handle });
      await appendWorkbenchEvent(config.eventLog, config.sessionId, "provider", {
        id: model.provider,
        model: model.id,
        agent: modelRoute.provider,
        route: modelRoute.selection.route,
        adapterMode: modelRoute.selection.mode,
        adapter: runtimeManifest.status === "available"
          ? runtimeManifest.commandProvenance
          : null,
        isolationCapability: modelRoute.selection.isolationCapability,
        acpxFallback: resolvedProfile.profile.permissions.acpxFallback,
        acpxPermissionMode: "deny-all",
        hostCallbackScope: "adapter-emitted permission requests",
        providerNativeReads: "observable but not host-decided",
        backendSessionPresent: Boolean(providerStatus.backendSessionId),
        backendSessionId: providerStatus.backendSessionId ?? null,
        agentSessionPresent: Boolean(providerStatus.agentSessionId),
        agentSessionId: providerStatus.agentSessionId ?? null,
        runtimeSessionKey: handle.sessionKey,
        state: "ready",
      });
      const turn = activeRoute.runtime.startTurn({
        handle,
        text: latestUserText(context),
        mode: "prompt",
        requestId: `${config.sessionId}-${modelRoute.provider}`,
        ...(options?.signal ? { signal: options.signal } : {}),
      });
      let text = "";
      let started = false;
      let observedTool = false;
      for await (const event of turn.events) {
        const record = mapRuntimeEvent(event, usage);
        if (record.category === "tool_call" && event.type === "tool_call") {
          observedTool = true;
          await appendWorkbenchEvent(
            config.eventLog,
            config.sessionId,
            "tool",
            {
              provider: modelRoute.provider,
              model: model.id,
              kind: event.kind ?? null,
              status: event.status ?? null,
              title: event.title ?? event.text,
              input: event.rawInput,
            },
            { canaries: config.redactionCanaries },
          );
        }
        if (record.category !== "text") continue;
        if (!started) {
          output.content.push({ type: "text", text: "" });
          stream.push({ type: "text_start", contentIndex: 0, partial: output });
          started = true;
        }
        text += record.text;
        const block = output.content[0];
        if (block?.type === "text") block.text = text;
        stream.push({ type: "text_delta", contentIndex: 0, delta: record.text, partial: output });
      }
      const result = await turn.result;
      if (result.status !== "completed") {
        throw new Error(`ACPX turn did not complete: ${result.status}`);
      }
      assertObservableTurn(modelRoute.provider, started, observedTool);
      await appendWorkbenchEvent(config.eventLog, config.sessionId, "verification", {
        check: "provider-turn",
        state: "pass",
        provider: modelRoute.provider,
        model: model.id,
        stopReason: result.stopReason ?? null,
      });
      output.usage = piUsage(usage);
      if (started) {
        stream.push({ type: "text_end", contentIndex: 0, content: text, partial: output });
      }
      stream.push({ type: "done", reason: "stop", message: output });
      stream.end();
    } catch (error) {
      output.stopReason = options?.signal?.aborted ? "aborted" : "error";
      output.errorMessage = error instanceof Error ? error.message : "ACPX provider failed";
      await appendWorkbenchEvent(
        config.eventLog,
        config.sessionId,
        "failure",
        {
          stage: "provider-turn",
          provider: selectedProvider,
          model: model.id,
          message: output.errorMessage,
        },
        { canaries: config.redactionCanaries },
      );
      stream.push({ type: "error", reason: output.stopReason, error: output });
      stream.end();
    }
  })();
  return stream;
}

export default async function register(pi: ExtensionAPI): Promise<void> {
  registerBeadsReadTool(pi, {
    repositoryRoot: config.repositoryRoot,
    eventLog: config.eventLog,
    sessionId: config.sessionId,
    redactionCanaries: config.redactionCanaries,
  });
  const models = configuredModelRoutes(resolvedProfile.profile).map(
    ({ provider, selection }) => ({
      id: selection.model,
      name: `${provider.charAt(0).toUpperCase() + provider.slice(1)} ${selection.model.replace(`${provider}:`, "")}`,
      api: "acpx" as any,
      provider: "acpx-workbench",
      baseUrl: "https://localhost",
      reasoning: true,
      input: ["text"] as ("text" | "image")[],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: modelContextWindow(selection),
      maxTokens: 32_768,
    }),
  );
  const provider = createProvider({
    id: "acpx-workbench",
    name: "ACPX Workbench",
    auth: {
      apiKey: {
        name: "Ambient provider authentication",
        async login() {
          throw new Error("Use the selected provider CLI to authenticate before launching Pi");
        },
        async resolve() {
          return {
            auth: { apiKey: "ambient" },
            source: "Selected provider CLI via ACPX",
          };
        },
        async check() {
          return { type: "api_key", source: "Selected provider CLI via ACPX" };
        },
      },
    },
    models,
    api: { stream: streamAcpx, streamSimple: streamAcpx },
  });
  pi.registerProvider(provider);
  pi.on("session_shutdown", async () => {
    const activeRoutes = await providerPool.fulfilled();
    await Promise.allSettled(
      activeRoutes.flatMap((route) =>
        [...route.handles.values()].map((handle) =>
          route.runtime.close({ handle, reason: "Pi session shutdown" })
        )
      ),
    );
  });
}
