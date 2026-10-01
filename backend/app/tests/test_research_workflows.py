"""Integration tests for evidence, workflow, search, evaluation, and governance."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import db
from app.lab import repo, search, workflows
from app.lab.evaluation import EvaluationRunner
from app.lab.orchestrator import LabOrchestrator
from app.main import app
from app.models import AutomationRun, ModelCall
from app.providers.base import ChatMessage, StreamDone, TextDelta, Usage
from app.providers.mock_provider import MockProvider


@pytest.fixture
def workflow_db(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'workflow.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    return engine


def _organization() -> tuple[str, str, str]:
    department = repo.create_department(
        {"name": "Evidence", "description": "", "kind": "department"}
    )
    agent = repo.create_agent(
        {
            "department_id": department.id,
            "name": "Ada",
            "role": "Researcher",
            "mission": "Test claims against supplied evidence.",
            "duties": ["Cite captured sources"],
            "focus": ["Counter-evidence"],
            "priorities": ["Accuracy"],
            "model": "deepseek/deepseek-chat",
            "communication_scope": "department",
        }
    )
    project = repo.create_project(
        {
            "name": "Battery study",
            "description": "Compare storage paths",
            "objective": "Choose a reversible battery experiment.",
        }
    )
    return department.id, agent.id, project.id


def _task(department_id: str, agent_id: str, project_id: str, title: str):
    return repo.create_task(
        {
            "project_id": project_id,
            "department_id": department_id,
            "assigned_agent_id": agent_id,
            "title": title,
            "objective": f"Research {title}.",
        }
    )


async def test_evidence_packet_review_claim_search_and_dossier(workflow_db, monkeypatch) -> None:
    department_id, agent_id, project_id = _organization()
    task = _task(department_id, agent_id, project_id, "Cycle life")
    source = workflows.create_source(
        {
            "project_id": project_id,
            "title": "Cell report",
            "source_type": "note",
            "origin": "local notebook",
            "content": "The measured cycle life was 820 cycles under the stated protocol.",
            "metadata": {"author": "lab"},
        }
    )
    excerpt = workflows.create_excerpt(
        source.id,
        {"quote": "cycle life was 820 cycles", "locator": "Results"},
    )
    source_link = workflows.link_task_source(
        task.id, {"source_id": source.id, "purpose": "primary"}
    )

    # Remove the mock typing delay so this integration test stays fast.
    monkeypatch.setattr("app.providers.mock_provider.CHUNK_DELAY_SECONDS", 0)
    run = await LabOrchestrator(MockProvider()).run_task_now(task.id)
    assert run.status == "completed"
    finding = next(row for row in repo.snapshot()["findings"] if row.task_id == task.id)
    review = workflows.review_finding(
        finding.id,
        {"decision": "accepted", "notes": "Bounded conclusion", "reviewer": "Founder"},
    )
    claim = workflows.create_claim(
        {
            "project_id": project_id,
            "finding_id": finding.id,
            "statement": "The tested cell reached 820 cycles under the captured protocol.",
            "confidence": 0.8,
        }
    )
    evidence = workflows.attach_claim_evidence(
        claim.id, {"excerpt_id": excerpt.id, "stance": "supports", "note": "Direct result"}
    )

    matches = search.search("820 cycle", project_id=project_id)
    dossier = workflows.project_dossier(project_id)
    markdown = workflows.render_dossier_markdown(project_id)

    assert review.decision == "accepted"
    assert evidence.claim_id == claim.id
    assert any(match["kind"] == "source" for match in matches)
    assert dossier["sources"][0]["content_sha256"] == source.content_sha256
    assert dossier["excerpts"][0]["id"] == excerpt.id
    assert dossier["source_links"][0]["id"] == source_link.id
    assert dossier["claim_evidence"][0]["id"] == evidence.id
    assert "# Battery study" in markdown
    assert "Cell report" in markdown
    assert "cycle life was 820 cycles" in markdown
    workflows.unlink_task_source(source_link.id)
    assert workflows.task_source_packet(task.id) == []


def test_dependency_cycle_readiness_and_action_promotion(workflow_db) -> None:
    department_id, agent_id, project_id = _organization()
    first = _task(department_id, agent_id, project_id, "Baseline")
    second = _task(department_id, agent_id, project_id, "Comparison")
    edge = workflows.add_dependency(second.id, first.id)

    readiness = workflows.task_readiness(second.id)
    assert readiness["ready"] is False
    assert readiness["blockers"][0]["task_id"] == first.id
    assert readiness["dependencies"][0]["dependency_id"] == edge.id
    with pytest.raises(repo.LabValidationError, match="cycle"):
        workflows.add_dependency(first.id, second.id)
    with pytest.raises(repo.LabConflictError, match="incomplete"):
        workflows.assert_task_ready(second.id)

    action = workflows.create_action(
        {
            "project_id": project_id,
            "owner_agent_id": agent_id,
            "title": "Investigate thermal drift",
            "details": "Compare two bounded conditions.",
        }
    )
    promoted = workflows.promote_action(action.id, {})
    assert promoted.assigned_agent_id == agent_id
    assert workflows.update_action(action.id, {"status": "completed"}).status == "completed"
    workflows.remove_dependency(edge.id)
    assert workflows.task_readiness(second.id)["ready"] is True


class BlockingProvider:
    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        max_output_tokens: int | None = None,
    ):
        yield TextDelta(text="started ")
        await asyncio.sleep(60)
        yield StreamDone(usage=Usage(tokens_in=10, tokens_out=2))


class CapturingProvider:
    def __init__(self, usage: Usage | None = None) -> None:
        self.prompts: list[str] = []
        self.output_limits: list[int | None] = []
        self.usage = usage or Usage(tokens_in=100, tokens_out=5)

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        max_output_tokens: int | None = None,
    ):
        self.prompts.append("\n".join(message.content for message in messages))
        self.output_limits.append(max_output_tokens)
        yield TextDelta(text="Bounded research response.")
        yield StreamDone(usage=self.usage)


async def test_source_packets_are_bounded_before_provider_egress(workflow_db) -> None:
    department_id, agent_id, project_id = _organization()
    task = _task(department_id, agent_id, project_id, "Bounded context")
    source = workflows.create_source(
        {
            "project_id": project_id,
            "title": "Large local note",
            "content": f"{'a' * 45_000}TAIL_SENTINEL",
        }
    )
    workflows.link_task_source(task.id, {"source_id": source.id})
    provider = CapturingProvider()

    run = await LabOrchestrator(provider).run_task_now(task.id)

    assert run.status == "completed"
    assert "TAIL_SENTINEL" not in provider.prompts[0]
    assert "a" * 40_000 in provider.prompts[0]
    assert "a" * 40_001 not in provider.prompts[0]


async def test_meeting_uses_one_cumulative_run_budget(workflow_db) -> None:
    department_id, agent_id, project_id = _organization()
    reviewer = repo.create_agent(
        {
            "department_id": department_id,
            "name": "Grace",
            "role": "Reviewer",
            "mission": "Challenge unsupported conclusions.",
            "model": "deepseek/deepseek-chat",
            "communication_scope": "department",
        }
    )
    meeting = repo.create_meeting(
        {
            "project_id": project_id,
            "department_id": department_id,
            "title": "Budgeted review",
            "agenda": "Compare the supplied evidence.",
            "facilitator_agent_id": agent_id,
            "participant_ids": [agent_id, reviewer.id],
        }
    )
    workflows.update_policy(
        project_id,
        {
            "max_run_tokens": 3_000,
            "max_run_usd": 100,
            "max_project_usd": 100,
            "max_concurrent_runs": 2,
        },
    )
    provider = CapturingProvider(Usage(tokens_in=1_000, tokens_out=1_000))

    run = await LabOrchestrator(provider).run_meeting_now(meeting.id)

    assert run.status == "failed"
    assert len(provider.prompts) == 2
    assert provider.output_limits[1] < provider.output_limits[0]
    assert workflows.model_call_totals(run_id=run.id) == pytest.approx((4_000, 0.0014))


async def test_run_cancellation_and_linked_retry_are_durable(workflow_db, monkeypatch) -> None:
    department_id, agent_id, project_id = _organization()
    task = _task(department_id, agent_id, project_id, "Cancellation")
    orchestrator = LabOrchestrator(BlockingProvider())
    run = await orchestrator.start_task(task.id)
    await asyncio.sleep(0.01)
    cancelled = await orchestrator.cancel(run.id)

    assert cancelled.status == "cancelled"
    assert repo.get_task(task.id).status == "cancelled"

    monkeypatch.setattr("app.providers.mock_provider.CHUNK_DELAY_SECONDS", 0)
    retry_orchestrator = LabOrchestrator(MockProvider())
    retry = await retry_orchestrator.retry(run.id)
    background = retry_orchestrator._run_tasks[retry.id]
    await background
    completed = repo.get_run(retry.id)
    assert completed.status == "completed"
    assert completed.retry_of_run_id == run.id
    assert completed.attempt == 2
    history = workflows.project_history(project_id)
    assert any(call.run_id == retry.id for call in history["model_calls"])
    with pytest.raises(repo.LabConflictError, match="failed or cancelled"):
        await retry_orchestrator.retry(completed.id)


async def test_multi_model_evaluation_persists_candidates_and_scores(
    workflow_db, monkeypatch
) -> None:
    _, _, project_id = _organization()
    workflows.update_policy(
        project_id,
        {
            "allowed_models": ["deepseek/deepseek-chat", "anthropic/claude-sonnet-4-5"],
            "max_run_tokens": 50_000,
            "max_run_usd": 10,
            "max_project_usd": 100,
            "max_concurrent_runs": 2,
            "data_classification": "local_only",
        },
    )
    experiment = workflows.create_evaluation(
        {
            "project_id": project_id,
            "name": "Memo comparison",
            "prompt": "Give one cautious recommendation.",
            "models": ["deepseek/deepseek-chat", "anthropic/claude-sonnet-4-5"],
            "criteria": ["quality", "calibration"],
        }
    )
    monkeypatch.setattr("app.providers.mock_provider.CHUNK_DELAY_SECONDS", 0)
    runner = EvaluationRunner(MockProvider())
    await runner.start(experiment.id)
    await runner._tasks[experiment.id]
    finished, candidates, _ = workflows.get_evaluation(experiment.id)

    assert finished.status == "completed"
    assert len(candidates) == 2
    assert all(candidate.response for candidate in candidates)
    score = workflows.score_candidate(
        candidates[0].id,
        {"criterion": "quality", "score": 8.5, "rationale": "Clear", "reviewer": "Founder"},
    )
    assert score.score == 8.5


def test_policy_trace_templates_and_automation_approval(workflow_db) -> None:
    _, _, project_id = _organization()
    policy = workflows.update_policy(
        project_id,
        {
            "data_classification": "confidential",
            "allowed_models": ["deepseek/deepseek-chat"],
            "max_run_tokens": 2_000,
            "max_run_usd": 1,
            "max_project_usd": 3,
            "max_concurrent_runs": 1,
        },
    )
    template = workflows.create_template(
        {"name": "Literature task", "kind": "task", "payload": {"expected_output": "memo"}}
    )
    trace = workflows.create_trace_link(
        {
            "project_id": project_id,
            "source_type": "project",
            "source_id": project_id,
            "target_type": "project",
            "target_id": project_id,
            "relationship": "refines",
        }
    )
    automation = workflows.create_automation_plan(
        {
            "project_id": project_id,
            "provider": "claude",
            "request": "Draft a test plan.",
            "plan": "Inspect, edit, run tests.",
            "capabilities": ["read_workspace"],
        }
    )
    approved = workflows.decide_automation(automation.id, "approve", "Reviewed")

    assert policy.max_concurrent_runs == 1
    assert workflows.archive_template(template.id).status == "archived"
    assert trace.relationship == "refines"
    assert approved.status == "approved"
    other_project = repo.create_project(
        {"name": "Other", "objective": "Keep project provenance separate."}
    )
    with pytest.raises(repo.LabValidationError, match="different project"):
        workflows.create_trace_link(
            {
                "project_id": project_id,
                "source_type": "project",
                "source_id": other_project.id,
                "target_type": "project",
                "target_id": project_id,
            }
        )
    with pytest.raises(repo.LabValidationError, match="workspace"):
        workflows.begin_automation(approved.id)


def test_running_evaluation_counts_toward_project_concurrency(workflow_db) -> None:
    _, _, project_id = _organization()
    workflows.update_policy(
        project_id,
        {
            "max_run_tokens": 50_000,
            "max_run_usd": 5,
            "max_project_usd": 100,
            "max_concurrent_runs": 1,
        },
    )
    experiment = workflows.create_evaluation(
        {
            "project_id": project_id,
            "name": "Concurrency",
            "prompt": "Compare one bounded answer.",
            "models": ["deepseek/deepseek-chat", "deepseek/deepseek-reasoner"],
            "criteria": ["quality"],
        }
    )
    workflows.mark_evaluation_running(experiment.id)

    with pytest.raises(repo.LabConflictError, match="concurrent run"):
        workflows.assert_run_allowed(project_id, ["deepseek/deepseek-chat"])


def test_startup_recovery_fails_interrupted_advanced_work(workflow_db) -> None:
    _, _, project_id = _organization()
    policy = workflows.get_policy(project_id)
    model_call = workflows.begin_model_call(
        project_id=project_id,
        run_id=None,
        agent_id=None,
        stage="evaluation_candidate",
        model="deepseek/deepseek-chat",
        system_prompt="Bounded system prompt",
        user_prompt="Bounded user prompt",
        policy=policy,
    )
    experiment = workflows.create_evaluation(
        {
            "project_id": project_id,
            "name": "Interrupted evaluation",
            "prompt": "Compare one answer.",
            "models": ["deepseek/deepseek-chat"],
            "criteria": ["quality"],
        }
    )
    workflows.mark_evaluation_running(experiment.id)
    automation = AutomationRun(
        project_id=project_id,
        request="Interrupted approved job",
        status="running",
    )
    with Session(workflow_db) as session:
        session.add(automation)
        session.commit()
        session.refresh(automation)

    recovered = workflows.recover_interrupted_work()

    assert recovered == {"model_calls": 1, "evaluations": 1, "automations": 1}
    assert workflows.recover_interrupted_work() == {
        "model_calls": 0,
        "evaluations": 0,
        "automations": 0,
    }
    finished, candidates, _ = workflows.get_evaluation(experiment.id)
    assert finished.status == "failed"
    assert candidates[0].status == "failed"
    with Session(workflow_db) as session:
        stored_call = session.get(ModelCall, model_call.id)
        stored_automation = session.get(AutomationRun, automation.id)
        assert stored_call is not None and stored_call.status == "failed"
        assert stored_call.completed_at is not None
        assert stored_automation is not None and stored_automation.status == "failed"
        assert stored_automation.completed_at is not None


def test_template_instantiation_validates_and_creates_entity(workflow_db) -> None:
    template = workflows.create_template(
        {
            "name": "Decision project",
            "kind": "project",
            "payload": {"name": "Templated project", "objective": "Make a decision."},
        }
    )
    client = TestClient(app)
    try:
        response = client.post(
            f"/api/lab/templates/{template.id}/instantiate",
            headers={"Origin": "http://127.0.0.1:5173"},
            json={"overrides": {"description": "Created from an audited template."}},
        )
    finally:
        client.close()

    assert response.status_code == 201
    assert response.json()["kind"] == "project"
    assert response.json()["entity"]["name"] == "Templated project"
    assert any(row.name == "Templated project" for row in repo.snapshot()["projects"])
