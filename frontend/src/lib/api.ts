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

/** Build the raw-bytes PTY socket URL for a given terminal id. */
export function ptyUrl(terminalId: string): string {
  return `ws://127.0.0.1:8000/pty/${terminalId}`;
}

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

/** One row in the sidebar's session history. */
export interface SessionSummary {
  id: string;
  title: string;
  status: string;
  round: number;
  created_at: string;
}

/** List past sessions (newest first) for the sidebar history. */
export async function getSessions(): Promise<SessionSummary[]> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/sessions`);
  if (!response.ok) {
    throw new Error(`list sessions failed: ${response.status}`);
  }
  return (await response.json()) as SessionSummary[];
}

/** Fetch one session with its messages and artifacts (to restore it into the UI). */
export async function getSession(sessionId: string): Promise<unknown> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/sessions/${sessionId}`);
  if (!response.ok) {
    throw new Error(`get session failed: ${response.status}`);
  }
  return await response.json();
}

// --- Workspaces + terminal (Phase 1, M5) -------------------------------------

/** One workspace row in the sidebar. */
export interface WorkspaceSummary {
  id: string;
  slug: string;
  path: string;
  status: string;
  created_at: string;
}

/** Build a workspace directory from a Spec artifact; the app enters the build phase. */
export async function postWorkspaceFromSpec(
  artifactId: number,
): Promise<{ workspace_id: string; path: string; slug: string }> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/from-spec/${artifactId}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`create workspace failed: ${response.status}`);
  }
  return (await response.json()) as { workspace_id: string; path: string; slug: string };
}

/** List workspaces (newest first) for the sidebar. */
export async function getWorkspaces(): Promise<WorkspaceSummary[]> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces`);
  if (!response.ok) {
    throw new Error(`list workspaces failed: ${response.status}`);
  }
  return (await response.json()) as WorkspaceSummary[];
}

/** Spawn a shell in a workspace and get the terminal id to open a /pty socket to. */
export async function createTerminal(workspaceId: string): Promise<{ terminal_id: string }> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/terminals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workspace_id: workspaceId }),
  });
  if (!response.ok) {
    throw new Error(`create terminal failed: ${response.status}`);
  }
  return (await response.json()) as { terminal_id: string };
}

/** Ask the backend to open a workspace in the user's editor (or reveal it). */
export async function openInEditor(workspaceId: string): Promise<string> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/open-in-editor`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`open-in-editor failed: ${response.status}`);
  }
  return ((await response.json()) as { result: string }).result;
}

/** Archive a workspace (moves it to History; the directory is kept). */
export async function archiveWorkspace(workspaceId: string): Promise<void> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/archive`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(`archive failed: ${response.status}`);
}

/** Restore an archived workspace back to the active list. */
export async function restoreWorkspace(workspaceId: string): Promise<void> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/restore`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(`restore failed: ${response.status}`);
}

/** Ask the backend to reveal a workspace in the OS file manager. */
export async function revealWorkspace(workspaceId: string): Promise<string> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/reveal`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`reveal failed: ${response.status}`);
  }
  return ((await response.json()) as { result: string }).result;
}

// --- Diff / Files / Checks (the review loop, M6) ------------------------------

/** One changed file in a workspace diff. */
export interface DiffFile {
  path: string;
  additions: number;
  deletions: number;
  status: string;
}

/** Fetch the per-file changes since the last commit. */
export async function getDiff(workspaceId: string): Promise<{ files: DiffFile[] }> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/diff`);
  if (!response.ok) throw new Error(`diff failed: ${response.status}`);
  return (await response.json()) as { files: DiffFile[] };
}

/** Fetch one file's content — working tree, or the committed version (ref="head"). */
export async function getFile(
  workspaceId: string,
  path: string,
  ref: "working" | "head" = "working",
): Promise<{ path: string; content: string }> {
  const query = new URLSearchParams({ path, ref });
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/file?${query}`);
  if (!response.ok) throw new Error(`read file failed: ${response.status}`);
  return (await response.json()) as { path: string; content: string };
}

/** Fetch the workspace's file list (for the Files tab). */
export async function getFiles(workspaceId: string): Promise<string[]> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/files`);
  if (!response.ok) throw new Error(`list files failed: ${response.status}`);
  return ((await response.json()) as { files: string[] }).files;
}

/** One saved verification command. */
export interface Check {
  id: string;
  name: string;
  command: string;
}

/** Fetch the workspace's saved checks. */
export async function getChecks(workspaceId: string): Promise<Check[]> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/checks`);
  if (!response.ok) throw new Error(`get checks failed: ${response.status}`);
  return ((await response.json()) as { checks: Check[] }).checks;
}

/** Persist the workspace's checks. */
export async function putChecks(workspaceId: string, list: Check[]): Promise<void> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/checks`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ checks: list }),
  });
  if (!response.ok) throw new Error(`save checks failed: ${response.status}`);
}

/** Run a saved check; its output streams over /ws (check_started/output/finished). */
export async function runCheck(workspaceId: string, checkId: string): Promise<void> {
  const response = await fetch(
    `${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/checks/${checkId}/run`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(`run check failed: ${response.status}`);
}

// --- Explain / mentor (the teaching layer, M7) --------------------------------

/** What to ask the mentor: something to explain and/or a question, plus context. */
export interface ExplainRequest {
  content?: string;
  question?: string;
  context?: string;
  context_label?: string;
}

/** Ask the mentor to explain something; the answer streams over /ws as role mentor. */
export async function postExplain(request: ExplainRequest): Promise<void> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(`explain failed: ${response.status}`);
}

/** Download a session (transcript + final Spec) as a markdown file (browser save). */
export async function exportSession(sessionId: string): Promise<void> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/sessions/${sessionId}/export`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`export failed: ${response.status}`);
  }
  // Turn the response into a file the browser saves, via a temporary object URL.
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${sessionId}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}
