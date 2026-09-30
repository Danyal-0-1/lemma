// Project/task board with isolated live streams addressed by run and task IDs.

import { useState, type FormEvent } from "react";

import { createLabEntity, runLabTask } from "../../lib/api";
import { Icon } from "../components/Icons";
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

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed.";
}

function ProjectForm({ onClose }: { onClose: () => void }) {
  const refresh = useLabStore((state) => state.refresh);
  const selectProject = useLabStore((state) => state.selectProject);
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const project = await createLabEntity<Project>("projects", {
        name,
        objective,
        description,
      });
      await refresh();
      selectProject(project.id);
      onClose();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="lab-form" onSubmit={(event) => void submit(event)}>
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
      {error && <p className="lab-inline-error">{error}</p>}
      <div className="lab-form-actions">
        <Button onClick={onClose}>Cancel</Button>
        <Button
          type="submit"
          variant="primary"
          disabled={saving || !name.trim() || !objective.trim()}
        >
          {saving ? "Creating…" : "Create project"}
        </Button>
      </div>
    </form>
  );
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
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const agent = agents.find((item) => item.id === agentId);
    try {
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
      selectTask(task.id);
      onClose();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="lab-form" onSubmit={(event) => void submit(event)}>
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
      {error && <p className="lab-inline-error">{error}</p>}
      <div className="lab-form-actions">
        <Button onClick={onClose}>Cancel</Button>
        <Button
          type="submit"
          variant="primary"
          disabled={saving || !agentId || !title.trim() || !objective.trim()}
        >
          {saving ? "Creating…" : "Create task"}
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
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  async function run() {
    setStarting(true);
    setError(null);
    try {
      const response = await runLabTask(task.id, instructions);
      registerRun(response);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setStarting(false);
    }
  }

  return (
    <aside className="lab-inspector">
      <header className="lab-inspector-header">
        <span>WORK PACKAGE</span>
        <StatusBadge status={live?.status ?? task.status} />
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
        {error && <p className="lab-inline-error">{error}</p>}
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
        <Button
          variant="primary"
          icon="play"
          onClick={() => void run()}
          disabled={starting || task.status === "running" || isRunning}
        >
          {starting ? "Starting…" : task.status === "completed" ? "Run again" : "Run research"}
        </Button>
      </footer>
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
  const [modal, setModal] = useState<"project" | "task" | null>(null);
  const project = snapshot.projects.find((item) => item.id === selectedProjectId)
    ?? snapshot.projects[0]
    ?? null;
  const projectTasks = project
    ? snapshot.tasks.filter((task) => task.project_id === project.id)
    : [];
  const selectedTask = snapshot.tasks.find((task) => task.id === selectedTaskId) ?? null;
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
