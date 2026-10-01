import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  cancelEvaluation,
  createEvaluation,
  getEvaluation,
  listEvaluations,
  runEvaluation,
  scoreEvaluationCandidate,
  type EvaluationDetail,
} from "../../lib/api";
import { useAsyncAction } from "../../lib/asyncAction";
import { AgentAvatar, Badge, Button, EmptyState, Field, Modal, StatusBadge } from "../components/UI";
import { useLabStore } from "../store";
import type { EvaluationExperiment } from "../types";

function ExperimentForm({ projectId, suggestedModels, onSaved, onClose }: {
  projectId: string;
  suggestedModels: string[];
  onSaved: (experiment: EvaluationExperiment) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [models, setModels] = useState(suggestedModels.join(", "));
  const [criteria, setCriteria] = useState("quality, calibration, usefulness");
  const action = useAsyncAction({ fallbackError: "Could not create the evaluation." });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const modelList = [...new Set(models.split(",").map((item) => item.trim()).filter(Boolean))];
    const criterionList = [...new Set(criteria.split(",").map((item) => item.trim()).filter(Boolean))];
    const result = await action.run(() => createEvaluation({
      project_id: projectId,
      name,
      prompt,
      models: modelList,
      criteria: criterionList,
    }));
    if (result.ok) { onSaved(result.value); onClose(); }
  }

  const modelCount = new Set(models.split(",").map((item) => item.trim()).filter(Boolean)).size;
  return <form className="lab-form" onSubmit={(event) => void submit(event)}>
    <Field label="Experiment name"><input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} autoFocus /></Field>
    <Field label="Shared prompt" hint="Every candidate receives exactly this prompt and the same safety system message."><textarea required rows={8} maxLength={20000} value={prompt} onChange={(event) => setPrompt(event.target.value)} /></Field>
    <Field label="Model IDs" hint="Two to eight configured model IDs, separated by commas."><textarea required rows={3} value={models} onChange={(event) => setModels(event.target.value)} /></Field>
    <Field label="Human scoring criteria"><input required value={criteria} onChange={(event) => setCriteria(event.target.value)} /></Field>
    {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
    <div className="lab-form-actions"><Button onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" disabled={action.pending || !name.trim() || !prompt.trim() || modelCount < 2}>{action.pending ? "Creating…" : `Create ${modelCount}-model arena`}</Button></div>
  </form>;
}

export default function EvaluationsView() {
  const snapshot = useLabStore((state) => state.snapshot);
  const selectedProjectId = useLabStore((state) => state.selectedProjectId);
  const project = snapshot.projects.find((item) => item.id === selectedProjectId)
    ?? snapshot.projects[0]
    ?? null;
  const modelIds = useMemo(
    () => [...new Set(snapshot.agents.map((agent) => agent.model).filter(Boolean))],
    [snapshot.agents],
  );
  const [experiments, setExperiments] = useState<EvaluationExperiment[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EvaluationDetail | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [scoreDrafts, setScoreDrafts] = useState<Record<string, string>>({});
  const action = useAsyncAction({ fallbackError: "The evaluation action failed." });

  async function reloadList(preferredId?: string) {
    if (!project) return;
    const rows = await listEvaluations(project.id);
    setExperiments(rows);
    setSelectedId((current) => preferredId ?? current ?? rows[0]?.id ?? null);
  }

  async function reloadDetail(id = selectedId) {
    if (!id) { setDetail(null); return; }
    setDetail(await getEvaluation(id));
  }

  useEffect(() => {
    setExperiments([]); setSelectedId(null); setDetail(null);
    if (project) void reloadList().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  useEffect(() => { void reloadDetail().catch(() => {}); }, [selectedId]);

  useEffect(() => {
    if (detail?.experiment.status !== "running" || !selectedId) return undefined;
    const timer = window.setInterval(() => void reloadDetail(selectedId).then(() => reloadList(selectedId)).catch(() => {}), 1200);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.experiment.status, selectedId]);

  async function start() {
    if (!selectedId) return;
    const result = await action.run(() => runEvaluation(selectedId));
    if (result.ok) { await reloadDetail(selectedId); await reloadList(selectedId); }
  }

  async function cancel() {
    if (!selectedId) return;
    const result = await action.run(() => cancelEvaluation(selectedId));
    if (result.ok) { await reloadDetail(selectedId); await reloadList(selectedId); }
  }

  async function score(candidateId: string, criterion: string) {
    const key = `${candidateId}:${criterion}`;
    const value = Number(scoreDrafts[key]);
    if (!Number.isFinite(value)) return;
    const result = await action.run(() => scoreEvaluationCandidate(candidateId, criterion, value));
    if (result.ok) await reloadDetail();
  }

  if (!project) return <EmptyState icon="research" title="Create a project first" detail="Model comparisons are tied to a project policy, budget, and durable history." />;

  return <main className="lab-view lab-evaluations-view">
    <header className="lab-page-header"><div><span className="lab-eyebrow">CONTROLLED COMPARISON</span><h1>Model evaluation arena</h1><p>Send one bounded prompt to several configured models, preserve exact provenance, and score the outputs yourself.</p></div><Button variant="primary" icon="plus" onClick={() => setShowCreate(true)}>New experiment</Button></header>
    <div className="lab-evaluation-layout">
      <aside className="lab-panel-card lab-evaluation-list"><header className="lab-card-header"><div><h2>{project.name}</h2><p>Experiments</p></div><Badge>{experiments.length}</Badge></header>{experiments.map((experiment) => <button key={experiment.id} type="button" className={selectedId === experiment.id ? "is-selected" : ""} onClick={() => setSelectedId(experiment.id)}><span><strong>{experiment.name}</strong><small>{experiment.models.length} models</small></span><StatusBadge status={experiment.status} /></button>)}{experiments.length === 0 && <p className="lab-card-empty">No comparisons yet.</p>}</aside>
      <section className="lab-evaluation-main">
        {!detail ? <EmptyState icon="research" title="Create a controlled comparison" detail="Use at least two configured model IDs and explicit criteria. Candidates run sequentially to bound spend." /> : <>
          <section className="lab-panel-card lab-evaluation-brief"><header className="lab-card-header"><div><h2>{detail.experiment.name}</h2><p>{detail.experiment.prompt}</p></div><StatusBadge status={detail.experiment.status} /></header><div className="lab-inline-actions">{["draft", "failed"].includes(detail.experiment.status) && <Button variant="primary" icon="play" onClick={() => void start()} disabled={action.pending}>Run candidates</Button>}{detail.experiment.status === "running" && <Button variant="danger" onClick={() => void cancel()}>Cancel evaluation</Button>}<span>{detail.experiment.criteria.join(" · ")}</span></div></section>
          <div className="lab-candidate-grid">{detail.candidates.map((candidate) => {
            const existing = detail.scores.filter((item) => item.candidate_id === candidate.id);
            return <article key={candidate.id} className="lab-panel-card lab-candidate-card"><header><AgentAvatar name={candidate.model} /><div><h2>{candidate.model}</h2><small>{candidate.tokens_in + candidate.tokens_out} tokens · ${candidate.usd.toFixed(4)} · {candidate.latency_ms ?? 0}ms</small></div><StatusBadge status={candidate.status} /></header><pre>{candidate.response || candidate.error || (candidate.status === "running" ? "Generating…" : "Not run")}</pre><section className="lab-score-grid"><h3>Human scores</h3>{detail.experiment.criteria.map((criterion) => { const prior = existing.filter((item) => item.criterion === criterion).at(-1); const key = `${candidate.id}:${criterion}`; return <div key={criterion}><label><span>{criterion}</span><input aria-label={`${criterion} score for ${candidate.model}`} type="number" min="0" max="10" step="0.5" value={scoreDrafts[key] ?? prior?.score ?? ""} onChange={(event) => setScoreDrafts((items) => ({ ...items, [key]: event.target.value }))} /></label><Button variant="ghost" onClick={() => void score(candidate.id, criterion)}>Save</Button></div>; })}</section></article>;
          })}</div>
        </>}
      </section>
    </div>
    {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
    {showCreate && <Modal title="New model evaluation" description="Model IDs must already exist in backend/config.toml; every call obeys the project's policy." onClose={() => setShowCreate(false)}><ExperimentForm projectId={project.id} suggestedModels={modelIds} onSaved={(experiment) => { setExperiments((items) => [experiment, ...items]); setSelectedId(experiment.id); }} onClose={() => setShowCreate(false)} /></Modal>}
  </main>;
}
