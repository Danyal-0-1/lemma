"""Synchronous persistence and domain invariants for the research lab.

FastAPI and the orchestrator call these functions through ``asyncio.to_thread``.
Keeping transactions here makes run claiming, result persistence, and audit writes
atomic even though model calls happen asynchronously elsewhere.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, SQLModel, select

from app.db import get_session
from app.models import (
    ActivityRecord,
    Department,
    Finding,
    LabAgent,
    LabRun,
    MeetingMessage,
    ResearchMeeting,
    ResearchProject,
    ResearchTask,
    TaskResult,
)


class LabError(Exception):
    """Base class for expected domain failures translated by the API layer."""


class LabNotFoundError(LabError):
    """Raised when a requested durable entity does not exist."""


class LabConflictError(LabError):
    """Raised for duplicate names or already-running work."""


class LabValidationError(LabError):
    """Raised when references or communication policy violate domain rules."""


def _now() -> datetime:
    return datetime.now(UTC)


def _require[RowT: SQLModel](
    db: Session, model: type[RowT], row_id: str, label: str
) -> RowT:
    row = db.get(model, row_id)
    if row is None:
        raise LabNotFoundError(f"{label} not found")
    return row


def _record(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: str,
    *,
    run_id: str | None = None,
    agent_id: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    db.add(
        ActivityRecord(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            run_id=run_id,
            agent_id=agent_id,
            details=details or {},
        )
    )


def _apply(row: SQLModel, changes: dict[str, Any]) -> None:
    for field, value in changes.items():
        setattr(row, field, value)
    if hasattr(row, "updated_at"):
        setattr(row, "updated_at", _now())


def _ensure_department(db: Session, department_id: str | None) -> Department | None:
    if department_id is None:
        return None
    department = _require(db, Department, department_id, "department")
    if department.status != "active":
        raise LabValidationError("department must be active")
    return department


def _ensure_agent(db: Session, agent_id: str, *, active: bool = False) -> LabAgent:
    agent = _require(db, LabAgent, agent_id, "agent")
    if active and agent.status != "active":
        raise LabValidationError(f"agent {agent.name!r} must be active")
    return agent


def _ensure_project(db: Session, project_id: str, *, active: bool = False) -> ResearchProject:
    project = _require(db, ResearchProject, project_id, "project")
    if active and project.status != "active":
        raise LabValidationError("project must be active")
    return project


def create_department(values: dict[str, Any]) -> Department:
    with get_session() as db:
        duplicate = db.exec(select(Department).where(Department.name == values["name"])).first()
        if duplicate is not None:
            raise LabConflictError("a department or mission team with that name already exists")
        department = Department(**values)
        db.add(department)
        _record(
            db,
            "department.created",
            "department",
            department.id,
            details={"kind": department.kind},
        )
        db.commit()
        db.refresh(department)
        return department


def update_department(department_id: str, changes: dict[str, Any]) -> Department:
    with get_session() as db:
        department = _require(db, Department, department_id, "department")
        if "name" in changes:
            duplicate = db.exec(
                select(Department).where(
                    Department.name == changes["name"], Department.id != department_id
                )
            ).first()
            if duplicate is not None:
                raise LabConflictError("a department or mission team with that name already exists")
        _apply(department, changes)
        db.add(department)
        _record(
            db,
            "department.updated",
            "department",
            department.id,
            details={"fields": list(changes)},
        )
        db.commit()
        db.refresh(department)
        return department


def create_agent(values: dict[str, Any]) -> LabAgent:
    with get_session() as db:
        _ensure_department(db, values.get("department_id"))
        agent = LabAgent(**values)
        db.add(agent)
        _record(db, "agent.created", "agent", agent.id, agent_id=agent.id)
        db.commit()
        db.refresh(agent)
        return agent


def update_agent(agent_id: str, changes: dict[str, Any]) -> LabAgent:
    with get_session() as db:
        agent = _require(db, LabAgent, agent_id, "agent")
        if "department_id" in changes:
            _ensure_department(db, changes["department_id"])
        _apply(agent, changes)
        db.add(agent)
        _record(
            db,
            "agent.updated",
            "agent",
            agent.id,
            agent_id=agent.id,
            details={"fields": list(changes)},
        )
        db.commit()
        db.refresh(agent)
        return agent


def create_project(values: dict[str, Any]) -> ResearchProject:
    with get_session() as db:
        project = ResearchProject(**values)
        db.add(project)
        _record(db, "project.created", "project", project.id)
        db.commit()
        db.refresh(project)
        return project


def update_project(project_id: str, changes: dict[str, Any]) -> ResearchProject:
    with get_session() as db:
        project = _require(db, ResearchProject, project_id, "project")
        _apply(project, changes)
        db.add(project)
        _record(db, "project.updated", "project", project.id, details={"fields": list(changes)})
        db.commit()
        db.refresh(project)
        return project


def _validate_assignment(
    db: Session, department_id: str | None, agent: LabAgent
) -> None:
    _ensure_department(db, department_id)
    if (
        department_id is not None
        and agent.department_id != department_id
        and agent.communication_scope != "organization"
    ):
        raise LabValidationError(
            "an agent outside the task's department/team needs organization communication scope"
        )


def create_task(values: dict[str, Any]) -> ResearchTask:
    with get_session() as db:
        _ensure_project(db, values["project_id"], active=True)
        agent = _ensure_agent(db, values["assigned_agent_id"], active=True)
        _validate_assignment(db, values.get("department_id"), agent)
        if values.get("status") == "running":
            raise LabValidationError("tasks enter running state only through the run endpoint")
        task = ResearchTask(**values)
        db.add(task)
        _record(db, "task.created", "task", task.id, agent_id=task.assigned_agent_id)
        db.commit()
        db.refresh(task)
        return task


def update_task(task_id: str, changes: dict[str, Any]) -> ResearchTask:
    with get_session() as db:
        task = _require(db, ResearchTask, task_id, "task")
        if task.status == "running":
            raise LabConflictError("a running task cannot be edited")
        if changes.get("status") == "running":
            raise LabValidationError("tasks enter running state only through the run endpoint")
        agent_id = changes.get("assigned_agent_id", task.assigned_agent_id)
        department_id = changes.get("department_id", task.department_id)
        agent = _ensure_agent(db, agent_id, active=True)
        _validate_assignment(db, department_id, agent)
        _apply(task, changes)
        db.add(task)
        _record(
            db,
            "task.updated",
            "task",
            task.id,
            agent_id=task.assigned_agent_id,
            details={"fields": list(changes)},
        )
        db.commit()
        db.refresh(task)
        return task


def _communication_allowed(agents: Iterable[LabAgent]) -> None:
    roster = list(agents)
    if len(roster) <= 1:
        return
    for agent in roster:
        others = [other for other in roster if other.id != agent.id]
        if agent.communication_scope == "isolated" and others:
            raise LabValidationError(
                f"agent {agent.name!r} is isolated and cannot join this meeting"
            )
        if agent.communication_scope == "department":
            if agent.department_id is None:
                raise LabValidationError(
                    f"agent {agent.name!r} needs a department/team for "
                    "department-scoped communication"
                )
            if any(other.department_id != agent.department_id for other in others):
                raise LabValidationError(
                    f"agent {agent.name!r} can communicate only inside its department/team"
                )


def validate_meeting_roster(db: Session, meeting: ResearchMeeting) -> list[LabAgent]:
    """Return the active, policy-compatible participant and facilitator roster."""
    ordered_ids = [*meeting.participant_ids]
    if meeting.facilitator_agent_id not in ordered_ids:
        ordered_ids.append(meeting.facilitator_agent_id)
    agents = [_ensure_agent(db, agent_id, active=True) for agent_id in ordered_ids]
    _communication_allowed(agents)
    return agents


def create_meeting(values: dict[str, Any]) -> ResearchMeeting:
    with get_session() as db:
        _ensure_project(db, values["project_id"], active=True)
        _ensure_department(db, values.get("department_id"))
        if values.get("status") == "running":
            raise LabValidationError("meetings enter running state only through the run endpoint")
        meeting = ResearchMeeting(**values)
        validate_meeting_roster(db, meeting)
        db.add(meeting)
        _record(db, "meeting.created", "meeting", meeting.id)
        db.commit()
        db.refresh(meeting)
        return meeting


def update_meeting(meeting_id: str, changes: dict[str, Any]) -> ResearchMeeting:
    with get_session() as db:
        meeting = _require(db, ResearchMeeting, meeting_id, "meeting")
        if meeting.status == "running":
            raise LabConflictError("a running meeting cannot be edited")
        if changes.get("status") == "running":
            raise LabValidationError("meetings enter running state only through the run endpoint")
        candidate = meeting.model_copy(deep=True)
        _apply(candidate, changes)
        _ensure_department(db, candidate.department_id)
        validate_meeting_roster(db, candidate)
        _apply(meeting, changes)
        db.add(meeting)
        _record(db, "meeting.updated", "meeting", meeting.id, details={"fields": list(changes)})
        db.commit()
        db.refresh(meeting)
        return meeting


def get_agent(agent_id: str) -> LabAgent:
    with get_session() as db:
        return _require(db, LabAgent, agent_id, "agent")


def get_task(task_id: str) -> ResearchTask:
    with get_session() as db:
        return _require(db, ResearchTask, task_id, "task")


def get_project(project_id: str) -> ResearchProject:
    with get_session() as db:
        return _require(db, ResearchProject, project_id, "project")


def get_meeting(meeting_id: str) -> ResearchMeeting:
    with get_session() as db:
        return _require(db, ResearchMeeting, meeting_id, "meeting")


def get_run(run_id: str) -> LabRun:
    with get_session() as db:
        return _require(db, LabRun, run_id, "run")


def recover_stale_runs() -> int:
    """Fail runs left active by a prior crash so their work can be retried safely."""
    with get_session() as db:
        stale = list(db.exec(select(LabRun).where(LabRun.status == "running")))
        if not stale:
            return 0
        completed_at = _now()
        for run in stale:
            run.status = "failed"
            run.error = "run was interrupted by a previous server shutdown"
            run.completed_at = completed_at
            db.add(run)
            if run.task_id is not None:
                task = db.get(ResearchTask, run.task_id)
                if task is not None and task.status == "running":
                    task.status = "failed"
                    task.updated_at = completed_at
                    db.add(task)
            if run.meeting_id is not None:
                meeting = db.get(ResearchMeeting, run.meeting_id)
                if meeting is not None and meeting.status == "running":
                    meeting.status = "failed"
                    meeting.updated_at = completed_at
                    db.add(meeting)
            _record(
                db,
                "run.recovered_as_failed",
                run.kind,
                run.task_id or run.meeting_id or run.id,
                run_id=run.id,
                details={"reason": "previous server shutdown"},
            )
        db.commit()
        return len(stale)


def begin_task_run(task_id: str) -> LabRun:
    """Atomically mark a task running and create its durable run row."""
    with get_session() as db:
        task = _require(db, ResearchTask, task_id, "task")
        if task.status == "running":
            raise LabConflictError("task already has a running execution")
        _ensure_project(db, task.project_id, active=True)
        agent = _ensure_agent(db, task.assigned_agent_id, active=True)
        _validate_assignment(db, task.department_id, agent)
        running = db.exec(
            select(LabRun).where(LabRun.task_id == task.id, LabRun.status == "running")
        ).first()
        if running is not None:
            raise LabConflictError("task already has a running execution")
        run = LabRun(kind="task", project_id=task.project_id, task_id=task.id)
        task.status = "running"
        task.updated_at = _now()
        db.add(run)
        db.add(task)
        _record(
            db,
            "task.run_started",
            "task",
            task.id,
            run_id=run.id,
            agent_id=task.assigned_agent_id,
        )
        db.commit()
        db.refresh(run)
        return run


def complete_task_run(
    run_id: str, content: str, tokens_in: int, tokens_out: int
) -> tuple[TaskResult, Finding]:
    """Persist a result + finding and finish the task/run in one transaction."""
    with get_session() as db:
        run = _require(db, LabRun, run_id, "run")
        if run.kind != "task" or run.task_id is None:
            raise LabValidationError("run is not a task execution")
        if run.status != "running":
            raise LabConflictError("run is no longer active")
        task = _require(db, ResearchTask, run.task_id, "task")
        result = TaskResult(
            project_id=run.project_id,
            task_id=task.id,
            run_id=run.id,
            agent_id=task.assigned_agent_id,
            content=content,
        )
        finding = Finding(
            project_id=run.project_id,
            task_id=task.id,
            result_id=result.id,
            agent_id=task.assigned_agent_id,
            title=task.title,
            content=content,
        )
        run.status = "completed"
        run.tokens_in = tokens_in
        run.tokens_out = tokens_out
        run.completed_at = _now()
        task.status = "completed"
        task.updated_at = _now()
        db.add(result)
        db.add(finding)
        db.add(run)
        db.add(task)
        _record(
            db,
            "task.run_completed",
            "task",
            task.id,
            run_id=run.id,
            agent_id=task.assigned_agent_id,
            details={"result_id": result.id, "finding_id": finding.id},
        )
        db.commit()
        db.refresh(result)
        db.refresh(finding)
        return result, finding


def fail_task_run(run_id: str, message: str) -> None:
    with get_session() as db:
        run = _require(db, LabRun, run_id, "run")
        if run.task_id is None:
            return
        task = _require(db, ResearchTask, run.task_id, "task")
        run.status = "failed"
        run.error = message[:2_000]
        run.completed_at = _now()
        task.status = "failed"
        task.updated_at = _now()
        db.add(run)
        db.add(task)
        _record(db, "task.run_failed", "task", task.id, run_id=run.id, details={"error": run.error})
        db.commit()


def begin_meeting_run(meeting_id: str) -> LabRun:
    """Validate communication policy, then atomically claim a meeting."""
    with get_session() as db:
        meeting = _require(db, ResearchMeeting, meeting_id, "meeting")
        if meeting.status == "running":
            raise LabConflictError("meeting already has a running execution")
        _ensure_project(db, meeting.project_id, active=True)
        _ensure_department(db, meeting.department_id)
        validate_meeting_roster(db, meeting)
        running = db.exec(
            select(LabRun).where(LabRun.meeting_id == meeting.id, LabRun.status == "running")
        ).first()
        if running is not None:
            raise LabConflictError("meeting already has a running execution")
        run = LabRun(kind="meeting", project_id=meeting.project_id, meeting_id=meeting.id)
        meeting.status = "running"
        meeting.updated_at = _now()
        db.add(run)
        db.add(meeting)
        _record(db, "meeting.run_started", "meeting", meeting.id, run_id=run.id)
        db.commit()
        db.refresh(run)
        return run


def add_meeting_message(
    run_id: str, agent_id: str, kind: str, ordinal: int, content: str
) -> MeetingMessage:
    with get_session() as db:
        run = _require(db, LabRun, run_id, "run")
        if run.meeting_id is None or run.status != "running":
            raise LabConflictError("meeting run is no longer active")
        message = MeetingMessage(
            meeting_id=run.meeting_id,
            run_id=run.id,
            agent_id=agent_id,
            kind=kind,
            ordinal=ordinal,
            content=content,
        )
        db.add(message)
        _record(
            db,
            "meeting.message_created",
            "meeting",
            run.meeting_id,
            run_id=run.id,
            agent_id=agent_id,
            details={"message_id": message.id, "kind": kind, "ordinal": ordinal},
        )
        db.commit()
        db.refresh(message)
        return message


def complete_meeting_run(run_id: str, tokens_in: int, tokens_out: int) -> None:
    with get_session() as db:
        run = _require(db, LabRun, run_id, "run")
        if run.meeting_id is None or run.status != "running":
            raise LabConflictError("meeting run is no longer active")
        meeting = _require(db, ResearchMeeting, run.meeting_id, "meeting")
        run.status = "completed"
        run.tokens_in = tokens_in
        run.tokens_out = tokens_out
        run.completed_at = _now()
        meeting.status = "completed"
        meeting.updated_at = _now()
        db.add(run)
        db.add(meeting)
        _record(db, "meeting.run_completed", "meeting", meeting.id, run_id=run.id)
        db.commit()


def fail_meeting_run(run_id: str, message: str) -> None:
    with get_session() as db:
        run = _require(db, LabRun, run_id, "run")
        if run.meeting_id is None:
            return
        meeting = _require(db, ResearchMeeting, run.meeting_id, "meeting")
        run.status = "failed"
        run.error = message[:2_000]
        run.completed_at = _now()
        meeting.status = "failed"
        meeting.updated_at = _now()
        db.add(run)
        db.add(meeting)
        _record(
            db,
            "meeting.run_failed",
            "meeting",
            meeting.id,
            run_id=run.id,
            details={"error": run.error},
        )
        db.commit()


def list_project_findings(project_id: str, limit: int = 30) -> list[Finding]:
    with get_session() as db:
        return list(
            db.exec(
                select(Finding)
                .where(Finding.project_id == project_id)
                .order_by(Finding.created_at.desc())
                .limit(limit)
            )
        )


def snapshot() -> dict[str, list[SQLModel]]:
    """Return the complete small-lab state plus a bounded recent activity feed."""
    with get_session() as db:
        return {
            "departments": list(db.exec(select(Department).order_by(Department.created_at))),
            "agents": list(db.exec(select(LabAgent).order_by(LabAgent.created_at))),
            "projects": list(db.exec(select(ResearchProject).order_by(ResearchProject.created_at))),
            "tasks": list(db.exec(select(ResearchTask).order_by(ResearchTask.created_at))),
            "results": list(db.exec(select(TaskResult).order_by(TaskResult.created_at))),
            "findings": list(db.exec(select(Finding).order_by(Finding.created_at))),
            "meetings": list(db.exec(select(ResearchMeeting).order_by(ResearchMeeting.created_at))),
            "meeting_messages": list(
                db.exec(
                    select(MeetingMessage).order_by(
                        MeetingMessage.created_at, MeetingMessage.ordinal
                    )
                )
            ),
            "runs": list(db.exec(select(LabRun).order_by(LabRun.started_at))),
            "activities": list(
                db.exec(
                    select(ActivityRecord).order_by(ActivityRecord.created_at.desc()).limit(250)
                )
            ),
        }
