// Context-sensitive explorer shown between the activity rail and the workbench.

import type { ReactNode } from "react";

import { useLabStore } from "../store";
import type { ResearchView } from "../types";
import { Icon } from "./Icons";

const TITLES: Record<ResearchView, string> = {
  hq: "R&D Studio",
  organization: "Organization",
  research: "Research",
  knowledge: "Evidence library",
  evaluations: "Model arena",
  meetings: "Meeting rooms",
  operations: "Operations",
  security: "Security",
};

function ExplorerHeader({ view }: { view: ResearchView }) {
  const refresh = useLabStore((state) => state.refresh);
  const refreshing = useLabStore((state) => state.refreshing);
  return (
    <header className="lab-explorer-header">
      <span>{TITLES[view]}</span>
      <button
        type="button"
        className={`lab-icon-button ${refreshing ? "is-spinning" : ""}`}
        onClick={() => void refresh()}
        aria-label="Refresh Studio data"
        title="Refresh"
      >
        <Icon name="refresh" size={15} />
      </button>
    </header>
  );
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="lab-explorer-section">
      <h2><span>⌄</span>{label}</h2>
      {children}
    </section>
  );
}

function HqExplorer() {
  const snapshot = useLabStore((state) => state.snapshot);
  const setView = useLabStore((state) => state.setView);
  const activeTasks = snapshot.tasks.filter((task) => ["queued", "running", "review"].includes(task.status));
  return (
    <>
      <Section label="NAVIGATE">
        {([
          ["organization", "Organization", snapshot.agents.length],
          ["research", "Research board", snapshot.tasks.length],
          ["knowledge", "Evidence library", snapshot.findings.length],
          ["evaluations", "Model arena", 0],
          ["meetings", "Meeting rooms", snapshot.meetings.length],
          ["operations", "Operations", snapshot.runs.length],
          ["security", "Security center", 0],
        ] as const).map(([id, label, count]) => (
          <button key={id} type="button" className="lab-explorer-row" onClick={() => setView(id)}>
            <span>{label}</span>{count > 0 && <span className="lab-row-count">{count}</span>}
          </button>
        ))}
      </Section>
      <Section label="NEEDS ATTENTION">
        {activeTasks.length === 0 ? (
          <p className="lab-sidebar-empty">No queued or active tasks.</p>
        ) : activeTasks.slice(0, 6).map((task) => (
          <button
            key={task.id}
            type="button"
            className="lab-explorer-row"
            onClick={() => {
              useLabStore.getState().selectTask(task.id);
              setView("research");
            }}
          >
            <span className="lab-row-main"><i className={`lab-status-dot is-${task.status}`} />{task.title}</span>
          </button>
        ))}
      </Section>
    </>
  );
}

function OrganizationExplorer() {
  const { departments, agents } = useLabStore((state) => state.snapshot);
  const selectedDepartmentId = useLabStore((state) => state.selectedDepartmentId);
  const selectedAgentId = useLabStore((state) => state.selectedAgentId);
  const selectDepartment = useLabStore((state) => state.selectDepartment);
  const selectAgent = useLabStore((state) => state.selectAgent);
  const groups = [
    { kind: "department", label: "DEPARTMENTS" },
    { kind: "mission_team", label: "MISSION TEAMS" },
  ];
  return <>{groups.map((group) => (
    <Section key={group.kind} label={group.label}>
      {departments.filter((department) => department.kind === group.kind).map((department) => (
        <div key={department.id}>
          <button
            type="button"
            className={`lab-explorer-row ${selectedDepartmentId === department.id && !selectedAgentId ? "is-selected" : ""}`}
            onClick={() => selectDepartment(department.id)}
          >
            <span className="lab-row-main"><Icon name="users" size={14} />{department.name}</span>
            <span className="lab-row-count">{agents.filter((agent) => agent.department_id === department.id).length}</span>
          </button>
          {selectedDepartmentId === department.id && agents.filter((agent) => agent.department_id === department.id).map((agent) => (
            <button
              key={agent.id}
              type="button"
              className={`lab-explorer-row lab-explorer-child ${selectedAgentId === agent.id ? "is-selected" : ""}`}
              onClick={() => selectAgent(agent.id)}
            >
              <span className="lab-row-main"><i className={`lab-status-dot is-${agent.status}`} />{agent.name}</span>
            </button>
          ))}
        </div>
      ))}
      {departments.every((department) => department.kind !== group.kind) && (
        <p className="lab-sidebar-empty">None yet.</p>
      )}
    </Section>
  ))}</>;
}

function ResearchExplorer() {
  const { projects, tasks } = useLabStore((state) => state.snapshot);
  const selectedProjectId = useLabStore((state) => state.selectedProjectId);
  const selectedTaskId = useLabStore((state) => state.selectedTaskId);
  const selectProject = useLabStore((state) => state.selectProject);
  const selectTask = useLabStore((state) => state.selectTask);
  return (
    <Section label="PROJECTS">
      {projects.map((project) => (
        <div key={project.id}>
          <button
            type="button"
            className={`lab-explorer-row ${selectedProjectId === project.id && !selectedTaskId ? "is-selected" : ""}`}
            onClick={() => selectProject(project.id)}
          >
            <span className="lab-row-main"><Icon name="research" size={14} />{project.name}</span>
            <span className="lab-row-count">{tasks.filter((task) => task.project_id === project.id).length}</span>
          </button>
          {selectedProjectId === project.id && tasks.filter((task) => task.project_id === project.id).map((task) => (
            <button
              key={task.id}
              type="button"
              className={`lab-explorer-row lab-explorer-child ${selectedTaskId === task.id ? "is-selected" : ""}`}
              onClick={() => selectTask(task.id)}
            >
              <span className="lab-row-main"><i className={`lab-status-dot is-${task.status}`} />{task.title}</span>
            </button>
          ))}
        </div>
      ))}
      {projects.length === 0 && <p className="lab-sidebar-empty">No research projects yet.</p>}
    </Section>
  );
}

function MeetingExplorer() {
  const meetings = useLabStore((state) => state.snapshot.meetings);
  const selected = useLabStore((state) => state.selectedMeetingId);
  const select = useLabStore((state) => state.selectMeeting);
  return (
    <Section label="ROOMS">
      {meetings.map((meeting) => (
        <button
          key={meeting.id}
          type="button"
          className={`lab-explorer-row ${selected === meeting.id ? "is-selected" : ""}`}
          onClick={() => select(meeting.id)}
        >
          <span className="lab-row-main"><i className={`lab-status-dot is-${meeting.status}`} />{meeting.title}</span>
          <span className="lab-row-count">{meeting.participant_ids.length}</span>
        </button>
      ))}
      {meetings.length === 0 && <p className="lab-sidebar-empty">No meeting rooms yet.</p>}
    </Section>
  );
}

function SecurityExplorer() {
  return (
    <>
      <Section label="SECURITY CENTER">
        <div className="lab-explorer-row is-selected">Posture overview</div>
        <div className="lab-explorer-row">Agent capabilities</div>
        <div className="lab-explorer-row">Communication scope</div>
      </Section>
      <Section label="POLICY">
        <p className="lab-sidebar-note">Ordinary research agents are synthesis-only: no autonomous web, host tools, or implicit file attachment. Optional M9 jobs use a separate approval boundary.</p>
      </Section>
    </>
  );
}

export default function ContextSidebar({ view }: { view: ResearchView }) {
  return (
    <aside className="lab-context-sidebar">
      <ExplorerHeader view={view} />
      <div className="lab-explorer-scroll">
        {view === "hq" && <HqExplorer />}
        {view === "organization" && <OrganizationExplorer />}
        {view === "research" && <ResearchExplorer />}
        {view === "knowledge" && <ResearchExplorer />}
        {view === "evaluations" && <ResearchExplorer />}
        {view === "meetings" && <MeetingExplorer />}
        {view === "operations" && <ResearchExplorer />}
        {view === "security" && <SecurityExplorer />}
      </div>
    </aside>
  );
}
