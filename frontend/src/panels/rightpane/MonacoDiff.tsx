// ─────────────────────────────────────────────────────────────────────────────
// MonacoDiff.tsx — a read-only diff of two texts, using Monaco's DiffEditor.
// READING ORDER: frontend #24
//
// WHAT IT DOES: shows `original` (the committed version) vs `modified` (the working
// tree) with Monaco's colored gutter. Loaded lazily by the Diff tab (see the side-effect
// import) so Monaco isn't in the initial bundle.
// ─────────────────────────────────────────────────────────────────────────────

import { DiffEditor } from "@monaco-editor/react";

import "../../lib/monaco";

/** Read-only inline diff of two strings. */
export default function MonacoDiff({
  original,
  modified,
}: {
  original: string;
  modified: string;
}) {
  return (
    <DiffEditor
      height="100%"
      theme="vs-dark"
      original={original}
      modified={modified}
      options={{
        readOnly: true,
        // Inline (not side-by-side) fits the narrow review pane better.
        renderSideBySide: false,
        minimap: { enabled: false },
        fontSize: 12,
        scrollBeyondLastLine: false,
      }}
    />
  );
}
