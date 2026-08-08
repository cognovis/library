import type { DockerCleanupReceipt } from "../docker-lifecycle-guard/index.ts";

export type { DockerCleanupReceipt } from "../docker-lifecycle-guard/index.ts";

export type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

export type NativeRole = {
  id?: string;
  focus?: string;
  model: string;
  thinking: ThinkingLevel;
};

export type FocusRole = Required<Pick<NativeRole, "id" | "focus">> & Pick<NativeRole, "model" | "thinking">;

export type NativePackProfile = {
  schema: "cognovis.pi.native-pack-profile.v1";
  id: string;
  version: string;
  maxPackSize: number;
  maxReviewTurns: number;
  implementer: NativeRole;
  preflight: FocusRole[];
  beadReviewers: FocusRole[];
  aggregateReviewers: FocusRole[];
  beadGates: string[][];
  packGates: string[][];
};

export type NativePackPacket = {
  schema: "cognovis.pi.native-pack-packet.v1";
  id: string;
  repository: string;
  worktree: string;
  beadIds: string[];
};

export type BeadRecord = { id: string; title: string; status: string; body: string };
export type GateResult = { argv: string[]; exitCode: number; output: string; durationMs: number };
export type GateEvidence = GateResult & {
  scope: "bead" | "pack";
  beadId?: string;
  reviewTurn?: number;
  candidateSha: string;
  completedAt: string;
};
export type CandidateSubject = { candidateSha: string; diffRange: string };
export type ReviewFinding = { id: string; severity: "blocking" | "advisory"; summary: string };

export type PreflightSubmission = {
  laneId: string;
  seams: string[];
  questions: string[];
  risks: string[];
};

export type BeadSubmission = {
  beadId: string;
  summary: string;
  evidence: string[];
};

export type ReviewSubmission = {
  laneId: string;
  decision: "clean" | "blocking";
  candidateSha: string;
  findings: ReviewFinding[];
};

export type AggregateSubmission = ReviewSubmission;

export type Approval = {
  approvedBy: string;
  decisions: Array<{ question?: string; answer?: string }>;
};

export type PackPhase =
  | "created"
  | "preflight"
  | "awaiting_approval"
  | "approved"
  | "bead_running"
  | "bead_review"
  | "pack_gates"
  | "aggregate_review"
  | "runtime_cleanup"
  | "delivery_ready"
  | "failed"
  | "aborted";

export type BeadState = {
  id: string;
  status: "queued" | "implementing" | "reviewing" | "committed" | "failed";
  commitSha?: string;
  reviewTurn: number;
};

export type PackState = {
  schema: "cognovis.pi.native-pack-state.v1";
  runId: string;
  packId: string;
  phase: PackPhase;
  baseSha: string;
  artifactsDir: string;
  profileId: string;
  beads: BeadState[];
  preflight: PreflightSubmission[];
  approval?: Approval;
  activeBeadId?: string;
  activeRole?: string;
  activity?: string;
  aggregateReviews: AggregateSubmission[];
  runtimeCleanup?: DockerCleanupReceipt;
  lastSequence: number;
  error?: string;
};

export type PackEvent = {
  schema: "cognovis.pi.native-pack-event.v1";
  sequence: number;
  runId: string;
  type: "phase" | "bead" | "activity" | "cleanup" | "error";
  phase?: PackPhase;
  beadId?: string;
  beadStatus?: BeadState["status"];
  commitSha?: string;
  role?: string;
  activity?: string;
  runtimeCleanup?: DockerCleanupReceipt;
  error?: string;
};
