import type { NativePackPacket, NativePackProfile, PackEvent, PackState } from "./types.ts";

export function createPackState(
  profile: NativePackProfile,
  packet: NativePackPacket,
  runId: string,
  baseSha: string,
  artifactsDir: string,
): PackState {
  return {
    schema: "cognovis.pi.native-pack-state.v1",
    runId,
    packId: packet.id,
    phase: "created",
    baseSha,
    artifactsDir,
    profileId: profile.id,
    beads: packet.beadIds.map((id) => ({ id, status: "queued", reviewTurn: 0 })),
    preflight: [],
    aggregateReviews: [],
    lastSequence: 0,
  };
}

export function applyPackEvent(state: PackState, event: PackEvent): PackState {
  if (event.schema !== "cognovis.pi.native-pack-event.v1") throw new Error("Unsupported Native Pack event schema");
  if (event.runId !== state.runId) throw new Error("Native Pack event run binding mismatch");
  if (event.sequence !== state.lastSequence + 1) throw new Error("Native Pack event sequence mismatch");
  const next: PackState = { ...state, beads: state.beads.map((bead) => ({ ...bead })), lastSequence: event.sequence };
  if (event.type === "phase" && event.phase) next.phase = event.phase;
  if (event.type === "bead" && event.beadId && event.beadStatus) {
    const bead = next.beads.find((entry) => entry.id === event.beadId);
    if (!bead) throw new Error(`Unknown Native Pack Bead: ${event.beadId}`);
    bead.status = event.beadStatus;
    if (event.commitSha) bead.commitSha = event.commitSha;
    if (event.beadStatus === "committed") delete next.activeBeadId;
    else next.activeBeadId = event.beadId;
  }
  if (event.type === "activity") {
    if (event.role !== undefined) next.activeRole = event.role;
    if (event.activity !== undefined) next.activity = event.activity;
  }
  if (event.type === "cleanup") {
    if (!event.runtimeCleanup) throw new Error("Native Pack cleanup event lacks its typed receipt");
    next.runtimeCleanup = event.runtimeCleanup;
  }
  if (event.type === "error") {
    next.phase = "failed";
    next.error = event.error ?? "Native Pack failed";
  }
  return next;
}

export function replayPackEvents(
  profile: NativePackProfile,
  packet: NativePackPacket,
  journal: string,
  baseSha: string,
  artifactsDir: string,
): PackState {
  const lines = journal.split("\n").filter((line) => line.trim());
  const first = lines[0] ? JSON.parse(lines[0]) as Partial<PackEvent> : undefined;
  const runId = first?.runId ?? "unbound";
  let state = createPackState(profile, packet, runId, baseSha, artifactsDir);
  for (const line of lines) state = applyPackEvent(state, JSON.parse(line) as PackEvent);
  return state;
}

function clip(text: string, width: number): string {
  if (width <= 0) return "";
  if (text.length <= width) return text;
  return width === 1 ? "…" : `${text.slice(0, width - 1)}…`;
}

export function renderPackLines(state: PackState, width: number, maxVisibleBeads = 8): string[] {
  const total = state.beads.length;
  const complete = state.beads.filter((bead) => bead.status === "committed").length;
  const selected = state.beads.length <= maxVisibleBeads
    ? state.beads
    : [...new Set([...state.beads.slice(0, maxVisibleBeads - 1), state.beads.find((bead) => bead.id === state.activeBeadId)].filter(Boolean))]
        .slice(0, maxVisibleBeads) as typeof state.beads;
  const lines = [
    `PACK ${state.packId}  ${state.phase.toUpperCase()}  ${complete}/${total} Beads`,
    `base ${state.baseSha.slice(0, 7)} | profile ${state.profileId} | run ${state.runId}`,
    "",
    ...selected.map((bead) => {
      const active = bead.id === state.activeBeadId ? ">" : " ";
      const commit = bead.commitSha ? ` ${bead.commitSha.slice(0, 7)}` : "";
      return `${active} ${bead.id.padEnd(18)} ${bead.status.toUpperCase()}${commit}`;
    }),
    ...(state.beads.length > selected.length ? [`  … ${state.beads.length - selected.length} Beads hidden; use /pack-details`] : []),
    `  PACK GATES         ${state.phase === "pack_gates" ? "RUNNING" : ["aggregate_review", "runtime_cleanup", "delivery_ready"].includes(state.phase) ? "CLEAN" : "PENDING"}`,
    `  PACK REVIEW        ${state.phase === "aggregate_review" ? "RUNNING" : ["runtime_cleanup", "delivery_ready"].includes(state.phase) ? "CLEAN" : "PENDING"}`,
    `  RUNTIME CLEANUP    ${state.phase === "runtime_cleanup" ? "RUNNING" : state.runtimeCleanup ? state.runtimeCleanup.status.toUpperCase() : "PENDING"}`,
  ];
  if (state.activeRole || state.activity) lines.push(`  ${state.activeRole ?? "activity"}: ${state.activity ?? "working"}`);
  if (state.error) lines.push(`  ERROR: ${state.error.replace(/\s+/g, " ").trim()}`);
  return lines.map((line) => clip(line, Math.max(1, width)));
}
