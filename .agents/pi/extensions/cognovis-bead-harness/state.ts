import type { BeadHarnessProfile } from "./profile.ts";

export const BEAD_HARNESS_UI_LENS_SCHEMA = "cognovis.pi.bead-harness-ui-lens.v1" as const;

export type LifecycleEvent = {
  schema: "cognovis.bead-harness-event.v2";
  sequence: number;
  bead_id: string;
  run_id: string;
  mode: string;
  phase: string;
  status: string;
  actor?: string;
  wave?: number;
  result?: string;
  subject?: { candidate_sha?: string; wave?: number };
  blocking_finding_ids?: string[];
  advisory_finding_ids?: string[];
  accepted_finding_ids?: string[];
  blocking_count?: number;
  advisory_count?: number;
  artifact_path?: string;
  artifact_sha256?: string;
  review_evidence_sha256?: string;
  terminal_reason?: string;
  session_close_state?: string;
};

type Lane = {
  label: string;
  model: string;
  status: string;
  result?: string;
  blockingFindings: string[];
  advisoryFindings: string[];
  evidencePath?: string;
  evidenceDigest?: string;
  wave?: number;
  candidateSha?: string;
  activity: string;
  activeSinceMs?: number;
  completedAtMs?: number;
};
export type HarnessView = {
  schema: typeof BEAD_HARNESS_UI_LENS_SCHEMA;
  beadId: string;
  mode: string;
  artifactsDir: string;
  profile: BeadHarnessProfile;
  lastSequence: number;
  runId?: string;
  wave: number;
  candidateSha?: string;
  lanes: Record<string, Lane>;
  reviewEvidenceDigest?: string;
  sessionClose: string;
  terminalReason?: string;
  startedAtMs: number;
};

function digest(value: unknown, label: string): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) throw new Error(`${label} is invalid`);
  return value;
}

function strings(value: unknown, label: string): string[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string" && item)) throw new Error(`${label} is invalid`);
  return [...value];
}

export function parseLifecycleEvent(line: string): LifecycleEvent {
  let value: unknown;
  try { value = JSON.parse(line); } catch { throw new Error("Lifecycle event is not JSON"); }
  if (!value || typeof value !== "object") throw new Error("Lifecycle event must be an object");
  const item = value as Record<string, unknown>;
  if (item.schema !== "cognovis.bead-harness-event.v2") throw new Error("Unsupported lifecycle event schema");
  if (!Number.isInteger(item.sequence) || Number(item.sequence) < 1) throw new Error("Lifecycle event sequence is invalid");
  for (const key of ["bead_id", "run_id", "mode", "phase", "status"]) if (typeof item[key] !== "string") throw new Error(`Lifecycle event ${key} is invalid`);
  digest(item.artifact_sha256, "Lifecycle artifact digest");
  digest(item.review_evidence_sha256, "Lifecycle review evidence digest");
  strings(item.blocking_finding_ids, "Lifecycle blocking findings");
  strings(item.advisory_finding_ids, "Lifecycle advisory findings");
  strings(item.accepted_finding_ids, "Lifecycle accepted findings");
  for (const key of ["blocking_count", "advisory_count"]) {
    if (item[key] !== undefined && (!Number.isInteger(item[key]) || Number(item[key]) < 0)) throw new Error(`Lifecycle ${key} is invalid`);
  }
  const phases = new Set(["implementation", "review-wave", "reviewer", "adjudication", "repair", "moc", "commit", "review-gate", "delivery"]);
  if (!phases.has(String(item.phase))) throw new Error(`Unsupported lifecycle phase: ${String(item.phase)}`);
  return item as LifecycleEvent;
}

function lane(label: string, model: string): Lane {
  return { label, model, status: "pending", blockingFindings: [], advisoryFindings: [], activity: "waiting" };
}

export function createHarnessView(
  profile: BeadHarnessProfile,
  beadId: string,
  artifactsDir: string,
  runId?: string,
  nowMs = Date.now(),
): HarnessView {
  const lanes: Record<string, Lane> = {
    implementer: lane("IMPLEMENTER", `${profile.implementer.harness}/${profile.implementer.model}`),
  };
  for (const reviewer of profile.reviewers) {
    const id = reviewer.id!;
    lanes[id] = lane(
      reviewer.perspective === "depth-failure" ? "DEPTH" : reviewer.perspective === "boundary-operator" ? "BOUNDARY" : "REVIEWER",
      `${reviewer.harness}/${reviewer.model}`,
    );
  }
  if (profile.adjudicator) {
    lanes.adjudicator = lane("ADJUDICATION", `${profile.adjudicator.harness}/${profile.adjudicator.model}`);
  }
  return {
    schema: BEAD_HARNESS_UI_LENS_SCHEMA,
    beadId,
    mode: profile.mode,
    artifactsDir,
    profile,
    lastSequence: 0,
    ...(runId ? { runId } : {}),
    wave: 0,
    lanes,
    sessionClose: "pending",
    startedAtMs: nowMs,
  };
}

export function replayLifecycle(
  profile: BeadHarnessProfile,
  beadId: string,
  artifactsDir: string,
  content: string,
  runId?: string,
  nowMs = Date.now(),
): HarnessView {
  let view = createHarnessView(profile, beadId, artifactsDir, runId, nowMs);
  for (const line of content.split("\n")) if (line.trim()) view = applyLifecycleEvent(view, parseLifecycleEvent(line));
  return view;
}

function transitionLane(target: Lane, status: string, activity: string, nowMs: number): void {
  if (status === "working" && target.status !== "working") {
    target.activeSinceMs = nowMs;
    delete target.completedAtMs;
  }
  if (["complete", "failed", "blocked"].includes(status)) target.completedAtMs = nowMs;
  target.status = status;
  target.activity = activity;
}

export function recordOwnerActivity(view: HarnessView, text: string, _nowMs = Date.now()): HarnessView {
  const next: HarnessView = structuredClone(view);
  const activity = text.split("\n").map((line) => line.trim()).filter(Boolean).at(-1);
  if (!activity) return next;
  const harness = activity.match(/^([A-Za-z0-9_-]+)\s*>/)?.[1];
  const roles = [
    ...next.profile.reviewers.map((reviewer) => ({ id: reviewer.id!, harness: reviewer.harness })),
    ...(next.profile.adjudicator ? [{ id: "adjudicator", harness: next.profile.adjudicator.harness }] : []),
  ];
  const activeRole = harness
    ? roles.find((role) => {
        if (role.harness !== harness) return false;
        if (next.lanes[role.id]?.status === "working") return true;
        return role.id === "adjudicator"
          && next.lanes.adjudicator?.status === "pending"
          && next.profile.reviewers.every((reviewer) => ["complete", "failed"].includes(next.lanes[reviewer.id!]!.status));
      })
    : undefined;
  const target = activeRole?.id ?? (next.lanes.implementer?.status === "working" ? "implementer" : undefined);
  if (target) next.lanes[target]!.activity = activity.slice(0, 80);
  return next;
}

export function applyLifecycleEvent(view: HarnessView, event: LifecycleEvent, nowMs = Date.now()): HarnessView {
  if (event.bead_id !== view.beadId) throw new Error("Lifecycle event has the wrong Bead binding");
  if (event.mode !== view.mode) throw new Error("Lifecycle event has the wrong profile mode");
  if (view.runId && event.run_id !== view.runId) throw new Error("Lifecycle event has the wrong run binding");
  if (event.sequence !== view.lastSequence + 1) throw new Error("Lifecycle event sequence is not contiguous");
  const next: HarnessView = structuredClone(view);
  next.lastSequence = event.sequence;
  next.runId = event.run_id;
  const eventWave = event.wave ?? event.subject?.wave;
  if (eventWave && eventWave < view.wave) throw new Error("Lifecycle event wave must be monotonic");
  if (eventWave) next.wave = eventWave;
  if (event.subject?.candidate_sha) {
    if (next.candidateSha && next.candidateSha !== event.subject.candidate_sha && (eventWave ?? view.wave) <= view.wave) {
      throw new Error("Lifecycle events do not use the same candidate subject");
    }
    next.candidateSha = event.subject.candidate_sha;
  }
  if (event.terminal_reason) next.terminalReason = event.terminal_reason;
  if (event.phase === "implementation") transitionLane(next.lanes.implementer!, event.status, `implementation ${event.status}`, nowMs);
  if (event.phase === "review-wave" && event.status === "working") {
    for (const reviewer of next.profile.reviewers) {
      transitionLane(next.lanes[reviewer.id!]!, "working", `review wave ${eventWave ?? next.wave}`, nowMs);
    }
  }
  if (event.phase === "reviewer") {
    if (!event.actor || !next.lanes[event.actor] || event.actor === "implementer" || event.actor === "adjudicator") {
      throw new Error(`Lifecycle event has unknown reviewer actor: ${event.actor ?? "missing"}`);
    }
    if (event.status === "complete" && (!event.artifact_path || !event.artifact_sha256)) {
      throw new Error("Completed reviewer event lacks artifact evidence");
    }
    if (event.status === "complete" && (!eventWave || !event.subject?.candidate_sha)) {
      throw new Error("Completed reviewer event lacks wave or candidate evidence");
    }
    if (event.artifact_path && next.profile.reviewers.some((reviewer) => reviewer.id !== event.actor && next.lanes[reviewer.id!]?.evidencePath === event.artifact_path)) {
      throw new Error("Reviewer artifact path is not unique");
    }
    const target = next.lanes[event.actor]!;
    transitionLane(target, event.status, `${event.phase} ${event.result ?? event.status}`, nowMs);
    if (event.result !== undefined) target.result = event.result;
    target.blockingFindings = [...(event.blocking_finding_ids ?? [])];
    target.advisoryFindings = [...(event.advisory_finding_ids ?? [])];
    if (event.blocking_count !== undefined && event.blocking_count !== target.blockingFindings.length) throw new Error("Reviewer blocking count does not match finding ids");
    if (event.advisory_count !== undefined && event.advisory_count !== target.advisoryFindings.length) throw new Error("Reviewer advisory count does not match finding ids");
    if (eventWave !== undefined) target.wave = eventWave;
    if (event.subject?.candidate_sha !== undefined) target.candidateSha = event.subject.candidate_sha;
    if (event.artifact_path !== undefined) target.evidencePath = event.artifact_path;
    if (event.artifact_sha256 !== undefined) target.evidenceDigest = event.artifact_sha256;
    if (
      next.lanes.adjudicator?.status === "pending"
      && next.profile.reviewers.every((reviewer) => ["complete", "failed"].includes(next.lanes[reviewer.id!]!.status))
    ) {
      next.lanes.adjudicator.activity = "awaiting adjudication decision";
    }
  }
  if (event.phase === "adjudication" && !next.lanes.adjudicator) throw new Error("Adjudication is not registered for this profile");
  if (event.phase === "adjudication" && next.lanes.adjudicator) {
    if (event.actor !== next.profile.adjudicator?.id) throw new Error("Adjudication actor does not match the registered adjudicator");
    if (event.artifact_path && next.profile.reviewers.some((reviewer) => next.lanes[reviewer.id!]?.evidencePath === event.artifact_path)) {
      throw new Error("Adjudication artifact reuses reviewer evidence");
    }
    if (event.artifact_sha256 && next.profile.reviewers.some((reviewer) => next.lanes[reviewer.id!]?.evidenceDigest === event.artifact_sha256)) {
      throw new Error("Adjudication digest reuses reviewer evidence");
    }
    if (event.result === "NOT_REQUIRED" && next.profile.reviewers.some((reviewer) => {
      const reviewerLane = next.lanes[reviewer.id!]!;
      return reviewerLane.blockingFindings.length > 0 || reviewerLane.advisoryFindings.length > 0;
    })) throw new Error("Adjudication cannot be not-required while findings exist");
    if (event.result !== "NOT_REQUIRED" && event.status === "complete" && (!event.artifact_path || !event.artifact_sha256)) {
      throw new Error("Completed adjudication event lacks artifact evidence");
    }
    transitionLane(next.lanes.adjudicator, event.status, event.result === "NOT_REQUIRED" ? "adjudication not required" : `adjudication ${event.status}`, nowMs);
    if (event.result !== undefined) next.lanes.adjudicator.result = event.result;
    next.lanes.adjudicator.blockingFindings = [...(event.accepted_finding_ids ?? [])];
    next.lanes.adjudicator.advisoryFindings = [...(event.advisory_finding_ids ?? [])];
    if (event.artifact_path !== undefined) next.lanes.adjudicator.evidencePath = event.artifact_path;
    if (event.artifact_sha256 !== undefined) next.lanes.adjudicator.evidenceDigest = event.artifact_sha256;
  }
  if (event.phase === "review-gate" && event.status === "complete" && event.review_evidence_sha256 !== undefined) {
    next.reviewEvidenceDigest = event.review_evidence_sha256;
  }
  if (event.phase === "delivery") next.sessionClose = event.session_close_state ?? event.status;
  return next;
}

function fit(value: string, width: number): string {
  return value.length <= width ? value : `${value.slice(0, Math.max(0, width - 1))}…`;
}

function elapsed(startMs: number | undefined, endMs: number): string {
  if (startMs === undefined) return "0s";
  const seconds = Math.max(0, Math.floor((endMs - startMs) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes}m${String(seconds % 60).padStart(2, "0")}s` : `${seconds}s`;
}

function laneLines(target: Lane, width: number, nowMs: number): string[] {
  const elapsedText = elapsed(target.activeSinceMs, target.completedAtMs ?? nowMs);
  const state = [target.status, target.result, `elapsed ${elapsedText}`].filter(Boolean).join(" · ");
  const evidence = target.evidenceDigest ? `evidence ${target.evidenceDigest.slice(0, 8)}` : "";
  const findings = [
    `${target.blockingFindings.length} blocker${target.blockingFindings.length === 1 ? "" : "s"}`,
    `${target.advisoryFindings.length} advisor${target.advisoryFindings.length === 1 ? "y" : "ies"}`,
    evidence,
  ].filter(Boolean).join(" · ");
  return [
    fit(`${target.label} · ${target.model}`, width),
    fit(`  ${state}`, width),
    fit(`  activity ${target.activity}`, width),
    fit(`  ${findings}`, width),
  ];
}

function validDigest(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

export function validateCompletedRun(
  view: HarnessView,
  state: Record<string, any>,
  gate?: Record<string, any>,
): void {
  if (view.schema !== BEAD_HARNESS_UI_LENS_SCHEMA) throw new Error("Unsupported Bead Harness UI lens schema");
  if (view.wave < 1) throw new Error("Bead Harness completed without a review wave");
  if (view.sessionClose !== "complete") throw new Error("Session Close is not complete");
  if (view.lanes.implementer?.status !== "complete") throw new Error("Implementer did not reach complete");
  for (const reviewer of view.profile.reviewers) {
    const target = view.lanes[reviewer.id!];
    if (!target || target.status !== "complete" || target.result === "SKIPPED") throw new Error(`Reviewer ${reviewer.id} did not complete`);
    if (!validDigest(target.evidenceDigest)) throw new Error(`Reviewer ${reviewer.id} lacks artifact evidence`);
    if (target.wave !== view.wave || target.candidateSha !== view.candidateSha) throw new Error(`Reviewer ${reviewer.id} evidence is stale`);
  }
  if (view.profile.adjudicator && view.lanes.adjudicator?.status !== "complete") throw new Error("Adjudication did not complete");
  if (
    state.contract !== "cognovis.bead-harness-run.v2"
    || state.bead_id !== view.beadId
    || state.run_id !== view.runId
    || state.preset?.mode !== view.mode
    || state.subject?.candidate_sha !== view.candidateSha
    || state.commit_sha !== view.candidateSha
  ) {
    throw new Error("Canonical harness state binding is invalid");
  }
  if (state.status !== "complete" || state.session_close_state !== "complete") throw new Error("Canonical harness state is not complete");
  if (!Array.isArray(state.events) || state.events.length !== view.lastSequence) throw new Error("Canonical event count does not match the rendered stream");
  if (state.terminal_reason || (state.accepted_findings?.length ?? 0) > 0) throw new Error("Canonical harness state still carries blocking work");
  const reportMap = state.review_results ?? {};
  const reportKeys = Object.keys(reportMap);
  const expectedReviewerIds = view.profile.reviewers.map((reviewer) => reviewer.id!);
  if (
    reportKeys.length !== expectedReviewerIds.length
    || reportKeys.some((id) => !expectedReviewerIds.includes(id))
    || expectedReviewerIds.some((id) => {
      const report = reportMap[id];
      const target = view.lanes[id];
      return !report
        || report.result === "SKIPPED"
        || report.result !== target?.result
        || report.subject?.candidate_sha !== view.candidateSha
        || report.subject?.wave !== view.wave
        || !validDigest(report.artifact?.sha256)
        || report.artifact.sha256 !== target?.evidenceDigest
        || !validDigest(report.normalized_sha256);
    })
  ) {
    throw new Error("Canonical final review wave lacks validated reviewer receipts");
  }
  const canonicalReviewers = Array.isArray(state.reviewers) ? state.reviewers : [];
  if (canonicalReviewers.length !== view.profile.reviewers.length || view.profile.reviewers.some((reviewer) => {
    const canonical = canonicalReviewers.find((item: any) => item.id === reviewer.id);
    return !canonical || typeof canonical.session !== "string" || !canonical.session;
  })) throw new Error("Canonical reviewer session bindings are missing");
  const lastAdjudication = Array.isArray(state.adjudication_history) ? state.adjudication_history.at(-1) : undefined;
  const registeredAdjudicator = state.adjudicator;
  if (view.profile.adjudicator && (
    !registeredAdjudicator
    || registeredAdjudicator.id !== view.profile.adjudicator.id
    || typeof registeredAdjudicator.session !== "string"
    || !registeredAdjudicator.session
    || canonicalReviewers.some((item: any) => item.session === registeredAdjudicator.session)
    || !lastAdjudication
    || lastAdjudication.wave !== view.wave
    || lastAdjudication.subject?.candidate_sha !== view.candidateSha
    || (lastAdjudication.status === "not_required" && view.profile.reviewers.some((reviewer) => view.lanes[reviewer.id!]!.blockingFindings.length > 0 || view.lanes[reviewer.id!]!.advisoryFindings.length > 0))
    || (lastAdjudication.status !== "not_required" && (
      lastAdjudication.adjudicator?.id !== registeredAdjudicator.id
      || lastAdjudication.adjudicator?.session !== registeredAdjudicator.session
      || !validDigest(lastAdjudication.artifact?.sha256)
      || lastAdjudication.artifact.sha256 !== view.lanes.adjudicator?.evidenceDigest
    ))
  )) {
    throw new Error("Canonical adjudication receipt is missing");
  }
  if (
    !gate
    || gate.contract !== "review_gate_v1"
    || gate.gate_kind !== "aggregate"
    || gate.candidate_sha !== view.candidateSha
    || gate.review_evidence?.contract !== "review_evidence_receipt_v1"
    || !validDigest(gate.review_evidence_sha256)
    || gate.review_evidence.history_sha256 !== gate.review_evidence_sha256
  ) {
    throw new Error("Canonical aggregate review evidence is missing or invalid");
  }
  if (!view.reviewEvidenceDigest) throw new Error("Lifecycle review evidence authorization is missing");
  if (view.reviewEvidenceDigest !== gate.review_evidence_sha256) {
    throw new Error("Lifecycle and aggregate review evidence digests differ");
  }
}

export function renderHarnessLines(view: HarnessView, width: number, nowMs = Date.now()): string[] {
  const safeWidth = Math.max(30, width);
  const lines = [fit(`COGNOVIS BEAD HARNESS · ${view.mode} · ${view.beadId} · wave ${view.wave}/${view.profile.maxReviewWaves} · elapsed ${elapsed(view.startedAtMs, nowMs)}`, safeWidth)];
  const ordered = Object.values(view.lanes);
  if (safeWidth >= 100 && ordered.length > 1) {
    const leftWidth = Math.floor((safeWidth - 3) / 2);
    for (let index = 0; index < ordered.length; index += 2) {
      const left = laneLines(ordered[index]!, leftWidth, nowMs);
      const right = ordered[index + 1] ? laneLines(ordered[index + 1]!, leftWidth, nowMs) : ["", "", "", ""];
      for (let line = 0; line < left.length; line += 1) {
        lines.push(`${left[line]!.padEnd(leftWidth)} │ ${right[line]!}`.slice(0, safeWidth));
      }
    }
  } else {
    for (const target of ordered) lines.push(...laneLines(target, safeWidth, nowMs));
  }
  lines.push(fit(`Session Close ${view.sessionClose}${view.terminalReason ? ` · ${view.terminalReason}` : ""}`, safeWidth));
  if (view.reviewEvidenceDigest) lines.push(fit(`review evidence ${view.reviewEvidenceDigest.slice(0, 12)}`, safeWidth));
  lines.push(fit(`artifacts: ${view.artifactsDir}`, safeWidth));
  return lines;
}
