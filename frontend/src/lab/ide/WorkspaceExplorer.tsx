import { useEffect, useMemo, useState } from "react";

import { getFile, type WorkspaceTreeNode } from "../../lib/api";
import { Icon } from "../components/Icons";

function extensionClass(name: string): string {
  const extension = name.split(".").pop()?.toLowerCase();
  if (["ts", "tsx", "js", "jsx"].includes(extension ?? "")) return "is-code";
  if (["json", "yaml", "yml", "toml"].includes(extension ?? "")) return "is-config";
  if (["md", "txt"].includes(extension ?? "")) return "is-doc";
  return "";
}

function TreeRow({
  node,
  depth,
  selected,
  expanded,
  toggle,
  open,
}: {
  node: WorkspaceTreeNode;
  depth: number;
  selected: string | null;
  expanded: Set<string>;
  toggle: (path: string) => void;
  open: (path: string) => void;
}) {
  const directory = node.type === "directory";
  const isOpen = directory && expanded.has(node.path);
  return (
    <>
      <button
        type="button"
        className={`ide-tree-row ${selected === node.path ? "is-selected" : ""}`}
        style={{ paddingLeft: 8 + depth * 13 }}
        onClick={() => directory ? toggle(node.path) : open(node.path)}
        title={node.path || node.name}
      >
        <span className="ide-tree-arrow">{directory && <Icon name={isOpen ? "chevronDown" : "chevronRight"} size={13} />}</span>
        <Icon name={directory ? "folder" : "file"} size={15} />
        <span className={directory ? "" : extensionClass(node.name)}>{node.name}</span>
      </button>
      {directory && isOpen && node.children?.map((child) => (
        <TreeRow key={child.path} node={child} depth={depth + 1} selected={selected} expanded={expanded} toggle={toggle} open={open} />
      ))}
    </>
  );
}

export function ExplorerPanel({
  tree,
  selected,
  loading,
  truncated,
  onOpen,
}: {
  tree: WorkspaceTreeNode | null;
  selected: string | null;
  loading: boolean;
  truncated: boolean;
  onOpen: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([""]));

  useEffect(() => {
    if (!tree) return;
    setExpanded(new Set([tree.path, ...(tree.children ?? []).filter((node) => node.type === "directory").slice(0, 4).map((node) => node.path)]));
  }, [tree]);

  function toggle(path: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  }

  if (loading) return <div className="ide-side-message"><span className="lab-spinner" />Loading project files…</div>;
  if (!tree) return <div className="ide-side-message">No project tree is available.</div>;

  return (
    <div className="ide-tree" role="tree" aria-label="Workspace files">
      <div className="ide-section-title"><span><Icon name="chevronDown" size={13} /> {tree.name}</span></div>
      {(tree.children ?? []).map((node) => (
        <TreeRow key={node.path} node={node} depth={0} selected={selected} expanded={expanded} toggle={toggle} open={onOpen} />
      ))}
      {truncated && <p className="ide-tree-note">Large tree truncated for safety. Use Search or Terminal for deeper paths.</p>}
    </div>
  );
}

function flatten(node: WorkspaceTreeNode | null): string[] {
  if (!node) return [];
  if (node.type === "file") return [node.path];
  return (node.children ?? []).flatMap(flatten);
}

interface Match { path: string; line: number; preview: string }

export function SearchPanel({
  workspaceId,
  tree,
  onOpen,
}: {
  workspaceId: string;
  tree: WorkspaceTreeNode | null;
  onOpen: (path: string, line?: number) => void;
}) {
  const paths = useMemo(() => flatten(tree), [tree]);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<Match[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search() {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) { setMatches([]); return; }
    setSearching(true);
    setError(null);
    const found: Match[] = [];
    try {
      const bounded = paths.slice(0, 250);
      for (let offset = 0; offset < bounded.length && found.length < 200; offset += 12) {
        const batch = await Promise.all(bounded.slice(offset, offset + 12).map(async (path) => {
          try { return { path, content: (await getFile(workspaceId, path)).content }; }
          catch { return null; }
        }));
        for (const file of batch) {
          if (!file || file.content.includes("\0")) continue;
          file.content.split(/\r?\n/).forEach((line, index) => {
            if (found.length < 200 && line.toLocaleLowerCase().includes(needle)) {
              found.push({ path: file.path, line: index + 1, preview: line.trim().slice(0, 180) });
            }
          });
        }
      }
      setMatches(found);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Search failed");
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="ide-search-panel">
      <form onSubmit={(event) => { event.preventDefault(); void search(); }}>
        <label htmlFor="workspace-search">Search files</label>
        <div><input id="workspace-search" autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search" /><button type="submit" aria-label="Search"><Icon name="search" size={15} /></button></div>
      </form>
      <p className="ide-search-meta">{searching ? "Searching…" : matches.length ? `${matches.length}${matches.length === 200 ? "+" : ""} results` : `Up to ${Math.min(paths.length, 250)} files`}</p>
      {error && <p className="ide-inline-error">{error}</p>}
      <div className="ide-search-results">
        {matches.map((match, index) => (
          <button key={`${match.path}:${match.line}:${index}`} type="button" onClick={() => onOpen(match.path, match.line)}>
            <strong><Icon name="file" size={13} />{match.path}</strong>
            <span><b>{match.line}</b>{match.preview || "(blank line)"}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

