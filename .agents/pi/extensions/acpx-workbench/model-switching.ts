import type { ProviderSelection, WorkbenchProfile } from "./profile.ts";
import {
  WORKBENCH_PROVIDERS,
  type WorkbenchProvider,
} from "./providers.ts";

export interface ModelRoute {
  provider: WorkbenchProvider;
  selection: ProviderSelection;
}

export function configuredModelRoutes(
  profile: WorkbenchProfile,
): ModelRoute[] {
  return WORKBENCH_PROVIDERS.flatMap((provider) =>
    profile.provider.models[provider].map((route) => {
      const model = typeof route === "string" ? route : route.id;
      const adapterModel = typeof route === "string" ? route : route.nativeModel;
      return {
        provider,
        selection: { ...profile.provider.selections[provider], model, adapterModel },
      };
    })
  );
}

export function routeForModel(
  profile: WorkbenchProfile,
  modelId: string,
): ModelRoute {
  const route = configuredModelRoutes(profile).find(
    ({ selection }) => selection.model === modelId,
  );
  if (!route) throw new Error(`No managed provider route owns model: ${modelId}`);
  return route;
}

export function providerSessionKey(
  workbenchSessionId: string,
  provider: WorkbenchProvider,
  modelId: string,
): string {
  const normalizedModel = modelId.replace(/[^a-zA-Z0-9.-]/g, "_");
  return `${workbenchSessionId}-${provider}-${normalizedModel}`;
}

export function modelContextWindow(selection: ProviderSelection): number {
  return adapterModelId(selection).endsWith("[1m]") ? 1_000_000 : 200_000;
}

export function adapterModelId(selection: ProviderSelection): string {
  return selection.adapterModel ?? selection.model;
}

export function assertObservableTurn(
  provider: WorkbenchProvider,
  textObserved: boolean,
  toolObserved: boolean,
): void {
  if (!textObserved && !toolObserved) {
    throw new Error(
      `${provider} provider returned no text or observable tool activity`,
    );
  }
}

export class LazyProviderPool<T> {
  private readonly values = new Map<WorkbenchProvider, Promise<T>>();

  constructor(
    private readonly create: (provider: WorkbenchProvider) => Promise<T>,
  ) {}

  get(provider: WorkbenchProvider): Promise<T> {
    const existing = this.values.get(provider);
    if (existing) return existing;
    const created = this.create(provider).catch((error) => {
      if (this.values.get(provider) === created) {
        this.values.delete(provider);
      }
      throw error;
    });
    this.values.set(provider, created);
    return created;
  }

  async fulfilled(): Promise<T[]> {
    const settled = await Promise.allSettled(this.values.values());
    const fulfilled: T[] = [];
    for (const result of settled) {
      if (result.status === "fulfilled") fulfilled.push(result.value as T);
    }
    return fulfilled;
  }
}
