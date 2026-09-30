import Editor from "@monaco-editor/react";

import "../../lib/monaco";
import { usePreferencesStore } from "../../store/preferencesStore";

const EXTENSIONS: Record<string, string> = {
  css: "css", html: "html", htm: "html", js: "javascript", jsx: "javascript",
  diff: "diff",
  json: "json", jsonc: "json", md: "markdown", mdx: "markdown", py: "python",
  rs: "rust", sh: "shell", bash: "shell", ts: "typescript", tsx: "typescript",
  xml: "xml", svg: "xml", yml: "yaml", yaml: "yaml", toml: "ini", ini: "ini",
  env: "ini", dockerfile: "dockerfile",
};

function languageFor(path: string): string {
  const name = path.split("/").pop()?.toLowerCase() ?? "";
  if (name === "dockerfile") return "dockerfile";
  return EXTENSIONS[name.split(".").pop() ?? ""] ?? "plaintext";
}

export default function CodeEditor({
  path,
  content,
  line,
  language,
}: {
  path: string;
  content: string;
  line?: number;
  language?: string;
}) {
  const fontSize = usePreferencesStore((state) => state.editorFontSize);
  const minimap = usePreferencesStore((state) => state.minimap);
  const wordWrap = usePreferencesStore((state) => state.wordWrap);
  const resolvedTheme = usePreferencesStore((state) => state.resolvedTheme);

  return (
    <Editor
      key={`${path}:${line ?? 0}:${resolvedTheme}`}
      height="100%"
      path={path}
      language={language ?? languageFor(path)}
      theme={resolvedTheme === "light" ? "vs" : "vs-dark"}
      value={content}
      onMount={(editor) => {
        if (line && line > 0) {
          editor.setPosition({ lineNumber: line, column: 1 });
          editor.revealLineInCenter(line);
          editor.focus();
        }
      }}
      options={{
        readOnly: true,
        domReadOnly: true,
        fontFamily: "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace",
        fontSize,
        minimap: { enabled: minimap },
        wordWrap: wordWrap ? "on" : "off",
        automaticLayout: true,
        scrollBeyondLastLine: false,
        smoothScrolling: true,
        renderWhitespace: "selection",
        padding: { top: 8 },
      }}
    />
  );
}
