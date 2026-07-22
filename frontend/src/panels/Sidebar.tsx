// ─────────────────────────────────────────────────────────────────────────────
// Sidebar.tsx — the left panel: Sessions + Workspaces (flat lists) + History.
// READING ORDER: frontend #13
//
// WHAT IT DOES (M1): renders the two flat lists and their New buttons. There's no
// data to list yet (sessions arrive with persistence in M3; workspaces in M5), so
// this is mostly empty states + the "New session" button (wired up in M3).
//
// WHY it's flat: PROMPT.md §12 rule 4 — sidebar rows are one line, nothing nests
// deeper than one level. Keeping that discipline from the start avoids a tree maze.
// ─────────────────────────────────────────────────────────────────────────────

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
  return (
    <aside className="flex h-full flex-col bg-sidebar">
      <SectionLabel label="Sessions" />
      <p className="px-3 pb-2 text-muted">No ideation sessions yet.</p>
      <button
        // Real ideation sessions begin in M3; disabled until then.
        type="button"
        disabled
        className="mx-3 mb-3 cursor-not-allowed rounded bg-accent/50 px-3 py-1.5 text-left text-white/70"
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
