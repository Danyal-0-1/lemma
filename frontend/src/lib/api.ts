// ─────────────────────────────────────────────────────────────────────────────
// api.ts — tiny helpers for the backend's REST endpoints.
// READING ORDER: frontend #10
//
// WHAT THIS FILE DOES: centralizes the backend base URL and wraps the REST calls
// the UI makes. REST is for ACTIONS (do a thing); the WebSocket (ws.ts) is for
// STREAMS (watch things happen). Keeping that split is a core idea of the design.
//
// WHY one place for the base URL: the backend runs on :8000 and the frontend on
// :5173 during development. Defining the origin once here means no scattered
// hard-coded URLs to update later.
// ─────────────────────────────────────────────────────────────────────────────

/** The backend origin. In dev the frontend (:5173) calls the backend (:8000). */
export const BACKEND_ORIGIN = "http://127.0.0.1:8000";

/** The event-stream WebSocket URL, derived from the same origin. */
export const WS_URL = "ws://127.0.0.1:8000/ws";

/** What GET /health returns. Used to show the MOCK badge accurately. */
export interface Health {
  status: string;
  version: string;
  mock_llm: boolean;
}

/** Fetch backend health once at startup, e.g. to know whether we're in mock mode. */
export async function getHealth(): Promise<Health> {
  const response = await fetch(`${BACKEND_ORIGIN}/health`);
  if (!response.ok) {
    throw new Error(`health check failed: ${response.status}`);
  }
  return (await response.json()) as Health;
}

/** Trigger the scripted demo crew round (M1). The conversation streams in over /ws. */
export async function postDemo(): Promise<{ session_id: string }> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/demo`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`demo failed: ${response.status}`);
  }
  return (await response.json()) as { session_id: string };
}

/** Stream ONE real (or mock) Generator turn for a seed idea (M2). Streams over /ws. */
export async function postOneshot(seed?: string): Promise<{ session_id: string }> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/oneshot`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // Send the seed only if given; the backend has a sensible default otherwise.
    body: JSON.stringify(seed ? { seed } : {}),
  });
  if (!response.ok) {
    throw new Error(`oneshot failed: ${response.status}`);
  }
  return (await response.json()) as { session_id: string };
}

/** Start a full ideation crew session for a seed idea (M3). Streams over /ws. */
export async function postSession(seed: string): Promise<{ session_id: string }> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seed }),
  });
  if (!response.ok) {
    throw new Error(`start session failed: ${response.status}`);
  }
  return (await response.json()) as { session_id: string };
}

/** Send the founder's gate decision (approve / changes / reject) for a session. */
export async function postApproval(
  sessionId: string,
  decision: "approve" | "changes" | "reject",
  feedback?: string,
): Promise<void> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/sessions/${sessionId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, feedback: feedback ?? null }),
  });
  if (!response.ok) {
    throw new Error(`approval failed: ${response.status}`);
  }
}

/** Ask a running session to stop between turns. */
export async function postCancel(sessionId: string): Promise<void> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/sessions/${sessionId}/cancel`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`cancel failed: ${response.status}`);
  }
}
