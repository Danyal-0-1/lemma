// ─────────────────────────────────────────────────────────────────────────────
// Sidebar.tsx — the left panel: Sessions (from the DB) + Workspaces + History.
// READING ORDER: frontend #13
//
// WHAT IT DOES (M4): lists past ideation sessions loaded from the backend, each a
// one-line row with a status dot. Clicking a row restores that session (its
// transcript + artifacts) into the UI, read-only. It refreshes whenever a session
// finishes (the phase returns to idle).
//
// WHY one line per row: PROMPT.md §12 rule 4 — flat, predictable, no nested trees.
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useState } from "react";

import {
  getSession,
  getSessions,
  getWorkspaces,
  type SessionSummary,
  type WorkspaceSummary,
} from "../lib/api";
import type { RestorePayload } from "../store/appStore";
import { useAppStore } from "../store/appStore";

// Status → dot color. Approved is green; in-flight is amber; ended-without-approval dim.
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
  const clearConversation = useAppStore((s) => s.clearConversation);

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);

  // Refresh the lists on mount and whenever the phase changes (e.g. a session finished
  // or a workspace was just created).
  useEffect(() => {
    getWorkspaces()
      .then(setWorkspaces)
      .catch(() => {});
    if (phase === "idle") {
      getSessions()
        .then(setSessions)
        .catch(() => {
          // A failed fetch just leaves the list as-is; the status dot shows the outage.
        });
    }
  }, [phase]);

  async function handleOpen(id: string) {
    const payload = (await getSession(id)) as RestorePayload;
    restoreSession(payload);
  }

  return (
    <aside className="flex h-full flex-col bg-sidebar">
      <SectionLabel label="Sessions" />
      {sessions.length === 0 ? (
        <p className="px-3 pb-2 text-muted">No ideation sessions yet.</p>
      ) : (
        <div className="flex flex-col">
          {sessions.map((session) => (
            <button
              key={session.id}
              type="button"
              onClick={() => handleOpen(session.id)}
              title={`${session.title} — ${session.status}`}
              className={`flex items-center gap-2 px-3 py-1.5 text-left hover:bg-line ${
                session.id === currentSessionId ? "bg-line" : ""
              }`}
            >
              <span
                className={`h-2 w-2 flex-none rounded-full ${STATUS_DOT[session.status] ?? "bg-muted"}`}
              />
              <span className="truncate text-fg">{session.title}</span>
            </button>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={clearConversation}
        className="mx-3 my-2 rounded bg-accent px-3 py-1.5 text-left text-white hover:bg-accent-hover"
      >
        + New session
      </button>

      <SectionLabel label="Workspaces" />
      {workspaces.length === 0 ? (
        <p className="px-3 pb-2 text-muted">No workspaces yet.</p>
      ) : (
        <div className="flex flex-col">
          {workspaces.map((workspace) => (
            <button
              key={workspace.id}
              type="button"
              onClick={() =>
                activateWorkspace({
                  id: workspace.id,
                  path: workspace.path,
                  slug: workspace.slug,
                })
              }
              title={`${workspace.slug} — ${workspace.status}`}
              className={`flex items-center gap-2 px-3 py-1.5 text-left hover:bg-line ${
                workspace.id === activeWorkspace?.id ? "bg-line" : ""
              }`}
            >
              <span
                className={`h-2 w-2 flex-none rounded-full ${STATUS_DOT[workspace.status] ?? "bg-muted"}`}
              />
              <span className="flex-1 truncate text-fg">{workspace.slug}</span>
              {/* Conductor-style +/- counts on the active workspace when it's dirty. */}
              {workspace.id === activeWorkspace?.id && diffCounts && diffCounts.additions + diffCounts.deletions > 0 && (
                <span className="flex-none font-mono text-[11px]">
                  <span className="text-ok">+{diffCounts.additions}</span>{" "}
                  <span className="text-err">−{diffCounts.deletions}</span>
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Archived items collapse into History (M8). Shown here so the shape is visible. */}
      <div className="mt-auto border-t border-line px-3 py-2 text-[11px] text-muted">
        History (empty)
      </div>
    </aside>
  );
}
