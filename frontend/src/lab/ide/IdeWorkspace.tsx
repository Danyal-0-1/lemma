import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getFile,
  getWorkspaces,
  getWorkspaceTree,
  type WorkspaceSummary,
  type WorkspaceTreeNode,
} from "../../lib/api";
import { useAppStore } from "../../store/appStore";
import { Icon } from "../components/Icons";
import type { IdeView } from "../types";
import SourceControlPanel from "./SourceControlPanel";
import { ExplorerPanel, SearchPanel } from "./WorkspaceExplorer";

const CodeEditor = lazy(() => import("./CodeEditor"));
const TerminalTab = lazy(() => import("../../panels/rightpane/TerminalTab"));

interface OpenDocument {
  id: string;
  label: string;
  path: string;
  content: string;
  kind: "file" | "diff";
  line?: number;
}

const VIEW_TITLES: Record<IdeView, string> = {
  explorer: "Explorer",
  search: "Search",
  source_control: "Source Control",
  terminal: "Terminal",
};

function flattenFiles(node: WorkspaceTreeNode | null): string[] {
  if (!node) return [];
  if (node.type === "file") return [node.path];
  return (node.children ?? []).flatMap(flattenFiles);
}

function shortLabel(path: string): string {
  return path.split("/").pop() || path;
}

export default function IdeWorkspace({ view }: { view: IdeView }) {
  const hostExecution = useAppStore((state) => state.hostExecutionEnabled);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [tree, setTree] = useState<WorkspaceTreeNode | null>(null);
  const [treeTruncated, setTreeTruncated] = useState(false);
  const [loadingTree, setLoadingTree] = useState(true);
  const [documents, setDocuments] = useState<OpenDocument[]>([]);
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const requestSequence = useRef(0);

  const workspace = useMemo(
    () => workspaces.find((item) => item.id === workspaceId) ?? null,
    [workspaceId, workspaces],
  );
  const activeDocument = useMemo(
    () => documents.find((item) => item.id === activeDocumentId) ?? null,
    [activeDocumentId, documents],
  );

  useEffect(() => {
    let cancelled = false;
    getWorkspaces()
      .then((items) => {
        if (cancelled) return;
        const active = items.filter((item) => item.status === "active");
        setWorkspaces(active);
        setWorkspaceId((current) =>
          active.some((item) => item.id === current) ? current : (active[0]?.id ?? ""),
        );
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not load workspaces.");
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!workspaceId) {
      setTree(null);
      setLoadingTree(false);
      return;
    }
    let cancelled = false;
    setTree(null);
    setTreeTruncated(false);
    setLoadingTree(true);
    setError(null);
    getWorkspaceTree(workspaceId)
      .then((result) => {
        if (cancelled) return;
        setTree(result.root);
        setTreeTruncated(result.truncated);
        setLoadingTree(false);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setTree(null);
        setLoadingTree(false);
        setError(cause instanceof Error ? cause.message : "Could not read the workspace tree.");
      });
    return () => { cancelled = true; };
  }, [refreshToken, workspaceId]);

  const openFile = useCallback(async (path: string, line?: number) => {
    if (!workspaceId) return;
    const request = ++requestSequence.current;
    setError(null);
    try {
      const file = await getFile(workspaceId, path, "working");
      if (request !== requestSequence.current) return;
      const document: OpenDocument = {
        id: `file:${path}`,
        label: shortLabel(path),
        path,
        content: file.content,
        kind: "file",
        line,
      };
      setDocuments((current) => {
        const found = current.findIndex((item) => item.id === document.id);
        if (found < 0) return [...current, document];
        const next = current.slice();
        next[found] = document;
        return next;
      });
      setActiveDocumentId(document.id);
    } catch (cause) {
      if (request === requestSequence.current) {
        setError(cause instanceof Error ? cause.message : "Could not open the file.");
      }
    }
  }, [workspaceId]);

  useEffect(() => {
    if (!tree || documents.length > 0) return;
    const files = flattenFiles(tree);
    const first = files.find((path) => path.toLowerCase() === "readme.md")
      ?? files.find((path) => path.endsWith("/README.md"))
      ?? files[0];
    if (first) void openFile(first);
  }, [documents.length, openFile, tree]);

  useEffect(() => {
    setDocuments([]);
    setActiveDocumentId(null);
    requestSequence.current += 1;
  }, [workspaceId]);

  function openDiff(path: string, patch: string, staged: boolean) {
    const document: OpenDocument = {
      id: `diff:${staged ? "staged" : "working"}:${path}`,
      label: `${shortLabel(path)} (${staged ? "index" : "working"})`,
      path: `${path}.diff`,
      content: patch,
      kind: "diff",
    };
    setDocuments((current) => {
      const index = current.findIndex((item) => item.id === document.id);
      if (index < 0) return [...current, document];
      const next = current.slice();
      next[index] = document;
      return next;
    });
    setActiveDocumentId(document.id);
  }

  function closeDocument(id: string) {
    setDocuments((current) => {
      const index = current.findIndex((item) => item.id === id);
      const next = current.filter((item) => item.id !== id);
      if (activeDocumentId === id) {
        setActiveDocumentId(next[Math.max(0, index - 1)]?.id ?? next[0]?.id ?? null);
      }
      return next;
    });
  }

  const sideContent = (() => {
    if (!workspace) return <div className="ide-side-message">No active workspace is available.</div>;
    if (view === "explorer") {
      return <ExplorerPanel tree={tree} selected={activeDocument?.kind === "file" ? activeDocument.path : null} loading={loadingTree} truncated={treeTruncated} onOpen={(path) => void openFile(path)} />;
    }
    if (view === "search") {
      return <SearchPanel workspaceId={workspace.id} tree={tree} onOpen={(path, line) => void openFile(path, line)} />;
    }
    if (view === "source_control") {
      return <SourceControlPanel workspaceId={workspace.id} hostExecution={hostExecution} onOpenDiff={openDiff} />;
    }
    return (
      <div className="ide-terminal-sidebar">
        <div className={`ide-lock-note ${hostExecution ? "is-enabled" : ""}`}>
          <Icon name={hostExecution ? "check" : "security"} size={16} />
          <span><strong>{hostExecution ? "Trusted terminal enabled" : "Terminal locked"}</strong>{hostExecution ? "Commands run only in the selected workspace." : "Set ENABLE_HOST_EXECUTION=true in backend/.env and restart to opt in."}</span>
        </div>
        <h3>Security boundary</h3>
        <p>The terminal belongs to you, the local operator. Research agents never receive shell access automatically.</p>
        <code>{workspace.path}</code>
      </div>
    );
  })();

  return (
    <div className="ide-workbench">
      <aside className="ide-sidebar">
        <header className="ide-sidebar-header">
          <span>{VIEW_TITLES[view]}</span>
          <button type="button" onClick={() => setRefreshToken((value) => value + 1)} aria-label="Refresh workspace" title="Refresh"><Icon name="refresh" size={15} /></button>
        </header>
        <label className="ide-workspace-picker">
          <span>Workspace</span>
          <select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)} disabled={workspaces.length === 0}>
            {workspaces.map((item) => <option key={item.id} value={item.id}>{item.slug}</option>)}
          </select>
        </label>
        {error && <p className="ide-inline-error">{error}</p>}
        <div className="ide-sidebar-content">{sideContent}</div>
      </aside>

      <main className="ide-editor-group">
        {view === "terminal" ? (
          <>
            <div className="ide-editor-tabs"><div className="ide-editor-tab is-active"><Icon name="terminal" size={14} /><span>Terminal</span></div></div>
            <div className="ide-terminal-area">
              {!workspace ? (
                <div className="ide-editor-empty"><Icon name="terminal" size={44} /><h2>No active workspace</h2><p>Create or restore a workspace before opening its terminal.</p></div>
              ) : !hostExecution ? (
                <div className="ide-editor-empty"><Icon name="terminal" size={44} /><h2>Trusted terminal is locked</h2><p>Enable <code>ENABLE_HOST_EXECUTION=true</code> only when you intend to run local commands, then restart the backend and reload this page.</p></div>
              ) : (
                <Suspense fallback={<div className="ide-side-message">Loading terminal…</div>}>
                  <TerminalTab workspaceId={workspace.id} active />
                </Suspense>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="ide-editor-tabs">
              {documents.map((document) => (
                <div key={document.id} className={`ide-editor-tab ${document.id === activeDocumentId ? "is-active" : ""}`}>
                  <button type="button" className="ide-tab-select" onClick={() => setActiveDocumentId(document.id)} title={document.path}><Icon name={document.kind === "diff" ? "sourceControl" : "file"} size={14} /><span>{document.label}</span></button>
                  <button type="button" className="ide-tab-close" onClick={() => closeDocument(document.id)} aria-label={`Close ${document.label}`}><Icon name="close" size={12} /></button>
                </div>
              ))}
            </div>
            <div className="ide-breadcrumbs">
              {activeDocument ? activeDocument.path.split("/").map((part, index, parts) => <span key={`${part}:${index}`}>{part}{index < parts.length - 1 && <Icon name="chevronRight" size={11} />}</span>) : <span>{workspace?.slug ?? "Workspace"}</span>}
            </div>
            <div className="ide-editor-content">
              {activeDocument ? (
                <Suspense fallback={<div className="ide-side-message">Loading code editor…</div>}>
                  <CodeEditor path={activeDocument.path} content={activeDocument.content} line={activeDocument.line} language={activeDocument.kind === "diff" ? "diff" : undefined} />
                </Suspense>
              ) : (
                <div className="ide-editor-empty"><div className="ide-empty-mark">λ</div><h2>Lemma Workbench</h2><p>Choose a file in Explorer, search the project, or inspect a Source Control change.</p><dl><div><dt>Explorer</dt><dd>⌘1</dd></div><div><dt>Search</dt><dd>⌘2</dd></div><div><dt>Command palette</dt><dd>⌘K</dd></div></dl></div>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
