// ─────────────────────────────────────────────────────────────────────────────
// App.tsx — the three-panel shell. READING ORDER: frontend #8
//
// WHAT IT DOES (M0): renders the VS Code-dark layout the whole app lives inside —
// a title bar, three columns (Sidebar | Conversation | Review pane), and a status
// bar — with placeholder content. No data or interactivity yet; those arrive with
// the event pipe in M1.
//
// WHY the layout is exactly three panels: PROMPT.md §12 is strict about it — never
// more panels, never floating windows. Getting the skeleton right now means every
// later milestone just fills a panel in, rather than restructuring the page.
//
// This is a single file for M0 so the whole shell is visible at once. In M1 the
// panels are split into their own components under src/panels/.
// ─────────────────────────────────────────────────────────────────────────────

/** A section heading used inside the sidebar (e.g. "SESSIONS", "WORKSPACES"). */
function SidebarSection({ label }: { label: string }) {
  return (
    <div className="px-3 pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
      {label}
    </div>
  );
}

/** The left column: two flat lists (sessions, workspaces) plus their New buttons. */
function Sidebar() {
  return (
    <aside className="flex h-full w-60 flex-none flex-col border-r border-line bg-sidebar">
      <SidebarSection label="Sessions" />
      <p className="px-3 pb-2 text-muted">No ideation sessions yet.</p>
      <button
        className="mx-3 mb-2 rounded bg-accent px-3 py-1.5 text-left text-white hover:bg-accent-hover"
        // Wired up in M1; inert placeholder for now.
        type="button"
        disabled
      >
        + New session
      </button>

      <SidebarSection label="Workspaces" />
      <p className="px-3 pb-2 text-muted">No workspaces yet.</p>

      {/* History lives here as a collapsed section once archiving exists (M8). */}
      <div className="mt-auto border-t border-line px-3 py-2 text-[11px] text-muted">
        History (empty)
      </div>
    </aside>
  );
}

/** The center column: the crew debate / mentor conversation and its composer. */
function Conversation() {
  return (
    <main className="flex h-full flex-1 flex-col bg-panel">
      <div className="flex flex-1 items-center justify-center p-8">
        {/* Empty states teach — this exact copy is specified in PROMPT.md §12. */}
        <p className="max-w-md text-center text-muted">
          Start an ideation session — the crew will debate here.
        </p>
      </div>
      <div className="border-t border-line p-3">
        <textarea
          className="h-16 w-full resize-none rounded border border-line bg-sidebar px-2 py-1.5 text-fg placeholder:text-muted focus:border-accent focus:outline-none"
          placeholder="Describe an idea to start… (composer activates in M1)"
          disabled
        />
      </div>
    </main>
  );
}

/** The right column: phase-aware review tabs. In the idle phase only Spec exists. */
function ReviewPane() {
  return (
    <section className="flex h-full w-[440px] flex-none flex-col border-l border-line bg-panel">
      <div className="flex items-center gap-1 border-b border-line bg-sidebar px-2 py-1.5">
        {/* Only the tabs valid in the current phase are ever rendered (phase-aware chrome). */}
        <span className="rounded px-2 py-0.5 text-fg">Spec</span>
      </div>
      <div className="flex flex-1 items-center justify-center p-8">
        <p className="max-w-xs text-center text-muted">
          The approved Spec will appear here once the crew produces one.
        </p>
      </div>
    </section>
  );
}

/** The bottom bar: connection dot, current phase, cost meter, and the MOCK badge. */
function StatusBar() {
  return (
    <footer className="flex h-6 flex-none items-center gap-4 border-t border-line bg-sidebar px-3 text-[11px] text-muted">
      {/* The dot goes green/amber once the WebSocket connects in M1. Neutral for now. */}
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-2 w-2 rounded-full bg-muted" />
        disconnected
      </span>
      <span>phase: idle</span>
      <span>$0.00 today</span>
      <span className="ml-auto rounded bg-line px-1.5 py-0.5 font-mono text-warn">MOCK</span>
    </footer>
  );
}

/** The application root: the fixed three-panel shell everything else renders into. */
export default function App() {
  return (
    <div className="flex h-full flex-col">
      {/* Slim title bar. */}
      <header className="flex h-9 flex-none items-center border-b border-line bg-sidebar px-3 font-semibold text-fg">
        AI Company
      </header>

      {/* The three panels. In M1 these become resizable via react-resizable-panels. */}
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <Conversation />
        <ReviewPane />
      </div>

      <StatusBar />
    </div>
  );
}
