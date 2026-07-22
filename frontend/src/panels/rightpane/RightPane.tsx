// ─────────────────────────────────────────────────────────────────────────────
// RightPane.tsx — the right panel: phase-aware review tabs.
// READING ORDER: frontend #16
//
// WHAT IT DOES (through M4): in the ideation phase the only tab is Spec, which now
// renders the real SpecTab (versions, JSON tree, raw Monaco, idea evolution, export).
// The Diff / Terminal / Files / Checks tabs arrive with workspaces in M5+, and are
// intentionally NOT rendered until then (phase-aware chrome, PROMPT.md §12 rule 1).
// ─────────────────────────────────────────────────────────────────────────────

import SpecTab from "./SpecTab";

/** The right column of the three-panel shell. */
export default function RightPane() {
  return (
    <section className="flex h-full flex-col bg-panel">
      <div className="flex items-center gap-1 border-b border-line bg-sidebar px-2 py-1.5">
        {/* Only the tabs valid in the current phase appear. Idle/ideation → just "Spec". */}
        <span className="rounded px-2 py-0.5 text-fg">Spec</span>
      </div>
      <div className="min-h-0 flex-1">
        <SpecTab />
      </div>
    </section>
  );
}
