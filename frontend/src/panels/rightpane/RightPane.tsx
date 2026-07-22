// ─────────────────────────────────────────────────────────────────────────────
// RightPane.tsx — the right panel: phase-aware review tabs.
// READING ORDER: frontend #16
//
// WHAT IT DOES (M1): in the idle/ideation phase, the only review tab is Spec. The
// Diff / Terminal / Files / Checks tabs are intentionally NOT rendered yet — they
// only make sense once a workspace exists (build phase, M5+). Rendering tabs that
// do nothing would violate the "phase-aware chrome" rule (PROMPT.md §12 rule 1).
//
// This is a placeholder that the SpecTab (M4) and the build tabs (M5/M6) fill in.
// ─────────────────────────────────────────────────────────────────────────────

/** The right column of the three-panel shell. */
export default function RightPane() {
  return (
    <section className="flex h-full flex-col bg-panel">
      <div className="flex items-center gap-1 border-b border-line bg-sidebar px-2 py-1.5">
        {/* Only the tabs valid in the current phase appear. Idle → just "Spec". */}
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
