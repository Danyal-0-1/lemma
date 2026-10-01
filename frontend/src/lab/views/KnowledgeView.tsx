import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  archiveSourceDocument,
  attachClaimEvidence,
  createResearchClaim,
  createSourceDocument,
  createSourceExcerpt,
  createTraceLink,
  downloadProjectDossier,
  getProjectDossier,
  getWorkspaces,
  linkSourceToTask,
  listProjectSources,
  promoteActionItem,
  reviewFinding,
  searchResearch,
  unlinkSourceFromTask,
  updateActionItem,
  type SearchMatch,
  type WorkspaceSummary,
} from "../../lib/api";
import { useAsyncAction } from "../../lib/asyncAction";
import { Icon } from "../components/Icons";
import { Badge, Button, EmptyState, Field, Modal, StatusBadge } from "../components/UI";
import { useLabStore } from "../store";
import type { ProjectDossier, SourceDocument } from "../types";

type Tab = "sources" | "findings" | "search" | "dossier";

function SourceForm({ projectId, onSaved, onClose }: {
  projectId: string;
  onSaved: (source: SourceDocument) => void;
  onClose: () => void;
}) {
  const [title, setTitle] = useState("");
  const [origin, setOrigin] = useState("");
  const [sourceType, setSourceType] = useState("note");
  const [content, setContent] = useState("");
  const action = useAsyncAction({ fallbackError: "Could not capture the source." });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(() => createSourceDocument({
      project_id: projectId,
      title,
      source_type: sourceType,
      origin,
      content,
    }));
    if (result.ok) {
      onSaved(result.value);
      onClose();
    }
  }

  return (
    <form className="lab-form" onSubmit={(event) => void submit(event)}>
      <div className="lab-form-grid">
        <Field label="Source title"><input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} autoFocus /></Field>
        <Field label="Type">
          <select value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
            <option value="note">Note</option><option value="url">URL capture</option>
            <option value="file">File capture</option><option value="transcript">Transcript</option>
          </select>
        </Field>
        <div className="lab-field-span-2"><Field label="Origin" hint="URL, filename, notebook, interview, or other provenance."><input maxLength={1000} value={origin} onChange={(event) => setOrigin(event.target.value)} /></Field></div>
        <div className="lab-field-span-2"><Field label="Captured content" hint="Stored locally with a SHA-256 content identity."><textarea required rows={12} maxLength={500000} value={content} onChange={(event) => setContent(event.target.value)} /></Field></div>
      </div>
      {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
      <div className="lab-form-actions"><Button onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" disabled={action.pending || !title.trim() || !content.trim()}>{action.pending ? "Capturing…" : "Capture source"}</Button></div>
    </form>
  );
}

export default function KnowledgeView() {
  const snapshot = useLabStore((state) => state.snapshot);
  const selectedProjectId = useLabStore((state) => state.selectedProjectId);
  const project = snapshot.projects.find((item) => item.id === selectedProjectId)
    ?? snapshot.projects[0]
    ?? null;
  const [tab, setTab] = useState<Tab>("sources");
  const [sources, setSources] = useState<SourceDocument[]>([]);
  const [dossier, setDossier] = useState<ProjectDossier | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [showSource, setShowSource] = useState(false);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<SearchMatch[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [quote, setQuote] = useState("");
  const [locator, setLocator] = useState("");
  const [selectedExcerptId, setSelectedExcerptId] = useState("");
  const [claimText, setClaimText] = useState("");
  const [claimFindingId, setClaimFindingId] = useState("");
  const [traceSource, setTraceSource] = useState("");
  const [traceWorkspace, setTraceWorkspace] = useState("");
  const [actionAssignees, setActionAssignees] = useState<Record<string, string>>({});
  const action = useAsyncAction({ fallbackError: "The evidence action failed." });

  const findings = useMemo(
    () => project ? snapshot.findings.filter((item) => item.project_id === project.id) : [],
    [project, snapshot.findings],
  );
  const tasks = useMemo(
    () => project ? snapshot.tasks.filter((item) => item.project_id === project.id) : [],
    [project, snapshot.tasks],
  );
  const selectedTaskLinks = useMemo(
    () => dossier?.source_links.filter((link) => link.task_id === selectedTaskId) ?? [],
    [dossier?.source_links, selectedTaskId],
  );
  const sourceAlreadyLinked = selectedTaskLinks.some(
    (link) => link.source_id === selectedSourceId,
  );

  async function reload(preferredExcerptId?: string) {
    if (!project) return;
    const [nextSources, nextDossier, nextWorkspaces] = await Promise.all([
      listProjectSources(project.id),
      getProjectDossier(project.id),
      getWorkspaces(),
    ]);
    setSources(nextSources);
    setDossier(nextDossier);
    setWorkspaces(nextWorkspaces.filter((item) => item.status === "active"));
    setSelectedSourceId((current) => (
      nextSources.some((source) => source.id === current) ? current : nextSources[0]?.id || ""
    ));
    setSelectedTaskId((current) => (
      tasks.some((task) => task.id === current) ? current : tasks[0]?.id || ""
    ));
    setSelectedExcerptId((current) => {
      if (preferredExcerptId) return preferredExcerptId;
      return nextDossier.excerpts.some((excerpt) => excerpt.id === current) ? current : "";
    });
  }

  useEffect(() => {
    setSources([]); setDossier(null); setSelectedSourceId(""); setSelectedTaskId("");
    setSelectedExcerptId(""); setMatches([]);
    if (project) void reload().catch(() => {});
    // Project identity intentionally resets the project-scoped evidence view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  async function runSearch(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    const result = await action.run(() => searchResearch(query, project.id));
    if (result.ok) setMatches(result.value);
  }

  async function linkSource() {
    if (!selectedSourceId || !selectedTaskId) return;
    const result = await action.run(() => linkSourceToTask(selectedTaskId, selectedSourceId));
    if (result.ok) await reload();
  }

  async function captureExcerpt(event: FormEvent) {
    event.preventDefault();
    if (!selectedSourceId) return;
    const result = await action.run(() => createSourceExcerpt(selectedSourceId, { quote, locator }));
    if (result.ok) {
      setQuote(""); setLocator("");
      await reload(result.value.id);
    }
  }

  async function addClaim(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    const result = await action.run(async () => {
      const claim = await createResearchClaim({
        project_id: project.id,
        ...(claimFindingId ? { finding_id: claimFindingId } : {}),
        statement: claimText,
      });
      if (selectedExcerptId) {
        await attachClaimEvidence(claim.id, selectedExcerptId, "supports");
      }
      return claim;
    });
    if (result.ok) {
      setClaimText(""); setClaimFindingId("");
      await reload();
    }
  }

  async function addTrace() {
    if (!project || !traceSource || !traceWorkspace) return;
    const [sourceType, sourceId] = traceSource.split(":", 2);
    const result = await action.run(() => createTraceLink({
      project_id: project.id,
      source_type: sourceType,
      source_id: sourceId,
      target_type: "workspace",
      target_id: traceWorkspace,
      relationship: "informs",
      note: "Linked by founder from the evidence library.",
    }));
    if (result.ok) await reload();
  }

  if (!project) return <EmptyState icon="research" title="Create a research project first" detail="The evidence library is project-scoped so every source and claim has a durable home." />;

  return (
    <main className="lab-view lab-knowledge-view">
      <header className="lab-page-header">
        <div><span className="lab-eyebrow">EVIDENCE & TRACEABILITY</span><h1>{project.name} knowledge base</h1><p>Capture sources, review findings, normalize claims, search locally, and export a decision dossier.</p></div>
        <div className="lab-header-actions"><Button icon="plus" onClick={() => setShowSource(true)}>Capture source</Button><Button variant="primary" onClick={() => void action.run(() => downloadProjectDossier(project.id))}>Export dossier</Button></div>
      </header>

      <nav className="lab-subtabs" aria-label="Knowledge sections">
        {(["sources", "findings", "search", "dossier"] as Tab[]).map((item) => <button type="button" key={item} className={tab === item ? "is-active" : ""} onClick={() => setTab(item)}>{item}</button>)}
      </nav>

      {tab === "sources" && <div className="lab-dashboard-grid">
        <section className="lab-panel-card lab-span-2">
          <header className="lab-card-header"><div><h2>Source library</h2><p>Captured content is immutable in identity; archive superseded records.</p></div><Badge>{sources.length}</Badge></header>
          <div className="lab-source-list">
            {sources.map((source) => <article key={source.id} className={selectedSourceId === source.id ? "is-selected" : ""}>
              <button type="button" onClick={() => setSelectedSourceId(source.id)}><span><strong>{source.title}</strong><small>{source.source_type} · {source.origin || "local capture"}</small></span><code>{source.content_sha256.slice(0, 10)}</code></button>
              <p>{source.content.slice(0, 260)}{source.content.length > 260 ? "…" : ""}</p>
              <Button variant="ghost" onClick={() => void action.run(async () => { await archiveSourceDocument(source.id); await reload(); })}>Archive</Button>
            </article>)}
            {sources.length === 0 && <p className="lab-card-empty">No captured sources yet.</p>}
          </div>
        </section>
        <section className="lab-panel-card">
          <header className="lab-card-header"><div><h2>Source packet</h2><p>Give a task explicit, auditable context.</p></div></header>
          <Field label="Source"><select value={selectedSourceId} onChange={(event) => setSelectedSourceId(event.target.value)}><option value="">Select source</option>{sources.map((source) => <option key={source.id} value={source.id}>{source.title}</option>)}</select></Field>
          <Field label="Task"><select value={selectedTaskId} onChange={(event) => setSelectedTaskId(event.target.value)}><option value="">Select task</option>{tasks.map((task) => <option key={task.id} value={task.id}>{task.title}</option>)}</select></Field>
          <Button variant="primary" disabled={!selectedSourceId || !selectedTaskId || sourceAlreadyLinked || action.pending} onClick={() => void linkSource()}>{sourceAlreadyLinked ? "Already attached" : "Attach to task"}</Button>
          <div className="lab-compact-list">{selectedTaskLinks.map((link) => <div key={link.id}><span><strong>{sources.find((source) => source.id === link.source_id)?.title ?? "Archived source"}</strong><small>{link.purpose}</small></span><Button variant="ghost" onClick={() => void action.run(async () => { await unlinkSourceFromTask(link.id); await reload(); })}>Remove</Button></div>)}</div>
          <hr />
          <form onSubmit={(event) => void captureExcerpt(event)}>
            <Field label="Exact quotation"><textarea required rows={4} value={quote} onChange={(event) => setQuote(event.target.value)} placeholder="Paste a verbatim passage from the selected source." /></Field>
            <Field label="Locator"><input value={locator} onChange={(event) => setLocator(event.target.value)} placeholder="p. 8, Results, 00:14:22…" /></Field>
            <Button type="submit" disabled={!selectedSourceId || !quote.trim()}>Create excerpt</Button>
          </form>
          {selectedExcerptId && <p className="lab-success-note"><Icon name="check" size={14} /> Evidence excerpt selected for the next claim.</p>}
          <div className="lab-compact-list">{dossier?.excerpts.map((excerpt) => <button type="button" key={excerpt.id} className={selectedExcerptId === excerpt.id ? "is-selected" : ""} onClick={() => setSelectedExcerptId(excerpt.id)}><span><strong>{sources.find((source) => source.id === excerpt.source_id)?.title ?? "Captured source"}</strong><small>{excerpt.locator || "Exact excerpt"} · {excerpt.quote.slice(0, 80)}</small></span></button>)}</div>
        </section>
      </div>}

      {tab === "findings" && <div className="lab-dashboard-grid">
        <section className="lab-panel-card lab-span-2"><header className="lab-card-header"><div><h2>Human review queue</h2><p>Model output remains proposed until a person records a decision.</p></div><Badge>{findings.length}</Badge></header>
          <div className="lab-findings-list">{findings.map((finding) => {
            const latestReview = dossier?.finding_reviews.filter((review) => review.finding_id === finding.id).at(-1);
            const recordReview = (decision: "accepted" | "rejected" | "needs_revision") => action.run(async () => { await reviewFinding(finding.id, decision); await reload(); });
            return <article key={finding.id}><h3>{finding.title}</h3>{latestReview && <StatusBadge status={latestReview.decision} />}<p>{finding.content}</p><div className="lab-inline-actions"><Button onClick={() => void recordReview("accepted")}>Accept</Button><Button onClick={() => void recordReview("needs_revision")}>Needs revision</Button><Button variant="danger" onClick={() => void recordReview("rejected")}>Reject</Button></div></article>;
          })}</div>
        </section>
        <section className="lab-panel-card"><header className="lab-card-header"><div><h2>Normalize a claim</h2><p>Optionally bind it to the excerpt created in Sources.</p></div></header>
          <form onSubmit={(event) => void addClaim(event)}><Field label="Finding"><select value={claimFindingId} onChange={(event) => setClaimFindingId(event.target.value)}><option value="">Independent claim</option>{findings.map((finding) => <option key={finding.id} value={finding.id}>{finding.title}</option>)}</select></Field><Field label="Evidence excerpt"><select value={selectedExcerptId} onChange={(event) => setSelectedExcerptId(event.target.value)}><option value="">No evidence link yet</option>{dossier?.excerpts.map((excerpt) => <option key={excerpt.id} value={excerpt.id}>{sources.find((source) => source.id === excerpt.source_id)?.title ?? "Source"} · {excerpt.locator || excerpt.quote.slice(0, 60)}</option>)}</select></Field><Field label="Claim statement"><textarea required rows={5} value={claimText} onChange={(event) => setClaimText(event.target.value)} /></Field><Button type="submit" variant="primary" disabled={!claimText.trim() || action.pending}>Save claim{selectedExcerptId ? " + evidence" : ""}</Button></form>
          <div className="lab-compact-list">{dossier?.claims.map((claim) => <div key={claim.id}><span><strong>{claim.statement}</strong><small>{claim.status} · {claim.confidence ?? "unscored"} · {dossier.claim_evidence.filter((edge) => edge.claim_id === claim.id).length} evidence link(s)</small></span></div>)}</div>
        </section>
      </div>}

      {tab === "search" && <section className="lab-panel-card">
        <header className="lab-card-header"><div><h2>Local full-text retrieval</h2><p>SQLite FTS ranks projects, tasks, sources, findings, claims, and meeting transcripts.</p></div></header>
        <form className="lab-search-form" onSubmit={(event) => void runSearch(event)}><Icon name="search" size={17} /><input required value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search this project's evidence…" /><Button type="submit" variant="primary" disabled={action.pending}>Search</Button></form>
        <div className="lab-search-results">{matches.map((match) => <article key={`${match.kind}:${match.entity_id}`}><Badge>{match.kind}</Badge><h3>{match.title}</h3><p>{match.snippet}</p></article>)}{matches.length === 0 && <p className="lab-card-empty">Enter terms to retrieve ranked local evidence.</p>}</div>
      </section>}

      {tab === "dossier" && dossier && <div className="lab-dashboard-grid">
        <section className="lab-panel-card lab-span-2"><header className="lab-card-header"><div><h2>Project dossier</h2><p>A portable record of evidence, findings, decisions, actions, and downstream links.</p></div><Button onClick={() => void action.run(() => downloadProjectDossier(project.id))}>Download Markdown</Button></header><div className="lab-metrics"><article><span>Sources</span><strong>{dossier.sources.length}</strong></article><article><span>Excerpts</span><strong>{dossier.excerpts.length}</strong></article><article><span>Claims</span><strong>{dossier.claims.length}</strong></article><article><span>Runs</span><strong>{dossier.runs.length}</strong></article></div><div className="lab-dossier-sections"><h3>Decisions</h3>{dossier.outcomes.map((outcome) => <article key={outcome.id}><p>{outcome.summary}</p><ul>{outcome.decisions.map((decision) => <li key={decision}>{decision}</li>)}</ul></article>)}<h3>Actions</h3>{dossier.actions.map((item) => <article key={item.id}><p><StatusBadge status={item.status} /> {item.title}</p><div className="lab-inline-actions">{!item.owner_agent_id && !item.promoted_task_id && <select aria-label={`Owner for ${item.title}`} value={actionAssignees[item.id] ?? ""} onChange={(event) => setActionAssignees((current) => ({ ...current, [item.id]: event.target.value }))}><option value="">Choose owner</option>{snapshot.agents.filter((agent) => agent.status === "active").map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select>}{!item.promoted_task_id && <Button variant="ghost" disabled={!item.owner_agent_id && !actionAssignees[item.id]} onClick={() => void action.run(async () => { await promoteActionItem(item.id, item.owner_agent_id ?? actionAssignees[item.id]); await reload(); await useLabStore.getState().refresh(); })}>Promote to task</Button>}{!(["completed", "cancelled"].includes(item.status)) && <Button onClick={() => void action.run(async () => { await updateActionItem(item.id, { status: "completed" }); await reload(); })}>Complete</Button>}</div></article>)}</div></section>
        <section className="lab-panel-card"><header className="lab-card-header"><div><h2>Downstream trace</h2><p>Link accepted research to a build workspace.</p></div></header><Field label="Research source"><select value={traceSource} onChange={(event) => setTraceSource(event.target.value)}><option value="">Select entity</option>{findings.map((item) => <option key={item.id} value={`finding:${item.id}`}>Finding · {item.title}</option>)}{dossier.claims.map((item) => <option key={item.id} value={`claim:${item.id}`}>Claim · {item.statement.slice(0, 50)}</option>)}</select></Field><Field label="Workspace"><select value={traceWorkspace} onChange={(event) => setTraceWorkspace(event.target.value)}><option value="">Select workspace</option>{workspaces.map((item) => <option key={item.id} value={item.id}>{item.slug}</option>)}</select></Field><Button variant="primary" disabled={!traceSource || !traceWorkspace} onClick={() => void addTrace()}>Create trace link</Button><div className="lab-compact-list">{dossier.trace_links.map((link) => <div key={link.id}><span><strong>{link.source_type} → {link.target_type}</strong><small>{link.relationship}</small></span></div>)}</div></section>
      </div>}

      {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
      {showSource && <Modal title="Capture a source" description="Lemma stores the supplied content locally; it does not fetch a URL automatically." onClose={() => setShowSource(false)}><SourceForm projectId={project.id} onSaved={() => void reload()} onClose={() => setShowSource(false)} /></Modal>}
    </main>
  );
}
