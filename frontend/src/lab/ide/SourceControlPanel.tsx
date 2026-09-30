import { useCallback, useEffect, useMemo, useState } from "react";

import {
  commitGitChanges,
  getGitDiff,
  getGitStatus,
  pushGitBranch,
  stageGitPaths,
  type GitChange,
  type GitStatus,
  unstageGitPaths,
} from "../../lib/api";
import { Icon } from "../components/Icons";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Source-control operation failed.";
}

const CHANGE_CODES: Record<string, string> = {
  added: "A",
  changed: "M",
  conflict: "!",
  copied: "C",
  deleted: "D",
  modified: "M",
  renamed: "R",
  "type changed": "T",
  untracked: "U",
};

function ChangeRow({ change, locked, onDiff, onToggle }: { change: GitChange; locked: boolean; onDiff: () => void; onToggle: () => void }) {
  return (
    <div className={`ide-change-row ${change.conflict ? "is-conflict" : ""}`}>
      <button type="button" onClick={onDiff} title={`Open diff for ${change.path}`}>
        <span>{change.path.split("/").pop()}</span><small>{change.path.includes("/") ? change.path.slice(0, change.path.lastIndexOf("/")) : ""}</small>
      </button>
      <span className="ide-change-code" title={change.status}>{CHANGE_CODES[change.status] ?? (`${change.index}${change.working_tree}`.trim() || "M")}</span>
      <button type="button" className="ide-change-action" disabled={locked} onClick={onToggle} title={locked ? "Host execution is locked" : change.staged ? "Unstage changes" : "Stage changes"}>{change.staged ? "−" : "+"}</button>
    </div>
  );
}

export default function SourceControlPanel({
  workspaceId,
  hostExecution,
  onOpenDiff,
}: {
  workspaceId: string;
  hostExecution: boolean;
  onOpenDiff: (path: string, patch: string, staged: boolean) => void;
}) {
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmPush, setConfirmPush] = useState(false);

  const refresh = useCallback(async () => {
    setError(null);
    try { setStatus(await getGitStatus(workspaceId)); }
    catch (cause) { setError(errorMessage(cause)); }
  }, [workspaceId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const staged = useMemo(() => status?.changes.filter((change) => change.staged) ?? [], [status]);
  const unstaged = useMemo(() => status?.changes.filter((change) => !change.staged) ?? [], [status]);
  const remote = status?.upstream?.split("/")[0] || "origin";
  const branch = status?.branch || "";
  const locked = !hostExecution || busy;

  async function mutate(operation: () => Promise<GitStatus>, success?: string) {
    setBusy(true); setError(null); setNotice(null);
    try { setStatus(await operation()); if (success) setNotice(success); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function openDiff(change: GitChange) {
    setError(null);
    try {
      const result = await getGitDiff(workspaceId, change.path, change.staged);
      onOpenDiff(change.path, result.patch || "No textual diff is available for this file.", result.staged);
    } catch (cause) { setError(errorMessage(cause)); }
  }

  async function commit() {
    if (!message.trim()) { setError("Enter a commit message first."); return; }
    setBusy(true); setError(null); setNotice(null);
    try {
      const result = await commitGitChanges(workspaceId, message.trim());
      setStatus(result.status); setMessage(""); setNotice(`Committed ${result.commit.slice(0, 8)} · ${result.summary}`);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function push() {
    setConfirmPush(false); setBusy(true); setError(null); setNotice(null);
    try {
      const result = await pushGitBranch(workspaceId, remote, branch);
      setStatus(result.status); setNotice(result.output || `Pushed ${result.branch} to ${result.remote}.`);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  if (!status && !error) return <div className="ide-side-message"><span className="lab-spinner" />Reading repository…</div>;

  return (
    <div className="ide-scm-panel">
      {!hostExecution && <div className="ide-lock-note"><Icon name="security" size={15} /><span><strong>Git writes are locked</strong>Enable trusted host execution to stage, commit, or push. Status and diffs remain readable.</span></div>}
      {error && <p className="ide-inline-error">{error}</p>}
      {notice && <p className="ide-inline-success">{notice}</p>}
      {status && !status.repository && <div className="ide-side-message">This workspace is not a Git repository.</div>}
      {status?.repository && (
        <>
          <div className="ide-scm-branch"><Icon name="branch" size={15} /><span>{status.detached ? "detached HEAD" : status.branch}</span>{status.upstream && <small>{status.ahead > 0 ? `↑${status.ahead}` : ""} {status.behind > 0 ? `↓${status.behind}` : ""}</small>}<button type="button" onClick={() => void refresh()} aria-label="Refresh source control"><Icon name="refresh" size={14} /></button></div>
          <div className="ide-commit-box">
            <textarea rows={3} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Message (⌘Enter to commit)" onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") void commit(); }} />
            <button type="button" disabled={locked || !message.trim() || staged.length === 0} onClick={() => void commit()}>{busy ? "Working…" : "Commit"}</button>
          </div>
          {staged.length > 0 && <section className="ide-change-group"><header><span><Icon name="chevronDown" size={13} /> Staged Changes</span><button type="button" disabled={locked} onClick={() => void mutate(() => unstageGitPaths(workspaceId, staged.map((item) => item.path)))} title="Unstage all">−</button></header>{staged.map((change) => <ChangeRow key={`s:${change.path}`} change={change} locked={locked} onDiff={() => void openDiff(change)} onToggle={() => void mutate(() => unstageGitPaths(workspaceId, [change.path]))} />)}</section>}
          {unstaged.length > 0 && <section className="ide-change-group"><header><span><Icon name="chevronDown" size={13} /> Changes</span><button type="button" disabled={locked} onClick={() => void mutate(() => stageGitPaths(workspaceId, unstaged.map((item) => item.path)))} title="Stage all">+</button></header>{unstaged.map((change) => <ChangeRow key={`u:${change.path}`} change={change} locked={locked} onDiff={() => void openDiff(change)} onToggle={() => void mutate(() => stageGitPaths(workspaceId, [change.path]))} />)}</section>}
          {status.clean && <div className="ide-clean-state"><Icon name="check" size={22} /><strong>No changes</strong><span>Your working tree is clean.</span></div>}
          <div className="ide-scm-actions"><button type="button" disabled={locked || !branch || !status.upstream} onClick={() => setConfirmPush(true)}><Icon name="cloudUpload" size={15} /> Push to {remote}</button>{!status.upstream && <small>Configure an upstream before pushing.</small>}</div>
        </>
      )}
      {confirmPush && <div className="ide-confirm-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setConfirmPush(false)}><div className="ide-confirm" role="alertdialog" aria-modal="true" aria-labelledby="push-title"><Icon name="cloudUpload" size={26} /><h2 id="push-title">Push changes?</h2><p>This sends local commits from <strong>{branch}</strong> to the configured <strong>{remote}</strong> remote. This affects an external repository.</p><div><button type="button" onClick={() => setConfirmPush(false)}>Cancel</button><button type="button" className="is-primary" onClick={() => void push()}>Push {branch}</button></div></div></div>}
    </div>
  );
}
