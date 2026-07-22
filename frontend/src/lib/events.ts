// ─────────────────────────────────────────────────────────────────────────────
// events.ts — the TypeScript mirror of the backend's event envelope.
// READING ORDER: frontend #9
//
// WHAT THIS FILE DOES: describes, in types, the exact shape of every /ws message so
// the rest of the frontend gets autocomplete and compile-time safety when reading
// events. It is the counterpart to backend/app/events.py — keep the two in sync.
//
// WHY types for wire data: the browser receives raw JSON. Typing it here means a
// typo like `payload.txt` (instead of `text`) fails at compile time, not silently
// at runtime in front of the user.
// ─────────────────────────────────────────────────────────────────────────────

/** Who is speaking in the Conversation. Mirrors the backend role names. */
export type Role = "generator" | "researcher" | "critic" | "pm" | "mentor" | "system";

/** The app's two working phases plus idle. Drives phase-aware chrome. */
export type Phase = "idle" | "ideation" | "build";

/** The envelope every /ws frame uses. `P` is the payload type for a given event. */
export interface Event<P = Record<string, unknown>> {
  v: number;
  seq: number;
  ts: string;
  session_id: string | null;
  event: string;
  payload: P;
}

// --- Payload shapes, one per event we consume (PROMPT.md §7) ------------------

export interface HelloPayload {
  server_version: string;
  active_session: string | null;
}

export interface PhaseChangedPayload {
  phase: Phase;
}

export interface TurnStartedPayload {
  role: Role;
  round: number;
}

export interface TokenStreamPayload {
  role: Role;
  text: string;
}

export interface TurnCompletedPayload {
  role: Role;
  round: number;
  usage: { in: number; out: number };
}

export interface CostUpdatePayload {
  session_tokens_in: number;
  session_tokens_out: number;
  session_usd: number;
  day_usd: number;
}

export interface ErrorPayload {
  where: string;
  message: string;
  recoverable: boolean;
}

export interface AwaitingApprovalPayload {
  artifact_id: number;
  question: string;
}

export interface ApprovalResolvedPayload {
  artifact_id: number;
  decision: string;
  feedback?: string | null;
}

export interface ArtifactPayload {
  artifact_id: number;
  kind: "ideadoc" | "spec";
  version: number;
  content: unknown;
}

export interface BudgetExceededPayload {
  limit: number;
  used: number;
}

export interface WorkspaceCreatedPayload {
  workspace_id: string;
  path: string;
  slug: string;
}
