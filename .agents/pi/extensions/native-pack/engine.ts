import fs from "node:fs";
import path from "node:path";

import { applyPackEvent, createPackState } from "./state.ts";
import type {
  AggregateSubmission,
  Approval,
  BeadRecord,
  BeadSubmission,
  CandidateSubject,
  DockerCleanupReceipt,
  FocusRole,
  GateEvidence,
  GateResult,
  NativePackPacket,
  NativePackProfile,
  PackEvent,
  PackPhase,
  PackState,
  PreflightSubmission,
  ReviewSubmission,
} from "./types.ts";

export interface NativePackHost {
  validateLinkedWorktree(worktree: string, repository?: string): Promise<void>;
  loadBead(beadId: string): Promise<BeadRecord>;
  claimBeads(beadIds: string[]): Promise<void>;
  currentHead(): Promise<string>;
  assertClean(): Promise<void>;
  candidateSubject(baseSha: string): Promise<CandidateSubject>;
  assertCandidate(candidateSha: string): Promise<void>;
  runGate(argv: string[]): Promise<GateResult>;
  cleanupEphemeralDocker(beadIds: string[]): Promise<DockerCleanupReceipt>;
  commitBead(beadId: string): Promise<string>;
}

export interface NativePackSessions {
  preflight(lane: FocusRole, packet: NativePackPacket, beads: BeadRecord[]): Promise<PreflightSubmission>;
  implement(beadId: string, bead: BeadRecord, approval: Approval): Promise<BeadSubmission>;
  repair(beadId: string, findings: ReviewSubmission[]): Promise<BeadSubmission>;
  releaseImplementer(beadId: string): Promise<void>;
  review(lane: FocusRole, beadId: string, candidateSha: string, diffRange: string): Promise<ReviewSubmission>;
  aggregate(lane: FocusRole, candidateSha: string, diffRange: string, commits: Array<{ beadId: string; sha: string }>): Promise<AggregateSubmission>;
  dispose(): Promise<void>;
}

function writeJsonAtomic(filePath: string, value: unknown): void {
  const temporary = `${filePath}.tmp-${process.pid}`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  fs.renameSync(temporary, filePath);
}

export class NativePackEngine {
  readonly profile: NativePackProfile;
  readonly host: NativePackHost;
  readonly sessions: NativePackSessions;
  readonly artifactsDir: string;
  readonly runId: string;
  state!: PackState;
  packet!: NativePackPacket;
  beads: BeadRecord[] = [];
  private journalPath: string;
  private aborted = false;

  constructor(profile: NativePackProfile, host: NativePackHost, sessions: NativePackSessions, artifactsDir: string, runId: string) {
    this.profile = profile;
    this.host = host;
    this.sessions = sessions;
    this.artifactsDir = artifactsDir;
    this.runId = runId;
    this.journalPath = path.join(artifactsDir, "lifecycle.jsonl");
    fs.mkdirSync(artifactsDir, { recursive: true, mode: 0o700 });
  }

  private persist(): void {
    writeJsonAtomic(path.join(this.artifactsDir, "state.json"), this.state);
  }

  private emit(input: Omit<PackEvent, "schema" | "sequence" | "runId">): void {
    const event: PackEvent = {
      schema: "cognovis.pi.native-pack-event.v1",
      sequence: this.state.lastSequence + 1,
      runId: this.runId,
      ...input,
    };
    fs.appendFileSync(this.journalPath, `${JSON.stringify(event)}\n`, { encoding: "utf8", mode: 0o600 });
    this.state = applyPackEvent(this.state, event);
    this.persist();
  }

  private phase(phase: PackPhase): void {
    this.emit({ type: "phase", phase });
  }

  private persistGate(result: GateResult, evidence: Omit<GateEvidence, keyof GateResult | "completedAt">, index: number): void {
    const directory = path.join(this.artifactsDir, "gates");
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    const bead = evidence.beadId ? `-${evidence.beadId.replace(/[^A-Za-z0-9_.-]/g, "_")}` : "";
    const turn = evidence.reviewTurn ? `-turn-${evidence.reviewTurn}` : "";
    writeJsonAtomic(path.join(directory, `${evidence.scope}${bead}${turn}-${index}.json`), {
      ...result,
      ...evidence,
      completedAt: new Date().toISOString(),
    } satisfies GateEvidence);
  }

  private gateFailure(label: string, result: GateResult): Error {
    const diagnostic = result.output.trim().slice(-2_000);
    return new Error(`${label}: ${result.argv.join(" ")}${diagnostic ? `\n${diagnostic}` : ""}`);
  }

  private validateBeadSubmission(submission: BeadSubmission, beadId: string, label: string): void {
    if (submission.beadId !== beadId) throw new Error(`${label} submission Bead mismatch: ${submission.beadId}`);
    if (!submission.summary?.trim()) throw new Error(`${label} submission summary is empty`);
    if (!Array.isArray(submission.evidence) || submission.evidence.length === 0 || submission.evidence.some((entry) => !entry.trim())) {
      throw new Error(`${label} submission evidence is empty or invalid`);
    }
  }

  private ensureActive(): void {
    if (this.aborted || this.state?.phase === "aborted") throw new Error("Native Pack aborted");
  }

  recordActivity(role: string, activity: string): void {
    if (!this.state || ["delivery_ready", "failed", "aborted"].includes(this.state.phase)) return;
    this.state.activeRole = role;
    this.state.activity = activity.replace(/\s+/g, " ").slice(-240);
    this.persist();
  }

  async preflight(packet: NativePackPacket): Promise<PackState> {
    if (packet.schema !== "cognovis.pi.native-pack-packet.v1") throw new Error("Unsupported Native Pack packet schema");
    if (!packet.id || !packet.repository || !packet.worktree) throw new Error("Native Pack identity, repository, and worktree are required");
    if (packet.beadIds.length < 2 || packet.beadIds.length > this.profile.maxPackSize) throw new Error(`Native Pack requires 2-${this.profile.maxPackSize} Beads`);
    if (new Set(packet.beadIds).size !== packet.beadIds.length) throw new Error("Native Pack Beads must be unique");
    this.packet = { ...packet, beadIds: [...packet.beadIds] };
    try {
      await this.host.validateLinkedWorktree(packet.worktree, packet.repository);
      this.ensureActive();
      await this.host.assertClean();
      this.ensureActive();
      const baseSha = await this.host.currentHead();
      this.ensureActive();
      this.state = createPackState(this.profile, packet, this.runId, baseSha, this.artifactsDir);
      writeJsonAtomic(path.join(this.artifactsDir, "pack.json"), packet);
      this.persist();
      this.phase("preflight");
      this.beads = await Promise.all(packet.beadIds.map((beadId) => this.host.loadBead(beadId)));
      this.ensureActive();
      const invalid = this.beads.find((bead) => !["open", "in_progress"].includes(bead.status));
      if (invalid) throw new Error(`Bead ${invalid.id} is not executable: ${invalid.status}`);
      const preflight = await Promise.all(this.profile.preflight.map((lane) => this.sessions.preflight(lane, packet, this.beads)));
      this.ensureActive();
      this.state.preflight = preflight;
      const expected = new Set(this.profile.preflight.map((lane) => lane.id));
      if (this.state.preflight.some((result) => !expected.delete(result.laneId)) || expected.size) throw new Error("Preflight lanes are incomplete or duplicated");
      this.persist();
      this.phase("awaiting_approval");
      return this.state;
    } catch (error) {
      if (!this.aborted && this.state && this.state.phase !== "failed") this.emit({ type: "error", error: error instanceof Error ? error.message : String(error) });
      await this.sessions.dispose();
      throw error;
    }
  }

  async approveAndRun(approval: Approval): Promise<PackState> {
    if (!this.state || this.state.phase !== "awaiting_approval") throw new Error("Native Pack is not awaiting approval");
    if (!approval.approvedBy.trim()) throw new Error("Approval requires an operator identity");
    this.state.approval = approval;
    writeJsonAtomic(path.join(this.artifactsDir, "approval.json"), approval);
    this.persist();
    this.phase("approved");
    try {
      this.ensureActive();
      await this.host.claimBeads(this.packet.beadIds);
      this.ensureActive();
      for (const bead of this.beads) {
        this.ensureActive();
        await this.runBead(bead, approval);
      }
      this.ensureActive();
      this.phase("pack_gates");
      for (const [index, argv] of this.profile.packGates.entries()) {
        this.ensureActive();
        const result = await this.host.runGate(argv);
        const candidateSha = await this.host.currentHead();
        this.persistGate(result, { scope: "pack", candidateSha }, index + 1);
        if (result.exitCode !== 0) throw this.gateFailure("Pack gate failed", result);
      }
      this.ensureActive();
      await this.host.assertClean();
      const finalSha = await this.host.currentHead();
      const diffRange = `${this.state.baseSha}..${finalSha}`;
      this.phase("aggregate_review");
      const commits = this.state.beads.map((bead) => ({ beadId: bead.id, sha: bead.commitSha! }));
      const reviews = await Promise.all(this.profile.aggregateReviewers.map((lane) => this.sessions.aggregate(lane, finalSha, diffRange, commits)));
      this.ensureActive();
      this.validateReviews(this.profile.aggregateReviewers, reviews, finalSha, "aggregate");
      if (reviews.some((review) => review.decision === "blocking" || review.findings.some((finding) => finding.severity === "blocking"))) {
        throw new Error("Aggregate review reported blocking findings");
      }
      await this.host.assertCandidate(finalSha);
      await this.host.assertClean();
      this.state.aggregateReviews = reviews;
      this.persist();
      this.phase("runtime_cleanup");
      const runtimeCleanup = await this.host.cleanupEphemeralDocker(this.packet.beadIds);
      this.emit({ type: "cleanup", runtimeCleanup });
      this.ensureActive();
      this.phase("delivery_ready");
      await this.sessions.dispose();
      return this.state;
    } catch (error) {
      if (!this.aborted) {
        const message = error instanceof Error ? error.message : String(error);
        this.emit({ type: "error", error: message });
      }
      await this.sessions.dispose();
      throw error;
    }
  }

  private async runBead(bead: BeadRecord, approval: Approval): Promise<void> {
    this.ensureActive();
    this.phase("bead_running");
    this.emit({ type: "bead", beadId: bead.id, beadStatus: "implementing" });
    const implementation = await this.sessions.implement(bead.id, bead, approval);
    this.ensureActive();
    this.validateBeadSubmission(implementation, bead.id, "Implementer");
    const beadBase = await this.host.currentHead();
    for (let turn = 1; turn <= this.profile.maxReviewTurns; turn++) {
      this.ensureActive();
      const state = this.state.beads.find((entry) => entry.id === bead.id)!;
      state.reviewTurn = turn;
      this.persist();
      for (const [index, argv] of this.profile.beadGates.entries()) {
        const result = await this.host.runGate(argv);
        const gateSubject = await this.host.candidateSubject(beadBase);
        this.persistGate(result, { scope: "bead", beadId: bead.id, reviewTurn: turn, candidateSha: gateSubject.candidateSha }, index + 1);
        if (result.exitCode !== 0) throw this.gateFailure(`Bead gate failed for ${bead.id}`, result);
      }
      this.ensureActive();
      const subject = await this.host.candidateSubject(beadBase);
      this.phase("bead_review");
      this.emit({ type: "bead", beadId: bead.id, beadStatus: "reviewing" });
      const reviews = await Promise.all(this.profile.beadReviewers.map((lane) => this.sessions.review(lane, bead.id, subject.candidateSha, subject.diffRange)));
      this.ensureActive();
      this.validateReviews(this.profile.beadReviewers, reviews, subject.candidateSha, `Bead ${bead.id}`);
      await this.host.assertCandidate(subject.candidateSha);
      const blocking = reviews.filter((review) => review.decision === "blocking" || review.findings.some((finding) => finding.severity === "blocking"));
      if (blocking.length === 0) {
        this.ensureActive();
        const commitSha = await this.host.commitBead(bead.id);
        this.emit({ type: "bead", beadId: bead.id, beadStatus: "committed", commitSha });
        await this.sessions.releaseImplementer(bead.id);
        return;
      }
      if (turn === this.profile.maxReviewTurns) throw new Error(`Review budget exhausted for ${bead.id}`);
      this.emit({ type: "bead", beadId: bead.id, beadStatus: "implementing" });
      const repair = await this.sessions.repair(bead.id, blocking);
      this.ensureActive();
      this.validateBeadSubmission(repair, bead.id, "Repair");
    }
  }

  private validateReviews(lanes: FocusRole[], reviews: ReviewSubmission[], candidateSha: string, label: string): void {
    if (reviews.length !== lanes.length) throw new Error(`${label} review lane count mismatch`);
    for (const [index, review] of reviews.entries()) {
      const lane = lanes[index]!;
      if (review.laneId !== lane.id) throw new Error(`${label} review lane mismatch at ${index}: expected ${lane.id}, received ${review.laneId}`);
      if (review.candidateSha !== candidateSha) throw new Error(`${label} review candidate mismatch`);
      if (review.decision !== "clean" && review.decision !== "blocking") throw new Error(`${label} review decision is invalid: ${String(review.decision)}`);
      if (!Array.isArray(review.findings) || review.findings.some((finding) => finding.severity !== "blocking" && finding.severity !== "advisory")) {
        throw new Error(`${label} review finding severity is invalid`);
      }
    }
  }

  async abort(): Promise<void> {
    this.aborted = true;
    if (this.state && !["delivery_ready", "failed", "aborted"].includes(this.state.phase)) {
      this.phase("aborted");
    }
    await this.sessions.dispose();
  }
}
