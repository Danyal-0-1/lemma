// Bounded meeting rooms: explicit roster, one contribution each, one synthesis.

import { useState, type FormEvent } from "react";

import { createLabEntity, runLabMeeting } from "../../lib/api";
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
import type { Meeting } from "../types";

const MAX_PARTICIPANTS = 12;

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed.";
}

function MeetingForm({ onClose }: { onClose: () => void }) {
  const snapshot = useLabStore((state) => state.snapshot);
  const refresh = useLabStore((state) => state.refresh);
  const selectMeeting = useLabStore((state) => state.selectMeeting);
  const agents = snapshot.agents.filter((agent) => agent.status === "active");
  const projects = snapshot.projects.filter((project) => project.status === "active");
  const departments = snapshot.departments.filter((group) => group.status === "active");
  const [projectId, setProjectId] = useState(projects[0]?.id ?? "");
  const [departmentId, setDepartmentId] = useState("");
  const [title, setTitle] = useState("");
  const [agenda, setAgenda] = useState("");
  const [facilitatorId, setFacilitatorId] = useState(agents[0]?.id ?? "");
  const [participants, setParticipants] = useState<string[]>(
    agents[0] ? [agents[0].id] : [],
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function toggle(id: string) {
    setParticipants((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id);
      if (current.length >= MAX_PARTICIPANTS) return current;
      return [...current, id];
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const meeting = await createLabEntity<Meeting>("meetings", {
        project_id: projectId,
        ...(departmentId ? { department_id: departmentId } : {}),
        title,
        agenda,
        facilitator_agent_id: facilitatorId,
        participant_ids: participants,
      });
      await refresh();
      selectMeeting(meeting.id);
      onClose();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="lab-form" onSubmit={(event) => void submit(event)}>
      <div className="lab-form-grid">
        <Field label="Project">
          <select
            required
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
          >
            <option value="" disabled>Select project</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>{project.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Room home">
          <select
            value={departmentId}
            onChange={(event) => setDepartmentId(event.target.value)}
          >
            <option value="">Cross-organization</option>
            {departments.map((group) => (
              <option key={group.id} value={group.id}>{group.name}</option>
            ))}
          </select>
        </Field>
        <div className="lab-field-span-2">
          <Field label="Meeting name">
            <input
              required
              maxLength={160}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Evidence reconciliation"
              autoFocus
            />
          </Field>
        </div>
        <div className="lab-field-span-2">
          <Field label="Agenda and desired decision">
            <textarea
              required
              maxLength={8000}
              rows={5}
              value={agenda}
              onChange={(event) => setAgenda(event.target.value)}
              placeholder="Compare the strongest findings, name disagreements, and decide which experiment should happen next."
            />
          </Field>
        </div>
        <Field label="Facilitator">
          <select
            required
            value={facilitatorId}
            onChange={(event) => setFacilitatorId(event.target.value)}
          >
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name} — {agent.role}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <fieldset className="lab-roster-field">
        <legend>
          Participants <span>Explicit roster · {participants.length}/{MAX_PARTICIPANTS}</span>
        </legend>
        <div className="lab-roster-grid">
          {agents.map((agent) => {
            const selected = participants.includes(agent.id);
            const atLimit = participants.length >= MAX_PARTICIPANTS;
            return (
              <label key={agent.id} className={selected ? "is-selected" : ""}>
                <input
                  type="checkbox"
                  checked={selected}
                  disabled={!selected && atLimit}
                  onChange={() => toggle(agent.id)}
                />
                <AgentAvatar name={agent.name} size="sm" />
                <span>
                  <strong>{agent.name}</strong>
                  <small>{agent.role} · {agent.communication_scope}</small>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <p className="lab-policy-note">
        <Icon name="security" size={14} />
        The roster is policy checked. Isolated agents cannot join multi-agent rooms;
        group-scoped agents cannot cross group boundaries.
      </p>
      {error && <p className="lab-inline-error">{error}</p>}
      <div className="lab-form-actions">
        <Button onClick={onClose}>Cancel</Button>
        <Button
          type="submit"
          variant="primary"
          disabled={
            saving
            || !projectId
            || !facilitatorId
            || participants.length === 0
            || !title.trim()
            || !agenda.trim()
          }
        >
          {saving ? "Creating…" : "Create meeting room"}
        </Button>
      </div>
    </form>
  );
}

export default function MeetingsView() {
  const snapshot = useLabStore((state) => state.snapshot);
  const selectedId = useLabStore((state) => state.selectedMeetingId);
  const liveRuns = useLabStore((state) => state.liveRuns);
  const registerRun = useLabStore((state) => state.registerRun);
  const [showCreate, setShowCreate] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const meeting = snapshot.meetings.find((item) => item.id === selectedId)
    ?? snapshot.meetings[0]
    ?? null;
  const messages = meeting
    ? snapshot.meeting_messages
      .filter((item) => item.meeting_id === meeting.id)
      .sort(
        (a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? "")
          || a.ordinal - b.ordinal,
      )
    : [];
  const live = meeting
    ? Object.values(liveRuns).filter((run) => run.meeting_id === meeting.id).at(-1)
    : undefined;
  const isRunning = live?.status === "running";
  const visibleMessages = isRunning
    ? messages.filter((message) => message.run_id !== live.run_id)
    : messages;
  const rosterIds = meeting
    ? [...new Set(
      [...meeting.participant_ids, meeting.facilitator_agent_id]
        .filter((id): id is string => Boolean(id)),
    )]
    : [];
  const canCreateMeeting = snapshot.projects.some((project) => project.status === "active")
    && snapshot.agents.some((agent) => agent.status === "active");

  async function run() {
    if (!meeting) return;
    setStarting(true);
    setError(null);
    try {
      const response = await runLabMeeting(meeting.id, instructions);
      registerRun(response);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="lab-view-with-inspector">
      <main className="lab-view lab-meeting-view">
        <header className="lab-page-header">
          <div>
            <span className="lab-eyebrow">BOUNDED COLLABORATION</span>
            <h1>{meeting?.title ?? "Meeting rooms"}</h1>
            <p>
              {meeting?.agenda
                ?? "Bring selected agents together to compare findings and produce a durable synthesis."}
            </p>
          </div>
          <div className="lab-header-actions">
            <Button
              variant="primary"
              icon="plus"
              onClick={() => setShowCreate(true)}
              disabled={!canCreateMeeting}
            >
              New room
            </Button>
          </div>
        </header>

        {!meeting ? (
          <EmptyState
            icon="meetings"
            title="No meeting rooms yet"
            detail="Create a project and at least one agent, then open a room with an explicit roster and agenda."
            action={(
              <Button
                variant="primary"
                onClick={() => setShowCreate(true)}
                disabled={!canCreateMeeting}
              >
                Create room
              </Button>
            )}
          />
        ) : (
          <>
            <UnverifiedNotice compact />
            <section className="lab-transcript" aria-label="Meeting transcript">
              {visibleMessages.map((item) => {
                const agent = snapshot.agents.find(
                  (candidate) => candidate.id === item.agent_id,
                );
                return (
                  <article
                    key={item.id}
                    className={`lab-message ${item.kind === "synthesis" ? "is-synthesis" : ""}`}
                  >
                    <AgentAvatar name={agent?.name ?? "Agent"} />
                    <div>
                      <header>
                        <strong>{agent?.name ?? "Agent"}</strong>
                        <Badge tone={item.kind === "synthesis" ? "ok" : "neutral"}>
                          {item.kind}
                        </Badge>
                      </header>
                      <pre>{item.content}</pre>
                    </div>
                  </article>
                );
              })}
              {isRunning && live.turns.map((turn) => {
                const agent = snapshot.agents.find((item) => item.id === turn.agent_id);
                return (
                  <article key={turn.id} className="lab-message is-live">
                    <AgentAvatar name={agent?.name ?? "Agent"} />
                    <div>
                      <header>
                        <strong>{agent?.name ?? "Agent"}</strong>
                        <Badge tone="warn">live</Badge>
                      </header>
                      <pre>{turn.text || "Preparing contribution…"}</pre>
                    </div>
                  </article>
                );
              })}
              {visibleMessages.length === 0 && (isRunning ? live.turns.length : 0) === 0 && (
                <div className="lab-transcript-empty">
                  <Icon name="meetings" size={26} />
                  <h2>The room is ready</h2>
                  <p>
                    Start the meeting when the agenda and roster look right. Each participant
                    contributes once, then the facilitator synthesizes.
                  </p>
                </div>
              )}
            </section>
          </>
        )}
      </main>

      <aside className="lab-inspector">
        {meeting ? (
          <>
            <header className="lab-inspector-header">
              <span>ROOM CONTROL</span>
              <StatusBadge status={live?.status ?? meeting.status} />
            </header>
            <div className="lab-inspector-scroll">
              <section className="lab-inspector-section">
                <h3>Agenda</h3>
                <p>{meeting.agenda}</p>
              </section>
              <section className="lab-inspector-section">
                <h3>Participants</h3>
                <div className="lab-participant-list">
                  {rosterIds.map((id) => {
                    const agent = snapshot.agents.find((item) => item.id === id);
                    return agent ? (
                      <div key={id}>
                        <AgentAvatar name={agent.name} size="sm" />
                        <span>
                          <strong>{agent.name}</strong>
                          <small>{agent.role}</small>
                        </span>
                        {id === meeting.facilitator_agent_id && <Badge>facilitator</Badge>}
                      </div>
                    ) : null;
                  })}
                </div>
              </section>
              <section className="lab-protocol">
                <h3>Room protocol</h3>
                <ol>
                  <li>Independent contribution</li>
                  <li>Shared transcript</li>
                  <li>Facilitator synthesis</li>
                  <li>Human review</li>
                </ol>
              </section>
              <Field label="Moderator guidance">
                <textarea
                  rows={3}
                  maxLength={4000}
                  value={instructions}
                  onChange={(event) => setInstructions(event.target.value)}
                  placeholder="Resolve the disagreement about…"
                />
              </Field>
              {error && <p className="lab-inline-error">{error}</p>}
              {live?.status === "failed" && live.error && (
                <p className="lab-inline-error">Meeting failed: {live.error}</p>
              )}
            </div>
            <footer className="lab-inspector-footer">
              <Button
                variant="primary"
                icon="play"
                onClick={() => void run()}
                disabled={starting || meeting.status === "running" || isRunning}
              >
                {starting
                  ? "Starting…"
                  : meeting.status === "completed"
                    ? "Run another round"
                    : "Start meeting"}
              </Button>
            </footer>
          </>
        ) : (
          <div className="lab-inspector-placeholder">
            <Icon name="meetings" size={28} />
            <h2>Select a room</h2>
          </div>
        )}
      </aside>

      {showCreate && (
        <Modal
          title="Create a meeting room"
          description="Explicit participants, fixed turns, durable transcript."
          onClose={() => setShowCreate(false)}
        >
          <MeetingForm onClose={() => setShowCreate(false)} />
        </Modal>
      )}
    </div>
  );
}
