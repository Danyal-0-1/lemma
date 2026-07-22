// ─────────────────────────────────────────────────────────────────────────────
// RightPane.tsx — the right panel: phase-aware review tabs.
// READING ORDER: frontend #16
//
// WHAT IT DOES (through M5):
//   • ideation phase → just the Spec tab.
//   • build phase   → a workspace header (Open in editor / Reveal) + tabs. In M5 those
//     are Terminal and Spec; Diff / Files / Checks arrive in M6. The Terminal stays
//     MOUNTED while another tab is active (hidden via CSS), so the shell survives tab
//     switches — you don't lose your `claude` session by peeking at the Spec.
//
// WHY phase-aware: PROMPT.md §12 rule 1 — a control that does nothing now isn't shown.
// No build tabs exist until a workspace does.
// ─────────────────────────────────────────────────────────────────────────────

import { lazy, Suspense, useState } from "react";

import { openInEditor, revealWorkspace } from "../../lib/api";
import { useAppStore } from "../../store/appStore";
import SpecTab from "./SpecTab";

// xterm.js is sizeable, so the terminal (and its dependency) loads only on entering
// the build phase — the same lazy pattern as the Monaco raw view.
const TerminalTab = lazy(() => import("./TerminalTab"));

type BuildTab = "terminal" | "spec";

/** A single tab button in the review pane's tab bar. */
function TabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-2 py-0.5 ${active ? "bg-line text-fg" : "text-muted hover:text-fg"}`}
    >
      {label}
    </button>
  );
}

/** The build-phase view: workspace header + Terminal/Spec tabs. */
function BuildPane({ workspaceId, slug }: { workspaceId: string; slug: string }) {
  const [tab, setTab] = useState<BuildTab>("terminal");

  return (
    <section className="flex h-full flex-col bg-panel">
      {/* Workspace header — hand-off buttons to the user's real tools. */}
      <div className="flex items-center gap-2 border-b border-line bg-sidebar px-2 py-1.5">
        <span className="truncate font-semibold text-fg">{slug}</span>
        <div className="ml-auto flex gap-1">
          <button
            type="button"
            onClick={() => openInEditor(workspaceId)}
            className="rounded border border-line px-2 py-0.5 text-fg hover:bg-line"
          >
            Open in editor
          </button>
          <button
            type="button"
            onClick={() => revealWorkspace(workspaceId)}
            className="rounded border border-line px-2 py-0.5 text-fg hover:bg-line"
          >
            Reveal
          </button>
        </div>
      </div>

      {/* Tab bar (M5: Terminal, Spec). */}
      <div className="flex items-center gap-1 border-b border-line px-2 py-1.5">
        <TabButton label="Terminal" active={tab === "terminal"} onClick={() => setTab("terminal")} />
        <TabButton label="Spec" active={tab === "spec"} onClick={() => setTab("spec")} />
      </div>

      {/* Content. Terminal stays mounted (hidden when inactive) to keep the shell alive. */}
      <div className="min-h-0 flex-1">
        <div className="h-full" style={{ display: tab === "terminal" ? "block" : "none" }}>
          <Suspense fallback={<p className="p-3 text-muted">Loading terminal…</p>}>
            <TerminalTab workspaceId={workspaceId} active={tab === "terminal"} />
          </Suspense>
        </div>
        {tab === "spec" && <SpecTab />}
      </div>
    </section>
  );
}

/** The ideation-phase view: just the Spec tab. */
function IdeationPane() {
  return (
    <section className="flex h-full flex-col bg-panel">
      <div className="flex items-center gap-1 border-b border-line bg-sidebar px-2 py-1.5">
        <span className="rounded px-2 py-0.5 text-fg">Spec</span>
      </div>
      <div className="min-h-0 flex-1">
        <SpecTab />
      </div>
    </section>
  );
}

/** The right column of the three-panel shell — picks a view by phase. */
export default function RightPane() {
  const phase = useAppStore((s) => s.phase);
  const workspace = useAppStore((s) => s.activeWorkspace);

  if (phase === "build" && workspace) {
    return <BuildPane workspaceId={workspace.id} slug={workspace.slug} />;
  }
  return <IdeationPane />;
}
