import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  archiveLabTemplate,
  cancelAutomation,
  cancelLabRun,
  createAutomationPlan,
  createLabTemplate,
  decideAutomation,
  getProjectBudget,
  getProjectPolicy,
  getProjectRuns,
  getWorkspaces,
  instantiateLabTemplate,
  listAutomations,
  listLabTemplates,
  retryLabRun,
  runAutomation,
  updateProjectPolicy,
  type WorkspaceSummary,
} from "../../lib/api";
import { useAsyncAction } from "../../lib/asyncAction";
import { useAppStore } from "../../store/appStore";
import { Badge, Button, EmptyState, Field, Modal, StatusBadge } from "../components/UI";
import { useLabStore } from "../store";
import type {
  AutomationRun,
  LabRun,
  LabTemplate,
  ProjectPolicy,
} from "../types";

type Tab = "jobs" | "policy" | "templates" | "automation";

const DEFAULT_POLICY: Omit<ProjectPolicy, "project_id"> = {
  data_classification: "local_only",
  allowed_models: [],
  max_run_tokens: 50000,
  max_run_usd: 5,
  max_project_usd: 100,
  max_concurrent_runs: 2,
};

function AutomationForm({ projectId, workspaces, onSaved, onClose }: {
  projectId: string;
  workspaces: WorkspaceSummary[];
  onSaved: (row: AutomationRun) => void;
  onClose: () => void;
}) {
  const [workspaceId, setWorkspaceId] = useState(workspaces[0]?.id ?? "");
  const [request, setRequest] = useState("");
  const [plan, setPlan] = useState("");
  const [write, setWrite] = useState(false);
  const [checks, setChecks] = useState(true);
  const action = useAsyncAction({ fallbackError: "Could not create the automation plan." });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const capabilities = ["read_workspace"];
    if (write) capabilities.push("write_workspace");
    if (checks) capabilities.push("run_checks");
    const result = await action.run(() => createAutomationPlan({
      project_id: projectId,
      workspace_id: workspaceId,
      request,
      plan,
      capabilities,
    }));
    if (result.ok) { onSaved(result.value); onClose(); }
  }

  return <form className="lab-form" onSubmit={(event) => void submit(event)}>
    <div className="lab-security-banner is-warn"><div><h2>Separate opt-in and billing boundary</h2><p>Headless execution is not the interactive terminal. It requires both host execution and M9 enablement, a configured absolute CLI path, an explicit approval below, and may use a separate metered credit pool.</p></div></div>
    <Field label="Workspace"><select required value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}><option value="">Select active workspace</option>{workspaces.map((item) => <option key={item.id} value={item.id}>{item.slug}</option>)}</select></Field>
    <Field label="Requested change"><textarea required rows={5} maxLength={20000} value={request} onChange={(event) => setRequest(event.target.value)} /></Field>
    <Field label="Approved plan" hint="State files, checks, and stop conditions before approval."><textarea rows={5} maxLength={20000} value={plan} onChange={(event) => setPlan(event.target.value)} /></Field>
    <fieldset className="lab-check-grid"><legend>Capability intent recorded for approval (not an OS sandbox)</legend><label><input type="checkbox" checked readOnly /> Read workspace</label><label><input type="checkbox" checked={write} onChange={(event) => setWrite(event.target.checked)} /> Write workspace</label><label><input type="checkbox" checked={checks} onChange={(event) => setChecks(event.target.checked)} /> Run checks</label></fieldset>
    {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
    <div className="lab-form-actions"><Button onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" disabled={!workspaceId || !request.trim() || action.pending}>Create approval gate</Button></div>
  </form>;
}

function TemplateForm({ onSaved, onClose }: {
  onSaved: (row: LabTemplate) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("task");
  const [description, setDescription] = useState("");
  const [payload, setPayload] = useState("{}");
  const action = useAsyncAction({ fallbackError: "Could not save the template." });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(async () => {
      let parsed: unknown;
      try { parsed = JSON.parse(payload); } catch { throw new Error("Template payload must be valid JSON."); }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Template payload must be a JSON object.");
      return await createLabTemplate({ name, kind, description, payload: parsed as Record<string, unknown> });
    });
    if (result.ok) { onSaved(result.value); onClose(); }
  }

  return <form className="lab-form" onSubmit={(event) => void submit(event)}><Field label="Name"><input required value={name} onChange={(event) => setName(event.target.value)} autoFocus /></Field><Field label="Kind"><select value={kind} onChange={(event) => setKind(event.target.value)}><option value="project">Project</option><option value="task">Task</option><option value="meeting">Meeting</option><option value="evaluation">Evaluation</option></select></Field><Field label="Description"><textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} /></Field><Field label="JSON defaults"><textarea rows={8} value={payload} onChange={(event) => setPayload(event.target.value)} /></Field>{action.error && <p className="lab-inline-error">{action.error}</p>}<div className="lab-form-actions"><Button onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" disabled={!name.trim()}>Save template</Button></div></form>;
}

function TemplateInstantiationForm({ template, onSaved, onClose }: {
  template: LabTemplate;
  onSaved: () => void;
  onClose: () => void;
}) {
  const [overrides, setOverrides] = useState("{}");
  const action = useAsyncAction({ fallbackError: "Could not instantiate the template." });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(async () => {
      let parsed: unknown;
      try { parsed = JSON.parse(overrides); } catch { throw new Error("Overrides must be valid JSON."); }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Overrides must be a JSON object.");
      }
      return await instantiateLabTemplate(template.id, parsed as Record<string, unknown>);
    });
    if (result.ok) { onSaved(); onClose(); }
  }

  return <form className="lab-form" onSubmit={(event) => void submit(event)}><p>The stored JSON below is the base payload. Supply only fields that should be added or replaced; required IDs must be present in either object.</p><pre>{JSON.stringify(template.payload, null, 2)}</pre><Field label="JSON overrides"><textarea rows={10} value={overrides} onChange={(event) => setOverrides(event.target.value)} autoFocus /></Field>{action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}<div className="lab-form-actions"><Button onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" disabled={action.pending}>{action.pending ? "Creating…" : `Create ${template.kind}`}</Button></div></form>;
}

export default function OperationsView() {
  const snapshot = useLabStore((state) => state.snapshot);
  const refreshSnapshot = useLabStore((state) => state.refresh);
  const selectedProjectId = useLabStore((state) => state.selectedProjectId);
  const project = snapshot.projects.find((item) => item.id === selectedProjectId)
    ?? snapshot.projects[0]
    ?? null;
  const [tab, setTab] = useState<Tab>("jobs");
  const [runs, setRuns] = useState<LabRun[]>([]);
  const [policy, setPolicy] = useState<Omit<ProjectPolicy, "project_id">>(DEFAULT_POLICY);
  const [budget, setBudget] = useState<{ tokens_used: number; usd_used: number; running: number } | null>(null);
  const [models, setModels] = useState("");
  const [templates, setTemplates] = useState<LabTemplate[]>([]);
  const [automations, setAutomations] = useState<AutomationRun[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [showAutomation, setShowAutomation] = useState(false);
  const [showTemplate, setShowTemplate] = useState(false);
  const [templateToInstantiate, setTemplateToInstantiate] = useState<LabTemplate | null>(null);
  const action = useAsyncAction({ fallbackError: "The operations request failed." });
  const hostExecution = useAppStore((state) => state.hostExecutionEnabled);
  const headlessCoding = useAppStore((state) => state.headlessCodingEnabled);

  const projectAutomations = useMemo(
    () => automations.filter((row) => row.project_id === project?.id),
    [automations, project?.id],
  );
  const hasRunningWork = runs.some((row) => row.status === "running")
    || projectAutomations.some((row) => row.status === "running");

  async function reload() {
    if (!project) return;
    const [nextRuns, nextPolicy, nextBudget, nextTemplates, nextAutomations, nextWorkspaces] = await Promise.all([
      getProjectRuns(project.id), getProjectPolicy(project.id), getProjectBudget(project.id),
      listLabTemplates(), listAutomations(), getWorkspaces(),
    ]);
    setRuns(nextRuns);
    const { project_id: _id, ...editable } = nextPolicy;
    setPolicy(editable); setModels(nextPolicy.allowed_models.join(", "));
    setBudget(nextBudget); setTemplates(nextTemplates); setAutomations(nextAutomations);
    setWorkspaces(nextWorkspaces.filter((item) => item.status === "active"));
  }

  useEffect(() => { if (project) void reload().catch(() => {}); }, [project?.id]);

  useEffect(() => {
    if (!project || !hasRunningWork) return undefined;
    const timer = window.setInterval(() => void reload().catch(() => {}), 1500);
    return () => window.clearInterval(timer);
    // Poll only while durable background work can change without another UI action.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasRunningWork, project?.id]);

  async function savePolicy(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    const next = { ...policy, allowed_models: [...new Set(models.split(",").map((item) => item.trim()).filter(Boolean))] };
    const result = await action.run(() => updateProjectPolicy(project.id, next));
    if (result.ok) await reload();
  }

  async function cancel(run: LabRun) {
    const result = await action.run(() => cancelLabRun(run.id));
    if (result.ok) { await reload(); await refreshSnapshot(); }
  }

  async function retry(run: LabRun) {
    const result = await action.run(() => retryLabRun(run.id));
    if (result.ok) { await reload(); await refreshSnapshot(); }
  }

  async function decide(row: AutomationRun, decision: "approve" | "reject") {
    const result = await action.run(() => decideAutomation(row.id, decision, decision === "approve" ? "Reviewed in Operations" : "Rejected in Operations"));
    if (result.ok) await reload();
  }

  async function execute(row: AutomationRun) {
    const result = await action.run(() => runAutomation(row.id));
    if (result.ok) await reload();
  }

  async function cancelAutomationJob(row: AutomationRun) {
    const result = await action.run(() => cancelAutomation(row.id));
    if (result.ok) await reload();
  }

  if (!project) return <EmptyState icon="research" title="Create a project first" detail="Operations combines a project's run queue, budgets, reusable templates, and approval gates." />;

  return <main className="lab-view lab-operations-view">
    <header className="lab-page-header"><div><span className="lab-eyebrow">DURABLE CONTROL PLANE</span><h1>{project.name} operations</h1><p>Inspect every attempt, stop or retry work, enforce spend policy, and gate optional coding automation.</p></div><Button icon="refresh" onClick={() => void reload()}>Refresh</Button></header>
    <nav className="lab-subtabs" aria-label="Operations sections">{(["jobs", "policy", "templates", "automation"] as Tab[]).map((item) => <button key={item} type="button" className={tab === item ? "is-active" : ""} onClick={() => setTab(item)}>{item}</button>)}</nav>

    {tab === "jobs" && <section className="lab-panel-card"><header className="lab-card-header"><div><h2>Run history and jobs</h2><p>Every retry is a new attempt linked to its predecessor; errors are safe for display.</p></div><Badge>{runs.length}</Badge></header><div className="lab-job-table" role="table"><div className="lab-policy-head" role="row"><span>Work</span><span>Status</span><span>Usage</span><span>Attempt</span><span>Actions</span></div>{runs.map((run) => { const task = snapshot.tasks.find((item) => item.id === run.task_id); const meeting = snapshot.meetings.find((item) => item.id === run.meeting_id); return <div key={run.id} role="row"><span><strong>{task?.title ?? meeting?.title ?? run.kind}</strong><small>{run.id.slice(0, 8)}{run.retry_of_run_id ? " · retry" : ""}</small></span><span><StatusBadge status={run.status} /></span><span>{run.tokens_in + run.tokens_out} tokens</span><span>#{run.attempt ?? 1}</span><span className="lab-inline-actions">{run.status === "running" && <Button variant="danger" onClick={() => void cancel(run)}>Cancel</Button>}{["failed", "cancelled"].includes(run.status) && <Button onClick={() => void retry(run)}>Retry</Button>}</span></div>; })}{runs.length === 0 && <p className="lab-card-empty">No model-backed work has run for this project.</p>}</div></section>}

    {tab === "policy" && <div className="lab-dashboard-grid"><section className="lab-panel-card"><header className="lab-card-header"><div><h2>Current budget</h2><p>Usage from durable model-call provenance.</p></div></header><div className="lab-metrics"><article><span>Tokens</span><strong>{budget?.tokens_used ?? 0}</strong></article><article><span>Spend</span><strong>${(budget?.usd_used ?? 0).toFixed(4)}</strong></article><article><span>Running</span><strong>{budget?.running ?? 0}</strong></article></div></section><section className="lab-panel-card lab-span-2"><header className="lab-card-header"><div><h2>Project policy</h2><p>Preflight model egress, allowlists, per-run budgets, total spend, and concurrency.</p></div></header><form className="lab-policy-form" onSubmit={(event) => void savePolicy(event)}><Field label="Data classification" hint="Local only blocks real remote models; confidential requires an explicit allowlist."><select value={policy.data_classification} onChange={(event) => setPolicy((item) => ({ ...item, data_classification: event.target.value as ProjectPolicy["data_classification"] }))}><option value="local_only">Local only</option><option value="confidential">Confidential</option><option value="public">Public</option></select></Field><Field label="Allowed model IDs" hint="Required for confidential projects. Local-only IDs must also be attested in LEMMA_LOCAL_MODEL_IDS."><textarea rows={3} value={models} onChange={(event) => setModels(event.target.value)} /></Field><div className="lab-form-grid"><Field label="Run token cap"><input type="number" min="128" value={policy.max_run_tokens} onChange={(event) => setPolicy((item) => ({ ...item, max_run_tokens: Number(event.target.value) }))} /></Field><Field label="Run USD cap"><input type="number" min="0" step="0.01" value={policy.max_run_usd} onChange={(event) => setPolicy((item) => ({ ...item, max_run_usd: Number(event.target.value) }))} /></Field><Field label="Project USD cap"><input type="number" min="0" step="0.01" value={policy.max_project_usd} onChange={(event) => setPolicy((item) => ({ ...item, max_project_usd: Number(event.target.value) }))} /></Field><Field label="Concurrent runs"><input type="number" min="1" max="12" value={policy.max_concurrent_runs} onChange={(event) => setPolicy((item) => ({ ...item, max_concurrent_runs: Number(event.target.value) }))} /></Field></div><Button type="submit" variant="primary" disabled={action.pending}>Save policy</Button></form></section></div>}

    {tab === "templates" && <section className="lab-panel-card"><header className="lab-card-header"><div><h2>Reusable lab templates</h2><p>Store and instantiate bounded JSON defaults for projects, tasks, meetings, or evaluations.</p></div><Button icon="plus" onClick={() => setShowTemplate(true)}>New template</Button></header><div className="lab-template-grid">{templates.map((row) => <article key={row.id}><Badge>{row.kind}</Badge><h3>{row.name}</h3><p>{row.description || "No description"}</p><pre>{JSON.stringify(row.payload, null, 2)}</pre><div className="lab-inline-actions"><Button variant="primary" onClick={() => setTemplateToInstantiate(row)}>Instantiate</Button><Button variant="ghost" onClick={() => void action.run(async () => { await archiveLabTemplate(row.id); await reload(); })}>Archive</Button></div></article>)}</div></section>}

    {tab === "automation" && <><section className={`lab-security-banner ${hostExecution && headlessCoding ? "is-warn" : "is-safe"}`}><div><h2>{hostExecution && headlessCoding ? "M9 is enabled; every job still needs approval" : "Headless execution is locked"}</h2><p>Plans cannot run until they are explicitly approved. The backend also requires both execution switches and an absolute, non-world-writable Claude executable path.</p></div></section><section className="lab-panel-card"><header className="lab-card-header"><div><h2>Approval-gated headless jobs</h2><p>Interactive terminals remain the default and clearer billing path.</p></div><Button variant="primary" icon="plus" disabled={workspaces.length === 0} onClick={() => setShowAutomation(true)}>Plan automation</Button></header><div className="lab-automation-list">{projectAutomations.map((row) => <article key={row.id}><header><div><strong>{row.request}</strong><small>{row.provider} · {row.workspace_id ?? "no workspace"}</small></div><StatusBadge status={row.status} /></header>{row.plan && <p>{row.plan}</p>}<div>{row.capabilities.map((item) => <Badge key={item}>{item}</Badge>)}</div>{row.error && <p className="lab-inline-error">{row.error}</p>}{row.output && <pre>{row.output}</pre>}<footer className="lab-inline-actions">{row.status === "planned" && <><Button variant="primary" onClick={() => void decide(row, "approve")}>Approve</Button><Button variant="danger" onClick={() => void decide(row, "reject")}>Reject</Button></>}{row.status === "approved" && <Button variant="primary" icon="play" onClick={() => void execute(row)}>Run approved plan</Button>}{row.status === "running" && <Button variant="danger" onClick={() => void cancelAutomationJob(row)}>Cancel job</Button>}</footer></article>)}</div></section></>}

    {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
    {showAutomation && <Modal title="Plan a headless coding job" description="Creating a plan does not execute it; a separate durable approval is required." onClose={() => setShowAutomation(false)}><AutomationForm projectId={project.id} workspaces={workspaces} onSaved={(row) => setAutomations((items) => [row, ...items])} onClose={() => setShowAutomation(false)} /></Modal>}
    {showTemplate && <Modal title="New reusable template" onClose={() => setShowTemplate(false)}><TemplateForm onSaved={(row) => setTemplates((items) => [row, ...items])} onClose={() => setShowTemplate(false)} /></Modal>}
    {templateToInstantiate && <Modal title={`Instantiate ${templateToInstantiate.name}`} description="The server validates the merged payload against the selected entity schema before creating anything." onClose={() => setTemplateToInstantiate(null)}><TemplateInstantiationForm template={templateToInstantiate} onSaved={() => { void refreshSnapshot(); void reload(); }} onClose={() => setTemplateToInstantiate(null)} /></Modal>}
  </main>;
}
