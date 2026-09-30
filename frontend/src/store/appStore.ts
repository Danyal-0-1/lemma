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
  CheckFinishedPayload,
  CheckOutputPayload,
  CheckStartedPayload,
  CostUpdatePayload,
  ErrorPayload,
  Event,
  PhaseChangedPayload,
  Phase,
  Role,
  TokenStreamPayload,
  TurnStartedPayload,
  WorkspaceCreatedPayload,
} from "../lib/events";
import type { ConnectionStatus } from "../lib/ws";

/** The live state of one check run (for its badge + streamed output). */
export interface CheckRun {
  status: "running" | "pass" | "fail";
  output: string[];
  exitCode?: number;
}

/** A pending human decision at the approval gate. */
export interface ApprovalRequest {
  artifactId: number;
  question: string;
}

/** The build workspace currently in view (its id, on-disk path, and slug). */
export interface WorkspaceInfo {
  id: string;
  path: string;
  slug: string;
}

/** The review tabs available in the build phase. */
export type BuildTab = "diff" | "terminal" | "files" | "checks" | "spec";

/** A transient error notification shown top-right. */
export interface Toast {
  id: string;
  message: string;
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
  hostExecutionEnabled: boolean;
  turns: Turn[];
  cost: Cost;
  // The session currently in view — running OR restored. Used to signal approve/cancel
  // (while running) and to export. Kept across the return to idle so export still works.
  sessionId: string | null;
  // Set when the crew is waiting for the founder's decision; null otherwise.
  awaitingApproval: ApprovalRequest | null;
  // Every artifact version we've seen for the current session (for the Spec tab).
  artifacts: ArtifactRecord[];
  // The build workspace in view, or null when we're not in the build phase.
  activeWorkspace: WorkspaceInfo | null;
  // The active workspace's +/- diff totals (set by the Diff tab; shown in the sidebar).
  diffCounts: { additions: number; deletions: number } | null;
  // Per-check run state, keyed by check id (badge + streamed output).
  checkRuns: Record<string, CheckRun>;
  // What the active review tab is showing, attached to mentor questions as context.
  mentorContext: { label: string; content: string } | null;
  // Which build-phase review tab is showing (lifted here so shortcuts can switch it).
  buildTab: BuildTab;
  // Transient error notifications (top-right toasts).
  toasts: Toast[];

  // --- actions ---
  setStatus: (status: ConnectionStatus) => void;
  setMock: (mock: boolean) => void;
  setHostExecutionEnabled: (enabled: boolean) => void;
  setSessionId: (id: string | null) => void;
  setDiffCounts: (counts: { additions: number; deletions: number } | null) => void;
  setMentorContext: (context: { label: string; content: string } | null) => void;
  setBuildTab: (tab: BuildTab) => void;
  addUserTurn: (text: string) => void;
  pushToast: (message: string) => void;
  dismissToast: (id: string) => void;
  newSession: () => void;
  exitWorkspace: () => void;
  clearConversation: () => void;
  restoreSession: (payload: RestorePayload) => void;
  activateWorkspace: (workspace: WorkspaceInfo) => void;
  applyEvent: (event: Event) => void;
}

const EMPTY_COST: Cost = { tokensIn: 0, tokensOut: 0, sessionUsd: 0, dayUsd: 0 };

export const useAppStore = create<AppState>((set) => ({
  status: "connecting",
  phase: "idle",
  mock: true,
  hostExecutionEnabled: false,
  turns: [],
  cost: EMPTY_COST,
  sessionId: null,
  awaitingApproval: null,
  artifacts: [],
  activeWorkspace: null,
  diffCounts: null,
  checkRuns: {},
  mentorContext: null,
  buildTab: "diff",
  toasts: [],

  setStatus: (status) => set({ status }),
  setMock: (mock) => set({ mock }),
  setHostExecutionEnabled: (hostExecutionEnabled) => set({ hostExecutionEnabled }),
  setSessionId: (id) => set({ sessionId: id }),
  setDiffCounts: (counts) => set({ diffCounts: counts }),
  setMentorContext: (context) => set({ mentorContext: context }),
  setBuildTab: (tab) => set({ buildTab: tab }),
  addUserTurn: (text) => set((state) => ({ turns: appendTurn(state.turns, "user", text) })),
  pushToast: (message) =>
    set((state) => ({ toasts: [...state.toasts, { id: crypto.randomUUID(), message }] })),
  dismissToast: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
  // Cmd/Ctrl+N — drop everything back to a fresh idle state ready for a new seed.
  newSession: () =>
    set({
      turns: [],
      cost: EMPTY_COST,
      awaitingApproval: null,
      artifacts: [],
      sessionId: null,
      activeWorkspace: null,
      phase: "idle",
    }),
  // Leave the build phase (e.g. after archiving the active workspace).
  exitWorkspace: () => set({ activeWorkspace: null, phase: "idle" }),
  activateWorkspace: (workspace) =>
    // Switching workspaces resets the review state so we don't show stale diff/checks.
    set({
      activeWorkspace: workspace,
      phase: "build",
      buildTab: "diff",
      diffCounts: null,
      checkRuns: {},
    }),
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
          // Starting a new ideation run leaves the build phase (and its review state).
          if (phase === "ideation") {
            return { phase, activeWorkspace: null, diffCounts: null, checkRuns: {} };
          }
          return { phase }; // build
        }

        case "workspace_created": {
          const p = event.payload as unknown as WorkspaceCreatedPayload;
          return {
            activeWorkspace: { id: p.workspace_id, path: p.path, slug: p.slug },
            diffCounts: null,
            checkRuns: {},
          };
        }

        case "check_started": {
          const p = event.payload as unknown as CheckStartedPayload;
          return {
            checkRuns: { ...state.checkRuns, [p.check_id]: { status: "running", output: [] } },
          };
        }

        case "check_output": {
          const p = event.payload as unknown as CheckOutputPayload;
          const existing = state.checkRuns[p.check_id] ?? { status: "running", output: [] };
          return {
            checkRuns: {
              ...state.checkRuns,
              [p.check_id]: { ...existing, output: [...existing.output, p.line] },
            },
          };
        }

        case "check_finished": {
          const p = event.payload as unknown as CheckFinishedPayload;
          const existing = state.checkRuns[p.check_id] ?? { status: "running", output: [] };
          return {
            checkRuns: {
              ...state.checkRuns,
              [p.check_id]: {
                ...existing,
                status: p.exit_code === 0 ? "pass" : "fail",
                exitCode: p.exit_code,
              },
            },
          };
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

        case "cost_update":
        case "lab_cost_update": {
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
          // Errors go both to the feed (a system bubble) and a transient toast (§7).
          return {
            turns: appendTurn(state.turns, "system", `⚠️ ${p.message}`),
            toasts: [...state.toasts, { id: crypto.randomUUID(), message: p.message }],
          };
        }

        case "budget_exceeded": {
          const p = event.payload as unknown as BudgetExceededPayload;
          const text = `⚠️ Budget stop: used ${p.used} tokens (limit ${p.limit}).`;
          return { turns: appendTurn(state.turns, "system", text) };
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

/** Append a non-streaming bubble for the given role (system notices, user questions). */
function appendTurn(turns: Turn[], role: Role, text: string): Turn[] {
  const turn: Turn = { id: crypto.randomUUID(), role, round: 0, text, streaming: false };
  return [...turns, turn];
}
