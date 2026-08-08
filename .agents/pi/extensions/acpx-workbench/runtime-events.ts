import type { AcpRuntimeEvent } from "acpx/runtime";

export interface MutableUsage {
  input?: number;
  output?: number;
  cacheRead?: number;
  cacheWrite?: number;
  totalTokens?: number;
  cost?: { amount?: number; currency?: string };
}

export type EventRecord =
  | { category: "text"; mapped: true; text: string }
  | { category: "status"; mapped: boolean; tag: string | null }
  | {
      category: "tool_call";
      mapped: false;
      status: string | null;
      kind: string | null;
    };

export function mapRuntimeEvent(
  event: AcpRuntimeEvent,
  usage: MutableUsage = {},
): EventRecord {
  if (event.type === "text_delta") {
    return { category: "text", mapped: true, text: event.text };
  }
  if (event.type === "status") {
    const mapped = event.tag === "usage_update";
    if (mapped) {
      const breakdown = event.breakdown;
      if (breakdown?.inputTokens !== undefined) usage.input = breakdown.inputTokens;
      if (breakdown?.outputTokens !== undefined) usage.output = breakdown.outputTokens;
      if (breakdown?.cachedReadTokens !== undefined) usage.cacheRead = breakdown.cachedReadTokens;
      if (breakdown?.cachedWriteTokens !== undefined) usage.cacheWrite = breakdown.cachedWriteTokens;
      if (breakdown?.totalTokens !== undefined) usage.totalTokens = breakdown.totalTokens;
      if (event.cost) usage.cost = { ...event.cost };
    }
    return { category: "status", mapped, tag: event.tag ?? null };
  }
  if (event.type === "tool_call") {
    return {
      category: "tool_call",
      mapped: false,
      status: event.status ?? null,
      kind: event.kind ?? null,
    };
  }
  return { category: "status", mapped: false, tag: event.type };
}

export function createEventInventory(records: readonly EventRecord[]) {
  const text = records.filter((record) => record.category === "text").length;
  const statuses = records.filter(
    (record): record is Extract<EventRecord, { category: "status" }> =>
      record.category === "status",
  );
  const toolCalls = records.filter((record) => record.category === "tool_call").length;
  return {
    observed: { text, status: statuses.length, toolCall: toolCalls },
    mapped: {
      text,
      usageStatus: statuses.filter(
        (record) => record.mapped && record.tag === "usage_update",
      ).length,
    },
    unsupported: {
      statusTags: [
        ...new Set(
          statuses
            .filter((record) => !record.mapped)
            .map((record) => record.tag ?? "unknown"),
        ),
      ].sort(),
      toolCalls,
    },
  };
}
