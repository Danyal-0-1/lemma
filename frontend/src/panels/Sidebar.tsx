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

import { getSession, getSessions, type SessionSummary } from "../lib/api";
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
  const restoreSession = useAppStore((s) => s.restoreSession);
  const clearConversation = useAppStore((s) => s.clearConversation);

  const [sessions, setSessions] = useState<SessionSummary[]>([]);

  // Load the session list on mount, and again each time we return to idle (a session
  // just finished, so it should now appear/updated in the list).
  useEffect(() => {
    if (phase !== "idle") return;
    getSessions()
      .then(setSessions)
      .catch(() => {
        // A failed fetch just leaves the list as-is; the status dot shows the outage.
      });
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
      <p className="px-3 pb-2 text-muted">No workspaces yet.</p>

      {/* Archived items collapse into History (M8). Shown here so the shape is visible. */}
      <div className="mt-auto border-t border-line px-3 py-2 text-[11px] text-muted">
        History (empty)
      </div>
    </aside>
  );
}
