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
  CostUpdatePayload,
  Event,
  PhaseChangedPayload,
  Phase,
  Role,
  TokenStreamPayload,
  TurnStartedPayload,
} from "../lib/events";
import type { ConnectionStatus } from "../lib/ws";

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

interface AppState {
  status: ConnectionStatus;
  phase: Phase;
  mock: boolean;
  turns: Turn[];
  cost: Cost;

  // --- actions ---
  setStatus: (status: ConnectionStatus) => void;
  setMock: (mock: boolean) => void;
  clearConversation: () => void;
  applyEvent: (event: Event) => void;
}

const EMPTY_COST: Cost = { tokensIn: 0, tokensOut: 0, sessionUsd: 0, dayUsd: 0 };

export const useAppStore = create<AppState>((set) => ({
  status: "connecting",
  phase: "idle",
  mock: true,
  turns: [],
  cost: EMPTY_COST,

  setStatus: (status) => set({ status }),
  setMock: (mock) => set({ mock }),
  clearConversation: () => set({ turns: [], cost: EMPTY_COST }),

  applyEvent: (event) =>
    set((state) => {
      switch (event.event) {
        case "phase_changed": {
          const { phase } = event.payload as unknown as PhaseChangedPayload;
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
