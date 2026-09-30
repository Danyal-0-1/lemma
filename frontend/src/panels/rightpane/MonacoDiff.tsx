// ─────────────────────────────────────────────────────────────────────────────
// MonacoDiff.tsx — a read-only diff of two texts, with "Explain this" on selection.
// READING ORDER: frontend #24
//
// WHAT IT DOES: shows `original` (committed) vs `modified` (working tree) inline. When
// you select text in the modified side, a floating "Explain this" button appears and
// hands that code to the mentor (onExplain). Loaded lazily by the Diff tab.
// ─────────────────────────────────────────────────────────────────────────────

import { DiffEditor, type DiffOnMount } from "@monaco-editor/react";
import { useState } from "react";

import "../../lib/monaco";
import { usePreferencesStore } from "../../store/preferencesStore";

interface Selection {
  text: string;
  top: number;
  left: number;
}

/** Read-only inline diff of two strings; selecting text reveals "Explain this". */
export default function MonacoDiff({
  original,
  modified,
  onExplain,
}: {
  original: string;
  modified: string;
  onExplain?: (text: string) => void;
}) {
  const [selection, setSelection] = useState<Selection | null>(null);
  const resolvedTheme = usePreferencesStore((state) => state.resolvedTheme);
  const fontSize = usePreferencesStore((state) => state.editorFontSize);
  const wordWrap = usePreferencesStore((state) => state.wordWrap);

  const handleMount: DiffOnMount = (diffEditor) => {
    // A diff editor is two code editors; we track selections on the modified (right) one.
    const editor = diffEditor.getModifiedEditor();
    editor.onDidChangeCursorSelection((event) => {
      const text = editor.getModel()?.getValueInRange(event.selection) ?? "";
      if (text.trim().length === 0) {
        setSelection(null);
        return;
      }
      const position = editor.getScrolledVisiblePosition(event.selection.getStartPosition());
      setSelection({ text, top: (position?.top ?? 0) + 4, left: position?.left ?? 0 });
    });
  };

  return (
    <div className="relative h-full">
      <DiffEditor
        onMount={handleMount}
        height="100%"
        theme={resolvedTheme === "light" ? "vs" : "vs-dark"}
        original={original}
        modified={modified}
        options={{
          readOnly: true,
          originalEditable: false,
          renderSideBySide: false,
          minimap: { enabled: false },
          fontSize,
          wordWrap: wordWrap ? "on" : "off",
          scrollBeyondLastLine: false,
        }}
      />
      {onExplain && selection && (
        <button
          type="button"
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
