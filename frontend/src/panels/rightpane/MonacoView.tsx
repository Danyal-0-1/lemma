// ─────────────────────────────────────────────────────────────────────────────
// MonacoView.tsx — a read-only Monaco editor for viewing one file, with "Explain this".
// READING ORDER: frontend #25
//
// WHAT IT DOES: shows file content read-only. When you SELECT some text, a floating
// "Explain this" button appears at the selection; clicking it hands the selected code to
// the mentor (onExplain). We only bundled the JSON language, so non-JSON renders as plain
// text. Loaded lazily, so Monaco stays out of the initial bundle.
// ─────────────────────────────────────────────────────────────────────────────

import Editor, { type OnMount } from "@monaco-editor/react";
import { useState } from "react";

import "../../lib/monaco";
import { usePreferencesStore } from "../../store/preferencesStore";

/** Where a selection is, so we can float the button next to it. */
interface Selection {
  text: string;
  top: number;
  left: number;
}

/** Read-only Monaco showing `content`; selecting text reveals "Explain this". */
export default function MonacoView({
  content,
  onExplain,
}: {
  content: string;
  onExplain?: (text: string) => void;
}) {
  const [selection, setSelection] = useState<Selection | null>(null);
  const resolvedTheme = usePreferencesStore((state) => state.resolvedTheme);
  const fontSize = usePreferencesStore((state) => state.editorFontSize);
  const minimap = usePreferencesStore((state) => state.minimap);
  const wordWrap = usePreferencesStore((state) => state.wordWrap);

  const handleMount: OnMount = (editor) => {
    editor.onDidChangeCursorSelection((event) => {
      const text = editor.getModel()?.getValueInRange(event.selection) ?? "";
      if (text.trim().length === 0) {
        setSelection(null);
        return;
      }
      // Position the button just under the selection's start, relative to the editor.
      const position = editor.getScrolledVisiblePosition(event.selection.getStartPosition());
      setSelection({ text, top: (position?.top ?? 0) + 4, left: position?.left ?? 0 });
    });
  };

  return (
    <div className="relative h-full">
      <Editor
        onMount={handleMount}
        height="100%"
        theme={resolvedTheme === "light" ? "vs" : "vs-dark"}
        defaultLanguage="plaintext"
        value={content}
        options={{
          readOnly: true,
          domReadOnly: true,
          minimap: { enabled: minimap },
          fontSize,
          wordWrap: wordWrap ? "on" : "off",
          scrollBeyondLastLine: false,
        }}
      />
      {onExplain && selection && (
        <button
          type="button"
          // preventDefault on mousedown so clicking doesn't clear the selection first.
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            onExplain(selection.text);
            setSelection(null);
          }}
          style={{ position: "absolute", top: selection.top, left: selection.left, zIndex: 10 }}
          className="rounded bg-accent px-2 py-0.5 text-[11px] text-white shadow hover:bg-accent-hover"
        >
          Explain this
        </button>
      )}
    </div>
  );
}
