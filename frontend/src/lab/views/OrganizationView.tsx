// Department and agent studio with structured duty cards and communication policy.

import { useState, type FormEvent } from "react";

import { createLabEntity, updateLabEntity } from "../../lib/api";
import { Icon } from "../components/Icons";
import { AgentAvatar, Badge, Button, EmptyState, Field, Modal, StatusBadge } from "../components/UI";
import { useLabStore } from "../store";
import type { Agent, DepartmentKind } from "../types";

function lines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "The change could not be saved.";
}

function GroupForm({ onClose }: { onClose: () => void }) {
  const refresh = useLabStore((state) => state.refresh);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<DepartmentKind>("department");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true); setError(null);
    try {
      await createLabEntity("departments", { name, description, kind });
      await refresh(); onClose();
    } catch (caught) { setError(message(caught)); } finally { setSaving(false); }
  }

  return (
    <form className="lab-form" onSubmit={(event) => void submit(event)}>
      <div className="lab-segmented">
        <button type="button" className={kind === "department" ? "is-active" : ""} onClick={() => setKind("department")}>Department</button>
        <button type="button" className={kind === "mission_team" ? "is-active" : ""} onClick={() => setKind("mission_team")}>Mission team</button>
      </div>
      <Field label="Name"><input required maxLength={160} value={name} onChange={(e) => setName(e.target.value)} placeholder="Applied Intelligence" autoFocus /></Field>
      <Field label="Mandate" hint="What this group owns and why it exists."><textarea maxLength={4000} rows={5} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Explore practical applications, surface risks, and turn evidence into decisions." /></Field>
      {error && <p className="lab-inline-error">{error}</p>}
      <div className="lab-form-actions"><Button onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" disabled={saving || !name.trim()}>{saving ? "Creating…" : "Create group"}</Button></div>
    </form>
  );
}

function AgentForm({ onClose }: { onClose: () => void }) {
  const departments = useLabStore((state) => state.snapshot.departments).filter((item) => item.status === "active");
  const refresh = useLabStore((state) => state.refresh);
  const selectedDepartmentId = useLabStore((state) => state.selectedDepartmentId);
  const [departmentId, setDepartmentId] = useState(selectedDepartmentId ?? departments[0]?.id ?? "");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [mission, setMission] = useState("");
  const [duties, setDuties] = useState("");
  const [focus, setFocus] = useState("");
  const [priorities, setPriorities] = useState("");
  const [scope, setScope] = useState("department");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(null);
    try {
      await createLabEntity<Agent>("agents", {
        ...(departmentId ? { department_id: departmentId } : {}), name, role, mission,
        duties: lines(duties), focus: lines(focus), priorities: lines(priorities),
        communication_scope: scope,
      });
      await refresh(); onClose();
    } catch (caught) { setError(message(caught)); } finally { setSaving(false); }
  }

  return (
    <form className="lab-form lab-form-grid" onSubmit={(event) => void submit(event)}>
      <Field label="Agent name"><input required maxLength={160} value={name} onChange={(e) => setName(e.target.value)} placeholder="Mira" autoFocus /></Field>
      <Field label="Role"><input required maxLength={160} value={role} onChange={(e) => setRole(e.target.value)} placeholder="Evidence Analyst" /></Field>
      <Field label="Home group"><select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}><option value="">Independent</option>{departments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
      <Field label="Communication"><select value={scope} onChange={(e) => setScope(e.target.value)}><option value="isolated">Isolated</option><option value="department">Same group only</option><option value="organization">Organization-wide</option></select></Field>
      <div className="lab-field-span-2"><Field label="Mission" hint="The outcome this agent is responsible for."><textarea required maxLength={4000} rows={4} value={mission} onChange={(e) => setMission(e.target.value)} placeholder="Evaluate claims against supplied evidence and make uncertainty visible." /></Field></div>
      <Field label="Core duties" hint="One duty per line"><textarea rows={6} value={duties} onChange={(e) => setDuties(e.target.value)} placeholder={"Compare competing claims\nIdentify evidence gaps\nDraft a decision memo"} /></Field>
      <Field label="Must consider" hint="One focus area per line"><textarea rows={6} value={focus} onChange={(e) => setFocus(e.target.value)} placeholder={"Source quality\nCounter-evidence\nImplementation constraints"} /></Field>
      <div className="lab-field-span-2"><Field label="Priority order" hint="One priority per line; order matters."><textarea rows={4} value={priorities} onChange={(e) => setPriorities(e.target.value)} placeholder={"Accuracy before speed\nState uncertainty\nMake recommendations actionable"} /></Field></div>
      {error && <p className="lab-inline-error lab-field-span-2">{error}</p>}
      <div className="lab-form-actions lab-field-span-2"><Button onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" disabled={saving || !name.trim() || !role.trim() || !mission.trim()}>{saving ? "Creating…" : "Create agent"}</Button></div>
    </form>
  );
}

function AgentInspector({ agent }: { agent: Agent }) {
  const refresh = useLabStore((state) => state.refresh);
  const groups = useLabStore((state) => state.snapshot.departments);
  const [mission, setMission] = useState(agent.mission);
  const [duties, setDuties] = useState(agent.duties.join("\n"));
  const [focus, setFocus] = useState(agent.focus.join("\n"));
  const [priorities, setPriorities] = useState(agent.priorities.join("\n"));
  const [scope, setScope] = useState(agent.communication_scope);
  const [status, setStatus] = useState(agent.status);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save() {
    setError(null); setSaved(false);
    try {
      await updateLabEntity("agents", agent.id, {
        mission, duties: lines(duties), focus: lines(focus), priorities: lines(priorities),
        communication_scope: scope, status,
      });
      await refresh(); setSaved(true);
    } catch (caught) { setError(message(caught)); }
  }

  return (
    <aside className="lab-inspector">
      <header className="lab-inspector-header"><span>AGENT DUTY CARD</span><StatusBadge status={status} /></header>
      <div className="lab-inspector-scroll">
        <div className="lab-agent-identity"><AgentAvatar name={agent.name} size="lg" /><div><h2>{agent.name}</h2><p>{agent.role}</p><small>{groups.find((item) => item.id === agent.department_id)?.name ?? "Independent"}</small></div></div>
        <div className="lab-boundary-callout"><Icon name="security" size={16} /><span>Prompt-only researcher. No shell, files, network, connectors, or secrets.</span></div>
        <Field label="Mission"><textarea rows={5} maxLength={4000} value={mission} onChange={(e) => setMission(e.target.value)} /></Field>
        <Field label="Duties"><textarea rows={6} value={duties} onChange={(e) => setDuties(e.target.value)} /></Field>
        <Field label="Must consider"><textarea rows={6} value={focus} onChange={(e) => setFocus(e.target.value)} /></Field>
        <Field label="Priorities"><textarea rows={5} value={priorities} onChange={(e) => setPriorities(e.target.value)} /></Field>
        <Field label="Communication policy"><select value={scope} onChange={(e) => setScope(e.target.value)}><option value="isolated">Isolated</option><option value="department">Same group only</option><option value="organization">Organization-wide</option></select></Field>
        <Field label="Availability"><select value={status} onChange={(e) => setStatus(e.target.value)}><option value="active">Active</option><option value="paused">Paused</option><option value="archived">Archived</option></select></Field>
        <div className="lab-model-row"><span>Model</span><code>{agent.model}</code></div>
        {error && <p className="lab-inline-error">{error}</p>}{saved && <p className="lab-inline-success">Duty card saved.</p>}
      </div>
      <footer className="lab-inspector-footer"><Button variant="primary" onClick={() => void save()}>Save duty card</Button></footer>
    </aside>
  );
}

export default function OrganizationView() {
  const snapshot = useLabStore((state) => state.snapshot);
  const selectedAgentId = useLabStore((state) => state.selectedAgentId);
  const selectAgent = useLabStore((state) => state.selectAgent);
  const [modal, setModal] = useState<"group" | "agent" | null>(null);
  const selected = snapshot.agents.find((agent) => agent.id === selectedAgentId) ?? null;

  return (
    <div className="lab-view-with-inspector">
      <main className="lab-view">
        <header className="lab-page-header"><div><span className="lab-eyebrow">PEOPLE & POLICY</span><h1>Organization</h1><p>Give each researcher a narrow charter and an explicit communication boundary.</p></div><div className="lab-header-actions"><Button icon="users" onClick={() => setModal("group")}>New group</Button><Button variant="primary" icon="plus" onClick={() => setModal("agent")} disabled={snapshot.departments.length === 0}>New agent</Button></div></header>
        {snapshot.departments.length === 0 ? (
          <EmptyState icon="organization" title="Create the first department" detail="Departments own durable expertise; mission teams gather agents temporarily around one goal." action={<Button variant="primary" onClick={() => setModal("group")}>Create group</Button>} />
        ) : (
          <section className="lab-agent-grid">
            {snapshot.agents.map((agent) => {
              const group = snapshot.departments.find((item) => item.id === agent.department_id);
              return <button key={agent.id} className={`lab-agent-card ${selectedAgentId === agent.id ? "is-selected" : ""}`} onClick={() => selectAgent(agent.id)}><div className="lab-agent-card-top"><AgentAvatar name={agent.name} size="lg" /><StatusBadge status={agent.status} /></div><h2>{agent.name}</h2><p className="lab-agent-role">{agent.role}</p><p>{agent.mission}</p><footer><Badge>{group?.name ?? "Independent"}</Badge><span>{agent.communication_scope.replaceAll("_", " ")}</span></footer></button>;
            })}
            {snapshot.agents.length === 0 && <EmptyState icon="agent" title="No agents yet" detail="Create a specialist and define exactly what it must do and consider." action={<Button variant="primary" onClick={() => setModal("agent")}>Create agent</Button>} />}
          </section>
        )}
      </main>
      {selected ? <AgentInspector key={selected.id} agent={selected} /> : <aside className="lab-inspector lab-inspector-placeholder"><Icon name="agent" size={28} /><h2>Select an agent</h2><p>Its duty card and communication policy will open here.</p></aside>}
      {modal === "group" && <Modal title="Create a group" description="A permanent department or a focused cross-functional mission team." onClose={() => setModal(null)}><GroupForm onClose={() => setModal(null)} /></Modal>}
      {modal === "agent" && <Modal title="Create a research agent" description="Structure the duty. Permissions remain code-enforced and separate." onClose={() => setModal(null)}><AgentForm onClose={() => setModal(null)} /></Modal>}
    </div>
  );
}
