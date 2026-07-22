// ─────────────────────────────────────────────────────────────────────────────
// DiffTab.tsx — review what changed in the workspace since the last commit.
// READING ORDER: frontend #26
//
// WHAT IT DOES: shows a per-file list (with +/- counts) of everything changed since
// HEAD. Clicking a file loads its committed vs working versions into a Monaco diff.
// It refreshes on demand (button) and polls every 5s WHILE this tab is visible, so a
// change you make in the terminal shows up on its own. It also publishes the total
// +/- counts to the store for the sidebar.
//
// WHY poll only when visible: polling a hidden tab wastes requests. `active` tells us
// when the Diff tab is the one on screen.
// ─────────────────────────────────────────────────────────────────────────────

import { lazy, Suspense, useCallback, useEffect, useState } from "react";

import { getDiff, getFile, type DiffFile } from "../../lib/api";
import { useAppStore } from "../../store/appStore";

const MonacoDiff = lazy(() => import("./MonacoDiff"));

// Poll cadence while the Diff tab is visible (PROMPT.md §10).
const POLL_MS = 5000;

// Status → color for the file row.
const STATUS_COLOR: Record<string, string> = {
  modified: "text-warn",
  untracked: "text-ok",
  deleted: "text-err",
};

/** The Diff tab. */
export default function DiffTab({ workspaceId, active }: { workspaceId: string; active: boolean }) {
  const setDiffCounts = useAppStore((s) => s.setDiffCounts);
  const [files, setFiles] = useState<DiffFile[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [original, setOriginal] = useState("");
  const [modified, setModified] = useState("");

  // Fetch the diff and publish the totals to the store (for the sidebar counts).
  const refresh = useCallback(async () => {
    const result = await getDiff(workspaceId);
    setFiles(result.files);
    const additions = result.files.reduce((sum, f) => sum + f.additions, 0);
    const deletions = result.files.reduce((sum, f) => sum + f.deletions, 0);
    setDiffCounts({ additions, deletions });
  }, [workspaceId, setDiffCounts]);

  // Refresh on becoming visible, then poll every 5s while visible.
  useEffect(() => {
    if (!active) return;
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, refresh]);

  // Load the two sides of the diff when a file is selected.
  async function openFile(path: string) {
    setSelected(path);
    const [head, working] = await Promise.all([
      getFile(workspaceId, path, "head"),
      getFile(workspaceId, path, "working"),
    ]);
    setOriginal(head.content);
    setModified(working.content);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-2 py-1.5">
        <span className="text-[11px] uppercase text-muted">{files.length} changed</span>
        <button
          type="button"
          onClick={() => void refresh()}
          className="rounded border border-line px-2 py-0.5 text-fg hover:bg-line"
        >
          ⟳ Refresh
        </button>
      </div>

      {files.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-8 text-center text-muted">
          No changes yet. Edit files in the Terminal, then Refresh.
        </div>
      ) : (
        <>
          {/* The changed-file list (scrolls if long). */}
          <div className="max-h-40 flex-none overflow-y-auto border-b border-line">
            {files.map((file) => (
              <button
                key={file.path}
                type="button"
                onClick={() => void openFile(file.path)}
                className={`flex w-full items-center gap-2 px-2 py-1 text-left hover:bg-line ${
                  selected === file.path ? "bg-line" : ""
                }`}
              >
                <span className={`flex-1 truncate ${STATUS_COLOR[file.status] ?? "text-fg"}`}>
                  {file.path}
                </span>
                <span className="font-mono text-[11px] text-ok">+{file.additions}</span>
                <span className="font-mono text-[11px] text-err">−{file.deletions}</span>
              </button>
            ))}
          </div>

          {/* The Monaco diff for the selected file. */}
          <div className="min-h-0 flex-1">
            {selected ? (
              <Suspense fallback={<p className="p-3 text-muted">Loading diff…</p>}>
                <MonacoDiff original={original} modified={modified} />
              </Suspense>
            ) : (
              <div className="flex h-full items-center justify-center text-muted">
                Select a file to see its diff.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
