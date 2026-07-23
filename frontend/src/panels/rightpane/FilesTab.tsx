// ─────────────────────────────────────────────────────────────────────────────
// FilesTab.tsx — browse the workspace's files, read-only.
// READING ORDER: frontend #27
//
// WHAT IT DOES: lists every file in the workspace; clicking one shows its content in a
// read-only Monaco editor. This is a viewer, not an editor — the coding agent and your
// real editor write code (PROMPT.md §15). Monaco loads lazily here too.
// ─────────────────────────────────────────────────────────────────────────────

import { lazy, Suspense, useEffect, useState } from "react";

import { getFile, getFiles } from "../../lib/api";
import { askMentor } from "../../lib/mentor";
import { useAppStore } from "../../store/appStore";

const MonacoView = lazy(() => import("./MonacoView"));

/** Shorten a selection so it reads well as a "You" bubble label. */
function clip(text: string): string {
  const oneLine = text.replace(/\s+/g, " ").trim();
  return oneLine.length > 50 ? `${oneLine.slice(0, 50)}…` : oneLine;
}

/** The Files tab. */
export default function FilesTab({ workspaceId, active }: { workspaceId: string; active: boolean }) {
  const setMentorContext = useAppStore((s) => s.setMentorContext);
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState("");

  // Refresh the file list whenever this tab becomes visible.
  useEffect(() => {
    if (!active) return;
    getFiles(workspaceId)
      .then(setFiles)
      .catch(() => {});
  }, [active, workspaceId]);

  async function openFile(path: string) {
    setSelected(path);
    const file = await getFile(workspaceId, path, "working");
    setContent(file.content);
    // Make this file the mentor's context, so a composer question is about it.
    setMentorContext({ label: path, content: `File ${path}:\n${file.content}` });
  }

  return (
    <div className="flex h-full flex-col">
      {/* File list. */}
      <div className="max-h-40 flex-none overflow-y-auto border-b border-line">
        {files.length === 0 ? (
          <p className="p-3 text-muted">No files.</p>
        ) : (
          files.map((path) => (
            <button
              key={path}
              type="button"
              onClick={() => void openFile(path)}
              className={`block w-full truncate px-2 py-1 text-left hover:bg-line ${
                selected === path ? "bg-line text-fg" : "text-fg"
              }`}
            >
              {path}
            </button>
          ))
        )}
      </div>

      {/* Read-only viewer for the selected file. */}
      <div className="min-h-0 flex-1">
        {selected ? (
          <Suspense fallback={<p className="p-3 text-muted">Loading…</p>}>
            <MonacoView
              content={content}
              onExplain={(text) => void askMentor({ userLabel: `Explain: ${clip(text)}`, content: text })}
            />
          </Suspense>
        ) : (
          <div className="flex h-full items-center justify-center text-muted">
            Select a file to view it.
          </div>
        )}
      </div>
    </div>
  );
}
