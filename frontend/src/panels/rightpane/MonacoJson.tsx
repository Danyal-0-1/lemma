// ─────────────────────────────────────────────────────────────────────────────
// MonacoJson.tsx — a read-only JSON view backed by the Monaco editor.
// READING ORDER: frontend #22  (teaches: code-splitting with React.lazy)
//
// WHAT IT DOES: renders a value as pretty-printed, read-only JSON in Monaco.
//
// WHY it imports "../../lib/monaco" here (not in main.tsx): Monaco is large. Keeping
// its setup inside THIS module means Monaco is only downloaded when this component is
// first used — SpecTab loads it lazily (React.lazy), so the app's initial bundle stays
// small and the editor arrives only when you click "Raw".
// ─────────────────────────────────────────────────────────────────────────────

import Editor from "@monaco-editor/react";

// Side-effect import: configures Monaco's offline workers before the editor mounts.
// It lives here so it's part of this lazily-loaded chunk, not the initial bundle.
import "../../lib/monaco";
import { usePreferencesStore } from "../../store/preferencesStore";

/** Read-only Monaco showing `value` as formatted JSON. */
export default function MonacoJson({ value }: { value: unknown }) {
  const resolvedTheme = usePreferencesStore((state) => state.resolvedTheme);
  const fontSize = usePreferencesStore((state) => state.editorFontSize);
  const minimap = usePreferencesStore((state) => state.minimap);
  const wordWrap = usePreferencesStore((state) => state.wordWrap);
  return (
    <Editor
      height="100%"
      defaultLanguage="json"
      theme={resolvedTheme === "light" ? "vs" : "vs-dark"}
      value={JSON.stringify(value, null, 2)}
      options={{
        readOnly: true,
        domReadOnly: true,
        minimap: { enabled: minimap },
        fontSize,
        wordWrap: wordWrap ? "on" : "off",
        scrollBeyondLastLine: false,
      }}
    />
  );
}
