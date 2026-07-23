// ─────────────────────────────────────────────────────────────────────────────
// Sidebar.tsx — the left panel: Sessions, Workspaces, and History (archived).
// READING ORDER: frontend #13
//
// WHAT IT DOES: lists past ideation sessions and build workspaces (loaded from the
// backend). Active workspaces sit under "Workspaces"; archived ones collapse into
// "History" and can be restored. Rows are one line with a status dot (PROMPT.md §12).
// Clicking a session restores it; clicking a workspace re-enters the build phase.
// ─────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useState } from "react";

import {
  archiveWorkspace,
  getSession,
  getSessions,
  getWorkspaces,
  restoreWorkspace,
  type SessionSummary,
  type WorkspaceSummary,
} from "../lib/api";
import type { RestorePayload } from "../store/appStore";
import { useAppStore } from "../store/appStore";

// Status → dot color.
const STATUS_DOT: Record<string, string> = {
  approved: "bg-ok",
  running: "bg-warn",
  awaiting_approval: "bg-warn",
  rejected: "bg-err",
  cancelled: "bg-muted",
  budget_stopped: "bg-err",
  active: "bg-ok",
  archived: "bg-muted",
};

/** A small uppercase section heading (e.g. "SESSIONS"). */
function SectionLabel({ label }: { label: string }) {
  return (
    <div className="px-3 pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
      {label}
    </div>
  );
}

/** The left column of the three-panel shell. */
export default function Sidebar() {
  const phase = useAppStore((s) => s.phase);
  const currentSessionId = useAppStore((s) => s.sessionId);
  const activeWorkspace = useAppStore((s) => s.activeWorkspace);
  const diffCounts = useAppStore((s) => s.diffCounts);
  const restoreSession = useAppStore((s) => s.restoreSession);
  const activateWorkspace = useAppStore((s) => s.activateWorkspace);
  const exitWorkspace = useAppStore((s) => s.exitWorkspace);
  const newSession = useAppStore((s) => s.newSession);

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);

  const refreshWorkspaces = useCallback(() => {
    getWorkspaces()
      .then(setWorkspaces)
      .catch(() => {});
  }, []);

  // Refresh the lists on mount and whenever the phase changes.
  useEffect(() => {
    refreshWorkspaces();
    if (phase === "idle") {
      getSessions()
        .then(setSessions)
        .catch(() => {});
    }
  }, [phase, refreshWorkspaces]);

  async function openSession(id: string) {
    restoreSession((await getSession(id)) as RestorePayload);
  }

  async function archive(id: string) {
    await archiveWorkspace(id);
    if (id === activeWorkspace?.id) exitWorkspace(); // close the build pane if it was open
    refreshWorkspaces();
  }

  async function restore(id: string) {
    await restoreWorkspace(id);
    refreshWorkspaces();
  }

  const active = workspaces.filter((w) => w.status === "active");
  const archived = workspaces.filter((w) => w.status === "archived");

  return (
    <aside className="flex h-full flex-col overflow-y-auto bg-sidebar">
      {/* Sessions */}
      <SectionLabel label="Sessions" />
      {sessions.length === 0 ? (
        <p className="px-3 pb-2 text-muted">No ideation sessions yet.</p>
      ) : (
        sessions.map((session) => (
          <button
            key={session.id}
            type="button"
            onClick={() => void openSession(session.id)}
            title={`${session.title} — ${session.status}`}
            className={`flex items-center gap-2 px-3 py-1.5 text-left hover:bg-line ${
              session.id === currentSessionId ? "bg-line" : ""
            }`}
          >
            <span className={`h-2 w-2 flex-none rounded-full ${STATUS_DOT[session.status] ?? "bg-muted"}`} />
            <span className="truncate text-fg">{session.title}</span>
          </button>
        ))
      )}
      <button
        type="button"
        onClick={newSession}
        className="mx-3 my-2 rounded bg-accent px-3 py-1.5 text-left text-white hover:bg-accent-hover"
      >
        + New session
      </button>

      {/* Workspaces (active) */}
      <SectionLabel label="Workspaces" />
      {active.length === 0 ? (
        <p className="px-3 pb-2 text-muted">No workspaces yet.</p>
      ) : (
        active.map((workspace) => (
          <div
            key={workspace.id}
            className={`flex items-center gap-2 px-3 py-1.5 hover:bg-line ${
              workspace.id === activeWorkspace?.id ? "bg-line" : ""
            }`}
          >
            <button
              type="button"
              onClick={() =>
                activateWorkspace({ id: workspace.id, path: workspace.path, slug: workspace.slug })
              }
              className="flex flex-1 items-center gap-2 truncate text-left"
            >
              <span className={`h-2 w-2 flex-none rounded-full ${STATUS_DOT[workspace.status]}`} />
              <span className="flex-1 truncate text-fg">{workspace.slug}</span>
            </button>
            {workspace.id === activeWorkspace?.id &&
              diffCounts &&
              diffCounts.additions + diffCounts.deletions > 0 && (
                <span className="flex-none font-mono text-[11px]">
                  <span className="text-ok">+{diffCounts.additions}</span>{" "}
                  <span className="text-err">−{diffCounts.deletions}</span>
                </span>
              )}
            <button
              type="button"
              onClick={() => void archive(workspace.id)}
              title="Archive"
              className="flex-none text-[11px] text-muted hover:text-fg"
            >
              archive
            </button>
          </div>
        ))
      )}

      {/* History (archived, collapsed) */}
      <button
        type="button"
        onClick={() => setHistoryOpen((open) => !open)}
        className="mt-auto flex items-center gap-1 border-t border-line px-3 py-2 text-[11px] uppercase text-muted hover:text-fg"
      >
        {historyOpen ? "▾" : "▸"} History ({archived.length})
      </button>
      {historyOpen &&
        archived.map((workspace) => (
          <div key={workspace.id} className="flex items-center gap-2 px-3 py-1.5 hover:bg-line">
            <span className="h-2 w-2 flex-none rounded-full bg-muted" />
            <span className="flex-1 truncate text-muted">{workspace.slug}</span>
            <button
              type="button"
              onClick={() => void restore(workspace.id)}
              title="Restore"
              className="flex-none text-[11px] text-muted hover:text-ok"
            >
              restore
            </button>
          </div>
        ))}
    </aside>
  );
}
