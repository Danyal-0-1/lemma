// ─────────────────────────────────────────────────────────────────────────────
// MonacoView.tsx — a read-only Monaco editor for viewing one file.
// READING ORDER: frontend #25
//
// WHAT IT DOES: shows file content read-only. We only bundled the JSON language, so
// other files render as plain text (still perfectly readable). Loaded lazily by the
// Files tab, so Monaco stays out of the initial bundle.
// ─────────────────────────────────────────────────────────────────────────────

import Editor from "@monaco-editor/react";

import "../../lib/monaco";

/** Read-only Monaco showing `content` as plain text. */
export default function MonacoView({ content }: { content: string }) {
  return (
    <Editor
      height="100%"
      theme="vs-dark"
      defaultLanguage="plaintext"
      value={content}
      options={{
        readOnly: true,
        minimap: { enabled: false },
        fontSize: 12,
        scrollBeyondLastLine: false,
      }}
    />
  );
}
