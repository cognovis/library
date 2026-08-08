export const AUTH_ENVIRONMENT_NAMES = [
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_AUTH_TOKEN",
  "ANTHROPIC_OAUTH_TOKEN",
  "CODEX_API_KEY",
  "KIMI_API_KEY",
  "MOONSHOT_API_KEY",
  "OPENAI_API_KEY",
] as const;

export type AuthEnvironmentName = (typeof AUTH_ENVIRONMENT_NAMES)[number];

export interface AuthSnapshot {
  apiKeySource: string | null;
  apiProvider: string | null;
  subscriptionType: string | null;
  tokenSource: string | null;
  environment: Record<AuthEnvironmentName, boolean>;
}

export function snapshotEnvironment(environment: NodeJS.ProcessEnv) {
  return Object.fromEntries(
    AUTH_ENVIRONMENT_NAMES.map((name) => [name, Boolean(environment[name])]),
  ) as Record<AuthEnvironmentName, boolean>;
}

export function classifyAuthProvenance(snapshot: AuthSnapshot): {
  classification: "subscription" | "api-key" | "ambiguous";
  reason: string;
} {
  if (snapshot.apiKeySource || Object.values(snapshot.environment).some(Boolean)) {
    return {
      classification: "api-key",
      reason: "API credential source or environment variable was observed",
    };
  }
  if (snapshot.apiProvider === "firstParty" && snapshot.subscriptionType !== null) {
    return {
      classification: "subscription",
      reason: "first-party subscription with no API credential source",
    };
  }
  return {
    classification: "ambiguous",
    reason: "subscription provenance could not be established",
  };
}

export function verifyPrecedenceControl(positive: AuthSnapshot, negative: AuthSnapshot) {
  return {
    pass:
      classifyAuthProvenance(positive).classification === "subscription" &&
      classifyAuthProvenance(negative).classification === "api-key" &&
      negative.apiKeySource === "ANTHROPIC_API_KEY",
    observedSource: negative.apiKeySource,
  };
}
