// ─────────────────────────────────────────────────────────────────────────────
// appStore.ts — the single source of UI truth (zustand).
// READING ORDER: frontend #12
//
// WHAT THIS FILE DOES: holds everything the UI renders — connection status, phase,
// the list of conversation turns, and the cost meter — and exposes `applyEvent`,
// which translates one incoming /ws event into a state change.
//
// WHY zustand (not Redux/Context): it's a tiny store you read with a hook
// (`useAppStore(s => s.turns)`) and write with `set(...)`. No providers, no
// boilerplate — the whole store is this one readable file. `applyEvent` is the
// heart: a single switch that is the mirror image of the backend's event list.
// ─────────────────────────────────────────────────────────────────────────────

import { create } from "zustand";

import type {
  ArtifactPayload,
  AwaitingApprovalPayload,
  BudgetExceededPayload,
  CostUpdatePayload,
  ErrorPayload,
  Event,
  PhaseChangedPayload,
  Phase,
  Role,
  TokenStreamPayload,
  TurnStartedPayload,
} from "../lib/events";
import type { ConnectionStatus } from "../lib/ws";

/** A pending human decision at the approval gate. */
export interface ApprovalRequest {
  artifactId: number;
  question: string;
}

/** One bubble in the Conversation: a single crew (or mentor) turn. */
export interface Turn {
  id: string;
  role: Role;
  round: number;
  text: string;
  // True while tokens are still streaming in; false once the turn completes.
  streaming: boolean;
}

/** The running cost meter shown in the status bar. */
export interface Cost {
  tokensIn: number;
  tokensOut: number;
  sessionUsd: number;
  dayUsd: number;
}

/** One saved artifact version (IdeaDoc or Spec), for the Spec tab. */
export interface ArtifactRecord {
  id: number;
  kind: "ideadoc" | "spec";
  version: number;
  content: unknown;
}

/** The shape GET /api/sessions/{id} returns, used to restore a past session. */
export interface RestorePayload {
  session: { id: string; title: string; status: string; round: number };
  messages: { role: Role; content: string }[];
  artifacts: { id: number; kind: "ideadoc" | "spec"; version: number; content_json: string }[];
}

interface AppState {
  status: ConnectionStatus;
  phase: Phase;
  mock: boolean;
  turns: Turn[];
  cost: Cost;
  // The session currently in view — running OR restored. Used to signal approve/cancel
  // (while running) and to export. Kept across the return to idle so export still works.
  sessionId: string | null;
  // Set when the crew is waiting for the founder's decision; null otherwise.
  awaitingApproval: ApprovalRequest | null;
  // Every artifact version we've seen for the current session (for the Spec tab).
  artifacts: ArtifactRecord[];

  // --- actions ---
  setStatus: (status: ConnectionStatus) => void;
  setMock: (mock: boolean) => void;
  setSessionId: (id: string | null) => void;
  clearConversation: () => void;
  restoreSession: (payload: RestorePayload) => void;
  applyEvent: (event: Event) => void;
}

const EMPTY_COST: Cost = { tokensIn: 0, tokensOut: 0, sessionUsd: 0, dayUsd: 0 };

export const useAppStore = create<AppState>((set) => ({
  status: "connecting",
  phase: "idle",
  mock: true,
  turns: [],
  cost: EMPTY_COST,
  sessionId: null,
  awaitingApproval: null,
  artifacts: [],

  setStatus: (status) => set({ status }),
  setMock: (mock) => set({ mock }),
  setSessionId: (id) => set({ sessionId: id }),
  clearConversation: () =>
    set({ turns: [], cost: EMPTY_COST, awaitingApproval: null, artifacts: [], sessionId: null }),

  restoreSession: (payload) =>
    set({
      // Load a past session read-only: its turns, its artifacts, its id (for export).
      sessionId: payload.session.id,
      phase: "idle",
      awaitingApproval: null,
      cost: EMPTY_COST,
      turns: payload.messages.map((message) => ({
        id: crypto.randomUUID(),
        role: message.role,
        round: 0,
        text: message.content,
        streaming: false,
      })),
      artifacts: payload.artifacts.map((artifact) => ({
        id: artifact.id,
        kind: artifact.kind,
        version: artifact.version,
        // Stored as a JSON string in the DB; parse it back into an object here.
        content: JSON.parse(artifact.content_json),
      })),
    }),

  applyEvent: (event) =>
    set((state) => {
      switch (event.event) {
        case "phase_changed": {
          const { phase } = event.payload as unknown as PhaseChangedPayload;
          // Returning to idle means the session ended — lower the approval bar, but
          // keep sessionId so the finished session can still be exported.
          if (phase === "idle") {
            return { phase, awaitingApproval: null };
          }
          return { phase };
        }

        case "agent_turn_started": {
          // A new speaker begins — push a fresh, empty, streaming bubble.
          const { role, round } = event.payload as unknown as TurnStartedPayload;
          const turn: Turn = {
            id: crypto.randomUUID(),
            role,
            round,
            text: "",
            streaming: true,
          };
          return { turns: [...state.turns, turn] };
        }

        case "token_stream": {
          // Append the chunk to the most recent turn (turns arrive sequentially).
          const { text } = event.payload as unknown as TokenStreamPayload;
          return { turns: appendToLastTurn(state.turns, text) };
        }

        case "agent_turn_completed": {
          // Mark the most recent turn as no longer streaming.
          return { turns: markLastTurnDone(state.turns) };
        }

        case "cost_update": {
          const p = event.payload as unknown as CostUpdatePayload;
          return {
            cost: {
              tokensIn: p.session_tokens_in,
              tokensOut: p.session_tokens_out,
              sessionUsd: p.session_usd,
              dayUsd: p.day_usd,
            },
          };
        }

        case "awaiting_approval": {
          const p = event.payload as unknown as AwaitingApprovalPayload;
          return {
            // Remember which session to signal, and raise the approval bar.
            sessionId: event.session_id,
            awaitingApproval: { artifactId: p.artifact_id, question: p.question },
          };
        }

        case "approval_resolved":
          // The decision has been recorded; lower the approval bar.
          return { awaitingApproval: null };

        case "artifact_created":
        case "artifact_updated": {
          const p = event.payload as unknown as ArtifactPayload;
          // Accumulate every version so the Spec tab can offer a version switcher.
          const record: ArtifactRecord = {
            id: p.artifact_id,
            kind: p.kind,
            version: p.version,
            content: p.content,
          };
          return { artifacts: [...state.artifacts, record] };
        }

        case "error": {
          const p = event.payload as unknown as ErrorPayload;
          return { turns: appendSystemTurn(state.turns, `⚠️ ${p.message}`) };
        }

        case "budget_exceeded": {
          const p = event.payload as unknown as BudgetExceededPayload;
          const text = `⚠️ Budget stop: used ${p.used} tokens (limit ${p.limit}).`;
          return { turns: appendSystemTurn(state.turns, text) };
        }

        // hello / heartbeat / anything we don't render: no state change.
        default:
          return {};
      }
    }),
}));

/** Return a new turns array with `text` appended to the last turn. Pure (no mutation). */
function appendToLastTurn(turns: Turn[], text: string): Turn[] {
  if (turns.length === 0) return turns;
  const next = turns.slice();
  const last = next[next.length - 1];
  next[next.length - 1] = { ...last, text: last.text + text };
  return next;
}

/** Return a new turns array with the last turn marked done (streaming = false). */
function markLastTurnDone(turns: Turn[]): Turn[] {
  if (turns.length === 0) return turns;
  const next = turns.slice();
  const last = next[next.length - 1];
  next[next.length - 1] = { ...last, streaming: false };
  return next;
}

/** Append a non-streaming "system" bubble (used for errors and budget notices). */
function appendSystemTurn(turns: Turn[], text: string): Turn[] {
  const turn: Turn = {
    id: crypto.randomUUID(),
    role: "system",
    round: 0,
    text,
    streaming: false,
  };
  return [...turns, turn];
}
