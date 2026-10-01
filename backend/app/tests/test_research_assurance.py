"""End-to-end tests for frozen protocols, assurance gates, and capsules."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import db
from app.lab import assurance, repo, research_capsule, workflows
from app.lab.integrity import canonical_json, canonical_sha256
from app.lab.orchestrator import LabOrchestrator
from app.main import app
from app.models import (
    AutomationRun,
    Finding,
    LabRun,
    ModelCall,
    ResearchAssuranceAcceptance,
    ResearchTask,
    TaskResult,
    Workspace,
)
from app.providers.mock_provider import MockProvider


@pytest.fixture
def assurance_db(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'assurance.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    return engine


def _organization() -> tuple[str, str, str, str]:
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
    task = repo.create_task(
        {
            "project_id": project.id,
            "department_id": department.id,
            "assigned_agent_id": agent.id,
            "title": "Cycle life",
            "objective": "Measure cycle life under the bounded protocol.",
        }
    )
    return department.id, agent.id, project.id, task.id


def _protocol(project_id: str):
    draft = assurance.create_protocol(
        project_id,
        {
            "question": "How long does the tested cell last?",
            "hypothesis": "The tested cell exceeds 800 cycles.",
            "method": "Use the captured fixed-temperature test result.",
            "acceptance_criteria": ["A direct measured cycle count is cited"],
            "limitations": ["One cell chemistry"],
            "created_by": "Founder",
        },
    )
    return assurance.approve_protocol(draft.id, "Founder")


def _after(*values: datetime) -> datetime:
    aware = [value if value.tzinfo is not None else value.replace(tzinfo=UTC) for value in values]
    return max(aware) + timedelta(microseconds=1)


def _source_evidence(project_id: str, task_id: str):
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
    link = workflows.link_task_source(
        task_id, {"source_id": source.id, "purpose": "primary evidence"}
    )
    return source, excerpt, link


def _completed_result(engine, agent_id: str, project_id: str, task_id: str, started_at: datetime):
    run = repo.begin_task_run(task_id)
    agent = repo.get_agent(agent_id)
    result_content = "The test reports 820 cycles under the bounded conditions."
    result = TaskResult(
        project_id=project_id,
        task_id=task_id,
        run_id=run.id,
        agent_id=agent_id,
        content=result_content,
        created_at=started_at,
    )
    finding = Finding(
        project_id=project_id,
        task_id=task_id,
        result_id=result.id,
        agent_id=agent_id,
        title="Measured cycle life",
        content=result_content,
        confidence=0.9,
        created_at=started_at,
    )
    model_call = ModelCall(
        project_id=project_id,
        run_id=run.id,
        agent_id=agent_id,
        stage="task_result",
        model="deepseek/deepseek-chat",
        system_prompt=LabOrchestrator._agent_prompt(
            agent, str(run.input_snapshot["task"]["objective"])
        ),
        user_prompt=LabOrchestrator._task_user_prompt(run.input_snapshot),
        policy_snapshot={"data_classification": "local_only"},
        status="completed",
        tokens_in=20,
        tokens_out=10,
        latency_ms=5,
        created_at=started_at,
        completed_at=started_at,
    )
    run_id = run.id
    finding_id = finding.id
    with Session(engine) as session:
        task = session.get(ResearchTask, task_id)
        stored_run = session.get(LabRun, run.id)
        assert task is not None
        assert stored_run is not None
        task.status = "completed"
        stored_run.status = "completed"
        stored_run.started_at = started_at
        stored_run.completed_at = started_at
        session.add(stored_run)
        session.add(result)
        session.add(finding)
        session.add(model_call)
        session.add(task)
        session.commit()
    return run_id, finding_id


def _reviewed_claim(project_id: str, finding_id: str, excerpt_id: str):
    workflows.review_finding(
        finding_id,
        {"decision": "accepted", "notes": "Checked", "reviewer": "Founder"},
    )
    claim = workflows.create_claim(
        {
            "project_id": project_id,
            "finding_id": finding_id,
            "statement": "The tested cell reached 820 cycles under the captured protocol.",
            "confidence": 0.9,
        }
    )
    evidence = workflows.attach_claim_evidence(
        claim.id,
        {"excerpt_id": excerpt_id, "stance": "supports", "note": "Direct measurement"},
    )
    claim = workflows.update_claim(claim.id, {"status": "accepted"})
    return claim, evidence


def test_protocols_are_immutable_versioned_and_detect_objective_drift(assurance_db) -> None:
    _, _, project_id, _ = _organization()
    first = _protocol(project_id)

    assert first.version == 1
    assert first.status == "approved"
    assert assurance.protocol_content_sha256(first) == first.content_sha256

    second = assurance.create_protocol(
        project_id,
        {
            "question": "Does a second bounded condition improve cycle life?",
            "hypothesis": "The second condition improves cycle life.",
            "method": "Compare the two captured conditions.",
            "acceptance_criteria": ["Both conditions have exact evidence"],
        },
    )
    assert second.version == 2
    assert second.supersedes_id == first.id
    assert second.created_by == "founder"
    assert second.limitations == []
    assert assurance.protocol_content_sha256(second) == second.content_sha256
    with pytest.raises(repo.LabConflictError, match="already has a draft"):
        assurance.create_protocol(
            project_id,
            {
                "question": "Third question",
                "hypothesis": "Third hypothesis",
                "method": "Third method",
                "acceptance_criteria": ["Third criterion"],
            },
        )

    repo.update_project(project_id, {"objective": "A changed objective."})
    with pytest.raises(repo.LabConflictError, match="objective changed"):
        assurance.approve_protocol(second.id, "Founder")
    withdrawn = assurance.withdraw_protocol(second.id, "Founder", "Objective changed")
    assert withdrawn.status == "withdrawn"
    third = assurance.create_protocol(
        project_id,
        {
            "question": "What answers the changed objective?",
            "hypothesis": "Fresh execution can answer it.",
            "method": "Run again with the updated scope.",
            "acceptance_criteria": ["Evidence matches the new objective"],
        },
    )
    assert third.version == 3
    assert assurance.approve_protocol(third.id, "Founder").status == "approved"
    by_version = {row.version: row.status for row in assurance.list_protocols(project_id)}
    assert by_version == {1: "superseded", 2: "withdrawn", 3: "approved"}


def test_assurance_enforces_full_pipeline_and_allows_correction(assurance_db) -> None:
    _, agent_id, project_id, task_id = _organization()
    protocol = _protocol(project_id)
    source, excerpt, source_link = _source_evidence(project_id, task_id)
    assert protocol.approved_at is not None
    run_id, finding_id = _completed_result(
        assurance_db,
        agent_id,
        project_id,
        task_id,
        _after(protocol.approved_at, source_link.created_at),
    )
    claim, supporting = _reviewed_claim(project_id, finding_id, excerpt.id)

    ready = assurance.assess_task(task_id)
    assert ready["status"] == "ready"
    assert ready["ready"] is True
    assert ready["run_id"] == run_id
    assert ready["coverage"]["total_claims"] == 1
    assert ready["coverage"]["supported_claims"] == 1
    assert ready["coverage"]["unsupported_claims"] == 0
    assert ready["coverage"]["contradicted_claims"] == 0
    assert ready["coverage"]["coverage_percent"] == 100.0
    assert ready["coverage"]["source_packet_count"] == 1
    assert ready["coverage"]["invalid_source_packet_refs"] == []
    with pytest.raises(repo.LabConflictError, match="confirm every"):
        assurance.accept_task(
            task_id,
            {"reviewer": "Founder", "confirmed_criteria": ["A different criterion"]},
        )
    accepted = assurance.accept_task(
        task_id,
        {
            "reviewer": "Founder",
            "notes": "Verified",
            "confirmed_criteria": protocol.acceptance_criteria,
        },
    )
    assert accepted["status"] == "accepted"
    first_snapshot = accepted["snapshot_sha256"]
    with Session(assurance_db) as session:
        acceptance = session.exec(select(ResearchAssuranceAcceptance)).one()
        assert acceptance.confirmed_criteria == protocol.acceptance_criteria
        assert canonical_sha256(acceptance.snapshot_json) == acceptance.snapshot_sha256
    with pytest.raises(repo.LabConflictError, match="already exists"):
        workflows.attach_claim_evidence(
            claim.id,
            {"excerpt_id": excerpt.id, "stance": "contextualizes"},
        )

    contradicting_excerpt = workflows.create_excerpt(
        source.id, {"quote": "under the stated protocol", "locator": "Results"}
    )
    contradiction = workflows.attach_claim_evidence(
        claim.id,
        {
            "excerpt_id": contradicting_excerpt.id,
            "stance": "contradicts",
            "note": "Mistaken stance",
        },
    )
    blocked = assurance.assess_task(task_id)
    assert blocked["status"] == "stale"
    assert blocked["ready"] is False
    assert blocked["claim_results"][0]["status"] == "disputed"
    assert blocked["claim_results"][0]["contradicting_evidence_ids"] == [contradiction.id]

    workflows.unlink_claim_evidence(contradiction.id)
    claim = workflows.update_claim(claim.id, {"status": "accepted"})
    assert claim.status == "accepted"
    assert assurance.assess_task(task_id)["status"] == "accepted"
    workflows.unlink_task_source(source_link.id)
    no_packet = assurance.assess_task(task_id)
    assert no_packet["status"] == "stale"
    assert "source_packet" in {
        check["code"] for check in no_packet["checks"] if not check["passed"]
    }
    replacement = workflows.link_task_source(
        task_id, {"source_id": source.id, "purpose": "verified primary evidence"}
    )
    relinked = assurance.assess_task(task_id)
    assert relinked["ready"] is False
    assert relinked["status"] == "stale"
    assert relinked["snapshot_sha256"] != first_snapshot
    assert "source_packet_before_run" in {
        check["code"] for check in relinked["checks"] if not check["passed"]
    }

    workflows.update_claim(claim.id, {"status": "retired"})
    retired = assurance.assess_task(task_id)
    assert retired["ready"] is False
    assert retired["coverage"]["total_claims"] == 0
    assert retired["claim_results"] == []
    assert supporting.id
    assert replacement.id


def test_protocol_must_predate_the_accepted_run(assurance_db) -> None:
    _, agent_id, project_id, task_id = _organization()
    _, excerpt, _ = _source_evidence(project_id, task_id)
    _, finding_id = _completed_result(
        assurance_db,
        agent_id,
        project_id,
        task_id,
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    _reviewed_claim(project_id, finding_id, excerpt.id)
    _protocol(project_id)

    assessment = assurance.assess_task(task_id)
    failed = {check["code"] for check in assessment["checks"] if not check["passed"]}
    assert "protocol_before_run" in failed
    with pytest.raises(repo.LabConflictError, match="Re-run the task"):
        assurance.accept_task(task_id, {"reviewer": "Founder"})


def test_claim_acceptance_invariants_and_review_downgrade(assurance_db) -> None:
    _, agent_id, project_id, task_id = _organization()
    protocol = _protocol(project_id)
    _, excerpt, source_link = _source_evidence(project_id, task_id)
    assert protocol.approved_at is not None
    _, finding_id = _completed_result(
        assurance_db,
        agent_id,
        project_id,
        task_id,
        _after(protocol.approved_at, source_link.created_at),
    )
    claim = workflows.create_claim(
        {
            "project_id": project_id,
            "finding_id": finding_id,
            "statement": "The tested cell reached 820 cycles.",
        }
    )
    with pytest.raises(repo.LabConflictError, match="finding review"):
        workflows.update_claim(claim.id, {"status": "accepted"})
    workflows.review_finding(
        finding_id, {"decision": "accepted", "reviewer": "Founder"}
    )
    with pytest.raises(repo.LabConflictError, match="supporting excerpt"):
        workflows.update_claim(claim.id, {"status": "accepted"})
    evidence = workflows.attach_claim_evidence(
        claim.id, {"excerpt_id": excerpt.id, "stance": "supports"}
    )
    assert workflows.update_claim(claim.id, {"status": "accepted"}).status == "accepted"
    with pytest.raises(repo.LabValidationError, match="separate review action"):
        workflows.update_claim(
            claim.id,
            {"statement": "A materially changed claim.", "status": "accepted"},
        )
    assert workflows.update_claim(
        claim.id, {"statement": "A materially changed claim."}
    ).status == "proposed"
    assert workflows.update_claim(claim.id, {"status": "accepted"}).status == "accepted"

    workflows.review_finding(
        finding_id, {"decision": "needs_revision", "reviewer": "Founder"}
    )
    with Session(assurance_db) as session:
        assert session.get(type(claim), claim.id).status == "proposed"
    with pytest.raises(repo.LabConflictError, match="finding review"):
        workflows.update_claim(claim.id, {"status": "accepted"})
    assert evidence.id


async def test_task_run_freezes_and_prompts_with_the_approved_protocol(
    assurance_db, monkeypatch
) -> None:
    _, agent_id, project_id, task_id = _organization()
    protocol = _protocol(project_id)
    source, _, source_link = _source_evidence(project_id, task_id)
    monkeypatch.setattr("app.providers.mock_provider.CHUNK_DELAY_SECONDS", 0)

    run = await LabOrchestrator(MockProvider()).run_task_now(
        task_id, "Keep the conclusion bounded."
    )
    with Session(assurance_db) as session:
        stored_run = session.get(LabRun, run.id)
        call = session.exec(
            select(ModelCall).where(
                ModelCall.run_id == run.id,
                ModelCall.stage == "task_result",
            )
        ).one()

    assert stored_run is not None
    assert stored_run.input_snapshot["protocol"]["id"] == protocol.id
    assert stored_run.input_snapshot["protocol"]["content_sha256"] == protocol.content_sha256
    assert stored_run.input_snapshot["founder_guidance"] == "Keep the conclusion bounded."
    assert stored_run.input_snapshot["agent"]["id"] == agent_id
    assert stored_run.input_snapshot["source_packet"][0]["link_id"] == source_link.id
    assert stored_run.input_snapshot["source_packet"][0]["source_id"] == source.id
    assert stored_run.input_snapshot["source_packet"][0]["content"] == source.content
    prompt_payload = json.loads(call.user_prompt.rsplit("\n\n", 1)[1])
    assert prompt_payload["research_protocol"]["id"] == protocol.id
    assert prompt_payload["research_protocol"]["method"] == protocol.method
    assert prompt_payload["research_protocol"]["acceptance_criteria"] == (
        protocol.acceptance_criteria
    )
    assert prompt_payload["source_packet"] == stored_run.input_snapshot["source_packet"]


async def test_task_execution_uses_frozen_agent_model_after_agent_edit(
    assurance_db, monkeypatch
) -> None:
    _, agent_id, project_id, task_id = _organization()
    _protocol(project_id)
    _source_evidence(project_id, task_id)
    monkeypatch.setattr("app.providers.mock_provider.CHUNK_DELAY_SECONDS", 0)
    original_agent = repo.get_agent(agent_id)
    policy = workflows.assert_run_allowed(project_id, [original_agent.model])
    run = repo.begin_task_run(task_id)

    repo.update_agent(agent_id, {"model": "replacement/remote-model"})
    await LabOrchestrator(MockProvider())._execute_task(run, "", policy)

    with Session(assurance_db) as session:
        stored_run = session.get(LabRun, run.id)
        call = session.exec(
            select(ModelCall).where(
                ModelCall.run_id == run.id,
                ModelCall.stage == "task_result",
            )
        ).one()
    assert stored_run is not None and stored_run.status == "completed"
    assert stored_run.input_snapshot["agent"]["model"] == original_agent.model
    assert call.model == original_agent.model


def test_archived_sources_cannot_satisfy_or_extend_the_runtime_packet(assurance_db) -> None:
    _, agent_id, project_id, task_id = _organization()
    protocol = _protocol(project_id)
    source, excerpt, link = _source_evidence(project_id, task_id)
    assert protocol.approved_at is not None
    _, finding_id = _completed_result(
        assurance_db,
        agent_id,
        project_id,
        task_id,
        _after(protocol.approved_at, link.created_at),
    )
    claim, _ = _reviewed_claim(project_id, finding_id, excerpt.id)
    archived = workflows.archive_source(source.id)
    assert workflows.task_source_packet(task_id) == []
    with pytest.raises(repo.LabConflictError, match="archived"):
        workflows.create_excerpt(source.id, {"quote": "cycle life"})
    other_task = repo.create_task(
        {
            "project_id": project_id,
            "assigned_agent_id": repo.get_task(task_id).assigned_agent_id,
            "title": "Other task",
            "objective": "Check archive behavior.",
        }
    )
    with pytest.raises(repo.LabConflictError, match="archived"):
        workflows.link_task_source(other_task.id, {"source_id": source.id})
    with pytest.raises(repo.LabConflictError, match="archived"):
        workflows.attach_claim_evidence(
            assurance.assess_task(task_id)["claim_results"][0]["claim_id"],
            {"excerpt_id": excerpt.id, "stance": "supports", "note": "duplicate"},
        )
    assessment = assurance.assess_task(task_id)
    failed = {check["code"] for check in assessment["checks"] if not check["passed"]}
    assert {
        "source_packet",
        "source_packet_run_binding",
        "claim_coverage",
        "evidence_integrity",
    } <= failed
    assert assessment["coverage"]["source_packet_count"] == 0
    assert assessment["coverage"]["excluded_source_packet_refs"] == [
        {"link_id": link.id, "reason": "source_archived"}
    ]
    assert archived.status == "archived"
    with Session(assurance_db) as session:
        assert session.get(type(claim), claim.id).status == "proposed"


def test_supporting_source_beyond_runtime_packet_limit_blocks_acceptance(assurance_db) -> None:
    _, agent_id, project_id, task_id = _organization()
    protocol = _protocol(project_id)
    links = []
    last_source = None
    last_excerpt = None
    for index in range(25):
        source = workflows.create_source(
            {
                "project_id": project_id,
                "title": f"Source {index:02d}",
                "source_type": "note",
                "content": f"Measurement {index:02d} is captured exactly.",
                "metadata": {},
            }
        )
        excerpt = workflows.create_excerpt(
            source.id, {"quote": f"Measurement {index:02d}", "locator": "line 1"}
        )
        links.append(workflows.link_task_source(task_id, {"source_id": source.id}))
        last_source = source
        last_excerpt = excerpt
    assert last_source is not None and last_excerpt is not None
    assert len(workflows.task_source_packet(task_id)) == 24
    assert protocol.approved_at is not None
    _, finding_id = _completed_result(
        assurance_db,
        agent_id,
        project_id,
        task_id,
        _after(protocol.approved_at, links[-1].created_at),
    )
    _reviewed_claim(project_id, finding_id, last_excerpt.id)

    assessment = assurance.assess_task(task_id)
    assert assessment["ready"] is False
    assert assessment["coverage"]["source_packet_count"] == 24
    assert assessment["coverage"]["unlinked_supporting_source_ids"] == [last_source.id]
    assert assessment["coverage"]["excluded_source_packet_refs"] == [
        {"link_id": links[-1].id, "reason": "outside_runtime_limit"}
    ]


def test_supporting_excerpt_beyond_bounded_source_text_blocks_acceptance(assurance_db) -> None:
    _, agent_id, project_id, task_id = _organization()
    protocol = _protocol(project_id)
    source = workflows.create_source(
        {
            "project_id": project_id,
            "title": "Long report",
            "source_type": "note",
            "content": ("A" * 40_050) + " decisive measurement",
            "metadata": {},
        }
    )
    excerpt = workflows.create_excerpt(
        source.id, {"quote": "decisive measurement", "locator": "appendix"}
    )
    link = workflows.link_task_source(task_id, {"source_id": source.id})
    assert protocol.approved_at is not None
    _, finding_id = _completed_result(
        assurance_db,
        agent_id,
        project_id,
        task_id,
        _after(protocol.approved_at, link.created_at),
    )
    _, evidence = _reviewed_claim(project_id, finding_id, excerpt.id)

    assessment = assurance.assess_task(task_id)
    failed = {check["code"] for check in assessment["checks"] if not check["passed"]}
    assert assessment["ready"] is False
    assert "evidence_in_source_packet" in failed
    assert assessment["coverage"]["unseen_supporting_evidence_ids"] == [evidence.id]


def test_capsule_is_deterministic_offline_verifiable_and_exposed_by_api(
    assurance_db, tmp_path: Path, monkeypatch
) -> None:
    _, agent_id, project_id, task_id = _organization()
    protocol = _protocol(project_id)
    _, excerpt, source_link = _source_evidence(project_id, task_id)
    assert protocol.approved_at is not None
    _, finding_id = _completed_result(
        assurance_db,
        agent_id,
        project_id,
        task_id,
        _after(protocol.approved_at, source_link.created_at),
    )
    _reviewed_claim(project_id, finding_id, excerpt.id)
    assurance.accept_task(
        task_id,
        {"reviewer": "Founder", "confirmed_criteria": protocol.acceptance_criteria},
    )

    capsule = research_capsule.build_capsule(project_id)
    assert capsule == research_capsule.build_capsule(project_id)
    verified = research_capsule.verify_capsule(capsule)
    assert verified["valid"] is True, verified["errors"]

    tampered = copy.deepcopy(capsule)
    tampered["manifest"]["sources"][0]["content"] += " tampered"
    tampered["manifest_sha256"] = assurance.canonical_sha256(tampered["manifest"])
    invalid = research_capsule.verify_capsule(tampered)
    assert invalid["valid"] is False
    assert any("source" in error for error in invalid["errors"])

    tampered_acceptance = copy.deepcopy(capsule)
    acceptance = tampered_acceptance["manifest"]["assurance_acceptances"][0]
    acceptance["snapshot_json"]["task"]["title"] = "Changed after acceptance"
    tampered_acceptance["manifest_sha256"] = assurance.canonical_sha256(
        tampered_acceptance["manifest"]
    )
    invalid_acceptance = research_capsule.verify_capsule(tampered_acceptance)
    assert invalid_acceptance["valid"] is False
    assert any("invalid snapshot" in error for error in invalid_acceptance["errors"])

    tampered_run = copy.deepcopy(capsule)
    tampered_run["manifest"]["runs"][0]["input_snapshot"]["task"]["title"] = "Other task"
    tampered_run["manifest_sha256"] = canonical_sha256(tampered_run["manifest"])
    assert research_capsule.verify_capsule(tampered_run)["valid"] is False

    tampered_call = copy.deepcopy(capsule)
    call = tampered_call["manifest"]["model_calls"][0]
    call["stage"] = "meeting_synthesis"
    acceptance = tampered_call["manifest"]["assurance_acceptances"][0]
    acceptance["snapshot_json"]["model_calls"][0]["provenance_sha256"] = (
        research_capsule.model_call_provenance_sha256(call)
    )
    acceptance["snapshot_sha256"] = canonical_sha256(acceptance["snapshot_json"])
    tampered_call["manifest_sha256"] = canonical_sha256(tampered_call["manifest"])
    assert research_capsule.verify_capsule(tampered_call)["valid"] is False

    tampered_packet = copy.deepcopy(capsule)
    run = tampered_packet["manifest"]["runs"][0]
    run["input_snapshot"]["source_packet"][0]["included_chars"] += 1
    run["input_sha256"] = canonical_sha256(run["input_snapshot"])
    acceptance = tampered_packet["manifest"]["assurance_acceptances"][0]
    acceptance["snapshot_json"]["run"]["input_snapshot"] = copy.deepcopy(
        run["input_snapshot"]
    )
    acceptance["snapshot_json"]["run"]["input_sha256"] = run["input_sha256"]
    acceptance["snapshot_sha256"] = canonical_sha256(acceptance["snapshot_json"])
    tampered_packet["manifest_sha256"] = canonical_sha256(tampered_packet["manifest"])
    assert research_capsule.verify_capsule(tampered_packet)["valid"] is False

    malformed = copy.deepcopy(capsule)
    acceptance = malformed["manifest"]["assurance_acceptances"][0]
    acceptance["snapshot_json"]["findings"] = ["not-an-object"]
    acceptance["snapshot_sha256"] = canonical_sha256(acceptance["snapshot_json"])
    malformed["manifest_sha256"] = canonical_sha256(malformed["manifest"])
    assert research_capsule.verify_capsule(malformed)["valid"] is False

    changed_claim = copy.deepcopy(capsule)
    acceptance = changed_claim["manifest"]["assurance_acceptances"][0]
    acceptance["snapshot_json"]["claims"][0]["statement"] = "Fabricated conclusion"
    acceptance["snapshot_sha256"] = canonical_sha256(acceptance["snapshot_json"])
    assessment = changed_claim["manifest"]["task_assurance"][0]
    assessment["snapshot"] = copy.deepcopy(acceptance["snapshot_json"])
    assessment["snapshot_sha256"] = acceptance["snapshot_sha256"]
    assessment["acceptance"]["snapshot_sha256"] = acceptance["snapshot_sha256"]
    changed_claim["manifest_sha256"] = canonical_sha256(changed_claim["manifest"])
    assert research_capsule.verify_capsule(changed_claim)["valid"] is False

    archived_source = copy.deepcopy(capsule)
    archived_source["manifest"]["sources"][0]["status"] = "archived"
    archived_source["manifest_sha256"] = canonical_sha256(archived_source["manifest"])
    assert research_capsule.verify_capsule(archived_source)["valid"] is False

    extra_contradiction = copy.deepcopy(capsule)
    added_edge = copy.deepcopy(extra_contradiction["manifest"]["claim_evidence"][0])
    added_edge["id"] = "extra-contradiction"
    added_edge["stance"] = "contradicts"
    extra_contradiction["manifest"]["claim_evidence"].append(added_edge)
    extra_contradiction["manifest_sha256"] = canonical_sha256(
        extra_contradiction["manifest"]
    )
    assert research_capsule.verify_capsule(extra_contradiction)["valid"] is False

    extra_claim = copy.deepcopy(capsule)
    added_claim = copy.deepcopy(extra_claim["manifest"]["claims"][0])
    added_claim["id"] = "extra-proposed-claim"
    added_claim["status"] = "proposed"
    extra_claim["manifest"]["claims"].append(added_claim)
    extra_claim["manifest_sha256"] = canonical_sha256(extra_claim["manifest"])
    assert research_capsule.verify_capsule(extra_claim)["valid"] is False

    capsule_path = tmp_path / "study.research-capsule.json"
    capsule_path.write_bytes(canonical_json(capsule))
    assert research_capsule.main(["verify", str(capsule_path)]) == 0

    client = TestClient(app)
    try:
        download = client.get(
            f"/api/lab/projects/{project_id}/capsule",
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        api_verify = client.post(
            "/api/lab/capsules/verify",
            headers={"Origin": "http://127.0.0.1:5173"},
            json=download.json(),
        )
        patch = client.patch(
            f"/api/lab/claims/{capsule['manifest']['claims'][0]['id']}",
            headers={"Origin": "http://127.0.0.1:5173"},
            json={"confidence": None},
        )
        monkeypatch.setattr(research_capsule, "MAX_CAPSULE_BYTES", 1)
        too_large = client.get(
            f"/api/lab/projects/{project_id}/capsule",
            headers={"Origin": "http://127.0.0.1:5173"},
        )
    finally:
        client.close()

    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert api_verify.status_code == 200
    assert api_verify.json()["valid"] is True
    assert patch.status_code == 200
    assert patch.json()["confidence"] is None
    assert too_large.status_code == 413
    with Session(assurance_db) as session:
        acceptances = list(session.exec(select(ResearchAssuranceAcceptance)))
    assert len(acceptances) == 1


def test_capsule_rejects_fabricated_ready_assessment(assurance_db) -> None:
    _, _, project_id, _ = _organization()
    capsule = research_capsule.build_capsule(project_id)
    assert research_capsule.verify_capsule(capsule)["valid"] is True

    fabricated = copy.deepcopy(capsule)
    assessment = fabricated["manifest"]["task_assurance"][0]
    assessment["checks"] = [
        {"code": "fabricated", "passed": True, "message": "Looks ready"}
    ]
    assessment["issues"] = []
    assessment["ready"] = True
    assessment["status"] = "ready"
    fabricated["manifest_sha256"] = canonical_sha256(fabricated["manifest"])
    assert research_capsule.verify_capsule(fabricated)["valid"] is False


def test_project_headless_automation_requires_public_classification(assurance_db) -> None:
    _, _, project_id, _ = _organization()
    workspace = Workspace(
        id="ws-assurance",
        slug="assurance",
        path="/tmp/lemma-assurance-workspace",
        spec_artifact_id=1,
    )
    automation = AutomationRun(
        project_id=project_id,
        workspace_id=workspace.id,
        provider="claude",
        request="Review the research capsule verifier.",
        plan="Read and run bounded checks.",
        capabilities=["read_workspace", "run_checks"],
        status="approved",
    )
    automation_id = automation.id
    with Session(assurance_db) as session:
        session.add(workspace)
        session.add(automation)
        session.commit()

    with pytest.raises(repo.LabValidationError, match="public classification"):
        workflows.begin_automation(automation_id)
    workflows.update_policy(project_id, {"data_classification": "public"})
    started, _ = workflows.begin_automation(automation_id)
    assert started.status == "running"
