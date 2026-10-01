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

import type {
  ActionItem,
  AutomationRun,
  EvaluationCandidate,
  EvaluationExperiment,
  LabRun,
  LabSnapshot,
  LabTemplate,
  ProjectDossier,
  ProjectPolicy,
  ResearchProtocol,
  ResearchClaim,
  ResearchTask,
  SourceDocument,
  TaskAssurance,
  TraceLink,
  CapsuleVerification,
} from "../lab/types";
import { normalizeLabSnapshot } from "../lab/types";

/**
 * Resolve the backend without baking one installation layout into the bundle.
 *
 * Development and the lightweight Linux package serve the UI on :5173 and the
 * private API on :8000. A single-server production bundle can serve both from the
 * same origin. Keeping this decision here prevents an installed build from trying
 * to contact a development URL on another machine.
 */
function resolveBackendOrigin(): string {
  const configured = import.meta.env.VITE_BACKEND_ORIGIN as string | undefined;
  if (configured?.trim()) return configured.trim().replace(/\/$/, "");
  if (["5173", "4173"].includes(window.location.port)) {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return window.location.origin;
}

export const BACKEND_ORIGIN = resolveBackendOrigin();

function websocketUrl(path: string): string {
  const url = new URL(path, `${BACKEND_ORIGIN}/`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

/** The event-stream WebSocket URL, derived from the REST origin. */
export const WS_URL = websocketUrl("ws");

/** Build the raw-bytes PTY socket URL for a given terminal id. */
export function ptyUrl(terminalId: string): string {
  return websocketUrl(`pty/${encodeURIComponent(terminalId)}`);
}

/** What GET /health returns. Used to show the MOCK badge accurately. */
export interface Health {
  status: string;
  version: string;
  mock_llm: boolean;
  enable_host_execution: boolean;
  enable_headless_coding?: boolean;
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
    throw await responseError(response, "create workspace failed");
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
    throw await responseError(response, "create terminal failed");
  }
  return (await response.json()) as { terminal_id: string };
}

/** Ask the backend to open a workspace in the user's editor (or reveal it). */
export async function openInEditor(workspaceId: string): Promise<string> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/open-in-editor`, {
    method: "POST",
  });
  if (!response.ok) {
    throw await responseError(response, "open-in-editor failed");
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
    throw await responseError(response, "reveal failed");
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

export interface WorkspaceTreeNode {
  name: string;
  path: string;
  type: "directory" | "file";
  children?: WorkspaceTreeNode[];
}

/** Fetch a bounded, server-validated tree rooted inside the selected workspace. */
export async function getWorkspaceTree(
  workspaceId: string,
): Promise<{ root: WorkspaceTreeNode; truncated: boolean }> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/tree`);
  if (!response.ok) throw await responseError(response, "workspace tree failed");
  return (await response.json()) as { root: WorkspaceTreeNode; truncated: boolean };
}

export interface GitChange {
  path: string;
  original_path: string | null;
  index: string;
  working_tree: string;
  staged: boolean;
  status: string;
  conflict: boolean;
}

export interface GitStatus {
  repository: boolean;
  branch: string | null;
  detached: boolean;
  upstream: string | null;
  ahead: number;
  behind: number;
  clean: boolean;
  changes: GitChange[];
}

export async function getGitStatus(workspaceId: string): Promise<GitStatus> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/git/status`);
  if (!response.ok) throw await responseError(response, "git status failed");
  return (await response.json()) as GitStatus;
}

export async function getGitDiff(
  workspaceId: string,
  path: string,
  staged = false,
): Promise<{ path: string; staged: boolean; patch: string; truncated: boolean }> {
  const query = new URLSearchParams({ path, staged: String(staged) });
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/git/diff?${query}`);
  if (!response.ok) throw await responseError(response, "git diff failed");
  return (await response.json()) as { path: string; staged: boolean; patch: string; truncated: boolean };
}

async function gitMutation<T>(workspaceId: string, action: string, body: object): Promise<T> {
  const response = await fetch(`${BACKEND_ORIGIN}/api/workspaces/${workspaceId}/git/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await responseError(response, `git ${action} failed`);
  return (await response.json()) as T;
}

export async function stageGitPaths(workspaceId: string, paths: string[]): Promise<GitStatus> {
  const payload = await gitMutation<{ ok: true; status: GitStatus }>(workspaceId, "stage", { paths });
  return payload.status;
}

export async function unstageGitPaths(workspaceId: string, paths: string[]): Promise<GitStatus> {
  const payload = await gitMutation<{ ok: true; status: GitStatus }>(workspaceId, "unstage", { paths });
  return payload.status;
}

export async function commitGitChanges(
  workspaceId: string,
  message: string,
): Promise<{ commit: string; summary: string; status: GitStatus }> {
  return await gitMutation(workspaceId, "commit", { message });
}

export async function pushGitBranch(
  workspaceId: string,
  remote: string,
  branch: string,
): Promise<{ remote: string; branch: string; output: string; status: GitStatus }> {
  return await gitMutation(workspaceId, "push", { remote, branch, confirm: true });
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
  if (!response.ok) throw await responseError(response, "run check failed");
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

// --- R&D Studio -------------------------------------------------------------

type LabEntity = "departments" | "agents" | "projects" | "tasks" | "meetings";

/** Read a useful backend error without leaking a full HTML/server response into the UI. */
async function responseError(response: Response, fallback: string): Promise<Error> {
  try {
    const payload = (await response.json()) as { detail?: unknown; message?: unknown };
    const detail = typeof payload.detail === "string" ? payload.detail : payload.message;
    if (typeof detail === "string" && detail.trim()) return new Error(detail);
  } catch {
    // A proxy or crashed dev server may return non-JSON; the status remains actionable.
  }
  return new Error(`${fallback} (${response.status})`);
}

async function labRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const response = await fetch(`${BACKEND_ORIGIN}/api/lab${path}`, {
    ...init,
    headers: init?.body && !isFormData
      ? { "Content-Type": "application/json", ...(init.headers ?? {}) }
      : init?.headers,
  });
  if (!response.ok) throw await responseError(response, "R&D Studio request failed");
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Load the complete small-lab snapshot used to hydrate the normalized UI store. */
export async function getLabSnapshot(): Promise<LabSnapshot> {
  const raw = await labRequest<unknown>("/snapshot");
  return normalizeLabSnapshot(raw);
}

/** Create one Lab entity. Payloads remain schema-shaped snake_case model inputs. */
export async function createLabEntity<T>(entity: LabEntity, payload: object): Promise<T> {
  return await labRequest<T>(`/${entity}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Partially update one Lab entity. */
export async function updateLabEntity<T>(
  entity: LabEntity,
  id: string,
  payload: object,
): Promise<T> {
  return await labRequest<T>(`/${entity}/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export interface LabRunResponse {
  run_id: string;
  status: string;
  task_id?: string;
  meeting_id?: string;
}

/** Start a task run. Instructions are explicit; no open file is attached implicitly. */
export async function runLabTask(taskId: string, instructions = ""): Promise<LabRunResponse> {
  return await labRequest<LabRunResponse>(`/tasks/${encodeURIComponent(taskId)}/run`, {
    method: "POST",
    body: JSON.stringify({ instructions }),
  });
}

/** Start a bounded meeting run. */
export async function runLabMeeting(
  meetingId: string,
  instructions = "",
): Promise<LabRunResponse> {
  return await labRequest<LabRunResponse>(`/meetings/${encodeURIComponent(meetingId)}/run`, {
    method: "POST",
    body: JSON.stringify({ instructions }),
  });
}

// --- Evidence-rich research workflows --------------------------------------

export interface SearchMatch {
  kind: string;
  entity_id: string;
  project_id: string;
  title: string;
  snippet: string;
  rank: number;
}

export async function searchResearch(
  query: string,
  projectId?: string,
  kinds: string[] = [],
): Promise<SearchMatch[]> {
  const result = await labRequest<{ matches: SearchMatch[] }>("/search", {
    method: "POST",
    body: JSON.stringify({
      query,
      ...(projectId ? { project_id: projectId } : {}),
      kinds,
      limit: 50,
    }),
  });
  return result.matches;
}

export async function listProjectSources(projectId: string): Promise<SourceDocument[]> {
  return await labRequest(`/projects/${encodeURIComponent(projectId)}/sources`);
}

export async function createSourceDocument(payload: {
  project_id: string;
  title: string;
  source_type: string;
  origin?: string;
  content: string;
}): Promise<SourceDocument> {
  return await labRequest("/sources", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function importSourceDocument(
  projectId: string,
  document: File,
  title = "",
): Promise<SourceDocument> {
  const form = new FormData();
  form.append("project_id", projectId);
  form.append("document", document, document.name);
  if (title.trim()) form.append("title", title.trim());
  return await labRequest("/sources/import-file", {
    method: "POST",
    body: form,
  });
}

export async function archiveSourceDocument(sourceId: string): Promise<SourceDocument> {
  return await labRequest(`/sources/${encodeURIComponent(sourceId)}/archive`, {
    method: "POST",
  });
}

export async function createSourceExcerpt(
  sourceId: string,
  payload: { quote: string; locator?: string },
): Promise<{ id: string; source_id: string; quote: string }> {
  return await labRequest(`/sources/${encodeURIComponent(sourceId)}/excerpts`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function linkSourceToTask(
  taskId: string,
  sourceId: string,
  purpose = "context",
): Promise<void> {
  await labRequest(`/tasks/${encodeURIComponent(taskId)}/sources`, {
    method: "POST",
    body: JSON.stringify({ source_id: sourceId, purpose }),
  });
}

export async function unlinkSourceFromTask(linkId: string): Promise<void> {
  await labRequest(`/task-source-links/${encodeURIComponent(linkId)}`, {
    method: "DELETE",
  });
}

export async function reviewFinding(
  findingId: string,
  decision: "accepted" | "rejected" | "needs_revision",
  notes = "",
): Promise<void> {
  await labRequest(`/findings/${encodeURIComponent(findingId)}/reviews`, {
    method: "POST",
    body: JSON.stringify({ decision, notes, reviewer: "founder" }),
  });
}

export async function createResearchClaim(payload: {
  project_id: string;
  finding_id?: string;
  statement: string;
  confidence?: number;
}): Promise<ResearchClaim> {
  return await labRequest("/claims", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function attachClaimEvidence(
  claimId: string,
  excerptId: string,
  stance: "supports" | "contradicts" | "contextualizes",
  note = "",
): Promise<void> {
  await labRequest(`/claims/${encodeURIComponent(claimId)}/evidence`, {
    method: "POST",
    body: JSON.stringify({ excerpt_id: excerptId, stance, note }),
  });
}

export async function updateResearchClaimStatus(
  claimId: string,
  status: "proposed" | "accepted" | "disputed" | "retired",
): Promise<ResearchClaim> {
  return await labRequest(`/claims/${encodeURIComponent(claimId)}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export async function removeClaimEvidence(evidenceId: string): Promise<void> {
  await labRequest(`/claim-evidence/${encodeURIComponent(evidenceId)}`, {
    method: "DELETE",
  });
}

export async function getProjectDossier(projectId: string): Promise<ProjectDossier> {
  return await labRequest(`/projects/${encodeURIComponent(projectId)}/dossier`);
}

export async function downloadProjectDossier(projectId: string): Promise<void> {
  const response = await fetch(
    `${BACKEND_ORIGIN}/api/lab/projects/${encodeURIComponent(projectId)}/dossier.md`,
  );
  if (!response.ok) throw await responseError(response, "dossier export failed");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `project-${projectId}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function getProjectPolicy(projectId: string): Promise<ProjectPolicy> {
  return await labRequest(`/projects/${encodeURIComponent(projectId)}/policy`);
}

export async function updateProjectPolicy(
  projectId: string,
  policy: Omit<ProjectPolicy, "project_id">,
): Promise<ProjectPolicy> {
  return await labRequest(`/projects/${encodeURIComponent(projectId)}/policy`, {
    method: "PUT",
    body: JSON.stringify(policy),
  });
}

export async function getProjectBudget(projectId: string): Promise<{
  tokens_used: number;
  usd_used: number;
  running: number;
  limits: ProjectPolicy;
}> {
  return await labRequest(`/projects/${encodeURIComponent(projectId)}/budget`);
}

export async function getProjectRuns(projectId: string): Promise<LabRun[]> {
  return await labRequest(`/projects/${encodeURIComponent(projectId)}/runs`);
}

export async function cancelLabRun(runId: string): Promise<LabRun> {
  return await labRequest(`/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
}

export async function retryLabRun(runId: string): Promise<LabRun> {
  return await labRequest(`/runs/${encodeURIComponent(runId)}/retry`, { method: "POST" });
}

export async function getTaskReadiness(taskId: string): Promise<{
  ready: boolean;
  dependencies: Array<{
    dependency_id: string;
    task_id: string;
    title: string;
    status: string;
  }>;
  blockers: Array<{
    dependency_id: string;
    task_id: string;
    title: string;
    status: string;
  }>;
}> {
  return await labRequest(`/tasks/${encodeURIComponent(taskId)}/readiness`);
}

// --- Research assurance ----------------------------------------------------

export async function listResearchProtocols(projectId: string): Promise<ResearchProtocol[]> {
  return await labRequest(`/projects/${encodeURIComponent(projectId)}/protocols`);
}

export async function createResearchProtocol(
  projectId: string,
  payload: Pick<
    ResearchProtocol,
    "question" | "hypothesis" | "method" | "acceptance_criteria" | "limitations"
  > & { created_by?: string },
): Promise<ResearchProtocol> {
  return await labRequest(`/projects/${encodeURIComponent(projectId)}/protocols`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function approveResearchProtocol(
  protocolId: string,
  approvedBy = "founder",
): Promise<ResearchProtocol> {
  return await labRequest(`/protocols/${encodeURIComponent(protocolId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ approved_by: approvedBy }),
  });
}

export async function withdrawResearchProtocol(
  protocolId: string,
  note = "Withdrawn during protocol review.",
  withdrawnBy = "founder",
): Promise<ResearchProtocol> {
  return await labRequest(`/protocols/${encodeURIComponent(protocolId)}/withdraw`, {
    method: "POST",
    body: JSON.stringify({ withdrawn_by: withdrawnBy, note }),
  });
}

export async function getTaskAssurance(taskId: string): Promise<TaskAssurance> {
  return await labRequest(`/tasks/${encodeURIComponent(taskId)}/assurance`);
}

export async function acceptAssuredTask(
  taskId: string,
  confirmedCriteria: string[],
  notes = "",
): Promise<TaskAssurance> {
  return await labRequest(`/tasks/${encodeURIComponent(taskId)}/accept`, {
    method: "POST",
    body: JSON.stringify({
      reviewer: "founder",
      notes,
      confirmed_criteria: confirmedCriteria,
    }),
  });
}

export async function downloadResearchCapsule(projectId: string): Promise<void> {
  const response = await fetch(
    `${BACKEND_ORIGIN}/api/lab/projects/${encodeURIComponent(projectId)}/capsule`,
  );
  if (!response.ok) throw await responseError(response, "research capsule export failed");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `project-${projectId}-research-capsule.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function verifyResearchCapsule(capsule: unknown): Promise<CapsuleVerification> {
  return await labRequest("/capsules/verify", {
    method: "POST",
    body: JSON.stringify(capsule),
  });
}

export async function addTaskDependency(
  taskId: string,
  dependsOnTaskId: string,
): Promise<void> {
  await labRequest(`/tasks/${encodeURIComponent(taskId)}/dependencies`, {
    method: "POST",
    body: JSON.stringify({ depends_on_task_id: dependsOnTaskId }),
  });
}

export async function removeTaskDependency(dependencyId: string): Promise<void> {
  await labRequest(`/dependencies/${encodeURIComponent(dependencyId)}`, {
    method: "DELETE",
  });
}

export async function recordMeetingOutcome(
  meetingId: string,
  payload: { summary: string; decisions: string[]; disagreements: string[] },
): Promise<void> {
  await labRequest(`/meetings/${encodeURIComponent(meetingId)}/outcomes`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createActionItem(payload: {
  project_id: string;
  meeting_id?: string;
  owner_agent_id?: string;
  title: string;
  details?: string;
}): Promise<ActionItem> {
  return await labRequest("/actions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateActionItem(
  actionId: string,
  payload: { status?: "open" | "in_progress" | "completed" | "cancelled"; owner_agent_id?: string },
): Promise<ActionItem> {
  return await labRequest(`/actions/${encodeURIComponent(actionId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function promoteActionItem(
  actionId: string,
  assignedAgentId?: string,
): Promise<ResearchTask> {
  return await labRequest(`/actions/${encodeURIComponent(actionId)}/promote`, {
    method: "POST",
    body: JSON.stringify(assignedAgentId ? { assigned_agent_id: assignedAgentId } : {}),
  });
}

export async function createTraceLink(payload: Omit<TraceLink, "id">): Promise<TraceLink> {
  return await labRequest("/trace-links", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface EvaluationDetail {
  experiment: EvaluationExperiment;
  candidates: EvaluationCandidate[];
  scores: Array<{
    id: string;
    candidate_id: string;
    criterion: string;
    score: number;
    rationale: string;
    reviewer: string;
  }>;
}

export async function listEvaluations(projectId: string): Promise<EvaluationExperiment[]> {
  return await labRequest(`/projects/${encodeURIComponent(projectId)}/evaluations`);
}

export async function createEvaluation(payload: {
  project_id: string;
  name: string;
  prompt: string;
  models: string[];
  criteria: string[];
}): Promise<EvaluationExperiment> {
  return await labRequest("/evaluations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getEvaluation(experimentId: string): Promise<EvaluationDetail> {
  return await labRequest(`/evaluations/${encodeURIComponent(experimentId)}`);
}

export async function runEvaluation(experimentId: string): Promise<EvaluationExperiment> {
  return await labRequest(`/evaluations/${encodeURIComponent(experimentId)}/run`, {
    method: "POST",
  });
}

export async function cancelEvaluation(experimentId: string): Promise<EvaluationExperiment> {
  return await labRequest(`/evaluations/${encodeURIComponent(experimentId)}/cancel`, {
    method: "POST",
  });
}

export async function scoreEvaluationCandidate(
  candidateId: string,
  criterion: string,
  score: number,
  rationale = "",
): Promise<void> {
  await labRequest(`/evaluation-candidates/${encodeURIComponent(candidateId)}/scores`, {
    method: "POST",
    body: JSON.stringify({ criterion, score, rationale, reviewer: "founder" }),
  });
}

export async function listAutomations(): Promise<AutomationRun[]> {
  return await labRequest("/automations");
}

export async function createAutomationPlan(payload: {
  project_id?: string;
  workspace_id?: string;
  request: string;
  plan?: string;
  capabilities: string[];
}): Promise<AutomationRun> {
  return await labRequest("/automations", {
    method: "POST",
    body: JSON.stringify({ provider: "claude", ...payload }),
  });
}

export async function decideAutomation(
  automationId: string,
  decision: "approve" | "reject",
  note = "",
): Promise<AutomationRun> {
  return await labRequest(`/automations/${encodeURIComponent(automationId)}/decision`, {
    method: "POST",
    body: JSON.stringify({ decision, note }),
  });
}

export async function runAutomation(automationId: string): Promise<AutomationRun> {
  return await labRequest(`/automations/${encodeURIComponent(automationId)}/run`, {
    method: "POST",
  });
}

export async function cancelAutomation(automationId: string): Promise<AutomationRun> {
  return await labRequest(`/automations/${encodeURIComponent(automationId)}/cancel`, {
    method: "POST",
  });
}

export async function listLabTemplates(kind?: string): Promise<LabTemplate[]> {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  return await labRequest(`/templates${query}`);
}

export async function createLabTemplate(payload: {
  name: string;
  kind: string;
  description?: string;
  payload: Record<string, unknown>;
}): Promise<LabTemplate> {
  return await labRequest("/templates", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function archiveLabTemplate(templateId: string): Promise<LabTemplate> {
  return await labRequest(`/templates/${encodeURIComponent(templateId)}/archive`, {
    method: "POST",
  });
}

export async function instantiateLabTemplate(
  templateId: string,
  overrides: Record<string, unknown>,
): Promise<{ kind: string; entity: Record<string, unknown> }> {
  return await labRequest(`/templates/${encodeURIComponent(templateId)}/instantiate`, {
    method: "POST",
    body: JSON.stringify({ overrides }),
  });
}
