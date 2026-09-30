// R&D Studio domain types and tolerant snapshot normalization.
// The backend owns the canonical snake_case schema; this file keeps the UI resilient
// while an older local database is being upgraded or optional collections are absent.

export type ResearchView = "hq" | "organization" | "research" | "meetings" | "security";
export type IdeView = "explorer" | "search" | "source_control" | "terminal";
export type LabView = ResearchView | IdeView | "workbench";

export type DepartmentKind = "department" | "mission_team";
export type EntityStatus = "active" | "paused" | "archived" | string;
export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | string;

export interface Department {
  id: string;
  name: string;
  description: string;
  kind: DepartmentKind;
  status: EntityStatus;
  created_at?: string;
  updated_at?: string;
}

export interface Agent {
  id: string;
  department_id: string | null;
  name: string;
  role: string;
  mission: string;
  duties: string[];
  focus: string[];
  priorities: string[];
  model: string;
  status: EntityStatus;
  communication_scope: "isolated" | "department" | "organization" | string;
  created_at?: string;
  updated_at?: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  objective: string;
  status: EntityStatus;
  created_at?: string;
  updated_at?: string;
}

export interface ResearchTask {
  id: string;
  project_id: string;
  department_id: string | null;
  assigned_agent_id: string | null;
  title: string;
  objective: string;
  context: string;
  expected_output: string;
  status: EntityStatus;
  created_at?: string;
  updated_at?: string;
}

export interface ResearchResult {
  id: string;
  task_id: string;
  run_id: string | null;
  agent_id: string | null;
  title: string;
  content: string;
  status: string;
  created_at?: string;
}

export interface Finding {
  id: string;
  task_id: string;
  project_id: string;
  result_id: string;
  agent_id: string;
  title: string;
  content: string;
  confidence: number | null;
  citations: { title?: string; url?: string }[];
  created_at?: string;
}

export interface Meeting {
  id: string;
  project_id: string | null;
  department_id: string | null;
  title: string;
  agenda: string;
  facilitator_agent_id: string | null;
  participant_ids: string[];
  status: EntityStatus;
  created_at?: string;
  updated_at?: string;
}

export interface MeetingMessage {
  id: string;
  meeting_id: string;
  run_id: string | null;
  agent_id: string | null;
  kind: "contribution" | "synthesis" | string;
  ordinal: number;
  content: string;
  created_at?: string;
}

export interface LabRun {
  id: string;
  kind: "task" | "meeting" | string;
  project_id: string;
  task_id: string | null;
  meeting_id: string | null;
  status: RunStatus;
  error?: string | null;
  tokens_in: number;
  tokens_out: number;
  started_at?: string;
  completed_at?: string | null;
}

export interface Activity {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string;
  run_id: string | null;
  agent_id: string | null;
  details: Record<string, unknown>;
  created_at?: string;
}

export interface LiveTurn {
  id: string;
  agent_id: string | null;
  text: string;
  complete: boolean;
}

export interface LiveRun {
  run_id: string;
  task_id: string | null;
  meeting_id: string | null;
  status: RunStatus;
  turns: LiveTurn[];
  error: string | null;
  started_at: string;
}

export interface LabSnapshot {
  departments: Department[];
  agents: Agent[];
  projects: Project[];
  tasks: ResearchTask[];
  results: ResearchResult[];
  findings: Finding[];
  meetings: Meeting[];
  meeting_messages: MeetingMessage[];
  runs: LabRun[];
  activities: Activity[];
}

const EMPTY_SNAPSHOT: LabSnapshot = {
  departments: [],
  agents: [],
  projects: [],
  tasks: [],
  results: [],
  findings: [],
  meetings: [],
  meeting_messages: [],
  runs: [],
  activities: [],
};

type JsonRecord = Record<string, unknown>;

function record(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function rows(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function nullableText(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function number(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string");
  if (typeof value !== "string" || value.trim() === "") return [];
  try {
    const parsed: unknown = JSON.parse(value);
    if (Array.isArray(parsed)) {
      return parsed.filter((item): item is string => typeof item === "string");
    }
  } catch {
    // Older data may be newline separated instead of JSON.
  }
  return value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
}

function base(row: JsonRecord) {
  return {
    id: text(row.id, crypto.randomUUID()),
    created_at: nullableText(row.created_at) ?? undefined,
    updated_at: nullableText(row.updated_at) ?? undefined,
  };
}

/** Normalize a backend model dump without letting one malformed optional row break the Studio. */
export function normalizeLabSnapshot(value: unknown): LabSnapshot {
  const root = record(value);
  return {
    ...EMPTY_SNAPSHOT,
    departments: rows(root.departments).map((row) => ({
      ...base(row),
      name: text(row.name, "Untitled group"),
      description: text(row.description),
      kind: row.kind === "mission_team" ? "mission_team" : "department",
      status: text(row.status, "active"),
    })),
    agents: rows(root.agents).map((row) => ({
      ...base(row),
      department_id: nullableText(row.department_id),
      name: text(row.name, "Unnamed agent"),
      role: text(row.role, "Research agent"),
      mission: text(row.mission),
      duties: stringList(row.duties),
      focus: stringList(row.focus),
      priorities: stringList(row.priorities),
      model: text(row.model, "default"),
      status: text(row.status, "active"),
      communication_scope: text(row.communication_scope, "isolated"),
    })),
    projects: rows(root.projects).map((row) => ({
      ...base(row),
      name: text(row.name, "Untitled project"),
      description: text(row.description),
      objective: text(row.objective),
      status: text(row.status, "active"),
    })),
    tasks: rows(root.tasks).map((row) => ({
      ...base(row),
      project_id: text(row.project_id),
      department_id: nullableText(row.department_id),
      assigned_agent_id: nullableText(row.assigned_agent_id),
      title: text(row.title, "Untitled task"),
      objective: text(row.objective),
      context: text(row.context),
      expected_output: text(row.expected_output),
      status: text(row.status, "draft"),
    })),
    results: rows(root.results).map((row) => ({
      ...base(row),
      task_id: text(row.task_id),
      run_id: nullableText(row.run_id),
      agent_id: nullableText(row.agent_id),
      title: text(row.title, "Model synthesis"),
      content: text(row.content, text(row.text)),
      status: text(row.status, "completed"),
    })),
    findings: rows(root.findings).map((row) => ({
      ...base(row),
      task_id: text(row.task_id),
      project_id: text(row.project_id),
      result_id: text(row.result_id),
      agent_id: text(row.agent_id),
      title: text(row.title, "Research finding"),
      content: text(row.content, text(row.text)),
      confidence: typeof row.confidence === "number" ? row.confidence : null,
      citations: Array.isArray(row.citations)
        ? row.citations.filter((item): item is { title?: string; url?: string } =>
            item !== null && typeof item === "object")
        : [],
    })),
    meetings: rows(root.meetings).map((row) => ({
      ...base(row),
      project_id: nullableText(row.project_id),
      department_id: nullableText(row.department_id),
      title: text(row.title, "Untitled meeting"),
      agenda: text(row.agenda),
      facilitator_agent_id: nullableText(row.facilitator_agent_id),
      participant_ids: stringList(row.participant_ids),
      status: text(row.status, "draft"),
    })),
    meeting_messages: rows(root.meeting_messages).map((row) => ({
      ...base(row),
      meeting_id: text(row.meeting_id),
      run_id: nullableText(row.run_id),
      agent_id: nullableText(row.agent_id),
      kind: text(row.kind, "contribution"),
      ordinal: number(row.ordinal),
      content: text(row.content, text(row.text)),
    })),
    runs: rows(root.runs).map((row) => ({
      id: text(row.id, crypto.randomUUID()),
      kind: text(row.kind, "task"),
      project_id: text(row.project_id),
      task_id: nullableText(row.task_id),
      meeting_id: nullableText(row.meeting_id),
      status: text(row.status, "queued"),
      error: nullableText(row.error),
      tokens_in: number(row.tokens_in),
      tokens_out: number(row.tokens_out),
      started_at: nullableText(row.started_at) ?? undefined,
      completed_at: nullableText(row.completed_at),
    })),
    activities: rows(root.activities).map((row) => ({
      ...base(row),
      action: text(row.action, "activity.recorded"),
      entity_type: text(row.entity_type, "entity"),
      entity_id: text(row.entity_id),
      run_id: nullableText(row.run_id),
      agent_id: nullableText(row.agent_id),
      details: record(row.details),
    })),
  };
}
