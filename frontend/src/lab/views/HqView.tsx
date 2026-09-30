// R&D Studio home: organization health, work in flight, and recent audit activity.

import { useLabStore } from "../store";
import { AgentAvatar, Badge, EmptyState, StatusBadge, UnverifiedNotice } from "../components/UI";
import { Icon } from "../components/Icons";

function relativeTime(value?: string): string {
  if (!value) return "recently";
  const delta = Date.now() - new Date(value).getTime();
  const minutes = Math.max(0, Math.round(delta / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export default function HqView() {
  const snapshot = useLabStore((state) => state.snapshot);
  const setView = useLabStore((state) => state.setView);
  const selectTask = useLabStore((state) => state.selectTask);
  const activeAgents = snapshot.agents.filter((agent) => agent.status === "active");
  const activeTasks = snapshot.tasks.filter((task) => ["queued", "running"].includes(task.status));
  const completeTasks = snapshot.tasks.filter((task) => task.status === "completed");

  return (
    <main className="lab-view lab-hq-view">
      <header className="lab-page-header lab-hero-header">
        <div>
          <span className="lab-eyebrow">RESEARCH OPERATIONS</span>
          <h1>R&D Headquarters</h1>
          <p>Design the team, assign focused research, and review what your agents conclude.</p>
        </div>
        <div className="lab-header-actions">
          <button className="lab-button lab-button-secondary" onClick={() => setView("organization")}>
            <Icon name="agent" size={15} /> Build team
          </button>
          <button className="lab-button lab-button-primary" onClick={() => setView("research")}>
            <Icon name="plus" size={15} /> New research
          </button>
        </div>
      </header>

      <UnverifiedNotice compact />

      <section className="lab-metrics" aria-label="Lab overview">
        <article><span>Agents</span><strong>{snapshot.agents.length}</strong><small>{activeAgents.length} active</small></article>
        <article><span>Groups</span><strong>{snapshot.departments.length}</strong><small>departments + teams</small></article>
        <article><span>In flight</span><strong>{activeTasks.length}</strong><small>queued or running</small></article>
        <article><span>Findings</span><strong>{snapshot.findings.length}</strong><small>{completeTasks.length} tasks complete</small></article>
      </section>

      {snapshot.departments.length === 0 && snapshot.agents.length === 0 ? (
        <EmptyState
          icon="organization"
          title="Assemble your research organization"
          detail="Start with a department or mission team, then define each agent's role, duties, focus, priorities, and communication boundary."
          action={<button className="lab-button lab-button-primary" onClick={() => setView("organization")}>Open Organization</button>}
        />
      ) : (
        <div className="lab-dashboard-grid">
          <section className="lab-panel-card lab-span-2">
            <header className="lab-card-header"><div><h2>Organization</h2><p>Active people and their functional homes</p></div><Badge>{activeAgents.length} online</Badge></header>
            <div className="lab-department-grid">
              {snapshot.departments.filter((group) => group.status === "active").map((group) => {
                const members = snapshot.agents.filter((agent) => agent.department_id === group.id);
                return (
                  <button
                    key={group.id}
                    className="lab-department-card"
                    onClick={() => {
                      useLabStore.getState().selectDepartment(group.id);
                      setView("organization");
                    }}
                  >
                    <span className="lab-card-icon"><Icon name={group.kind === "mission_team" ? "users" : "organization"} size={18} /></span>
                    <span className="lab-department-copy"><strong>{group.name}</strong><small>{group.kind === "mission_team" ? "Mission team" : "Department"} · {members.length} agents</small></span>
                    <span className="lab-avatar-stack">
                      {members.slice(0, 3).map((agent) => <AgentAvatar key={agent.id} name={agent.name} size="sm" />)}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="lab-panel-card">
            <header className="lab-card-header"><div><h2>Work in flight</h2><p>Current research queue</p></div></header>
            <div className="lab-compact-list">
              {activeTasks.slice(0, 6).map((task) => {
                const agent = snapshot.agents.find((item) => item.id === task.assigned_agent_id);
                return (
                  <button key={task.id} onClick={() => { selectTask(task.id); setView("research"); }}>
                    <i className={`lab-status-dot is-${task.status}`} />
                    <span><strong>{task.title}</strong><small>{agent?.name ?? "Unassigned"}</small></span>
                    <StatusBadge status={task.status} />
                  </button>
                );
              })}
              {activeTasks.length === 0 && <p className="lab-card-empty">No active work. The queue is clear.</p>}
            </div>
          </section>

          <section className="lab-panel-card lab-span-2">
            <header className="lab-card-header"><div><h2>Latest findings</h2><p>Reviewable outputs from completed tasks</p></div></header>
            <div className="lab-findings-list">
              {snapshot.findings.slice(-4).reverse().map((finding) => {
                const agent = snapshot.agents.find((item) => item.id === finding.agent_id);
                return (
                  <article key={finding.id}>
                    <div className="lab-finding-meta"><AgentAvatar name={agent?.name ?? "Agent"} size="sm" /><span>{agent?.name ?? "Agent"}</span><time>{relativeTime(finding.created_at)}</time></div>
                    <h3>{finding.title}</h3>
                    <p>{finding.content.slice(0, 260)}{finding.content.length > 260 ? "…" : ""}</p>
                  </article>
                );
              })}
              {snapshot.findings.length === 0 && <p className="lab-card-empty">Completed research findings will appear here.</p>}
            </div>
          </section>

          <section className="lab-panel-card">
            <header className="lab-card-header"><div><h2>Audit trail</h2><p>Recent durable actions</p></div></header>
            <ol className="lab-activity-list">
              {snapshot.activities.slice(0, 8).map((activity) => (
                <li key={activity.id}><i /><span><strong>{activity.action.replaceAll(".", " ")}</strong><small>{activity.entity_type} · {relativeTime(activity.created_at)}</small></span></li>
              ))}
              {snapshot.activities.length === 0 && <p className="lab-card-empty">No activity recorded yet.</p>}
            </ol>
          </section>
        </div>
      )}
    </main>
  );
}
