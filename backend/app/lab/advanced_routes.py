"""HTTP boundary for evidence, workflow, evaluation, and optional automation features."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ValidationError
from sqlmodel import SQLModel

from app.config import get_config
from app.lab import repo, search, workflows
from app.lab.advanced_schemas import (
    ActionItemCreate,
    ActionItemUpdate,
    AutomationDecisionRequest,
    AutomationPlanCreate,
    ClaimCreate,
    ClaimEvidenceCreate,
    EvaluationCreate,
    EvaluationScoreCreate,
    FindingReviewCreate,
    MeetingOutcomeCreate,
    ProjectPolicyUpdate,
    PromoteActionRequest,
    SearchQuery,
    SourceCreate,
    SourceExcerptCreate,
    TaskDependencyCreate,
    TaskSourceCreate,
    TemplateCreate,
    TemplateInstantiateRequest,
    TraceLinkCreate,
)
from app.lab.automation import automation_runner
from app.lab.evaluation import evaluation_runner
from app.lab.orchestrator import lab_orchestrator
from app.lab.schemas import MeetingCreate, ProjectCreate, TaskCreate

router = APIRouter(prefix="/api/lab", tags=["research-workflows"])


def _translate(error: repo.LabError) -> HTTPException:
    if isinstance(error, repo.LabNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, repo.LabConflictError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


async def _call[T](function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except repo.LabError as error:
        raise _translate(error) from error


def _dump(row: SQLModel) -> dict[str, Any]:
    return row.model_dump(mode="json")


def _values(request: BaseModel) -> dict[str, Any]:
    return request.model_dump(mode="json", exclude_unset=True)


def _configured_models() -> set[str]:
    config = get_config()
    return set(config.roles.values()) | set(config.pricing)


def _validate_models(models: list[str]) -> None:
    unknown = sorted(set(models) - _configured_models())
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"model IDs are not configured in backend/config.toml: {', '.join(unknown)}",
        )


@router.get("/projects/{project_id}/policy")
async def get_project_policy(project_id: str) -> dict[str, Any]:
    return _dump(await _call(workflows.get_policy, project_id))


@router.put("/projects/{project_id}/policy")
async def put_project_policy(project_id: str, request: ProjectPolicyUpdate) -> dict[str, Any]:
    values = _values(request)
    _validate_models(values.get("allowed_models", []))
    return _dump(await _call(workflows.update_policy, project_id, values))


@router.get("/projects/{project_id}/budget")
async def get_project_budget(project_id: str) -> dict[str, object]:
    return await _call(workflows.project_budget_summary, project_id)


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def create_source(request: SourceCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.create_source, _values(request)))


@router.get("/projects/{project_id}/sources")
async def list_sources(project_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
    rows = await _call(workflows.list_sources, project_id, include_archived=include_archived)
    return [_dump(row) for row in rows]


@router.post("/sources/{source_id}/archive")
async def archive_source(source_id: str) -> dict[str, Any]:
    return _dump(await _call(workflows.archive_source, source_id))


@router.post("/sources/{source_id}/excerpts", status_code=status.HTTP_201_CREATED)
async def create_excerpt(source_id: str, request: SourceExcerptCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.create_excerpt, source_id, _values(request)))


@router.post("/tasks/{task_id}/sources", status_code=status.HTTP_201_CREATED)
async def link_task_source(task_id: str, request: TaskSourceCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.link_task_source, task_id, _values(request)))


@router.get("/tasks/{task_id}/sources")
async def get_task_source_packet(task_id: str) -> list[dict[str, Any]]:
    return [_dump(row) for row in await _call(workflows.task_source_packet, task_id)]


@router.delete("/task-source-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_task_source(link_id: str) -> Response:
    await _call(workflows.unlink_task_source, link_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/findings/{finding_id}/reviews", status_code=status.HTTP_201_CREATED)
async def review_finding(finding_id: str, request: FindingReviewCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.review_finding, finding_id, _values(request)))


@router.post("/claims", status_code=status.HTTP_201_CREATED)
async def create_claim(request: ClaimCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.create_claim, _values(request)))


@router.post("/claims/{claim_id}/evidence", status_code=status.HTTP_201_CREATED)
async def attach_claim_evidence(claim_id: str, request: ClaimEvidenceCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.attach_claim_evidence, claim_id, _values(request)))


@router.post("/meetings/{meeting_id}/outcomes", status_code=status.HTTP_201_CREATED)
async def create_meeting_outcome(meeting_id: str, request: MeetingOutcomeCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.create_meeting_outcome, meeting_id, _values(request)))


@router.post("/actions", status_code=status.HTTP_201_CREATED)
async def create_action(request: ActionItemCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.create_action, _values(request)))


@router.patch("/actions/{action_id}")
async def update_action(action_id: str, request: ActionItemUpdate) -> dict[str, Any]:
    return _dump(await _call(workflows.update_action, action_id, _values(request)))


@router.post("/actions/{action_id}/promote", status_code=status.HTTP_201_CREATED)
async def promote_action(action_id: str, request: PromoteActionRequest) -> dict[str, Any]:
    return _dump(await _call(workflows.promote_action, action_id, _values(request)))


@router.post("/tasks/{task_id}/dependencies", status_code=status.HTTP_201_CREATED)
async def add_task_dependency(task_id: str, request: TaskDependencyCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.add_dependency, task_id, str(request.depends_on_task_id)))


@router.delete("/dependencies/{dependency_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_task_dependency(dependency_id: str) -> Response:
    await _call(workflows.remove_dependency, dependency_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tasks/{task_id}/readiness")
async def get_task_readiness(task_id: str) -> dict[str, object]:
    return await _call(workflows.task_readiness, task_id)


@router.post("/trace-links", status_code=status.HTTP_201_CREATED)
async def create_trace_link(request: TraceLinkCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.create_trace_link, _values(request)))


@router.get("/projects/{project_id}/trace-links")
async def get_trace_links(project_id: str) -> list[dict[str, Any]]:
    return [_dump(row) for row in await _call(workflows.list_trace_links, project_id)]


@router.get("/projects/{project_id}/history")
async def get_project_history(project_id: str, limit: int = 250) -> dict[str, Any]:
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    collections = await _call(workflows.project_history, project_id, limit)
    return {key: [_dump(row) for row in rows] for key, rows in collections.items()}


@router.get("/projects/{project_id}/dossier")
async def get_project_dossier(project_id: str) -> dict[str, Any]:
    return await _call(workflows.project_dossier, project_id)


@router.get("/projects/{project_id}/dossier.md")
async def export_project_dossier(project_id: str) -> Response:
    markdown = await _call(workflows.render_dossier_markdown, project_id)
    return Response(
        content=markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="project-{project_id}.md"'},
    )


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(request: TemplateCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.create_template, _values(request)))


@router.get("/templates")
async def list_templates(kind: str | None = None) -> list[dict[str, Any]]:
    return [_dump(row) for row in await _call(workflows.list_templates, kind)]


@router.post("/templates/{template_id}/archive")
async def archive_template(template_id: str) -> dict[str, Any]:
    return _dump(await _call(workflows.archive_template, template_id))


@router.post("/templates/{template_id}/instantiate", status_code=status.HTTP_201_CREATED)
async def instantiate_template(
    template_id: str, request: TemplateInstantiateRequest
) -> dict[str, Any]:
    template = await _call(workflows.get_template, template_id)
    payload = {**template.payload, **request.overrides}
    validators: dict[str, type[BaseModel]] = {
        "project": ProjectCreate,
        "task": TaskCreate,
        "meeting": MeetingCreate,
        "evaluation": EvaluationCreate,
    }
    validator = validators.get(template.kind)
    if validator is None:
        raise HTTPException(status_code=422, detail="template kind is not supported")
    try:
        values = validator.model_validate(payload).model_dump(mode="json")
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error
    if template.kind == "evaluation":
        _validate_models(values["models"])
        entity = await _call(workflows.create_evaluation, values)
    elif template.kind == "project":
        entity = await _call(repo.create_project, values)
    elif template.kind == "task":
        entity = await _call(repo.create_task, values)
    else:
        entity = await _call(repo.create_meeting, values)
    await _call(workflows.record_template_instantiation, template.id, entity.id)
    return {"kind": template.kind, "entity": _dump(entity)}


@router.post("/evaluations", status_code=status.HTTP_201_CREATED)
async def create_evaluation(request: EvaluationCreate) -> dict[str, Any]:
    values = _values(request)
    _validate_models(values["models"])
    return _dump(await _call(workflows.create_evaluation, values))


@router.get("/projects/{project_id}/evaluations")
async def list_evaluations(project_id: str) -> list[dict[str, Any]]:
    return [
        _dump(row) for row in await _call(workflows.list_evaluations, project_id)
    ]


@router.get("/evaluations/{experiment_id}")
async def get_evaluation(experiment_id: str) -> dict[str, Any]:
    experiment, candidates, scores = await _call(workflows.get_evaluation, experiment_id)
    return {
        "experiment": _dump(experiment),
        "candidates": [_dump(row) for row in candidates],
        "scores": [_dump(row) for row in scores],
    }


@router.post("/evaluations/{experiment_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_evaluation(experiment_id: str) -> dict[str, Any]:
    try:
        return _dump(await evaluation_runner.start(experiment_id))
    except repo.LabError as error:
        raise _translate(error) from error


@router.post("/evaluations/{experiment_id}/cancel")
async def cancel_evaluation(experiment_id: str) -> dict[str, Any]:
    try:
        return _dump(await evaluation_runner.cancel(experiment_id))
    except repo.LabError as error:
        raise _translate(error) from error


@router.post("/evaluation-candidates/{candidate_id}/scores", status_code=201)
async def score_evaluation_candidate(
    candidate_id: str, request: EvaluationScoreCreate
) -> dict[str, Any]:
    return _dump(await _call(workflows.score_candidate, candidate_id, _values(request)))


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    try:
        return _dump(await lab_orchestrator.cancel(run_id))
    except repo.LabError as error:
        raise _translate(error) from error


@router.post("/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_run(run_id: str) -> dict[str, Any]:
    try:
        return _dump(await lab_orchestrator.retry(run_id))
    except repo.LabError as error:
        raise _translate(error) from error


@router.get("/projects/{project_id}/runs")
async def list_runs(project_id: str, limit: int = 100) -> list[dict[str, Any]]:
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    return [_dump(row) for row in await _call(repo.list_project_runs, project_id, limit)]


@router.post("/search")
async def search_research(request: SearchQuery) -> dict[str, object]:
    values = _values(request)
    matches = await _call(
        search.search,
        values["query"],
        project_id=values.get("project_id"),
        kinds=values.get("kinds", []),
        limit=values.get("limit", 30),
    )
    return {"query": values["query"], "matches": matches}


@router.post("/automations", status_code=status.HTTP_201_CREATED)
async def create_automation(request: AutomationPlanCreate) -> dict[str, Any]:
    return _dump(await _call(workflows.create_automation_plan, _values(request)))


@router.get("/automations")
async def list_automations() -> list[dict[str, Any]]:
    return [_dump(row) for row in await _call(workflows.list_automations)]


@router.post("/automations/{automation_id}/decision")
async def decide_automation(
    automation_id: str, request: AutomationDecisionRequest
) -> dict[str, Any]:
    return _dump(
        await _call(
            workflows.decide_automation,
            automation_id,
            request.decision.value,
            request.note,
        )
    )


@router.post("/automations/{automation_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_automation(automation_id: str) -> dict[str, Any]:
    try:
        return _dump(await automation_runner.start(automation_id))
    except repo.LabError as error:
        raise _translate(error) from error


@router.post("/automations/{automation_id}/cancel")
async def cancel_automation(automation_id: str) -> dict[str, Any]:
    try:
        return _dump(await automation_runner.cancel(automation_id))
    except repo.LabError as error:
        raise _translate(error) from error
