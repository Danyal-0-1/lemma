// Project/task board with isolated live streams addressed by run and task IDs.

import { useEffect, useState, type FormEvent } from "react";

import {
  addTaskDependency,
  cancelLabRun,
  createLabEntity,
  getTaskReadiness,
  removeTaskDependency,
  retryLabRun,
  runLabTask,
  updateLabEntity,
} from "../../lib/api";
import { useAsyncAction } from "../../lib/asyncAction";
import { Icon } from "../components/Icons";
import ResearchAssurance from "../components/ResearchAssurance";
import {
  AgentAvatar,
  Badge,
  Button,
  EmptyState,
  Field,
  Modal,
  StatusBadge,
  UnverifiedNotice,
} from "../components/UI";
import { useLabStore } from "../store";
import type { Project, ResearchTask } from "../types";

function ProjectForm({ onClose }: { onClose: () => void }) {
  const refresh = useLabStore((state) => state.refresh);
  const selectProject = useLabStore((state) => state.selectProject);
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [description, setDescription] = useState("");
  const action = useAsyncAction({ fallbackError: "Could not create the project." });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(async () => {
      const project = await createLabEntity<Project>("projects", {
        name,
        objective,
        description,
      });
      await refresh();
      return project;
    });
    if (!result.ok) return;
    selectProject(result.value.id);
    onClose();
  }

  return (
    <form className="lab-form" aria-busy={action.pending} onSubmit={(event) => void submit(event)}>
      <Field label="Project name">
        <input
          required
          maxLength={160}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Battery reuse landscape"
          autoFocus
        />
      </Field>
      <Field label="Research objective">
        <textarea
          required
          maxLength={6000}
          rows={5}
          value={objective}
          onChange={(event) => setObjective(event.target.value)}
          placeholder="Determine the most credible technical and commercial paths…"
        />
      </Field>
      <Field label="Context">
        <textarea
          maxLength={4000}
          rows={4}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Scope, constraints, or background for the whole project."
        />
      </Field>
      {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
      <div className="lab-form-actions">
        <Button onClick={onClose} disabled={action.pending}>Cancel</Button>
        <Button
          type="submit"
          variant="primary"
          disabled={action.pending || !name.trim() || !objective.trim()}
        >
          {action.pending ? "Creating…" : "Create project"}
        </Button>
      </div>
    </form>
  );
}

function ProjectEditForm({ project, onClose }: { project: Project; onClose: () => void }) {
  const refresh = useLabStore((state) => state.refresh);
  const [name, setName] = useState(project.name);
  const [objective, setObjective] = useState(project.objective);
  const [description, setDescription] = useState(project.description);
  const [status, setStatus] = useState(project.status);
  const action = useAsyncAction({ fallbackError: "Could not update the project." });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(async () => {
      await updateLabEntity("projects", project.id, { name, objective, description, status });
      await refresh();
    });
    if (result.ok) onClose();
  }

  return <form className="lab-form" onSubmit={(event) => void submit(event)}>
    <Field label="Project name"><input required value={name} onChange={(event) => setName(event.target.value)} /></Field>
    <Field label="Research objective"><textarea required rows={5} value={objective} onChange={(event) => setObjective(event.target.value)} /></Field>
    <Field label="Context"><textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} /></Field>
    <Field label="Lifecycle"><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="draft">Draft</option><option value="active">Active</option><option value="completed">Completed</option><option value="archived">Archived</option></select></Field>
    {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
    <div className="lab-form-actions"><Button onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" disabled={!name.trim() || !objective.trim() || action.pending}>Save project</Button></div>
  </form>;
}

function TaskForm({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const agents = useLabStore((state) => state.snapshot.agents).filter(
    (agent) => agent.status === "active",
  );
  const refresh = useLabStore((state) => state.refresh);
  const selectTask = useLabStore((state) => state.selectTask);
  const [agentId, setAgentId] = useState(agents[0]?.id ?? "");
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("");
  const [context, setContext] = useState("");
  const [expected, setExpected] = useState("");
  const action = useAsyncAction({ fallbackError: "Could not create the research task." });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const agent = agents.find((item) => item.id === agentId);
    const result = await action.run(async () => {
      const task = await createLabEntity<ResearchTask>("tasks", {
        project_id: projectId,
        assigned_agent_id: agentId,
        ...(agent?.department_id ? { department_id: agent.department_id } : {}),
        title,
        objective,
        context,
        expected_output: expected,
      });
      await refresh();
      return task;
    });
    if (!result.ok) return;
    selectTask(result.value.id);
    onClose();
  }

  return (
    <form className="lab-form" aria-busy={action.pending} onSubmit={(event) => void submit(event)}>
      <Field label="Assigned researcher">
        <select required value={agentId} onChange={(event) => setAgentId(event.target.value)}>
          <option value="" disabled>Select an active agent</option>
          {agents.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name} — {agent.role}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Task title">
        <input
          required
          maxLength={160}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Compare degradation pathways"
          autoFocus
        />
      </Field>
      <Field label="Objective">
        <textarea
          required
          maxLength={6000}
          rows={4}
          value={objective}
          onChange={(event) => setObjective(event.target.value)}
          placeholder="What exact question should this agent answer?"
        />
      </Field>
      <Field
        label="Supplied context"
        hint="Treated as untrusted research data, never as system instructions."
      >
        <textarea
          maxLength={12000}
          rows={6}
          value={context}
          onChange={(event) => setContext(event.target.value)}
          placeholder="Paste notes, excerpts, known facts, or assumptions here."
        />
      </Field>
      <Field label="Expected deliverable">
        <textarea
          maxLength={4000}
          rows={3}
          value={expected}
          onChange={(event) => setExpected(event.target.value)}
          placeholder="A concise comparison with assumptions, uncertainties, and next experiments."
        />
      </Field>
      {agents.length === 0 && (
        <p className="lab-inline-error">Create an active agent before assigning work.</p>
      )}
      {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
      <div className="lab-form-actions">
        <Button onClick={onClose} disabled={action.pending}>Cancel</Button>
        <Button
          type="submit"
          variant="primary"
          disabled={action.pending || !agentId || !title.trim() || !objective.trim()}
        >
          {action.pending ? "Creating…" : "Create task"}
        </Button>
      </div>
    </form>
  );
}

function TaskEditForm({ task, onClose }: { task: ResearchTask; onClose: () => void }) {
  const agents = useLabStore((state) => state.snapshot.agents).filter(
    (agent) => agent.status === "active",
  );
  const refresh = useLabStore((state) => state.refresh);
  const [agentId, setAgentId] = useState(task.assigned_agent_id ?? "");
  const [title, setTitle] = useState(task.title);
  const [objective, setObjective] = useState(task.objective);
  const [context, setContext] = useState(task.context);
  const [expected, setExpected] = useState(task.expected_output);
  const [status, setStatus] = useState(task.status === "running" ? "queued" : task.status);
  const action = useAsyncAction({ fallbackError: "Could not update the research task." });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const agent = agents.find((item) => item.id === agentId);
    if (!agent) return;
    const result = await action.run(async () => {
      await updateLabEntity("tasks", task.id, {
        assigned_agent_id: agent.id,
        department_id: agent.department_id,
        title,
        objective,
        context,
        expected_output: expected,
        status,
      });
      await refresh();
    });
    if (result.ok) onClose();
  }

  return (
    <form className="lab-form" aria-busy={action.pending} onSubmit={(event) => void submit(event)}>
      <Field label="Assigned researcher">
        <select required value={agentId} onChange={(event) => setAgentId(event.target.value)}>
          <option value="" disabled>Select an active agent</option>
          {agents.map((agent) => (
            <option key={agent.id} value={agent.id}>{agent.name} — {agent.role}</option>
          ))}
        </select>
      </Field>
      <Field label="Task title">
        <input required maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} autoFocus />
      </Field>
      <Field label="Objective">
        <textarea required maxLength={6000} rows={4} value={objective} onChange={(event) => setObjective(event.target.value)} />
      </Field>
      <Field label="Supplied context" hint="Treated as untrusted research data, never as system instructions.">
        <textarea maxLength={12000} rows={6} value={context} onChange={(event) => setContext(event.target.value)} />
      </Field>
      <Field label="Expected deliverable">
        <textarea maxLength={4000} rows={3} value={expected} onChange={(event) => setExpected(event.target.value)} />
      </Field>
      <Field label="Lifecycle">
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="queued">Queued</option>
          <option value="completed">Completed</option>
          <option value="failed">Needs attention</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </Field>
      {agents.length === 0 && <p className="lab-inline-error">Create an active agent before reassigning work.</p>}
      {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
      <div className="lab-form-actions">
        <Button onClick={onClose} disabled={action.pending}>Cancel</Button>
        <Button
          type="submit"
          variant="primary"
          disabled={action.pending || !agentId || !title.trim() || !objective.trim()}
        >
          {action.pending ? "Saving…" : "Save task"}
        </Button>
      </div>
    </form>
  );
}

function TaskInspector({ task }: { task: ResearchTask }) {
  const snapshot = useLabStore((state) => state.snapshot);
  const liveRuns = useLabStore((state) => state.liveRuns);
  const registerRun = useLabStore((state) => state.registerRun);
  const agent = snapshot.agents.find((item) => item.id === task.assigned_agent_id);
  const persisted = [...snapshot.results].reverse().find((item) => item.task_id === task.id);
  const live = Object.values(liveRuns).filter((run) => run.task_id === task.id).at(-1);
  const isRunning = live?.status === "running";
  const [instructions, setInstructions] = useState("");
  const [dependencyId, setDependencyId] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [readiness, setReadiness] = useState<{
    ready: boolean;
    dependencies: Array<{
      dependency_id: string;
      task_id: string;
      title: string;
      status: string;
    }>;
    blockers: Array<{
      dependency_id: string;
      task_id: string;
      title: string;
      status: string;
    }>;
  } | null>(null);
  const action = useAsyncAction({ fallbackError: "Could not start the research run." });
  const candidates = snapshot.tasks.filter(
    (item) => item.project_id === task.project_id && item.id !== task.id,
  );
  const prior = [...snapshot.runs]
    .reverse()
    .find((run) => run.task_id === task.id && ["failed", "cancelled"].includes(run.status));

  useEffect(() => {
    setDependencyId("");
    void getTaskReadiness(task.id).then(setReadiness).catch(() => setReadiness(null));
  }, [task.id]);

  async function run() {
    const result = await action.run(() => runLabTask(task.id, instructions));
    if (result.ok) registerRun(result.value);
  }

  async function addDependency() {
    if (!dependencyId) return;
    const result = await action.run(() => addTaskDependency(task.id, dependencyId));
    if (result.ok) {
      setDependencyId("");
      setReadiness(await getTaskReadiness(task.id));
    }
  }

  async function removeDependency(dependencyId: string) {
    const result = await action.run(() => removeTaskDependency(dependencyId));
    if (result.ok) setReadiness(await getTaskReadiness(task.id));
  }

  async function cancel() {
    if (!live) return;
    const result = await action.run(() => cancelLabRun(live.run_id));
    if (result.ok) await useLabStore.getState().refresh();
  }

  async function retry() {
    if (!prior) return;
    const result = await action.run(() => retryLabRun(prior.id));
    if (result.ok) {
      registerRun({ run_id: result.value.id, task_id: task.id, status: result.value.status });
    }
  }

  return (
    <aside className="lab-inspector">
      <header className="lab-inspector-header">
        <span>WORK PACKAGE</span>
        <div className="lab-inline-actions">
          <Button variant="ghost" onClick={() => setEditOpen(true)} disabled={isRunning}>Edit</Button>
          <StatusBadge status={live?.status ?? task.status} />
        </div>
      </header>
      <div className="lab-inspector-scroll">
        <div className="lab-task-owner">
          {agent && <AgentAvatar name={agent.name} />}
          <div>
            <h2>{task.title}</h2>
            <p>{agent ? `${agent.name} · ${agent.role}` : "Unknown agent"}</p>
          </div>
        </div>
        <section className="lab-inspector-section">
          <h3>Objective</h3>
          <p>{task.objective}</p>
        </section>
        {task.context && (
          <section className="lab-inspector-section">
            <h3>Context supplied</h3>
            <p>{task.context}</p>
          </section>
        )}
        <section className="lab-inspector-section">
          <h3>Expected output</h3>
          <p>{task.expected_output || "Clear research memo with uncertainties and next steps."}</p>
        </section>
        <section className="lab-inspector-section">
          <h3>Prerequisites</h3>
          {readiness?.dependencies.map((dependency) => (
            <div className="lab-inline-actions" key={dependency.dependency_id}>
              <StatusBadge status={dependency.status} />
              <span>{dependency.title}</span>
              <Button
                variant="ghost"
                onClick={() => void removeDependency(dependency.dependency_id)}
                disabled={action.pending || isRunning}
              >Remove</Button>
            </div>
          ))}
          {readiness?.dependencies.length === 0 && <p>No prerequisites.</p>}
          {readiness?.ready && <p className="lab-success-note"><Icon name="check" size={14} /> Ready to run</p>}
          <div className="lab-inline-actions">
            <select aria-label="Dependency task" value={dependencyId} onChange={(event) => setDependencyId(event.target.value)}>
              <option value="">Add prerequisite…</option>
              {candidates.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
            </select>
            <Button variant="ghost" disabled={!dependencyId} onClick={() => void addDependency()}>Add</Button>
          </div>
        </section>
        <UnverifiedNotice compact />
        <Field label="Run guidance" hint="Optional direction for this run only.">
          <textarea
            rows={3}
            maxLength={4000}
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
            placeholder="Emphasize counter-evidence…"
          />
        </Field>
        {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
        {live?.status === "failed" && live.error && (
          <p className="lab-inline-error">Run failed: {live.error}</p>
        )}
        {isRunning && live && (
          <section className="lab-live-run">
            <header>
              <span className="lab-live-dot" />
              Live run <code>{live.run_id.slice(0, 8)}</code>
            </header>
            {live.turns.map((turn) => <pre key={turn.id}>{turn.text || "Thinking…"}</pre>)}
          </section>
        )}
        {!isRunning && persisted && (
          <section className="lab-result">
            <h3>Latest result</h3>
            <pre>{persisted.content}</pre>
          </section>
        )}
      </div>
      <footer className="lab-inspector-footer">
        {isRunning ? <Button
          variant="danger"
          onClick={() => void cancel()}
          disabled={action.pending}
        >Cancel run</Button> : prior && task.status !== "completed" ? <Button
          onClick={() => void retry()}
          disabled={action.pending}
        >Retry attempt</Button> : <Button
          variant="primary"
          icon="play"
          onClick={() => void run()}
          disabled={action.pending || task.status === "running" || isRunning || readiness?.ready === false}
        >
          {action.pending ? "Starting…" : task.status === "completed" ? "Run again" : "Run research"}
        </Button>}
      </footer>
      {editOpen && (
        <Modal
          title="Edit research task"
          description="Update the work package or lifecycle. Running tasks remain locked until they finish or are cancelled."
          onClose={() => setEditOpen(false)}
        >
          <TaskEditForm task={task} onClose={() => setEditOpen(false)} />
        </Modal>
      )}
    </aside>
  );
}

const COLUMNS = [
  { id: "queued", label: "Queued", accepts: ["draft", "queued"] },
  { id: "running", label: "In progress", accepts: ["running"] },
  { id: "completed", label: "Completed", accepts: ["completed"] },
  { id: "failed", label: "Needs attention", accepts: ["failed", "cancelled"] },
];

export default function ResearchView() {
  const snapshot = useLabStore((state) => state.snapshot);
  const selectedProjectId = useLabStore((state) => state.selectedProjectId);
  const selectedTaskId = useLabStore((state) => state.selectedTaskId);
  const selectTask = useLabStore((state) => state.selectTask);
  const [modal, setModal] = useState<"project" | "edit-project" | "task" | null>(null);
  const project = snapshot.projects.find((item) => item.id === selectedProjectId)
    ?? snapshot.projects[0]
    ?? null;
  const projectTasks = project
    ? snapshot.tasks.filter((task) => task.project_id === project.id)
    : [];
  const selectedTask = snapshot.tasks.find(
    (task) => task.id === selectedTaskId && task.project_id === project?.id,
  ) ?? null;
  const hasActiveAgent = snapshot.agents.some((agent) => agent.status === "active");
  const canCreateTask = project?.status === "active" && hasActiveAgent;

  return (
    <div className="lab-view-with-inspector">
      <main className="lab-view">
        <header className="lab-page-header">
          <div>
            <span className="lab-eyebrow">PROJECTS & RUNS</span>
            <h1>{project?.name ?? "Research board"}</h1>
            <p>
              {project?.objective
                ?? "Turn a broad topic into bounded, reviewable work packages."}
            </p>
          </div>
          <div className="lab-header-actions">
            {project && <Button onClick={() => setModal("edit-project")}>Edit project</Button>}
            <Button onClick={() => setModal("project")} icon="research">New project</Button>
            <Button
              variant="primary"
              icon="plus"
              onClick={() => setModal("task")}
              disabled={!canCreateTask}
            >
              New task
            </Button>
          </div>
        </header>

        {project && <ResearchAssurance project={project} task={selectedTask} />}

        {!project ? (
          <EmptyState
            icon="research"
            title="Open the first research project"
            detail="Projects hold a goal; tasks give one agent one bounded question and deliverable."
            action={(
              <Button variant="primary" onClick={() => setModal("project")}>
                Create project
              </Button>
            )}
          />
        ) : (
          <div className="lab-kanban">
            {COLUMNS.map((column) => {
              const tasks = projectTasks.filter((task) => column.accepts.includes(task.status));
              return (
                <section key={column.id} className="lab-kanban-column">
                  <header>
                    <span>{column.label}</span>
                    <Badge>{tasks.length}</Badge>
                  </header>
                  <div>
                    {tasks.map((task) => {
                      const agent = snapshot.agents.find(
                        (item) => item.id === task.assigned_agent_id,
                      );
                      return (
                        <button
                          key={task.id}
                          className={`lab-task-card ${selectedTaskId === task.id ? "is-selected" : ""}`}
                          onClick={() => selectTask(task.id)}
                        >
                          <div className="lab-task-card-title">
                            <Icon name="task" size={15} />
                            <strong>{task.title}</strong>
                          </div>
                          <p>{task.objective}</p>
                          <footer>
                            {agent ? (
                              <>
                                <AgentAvatar name={agent.name} size="sm" />
                                <span>{agent.name}</span>
                              </>
                            ) : (
                              <span>Unassigned</span>
                            )}
                            <StatusBadge status={task.status} />
                          </footer>
                        </button>
                      );
                    })}
                    {tasks.length === 0 && <p className="lab-column-empty">No tasks</p>}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </main>

      {selectedTask ? (
        <TaskInspector key={selectedTask.id} task={selectedTask} />
      ) : (
        <aside className="lab-inspector lab-inspector-placeholder">
          <Icon name="task" size={28} />
          <h2>Select a work package</h2>
          <p>Its brief, assigned agent, live stream, and latest finding will appear here.</p>
        </aside>
      )}

      {modal === "project" && (
        <Modal
          title="New research project"
          description="Define the broad decision or question your lab will investigate."
          onClose={() => setModal(null)}
        >
          <ProjectForm onClose={() => setModal(null)} />
        </Modal>
      )}
      {modal === "edit-project" && project && (
        <Modal
          title="Edit research project"
          description="Update its scope or lifecycle without deleting its history."
          onClose={() => setModal(null)}
        >
          <ProjectEditForm project={project} onClose={() => setModal(null)} />
        </Modal>
      )}
      {modal === "task" && project && (
        <Modal
          title="New research task"
          description={`Create a bounded work package inside ${project.name}.`}
          onClose={() => setModal(null)}
        >
          <TaskForm projectId={project.id} onClose={() => setModal(null)} />
        </Modal>
      )}
    </div>
  );
}
