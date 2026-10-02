"""FastAPI routes for departments, agents, research tasks, and meeting rooms.

The router is intentionally a thin boundary: Pydantic validates browser input,
``repo`` owns persistence and domain rules, and ``lab_orchestrator`` owns model runs.
"""

from __future__ import annotations

import asyncio
import logging
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
    ConnectionId,
    DepartmentCreate,
    DepartmentUpdate,
    MeetingCreate,
    MeetingUpdate,
    ModelId,
    ProjectCreate,
    ProjectUpdate,
    RunRequest,
    TaskCreate,
    TaskUpdate,
)
from app.providers import factory as provider_factory
from app.providers.connections import (
    ModelConnectionError,
    connection_catalog,
    get_connection,
    validate_connection_model,
)
from app.settings import get_settings

router = APIRouter(prefix="/api/lab", tags=["research-lab"])
logger = logging.getLogger("aicompany.lab.routes")


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


def _inferred_connection(model: str) -> str:
    """Map a legacy model prefix to its explicit built-in connection when possible."""
    return get_connection("legacy", model=model).id


def _agent_values(
    request: AgentCreate | AgentUpdate,
    current: Any | None = None,
) -> dict[str, Any]:
    values = _values(request)
    touches_connection = "model" in values or "model_connection" in values
    if isinstance(request, AgentUpdate) and not touches_connection:
        return values

    default_model = get_config().roles["researcher"]
    reset_model = "model" in values and not values.get("model")
    if isinstance(request, AgentCreate):
        model = values.get("model") or default_model
        connection_id = values.get("model_connection") or _inferred_connection(model)
        values["model"] = model
        values["model_connection"] = connection_id
    else:
        if current is None:
            raise RuntimeError("current agent is required to validate a connection update")
        model = default_model if reset_model else values.get("model", current.model)
        if reset_model and "model_connection" not in values:
            connection_id = _inferred_connection(model)
            values["model_connection"] = connection_id
        else:
            connection_id = values.get("model_connection", current.model_connection)
        if "model" in values:
            values["model"] = model

    try:
        validate_connection_model(connection_id, model)
    except ModelConnectionError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error
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
    current = await _call(repo.get_agent, agent_id)
    return _dump(await _call(repo.update_agent, agent_id, _agent_values(request, current)))


@router.get("/model-connections")
async def list_model_connections() -> dict[str, Any]:
    """Describe configured model routes without returning credentials or private paths."""
    settings = get_settings()
    return {
        "mock_mode": settings.mock_llm,
        "connections": [item.public_dict() for item in connection_catalog(settings)],
    }


class ConnectionTestRequest(BaseModel):
    """One bounded model choice used to verify a configured connection."""

    model: ModelId


@router.post("/model-connections/{connection_id}/test")
async def test_model_connection(
    connection_id: ConnectionId,
    request: ConnectionTestRequest,
) -> dict[str, Any]:
    """Run the provider adapter's small connection check and redact upstream failures."""
    try:
        return await provider_factory.test_connection(
            get_settings(), connection_id, request.model
        )
    except ModelConnectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="invalid model connection request",
        ) from None
    except Exception as error:  # noqa: BLE001 - upstream details must not reach the browser
        logger.warning(
            "model connection test failed for %s (%s)",
            connection_id,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="model connection test failed; verify its setup and try again",
        ) from None


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
