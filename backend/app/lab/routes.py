"""FastAPI routes for departments, agents, research tasks, and meeting rooms.

The router is intentionally a thin boundary: Pydantic validates browser input,
``repo`` owns persistence and domain rules, and ``lab_orchestrator`` owns model runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import SQLModel

from app.config import get_config
from app.lab import repo
from app.lab.orchestrator import lab_orchestrator
from app.lab.schemas import (
    AgentCreate,
    AgentUpdate,
    DepartmentCreate,
    DepartmentUpdate,
    MeetingCreate,
    MeetingUpdate,
    ProjectCreate,
    ProjectUpdate,
    RunRequest,
    TaskCreate,
    TaskUpdate,
)

router = APIRouter(prefix="/api/lab", tags=["research-lab"])

def _translate(error: repo.LabError) -> HTTPException:
    """Map expected domain failures to stable, non-leaking HTTP responses."""
    if isinstance(error, repo.LabNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, repo.LabConflictError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


async def _call[T](function: Callable[..., T], *args: Any) -> T:
    """Run one synchronous repository operation without blocking the event loop."""
    try:
        return await asyncio.to_thread(function, *args)
    except repo.LabError as error:
        raise _translate(error) from error


def _dump(row: SQLModel) -> dict[str, Any]:
    return row.model_dump(mode="json")


def _values(request: BaseModel) -> dict[str, Any]:
    return request.model_dump(mode="json", exclude_unset=True)


def _allowed_models() -> set[str]:
    config = get_config()
    return set(config.roles.values()) | set(config.pricing)


def _agent_values(request: AgentCreate | AgentUpdate) -> dict[str, Any]:
    values = _values(request)
    if "model" not in values and isinstance(request, AgentUpdate):
        return values
    if not values.get("model"):
        values["model"] = get_config().roles["researcher"]
    if values["model"] not in _allowed_models():
        raise HTTPException(
            status_code=422,
            detail="model must be one of the model IDs configured in backend/config.toml",
        )
    return values


@router.get("/snapshot")
async def get_snapshot() -> dict[str, list[dict[str, Any]]]:
    """Hydrate the small local lab with one bounded, consistent-shaped response."""
    rows = await _call(repo.snapshot)
    return {name: [_dump(row) for row in collection] for name, collection in rows.items()}


@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(request: DepartmentCreate) -> dict[str, Any]:
    return _dump(await _call(repo.create_department, _values(request)))


@router.patch("/departments/{department_id}")
async def update_department(department_id: str, request: DepartmentUpdate) -> dict[str, Any]:
    return _dump(await _call(repo.update_department, department_id, _values(request)))


@router.post("/agents", status_code=status.HTTP_201_CREATED)
async def create_agent(request: AgentCreate) -> dict[str, Any]:
    return _dump(await _call(repo.create_agent, _agent_values(request)))


@router.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, request: AgentUpdate) -> dict[str, Any]:
    return _dump(await _call(repo.update_agent, agent_id, _agent_values(request)))


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(request: ProjectCreate) -> dict[str, Any]:
    return _dump(await _call(repo.create_project, _values(request)))


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, request: ProjectUpdate) -> dict[str, Any]:
    return _dump(await _call(repo.update_project, project_id, _values(request)))


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(request: TaskCreate) -> dict[str, Any]:
    return _dump(await _call(repo.create_task, _values(request)))


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, request: TaskUpdate) -> dict[str, Any]:
    return _dump(await _call(repo.update_task, task_id, _values(request)))


@router.post("/tasks/{task_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_task(task_id: str, request: RunRequest) -> dict[str, str]:
    try:
        run = await lab_orchestrator.start_task(task_id, request.instructions)
    except repo.LabError as error:
        raise _translate(error) from error
    return {"run_id": run.id, "task_id": task_id, "status": run.status}


@router.post("/meetings", status_code=status.HTTP_201_CREATED)
async def create_meeting(request: MeetingCreate) -> dict[str, Any]:
    return _dump(await _call(repo.create_meeting, _values(request)))


@router.patch("/meetings/{meeting_id}")
async def update_meeting(meeting_id: str, request: MeetingUpdate) -> dict[str, Any]:
    return _dump(await _call(repo.update_meeting, meeting_id, _values(request)))


@router.post("/meetings/{meeting_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_meeting(meeting_id: str, request: RunRequest) -> dict[str, str]:
    try:
        run = await lab_orchestrator.start_meeting(meeting_id, request.instructions)
    except repo.LabError as error:
        raise _translate(error) from error
    return {"run_id": run.id, "meeting_id": meeting_id, "status": run.status}
