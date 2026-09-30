// ─────────────────────────────────────────────────────────────────────────────
// monaco.ts — make the Monaco editor run fully offline (no CDN).
// READING ORDER: frontend #19
//
// WHAT THIS FILE DOES: Monaco (the editor that powers VS Code) runs its language
// smarts in web workers. By default @monaco-editor/react downloads Monaco from a CDN,
// which would break the app offline. This file (1) tells Monaco which locally-bundled
// worker to use per language, and (2) points the React wrapper at the local monaco
// package. Import it once, for its side effects, before anything renders an editor.
//
// WHY the "?worker" imports: Vite turns those into separately-bundled worker scripts,
// so everything ships with the app — matching its local-first goal (PROMPT.md §0).
// ─────────────────────────────────────────────────────────────────────────────

import { loader } from "@monaco-editor/react";
// Import the editor API only (not the full monaco-editor entry, which bundles EVERY
// language). We then opt into JUST the languages we use, keeping the bundle small.
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
// Opt in to the JSON language service (validation + formatting for the Spec view).
import "monaco-editor/esm/vs/language/json/monaco.contribution";
import "monaco-editor/esm/vs/basic-languages/css/css.contribution";
import "monaco-editor/esm/vs/basic-languages/dockerfile/dockerfile.contribution";
import "monaco-editor/esm/vs/basic-languages/html/html.contribution";
import "monaco-editor/esm/vs/basic-languages/ini/ini.contribution";
import "monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution";
import "monaco-editor/esm/vs/basic-languages/markdown/markdown.contribution";
import "monaco-editor/esm/vs/basic-languages/python/python.contribution";
import "monaco-editor/esm/vs/basic-languages/rust/rust.contribution";
import "monaco-editor/esm/vs/basic-languages/shell/shell.contribution";
import "monaco-editor/esm/vs/basic-languages/typescript/typescript.contribution";
import "monaco-editor/esm/vs/basic-languages/xml/xml.contribution";
import "monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import jsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";

// Monaco looks for a global `MonacoEnvironment.getWorker` to create its workers.
// We give it one that returns the right locally-bundled worker for the language.
const globalWithMonaco = globalThis as typeof globalThis & {
  MonacoEnvironment?: monaco.Environment;
};

globalWithMonaco.MonacoEnvironment = {
  getWorker(_moduleId: unknown, label: string): Worker {
    // The JSON language service (validation, formatting) needs its own worker;
    // everything else uses the base editor worker.
    if (label === "json") {
      return new jsonWorker();
    }
    return new editorWorker();
  },
};

// Use the monaco we just imported (bundled locally) instead of the default CDN copy.
loader.config({ monaco });
