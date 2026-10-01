// R&D Studio state: durable snapshot + scoped live run streams.

import { create } from "zustand";

import { getLabSnapshot, type LabRunResponse } from "../lib/api";
import type {
  Event,
  LabRunCancelledPayload,
  LabRunCompletedPayload,
  LabRunFailedPayload,
  LabRunStartedPayload,
  LabTextDeltaPayload,
  LabTurnCompletedPayload,
  LabTurnStartedPayload,
} from "../lib/events";
import type { LabSnapshot, LabView, LiveRun, LiveTurn } from "./types";
import { currentView, writeViewToUrl } from "./navigation";

const EMPTY: LabSnapshot = {
  departments: [],
  agents: [],
  projects: [],
  tasks: [],
  results: [],
  findings: [],
  meetings: [],
  meeting_messages: [],
  runs: [],
  activities: [],
};

interface LabState {
  view: LabView;
  snapshot: LabSnapshot;
  liveRuns: Record<string, LiveRun>;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  selectedDepartmentId: string | null;
  selectedAgentId: string | null;
  selectedProjectId: string | null;
  selectedTaskId: string | null;
  selectedMeetingId: string | null;
  setView: (view: LabView) => void;
  restoreView: (view: LabView) => void;
  selectDepartment: (id: string | null) => void;
  selectAgent: (id: string | null) => void;
  selectProject: (id: string | null) => void;
  selectTask: (id: string | null) => void;
  selectMeeting: (id: string | null) => void;
  load: () => Promise<void>;
  refresh: () => Promise<void>;
  registerRun: (response: LabRunResponse) => void;
  applyEvent: (event: Event) => void;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "Could not load the R&D Studio.";
}

function initialRun(payload: LabRunStartedPayload, status = "running"): LiveRun {
  return {
    run_id: payload.run_id,
    task_id: payload.task_id ?? null,
    meeting_id: payload.meeting_id ?? null,
    status,
    turns: [],
    error: null,
    started_at: new Date().toISOString(),
  };
}

/** Make transient socket state converge on SQLite after a missed frame or reconnect. */
function reconcileLiveRuns(
  snapshot: LabSnapshot,
  current: Record<string, LiveRun>,
): Record<string, LiveRun> {
  const next = { ...current };
  let changed = false;

  for (const durable of snapshot.runs) {
    const existing = next[durable.id];
    if (existing) {
      const error = durable.error ?? null;
      if (existing.status !== durable.status || existing.error !== error) {
        next[durable.id] = { ...existing, status: durable.status, error };
        changed = true;
      }
    } else if (durable.status === "running") {
      next[durable.id] = {
        run_id: durable.id,
        task_id: durable.task_id,
        meeting_id: durable.meeting_id,
        status: durable.status,
        turns: [],
        error: durable.error ?? null,
        started_at: durable.started_at ?? new Date().toISOString(),
      };
      changed = true;
    }
  }

  return changed ? next : current;
}

function lastMatchingTurn(turns: LiveTurn[], predicate: (turn: LiveTurn) => boolean): number {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    if (predicate(turns[index])) return index;
  }
  return -1;
}

function upsertTurn(run: LiveRun, payload: LabTextDeltaPayload): LiveRun {
  const turns = run.turns.slice();
  let index = payload.turn_id ? turns.findIndex((turn) => turn.id === payload.turn_id) : -1;
  if (index < 0) {
    index = lastMatchingTurn(
      turns,
      (turn) => !turn.complete && turn.agent_id === (payload.agent_id ?? null),
    );
  }
  if (index < 0) {
    turns.push({
      id: payload.turn_id ?? crypto.randomUUID(),
      agent_id: payload.agent_id ?? null,
      text: payload.text,
      complete: false,
    });
  } else {
    const turn = turns[index];
    turns[index] = { ...turn, text: turn.text + payload.text };
  }
  return { ...run, status: "running", turns };
}

function beginTurn(run: LiveRun, payload: LabTurnStartedPayload): LiveRun {
  const turn: LiveTurn = {
    id: payload.turn_id ?? crypto.randomUUID(),
    agent_id: payload.agent_id ?? null,
    text: "",
    complete: false,
  };
  return { ...run, status: "running", turns: [...run.turns, turn] };
}

function finishTurn(run: LiveRun, payload: LabTurnCompletedPayload): LiveRun {
  const turns = run.turns.slice();
  let index = payload.turn_id ? turns.findIndex((turn) => turn.id === payload.turn_id) : -1;
  if (index < 0) index = lastMatchingTurn(turns, (turn) => !turn.complete);
  if (index >= 0) turns[index] = { ...turns[index], complete: true };
  return { ...run, turns };
}

export const useLabStore = create<LabState>((set, get) => ({
  view: currentView(),
  snapshot: EMPTY,
  liveRuns: {},
  loading: true,
  refreshing: false,
  error: null,
  selectedDepartmentId: null,
  selectedAgentId: null,
  selectedProjectId: null,
  selectedTaskId: null,
  selectedMeetingId: null,

  setView: (view) => {
    writeViewToUrl(view);
    set({ view });
  },
  restoreView: (view) => set({ view }),
  selectDepartment: (id) => set({ selectedDepartmentId: id, selectedAgentId: null }),
  selectAgent: (id) =>
    set((state) => {
      const agent = state.snapshot.agents.find((item) => item.id === id);
      return {
        selectedAgentId: id,
        selectedDepartmentId: agent?.department_id ?? state.selectedDepartmentId,
      };
    }),
  selectProject: (id) => set({ selectedProjectId: id, selectedTaskId: null }),
  selectTask: (id) =>
    set((state) => {
      const task = state.snapshot.tasks.find((item) => item.id === id);
      return { selectedTaskId: id, selectedProjectId: task?.project_id ?? state.selectedProjectId };
    }),
  selectMeeting: (id) => set({ selectedMeetingId: id }),

  load: async () => {
    set({ loading: true, error: null });
    try {
      const snapshot = await getLabSnapshot();
      set((state) => ({
        snapshot,
        liveRuns: reconcileLiveRuns(snapshot, state.liveRuns),
        loading: false,
        selectedDepartmentId:
          state.selectedDepartmentId ?? snapshot.departments[0]?.id ?? null,
        selectedProjectId: state.selectedProjectId ?? snapshot.projects[0]?.id ?? null,
        selectedMeetingId: state.selectedMeetingId ?? snapshot.meetings[0]?.id ?? null,
      }));
    } catch (error) {
      set({ loading: false, error: message(error) });
    }
  },

  refresh: async () => {
    set({ refreshing: true });
    try {
      const snapshot = await getLabSnapshot();
      set((state) => ({
        snapshot,
        liveRuns: reconcileLiveRuns(snapshot, state.liveRuns),
        refreshing: false,
        error: null,
      }));
    } catch (error) {
      set({ refreshing: false, error: message(error) });
    }
  },

  registerRun: (response) =>
    set((state) => {
      // A very fast mock/provider can publish the first socket event before the POST
      // response reaches the browser. Preserve that already-streaming run instead of
      // replacing its turns with a fresh empty placeholder.
      if (state.liveRuns[response.run_id]) return {};
      const payload: LabRunStartedPayload = {
        run_id: response.run_id,
        task_id: response.task_id,
        meeting_id: response.meeting_id,
      };
      return {
        liveRuns: {
          ...state.liveRuns,
          [response.run_id]: initialRun(payload, response.status || "queued"),
        },
      };
    }),

  applyEvent: (event) => {
    if (!event.event.startsWith("lab_")) return;
    const raw = event.payload as Record<string, unknown>;
    const runId = typeof raw.run_id === "string" ? raw.run_id : "";
    if (!runId) return;

    set((state) => {
      const address = event.payload as unknown as LabRunStartedPayload;
      const existing = state.liveRuns[runId] ?? initialRun(address);
      let next = existing;

      switch (event.event) {
        case "lab_run_started":
        case "lab_meeting_started":
          next = { ...existing, status: "running", error: null };
          break;
        case "lab_turn_started":
          next = beginTurn(existing, event.payload as unknown as LabTurnStartedPayload);
          break;
        case "lab_text_delta":
        case "lab_token_stream":
          next = upsertTurn(existing, event.payload as unknown as LabTextDeltaPayload);
          break;
        case "lab_turn_completed":
          next = finishTurn(existing, event.payload as unknown as LabTurnCompletedPayload);
          break;
        case "lab_run_completed": {
          const payload = event.payload as unknown as LabRunCompletedPayload;
          next = { ...existing, status: payload.status ?? "completed", error: null };
          break;
        }
        case "lab_run_cancelled": {
          const payload = event.payload as unknown as LabRunCancelledPayload;
          next = { ...existing, status: "cancelled", error: payload.message ?? null };
          break;
        }
        case "lab_run_failed": {
          const payload = event.payload as unknown as LabRunFailedPayload;
          next = { ...existing, status: "failed", error: payload.error ?? payload.message ?? "Run failed" };
          break;
        }
        default:
          return {};
      }
      return { liveRuns: { ...state.liveRuns, [runId]: next } };
    });

    if (["lab_run_completed", "lab_run_cancelled", "lab_run_failed", "lab_result_created", "lab_finding_created", "lab_meeting_message"].includes(event.event)) {
      window.setTimeout(() => void get().refresh(), 150);
    }
  },
}));
