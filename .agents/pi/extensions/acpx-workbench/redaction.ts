const SENSITIVE_KEY = /(?:api[_-]?key|authorization|cookie|credential|password|secret|token)/i;
const INLINE_SECRET_PATTERNS = [
  /\b(?:sk|sk-ant|sk-proj)-[A-Za-z0-9_-]{8,}\b/g,
  /\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b/gi,
  /\b(ANTHROPIC_(?:API_KEY|AUTH_TOKEN|OAUTH_TOKEN)\s*=\s*)[^\s"'`]+/gi,
  /\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)\s*=\s*)[^\s"'`]+/g,
] as const;

export interface RedactionOptions {
  canaries?: readonly string[];
}

export function redactText(value: string, options: RedactionOptions = {}): string {
  let redacted = value;
  for (const canary of options.canaries ?? []) {
    if (canary) redacted = redacted.replaceAll(canary, "[REDACTED]");
  }
  for (const pattern of INLINE_SECRET_PATTERNS) {
    pattern.lastIndex = 0;
    redacted = redacted.replace(pattern, (match, prefix?: string) =>
      prefix ? `${prefix}[REDACTED]` : "[REDACTED]",
    );
  }
  return redacted;
}

export function redactValue(
  value: unknown,
  options: RedactionOptions = {},
  key = "",
): unknown {
  const provenanceField = /(?:classification|present|source|stored)$/i.test(key);
  if (key && SENSITIVE_KEY.test(key) && !provenanceField) {
    if (typeof value === "boolean" || value === null) return value;
    return "[REDACTED]";
  }
  if (typeof value === "string") return redactText(value, options);
  if (Array.isArray(value)) return value.map((entry) => redactValue(entry, options));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([entryKey, entry]) => [
        entryKey,
        redactValue(entry, options, entryKey),
      ]),
    );
  }
  return value;
}

export function containsSecret(value: unknown, canaries: readonly string[] = []): boolean {
  const serialized = JSON.stringify(value).replaceAll("[REDACTED]", "");
  if (canaries.some((canary) => canary && serialized.includes(canary))) return true;
  return INLINE_SECRET_PATTERNS.some((pattern) => {
    pattern.lastIndex = 0;
    return pattern.test(serialized);
  });
}
