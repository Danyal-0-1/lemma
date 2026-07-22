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
import ChecksTab from "./ChecksTab";
import DiffTab from "./DiffTab";
import FilesTab from "./FilesTab";
import SpecTab from "./SpecTab";

// xterm.js is sizeable, so the terminal (and its dependency) loads only on entering
// the build phase — the same lazy pattern as the Monaco raw view.
const TerminalTab = lazy(() => import("./TerminalTab"));

// The build-phase review tabs (PROMPT.md §2). Diff is the default.
type BuildTab = "diff" | "terminal" | "files" | "checks" | "spec";
const BUILD_TABS: { id: BuildTab; label: string }[] = [
  { id: "diff", label: "Diff" },
  { id: "terminal", label: "Terminal" },
  { id: "files", label: "Files" },
  { id: "checks", label: "Checks" },
  { id: "spec", label: "Spec" },
];

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

/** The build-phase view: workspace header + review tabs. */
function BuildPane({ workspaceId, slug }: { workspaceId: string; slug: string }) {
  const [tab, setTab] = useState<BuildTab>("diff");

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

      {/* Tab bar. */}
      <div className="flex items-center gap-1 border-b border-line px-2 py-1.5">
        {BUILD_TABS.map(({ id, label }) => (
          <TabButton key={id} label={label} active={tab === id} onClick={() => setTab(id)} />
        ))}
      </div>

      {/* Content. Terminal stays mounted (hidden when inactive) to keep the shell alive;
          the other tabs mount on demand and get an `active` flag for their fetching. */}
      <div className="min-h-0 flex-1">
        <div className="h-full" style={{ display: tab === "terminal" ? "block" : "none" }}>
          <Suspense fallback={<p className="p-3 text-muted">Loading terminal…</p>}>
            <TerminalTab workspaceId={workspaceId} active={tab === "terminal"} />
          </Suspense>
        </div>
        {tab === "diff" && <DiffTab workspaceId={workspaceId} active />}
        {tab === "files" && <FilesTab workspaceId={workspaceId} active />}
        {tab === "checks" && <ChecksTab workspaceId={workspaceId} active />}
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
