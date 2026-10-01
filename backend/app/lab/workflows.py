"""Persistence and domain rules for evidence-rich research workflows.

The original lab repository stays focused on core organization and execution. This
module adds source provenance, review, task graphs, dossiers, policies, evaluation,
and approval-gated automation without making the route layer own transactions.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, SQLModel, select

from app.db import get_session
from app.lab import repo
from app.lab.governance import enforce_model_egress
from app.lab.integrity import MAX_TASK_SOURCE_COUNT
from app.models import (
    ActionItem,
    ActivityRecord,
    Artifact,
    AutomationRun,
    ClaimEvidence,
    Department,
    EvaluationCandidate,
    EvaluationExperiment,
    EvaluationScore,
    Finding,
    FindingReview,
    LabAgent,
    LabRun,
    LabTemplate,
    MeetingOutcome,
    ModelCall,
    ProjectPolicy,
    ResearchClaim,
    ResearchMeeting,
    ResearchProject,
    ResearchTask,
    SourceDocument,
    SourceExcerpt,
    TaskDependency,
    TaskResult,
    TaskSourceLink,
    TraceLink,
    Workspace,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _require[RowT: SQLModel](db: Session, model: type[RowT], row_id: Any, label: str) -> RowT:
    row = db.get(model, row_id)
    if row is None:
        raise repo.LabNotFoundError(f"{label} not found")
    return row


def _record(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: str,
    *,
    details: dict[str, object] | None = None,
    run_id: str | None = None,
    agent_id: str | None = None,
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


def _project(db: Session, project_id: str) -> ResearchProject:
    return _require(db, ResearchProject, project_id, "project")


def _same_project(expected: str, actual: str, label: str) -> None:
    if expected != actual:
        raise repo.LabValidationError(f"{label} belongs to a different project")


# ── Governance and budgets --------------------------------------------------


def _policy(db: Session, project_id: str, *, create: bool = False) -> ProjectPolicy:
    _project(db, project_id)
    policy = db.get(ProjectPolicy, project_id)
    if policy is None:
        policy = ProjectPolicy(project_id=project_id)
        if create:
            db.add(policy)
            db.flush()
    return policy


def get_policy(project_id: str) -> ProjectPolicy:
    with get_session() as db:
        policy = _policy(db, project_id, create=True)
        db.commit()
        db.refresh(policy)
        return policy


def update_policy(project_id: str, values: dict[str, Any]) -> ProjectPolicy:
    with get_session() as db:
        policy = _policy(db, project_id, create=True)
        for key, value in values.items():
            setattr(policy, key, value)
        policy.updated_at = _now()
        db.add(policy)
        _record(
            db, "project.policy_updated", "project", project_id, details={"fields": list(values)}
        )
        db.commit()
        db.refresh(policy)
        return policy


def assert_run_allowed(project_id: str, models: list[str]) -> ProjectPolicy:
    """Enforce stable preflight limits before creating a model-backed run."""
    with get_session() as db:
        policy = _policy(db, project_id, create=True)
        enforce_model_egress(policy, models)
        disallowed = (
            sorted(set(models) - set(policy.allowed_models)) if policy.allowed_models else []
        )
        if disallowed:
            raise repo.LabValidationError(
                f"project policy does not allow model(s): {', '.join(disallowed)}"
            )
        lab_running = db.exec(
            select(func.count())
            .select_from(LabRun)
            .where(LabRun.project_id == project_id, LabRun.status == "running")
        ).one()
        evaluation_running = db.exec(
            select(func.count())
            .select_from(EvaluationExperiment)
            .where(
                EvaluationExperiment.project_id == project_id,
                EvaluationExperiment.status == "running",
            )
        ).one()
        if int(lab_running) + int(evaluation_running) >= policy.max_concurrent_runs:
            raise repo.LabConflictError("project has reached its concurrent run limit")
        spent = db.exec(
            select(func.coalesce(func.sum(ModelCall.usd), 0.0)).where(
                ModelCall.project_id == project_id
            )
        ).one()
        if float(spent) >= policy.max_project_usd:
            raise repo.LabConflictError("project has reached its configured spend limit")
        db.commit()
        db.refresh(policy)
        return policy


def assert_model_allowed(project_id: str, model: str) -> ProjectPolicy:
    """Recheck egress and allowlist policy immediately before one provider call."""
    with get_session() as db:
        policy = _policy(db, project_id, create=True)
        enforce_model_egress(policy, [model])
        if policy.allowed_models and model not in policy.allowed_models:
            raise repo.LabValidationError(f"project policy does not allow model: {model}")
        db.commit()
        db.refresh(policy)
        return policy


def project_budget_summary(project_id: str) -> dict[str, object]:
    with get_session() as db:
        policy = _policy(db, project_id, create=True)
        tokens, usd = db.exec(
            select(
                func.coalesce(func.sum(ModelCall.tokens_in + ModelCall.tokens_out), 0),
                func.coalesce(func.sum(ModelCall.usd), 0.0),
            ).where(ModelCall.project_id == project_id)
        ).one()
        lab_running = db.exec(
            select(func.count())
            .select_from(LabRun)
            .where(LabRun.project_id == project_id, LabRun.status == "running")
        ).one()
        evaluation_running = db.exec(
            select(func.count())
            .select_from(EvaluationExperiment)
            .where(
                EvaluationExperiment.project_id == project_id,
                EvaluationExperiment.status == "running",
            )
        ).one()
        db.commit()
        return {
            "project_id": project_id,
            "tokens_used": int(tokens),
            "usd_used": round(float(usd), 6),
            "running": int(lab_running) + int(evaluation_running),
            "limits": policy.model_dump(mode="json"),
        }


# ── Source library and review ----------------------------------------------


def create_source(values: dict[str, Any]) -> SourceDocument:
    content = values["content"]
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    with get_session() as db:
        _project(db, values["project_id"])
        duplicate = db.exec(
            select(SourceDocument).where(
                SourceDocument.project_id == values["project_id"],
                SourceDocument.content_sha256 == digest,
                SourceDocument.status == "active",
            )
        ).first()
        if duplicate is not None:
            raise repo.LabConflictError("this source content is already in the project library")
        metadata = values.pop("metadata", {})
        source = SourceDocument(**values, metadata_json=metadata, content_sha256=digest)
        db.add(source)
        _record(
            db,
            "source.created",
            "source",
            source.id,
            details={"project_id": source.project_id, "sha256": digest},
        )
        db.commit()
        db.refresh(source)
        return source


def list_sources(project_id: str, *, include_archived: bool = False) -> list[SourceDocument]:
    with get_session() as db:
        _project(db, project_id)
        query = select(SourceDocument).where(SourceDocument.project_id == project_id)
        if not include_archived:
            query = query.where(SourceDocument.status == "active")
        return list(db.exec(query.order_by(SourceDocument.created_at.desc())))


def archive_source(source_id: str) -> SourceDocument:
    with get_session() as db:
        source = _require(db, SourceDocument, source_id, "source")
        source.status = "archived"
        source.updated_at = _now()
        db.add(source)
        excerpt_ids = list(
            db.exec(select(SourceExcerpt.id).where(SourceExcerpt.source_id == source.id))
        )
        affected_claim_ids = (
            list(
                db.exec(
                    select(ClaimEvidence.claim_id)
                    .where(ClaimEvidence.excerpt_id.in_(excerpt_ids))
                    .distinct()
                )
            )
            if excerpt_ids
            else []
        )
        for claim_id in affected_claim_ids:
            claim = db.get(ResearchClaim, claim_id)
            if claim is None or claim.status != "accepted":
                continue
            if "support" in _claim_acceptance_issues(db, claim):
                claim.status = "proposed"
                claim.updated_at = _now()
                db.add(claim)
                _record(
                    db,
                    "claim.auto_downgraded",
                    "claim",
                    claim.id,
                    details={
                        "project_id": claim.project_id,
                        "reason": "supporting_source_archived",
                        "source_id": source.id,
                        "status": "proposed",
                    },
                )
        _record(db, "source.archived", "source", source.id)
        db.commit()
        db.refresh(source)
        return source


def create_excerpt(source_id: str, values: dict[str, Any]) -> SourceExcerpt:
    with get_session() as db:
        source = _require(db, SourceDocument, source_id, "source")
        if source.status != "active":
            raise repo.LabConflictError("archived sources cannot receive new excerpts")
        quote = values["quote"]
        start = values.get("start_offset")
        end = values.get("end_offset")
        if (start is None) != (end is None):
            raise repo.LabValidationError("start_offset and end_offset must be supplied together")
        if start is None:
            start = source.content.find(quote)
            if start < 0:
                raise repo.LabValidationError("excerpt quote was not found in the captured source")
            end = start + len(quote)
        elif end <= start or end > len(source.content) or source.content[start:end] != quote:
            raise repo.LabValidationError("excerpt offsets do not match the captured source")
        excerpt = SourceExcerpt(
            project_id=source.project_id,
            source_id=source.id,
            locator=values.get("locator", ""),
            quote=quote,
            start_offset=start,
            end_offset=end,
            quote_sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        )
        db.add(excerpt)
        _record(
            db, "source.excerpt_created", "excerpt", excerpt.id, details={"source_id": source.id}
        )
        db.commit()
        db.refresh(excerpt)
        return excerpt


def link_task_source(task_id: str, values: dict[str, Any]) -> TaskSourceLink:
    with get_session() as db:
        task = _require(db, ResearchTask, task_id, "task")
        source = _require(db, SourceDocument, values["source_id"], "source")
        _same_project(task.project_id, source.project_id, "source")
        if source.status != "active":
            raise repo.LabConflictError("archived sources cannot be linked to new tasks")
        duplicate = db.exec(
            select(TaskSourceLink).where(
                TaskSourceLink.task_id == task.id, TaskSourceLink.source_id == source.id
            )
        ).first()
        if duplicate is not None:
            raise repo.LabConflictError("source is already linked to this task")
        link = TaskSourceLink(
            project_id=task.project_id,
            task_id=task.id,
            source_id=source.id,
            purpose=values.get("purpose", "context"),
        )
        db.add(link)
        _record(db, "task.source_linked", "task", task.id, details={"source_id": source.id})
        db.commit()
        db.refresh(link)
        return link


def task_source_packet(task_id: str) -> list[SourceDocument]:
    with get_session() as db:
        task = _require(db, ResearchTask, task_id, "task")
        return list(
            db.exec(
                select(SourceDocument)
                .join(TaskSourceLink, TaskSourceLink.source_id == SourceDocument.id)
                .where(
                    TaskSourceLink.task_id == task_id,
                    TaskSourceLink.project_id == task.project_id,
                    SourceDocument.project_id == task.project_id,
                    SourceDocument.status == "active",
                )
                .order_by(TaskSourceLink.created_at, TaskSourceLink.id)
                .limit(MAX_TASK_SOURCE_COUNT)
            )
        )


def unlink_task_source(link_id: str) -> None:
    with get_session() as db:
        link = _require(db, TaskSourceLink, link_id, "task source link")
        task_id = link.task_id
        source_id = link.source_id
        db.delete(link)
        _record(
            db,
            "task.source_unlinked",
            "task",
            task_id,
            details={
                "project_id": link.project_id,
                "link_id": link.id,
                "source_id": source_id,
                "purpose": link.purpose,
            },
        )
        db.commit()


def review_finding(finding_id: str, values: dict[str, Any]) -> FindingReview:
    with get_session() as db:
        finding = _require(db, Finding, finding_id, "finding")
        review = FindingReview(project_id=finding.project_id, finding_id=finding.id, **values)
        db.add(review)
        if review.decision != "accepted":
            accepted_claims = list(
                db.exec(
                    select(ResearchClaim).where(
                        ResearchClaim.finding_id == finding.id,
                        ResearchClaim.status == "accepted",
                    )
                )
            )
            for claim in accepted_claims:
                contradiction = db.exec(
                    select(ClaimEvidence).where(
                        ClaimEvidence.claim_id == claim.id,
                        ClaimEvidence.stance == "contradicts",
                    )
                ).first()
                claim.status = "disputed" if contradiction is not None else "proposed"
                claim.updated_at = _now()
                db.add(claim)
                _record(
                    db,
                    "claim.auto_downgraded",
                    "claim",
                    claim.id,
                    details={
                        "project_id": claim.project_id,
                        "reason": "finding_review_changed",
                        "review_id": review.id,
                        "decision": review.decision,
                        "status": claim.status,
                    },
                )
        _record(
            db,
            "finding.reviewed",
            "finding",
            finding.id,
            details={"decision": review.decision, "reviewer": review.reviewer},
        )
        db.commit()
        db.refresh(review)
        return review


def _claim_acceptance_issues(db: Session, claim: ResearchClaim) -> list[str]:
    """Return compact invariant codes preventing an accepted claim state."""
    issues: list[str] = []
    if claim.finding_id is not None:
        review = db.exec(
            select(FindingReview)
            .where(FindingReview.finding_id == claim.finding_id)
            .order_by(FindingReview.created_at.desc(), FindingReview.id.desc())
        ).first()
        if review is None or review.decision != "accepted":
            issues.append("finding_review")
    evidence_rows = list(
        db.exec(select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id))
    )
    if any(row.stance == "contradicts" for row in evidence_rows):
        issues.append("contradiction")
    has_support = False
    for evidence in evidence_rows:
        if evidence.stance != "supports":
            continue
        excerpt = db.get(SourceExcerpt, evidence.excerpt_id)
        source = db.get(SourceDocument, excerpt.source_id) if excerpt is not None else None
        if excerpt is None or source is None or source.status != "active":
            continue
        start = excerpt.start_offset
        end = excerpt.end_offset
        if (
            evidence.project_id == claim.project_id
            and excerpt.project_id == claim.project_id
            and source.project_id == claim.project_id
            and hashlib.sha256(source.content.encode("utf-8")).hexdigest()
            == source.content_sha256
            and hashlib.sha256(excerpt.quote.encode("utf-8")).hexdigest()
            == excerpt.quote_sha256
            and start is not None
            and end is not None
            and 0 <= start < end <= len(source.content)
            and source.content[start:end] == excerpt.quote
        ):
            has_support = True
            break
    if not has_support:
        issues.append("support")
    return issues


def create_claim(values: dict[str, Any]) -> ResearchClaim:
    if values.get("status") == "accepted":
        raise repo.LabValidationError(
            "new claims start as proposed; accept them only after evidence review"
        )
    with get_session() as db:
        _project(db, values["project_id"])
        finding_id = values.get("finding_id")
        if finding_id is not None:
            finding = _require(db, Finding, finding_id, "finding")
            _same_project(values["project_id"], finding.project_id, "finding")
        claim = ResearchClaim(**values)
        db.add(claim)
        _record(db, "claim.created", "claim", claim.id, details={"finding_id": finding_id or ""})
        db.commit()
        db.refresh(claim)
        return claim


def update_claim(claim_id: str, changes: dict[str, Any]) -> ResearchClaim:
    if not changes:
        raise repo.LabValidationError("at least one claim field must be supplied")
    with get_session() as db:
        claim = _require(db, ResearchClaim, claim_id, "claim")
        changes = dict(changes)
        previous = {key: getattr(claim, key) for key in changes}
        statement_changed = (
            "statement" in changes and changes["statement"] != claim.statement
        )
        if statement_changed and changes.get("status") == "accepted":
            raise repo.LabValidationError(
                "edit the claim statement first, then accept it in a separate review action"
            )
        if (
            statement_changed
            and claim.status == "accepted"
            and "status" not in changes
        ):
            changes["status"] = "proposed"
            previous["status"] = claim.status
        for key, value in changes.items():
            setattr(claim, key, value)
        if claim.status == "accepted":
            acceptance_issues = _claim_acceptance_issues(db, claim)
            if acceptance_issues:
                messages = {
                    "finding_review": "its latest finding review is accepted",
                    "contradiction": "contradictory evidence is resolved",
                    "support": "an active intact supporting excerpt is linked",
                }
                raise repo.LabConflictError(
                    "claim cannot be accepted until "
                    + "; ".join(messages[issue] for issue in acceptance_issues)
                )
        claim.updated_at = _now()
        db.add(claim)
        _record(
            db,
            "claim.updated",
            "claim",
            claim.id,
            details={
                "project_id": claim.project_id,
                "fields": list(changes),
                "previous": previous,
                "current": {key: getattr(claim, key) for key in changes},
            },
        )
        db.commit()
        db.refresh(claim)
        return claim


def attach_claim_evidence(claim_id: str, values: dict[str, Any]) -> ClaimEvidence:
    with get_session() as db:
        claim = _require(db, ResearchClaim, claim_id, "claim")
        excerpt = _require(db, SourceExcerpt, values["excerpt_id"], "excerpt")
        _same_project(claim.project_id, excerpt.project_id, "excerpt")
        source = _require(db, SourceDocument, excerpt.source_id, "source")
        _same_project(claim.project_id, source.project_id, "source")
        if source.status != "active":
            raise repo.LabConflictError("archived sources cannot be attached as evidence")
        duplicate = db.exec(
            select(ClaimEvidence).where(
                ClaimEvidence.claim_id == claim.id,
                ClaimEvidence.excerpt_id == excerpt.id,
            )
        ).first()
        if duplicate is not None:
            raise repo.LabConflictError("this evidence link already exists")
        evidence = ClaimEvidence(project_id=claim.project_id, claim_id=claim.id, **values)
        db.add(evidence)
        if evidence.stance == "contradicts" and claim.status == "accepted":
            claim.status = "disputed"
            claim.updated_at = _now()
            db.add(claim)
            _record(
                db,
                "claim.auto_downgraded",
                "claim",
                claim.id,
                details={
                    "project_id": claim.project_id,
                    "reason": "contradictory_evidence_attached",
                    "evidence_id": evidence.id,
                    "status": "disputed",
                },
            )
        _record(
            db,
            "claim.evidence_attached",
            "claim",
            claim.id,
            details={"excerpt_id": excerpt.id, "stance": evidence.stance},
        )
        db.commit()
        db.refresh(evidence)
        return evidence


def unlink_claim_evidence(evidence_id: str) -> None:
    with get_session() as db:
        evidence = _require(db, ClaimEvidence, evidence_id, "claim evidence")
        claim_id = evidence.claim_id
        excerpt_id = evidence.excerpt_id
        claim = _require(db, ResearchClaim, claim_id, "claim")
        db.delete(evidence)
        db.flush()
        if claim.status == "accepted" and "support" in _claim_acceptance_issues(db, claim):
            claim.status = "proposed"
            claim.updated_at = _now()
            db.add(claim)
            _record(
                db,
                "claim.auto_downgraded",
                "claim",
                claim.id,
                details={
                    "project_id": claim.project_id,
                    "reason": "supporting_evidence_unlinked",
                    "evidence_id": evidence_id,
                    "status": "proposed",
                },
            )
        _record(
            db,
            "claim.evidence_unlinked",
            "claim",
            claim_id,
            details={
                "project_id": evidence.project_id,
                "evidence_id": evidence_id,
                "excerpt_id": excerpt_id,
                "stance": evidence.stance,
                "note": evidence.note,
            },
        )
        db.commit()


# ── Meetings, actions, and task graph --------------------------------------


def create_meeting_outcome(meeting_id: str, values: dict[str, Any]) -> MeetingOutcome:
    with get_session() as db:
        meeting = _require(db, ResearchMeeting, meeting_id, "meeting")
        run_id = values.get("run_id")
        if run_id is not None:
            run = _require(db, LabRun, run_id, "run")
            if run.meeting_id != meeting.id:
                raise repo.LabValidationError("run does not belong to this meeting")
        outcome = MeetingOutcome(project_id=meeting.project_id, meeting_id=meeting.id, **values)
        db.add(outcome)
        _record(db, "meeting.outcome_recorded", "meeting", meeting.id, run_id=run_id)
        db.commit()
        db.refresh(outcome)
        return outcome


def create_action(values: dict[str, Any]) -> ActionItem:
    with get_session() as db:
        _project(db, values["project_id"])
        meeting_id = values.get("meeting_id")
        if meeting_id is not None:
            meeting = _require(db, ResearchMeeting, meeting_id, "meeting")
            _same_project(values["project_id"], meeting.project_id, "meeting")
        owner_id = values.get("owner_agent_id")
        if owner_id is not None:
            _require(db, LabAgent, owner_id, "owner agent")
        action = ActionItem(**values)
        db.add(action)
        _record(db, "action.created", "action", action.id, agent_id=owner_id)
        db.commit()
        db.refresh(action)
        return action


def update_action(action_id: str, changes: dict[str, Any]) -> ActionItem:
    if not changes:
        raise repo.LabValidationError("at least one field must be supplied")
    with get_session() as db:
        action = _require(db, ActionItem, action_id, "action item")
        if "owner_agent_id" in changes and changes["owner_agent_id"] is not None:
            _require(db, LabAgent, changes["owner_agent_id"], "owner agent")
        for key, value in changes.items():
            setattr(action, key, value)
        action.updated_at = _now()
        db.add(action)
        _record(db, "action.updated", "action", action.id, details={"fields": list(changes)})
        db.commit()
        db.refresh(action)
        return action


def promote_action(action_id: str, values: dict[str, Any]) -> ResearchTask:
    with get_session() as db:
        action = _require(db, ActionItem, action_id, "action item")
        if action.promoted_task_id is not None:
            raise repo.LabConflictError("action item has already been promoted")
        agent_id = values.get("assigned_agent_id") or action.owner_agent_id
        if agent_id is None:
            raise repo.LabValidationError("an assigned agent is required to promote this action")
        agent = _require(db, LabAgent, agent_id, "agent")
        if agent.status != "active":
            raise repo.LabValidationError("assigned agent must be active")
        department_id = values.get("department_id") or agent.department_id
        if department_id is not None:
            department = _require(db, Department, department_id, "department")
            if department.status != "active":
                raise repo.LabValidationError("department must be active")
        task = ResearchTask(
            project_id=action.project_id,
            department_id=department_id,
            assigned_agent_id=agent.id,
            title=action.title,
            objective=action.details or action.title,
            expected_output=values.get("expected_output", ""),
        )
        db.add(task)
        db.flush()
        action.promoted_task_id = task.id
        action.status = "in_progress"
        action.updated_at = _now()
        db.add(action)
        _record(
            db,
            "action.promoted_to_task",
            "action",
            action.id,
            agent_id=agent.id,
            details={"task_id": task.id},
        )
        db.commit()
        db.refresh(task)
        return task


def _dependency_graph(db: Session, project_id: str) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for edge in db.exec(select(TaskDependency).where(TaskDependency.project_id == project_id)):
        graph.setdefault(edge.task_id, set()).add(edge.depends_on_task_id)
    return graph


def _reaches(graph: dict[str, set[str]], start: str, target: str) -> bool:
    pending = [start]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(graph.get(current, ()))
    return False


def add_dependency(task_id: str, depends_on_task_id: str) -> TaskDependency:
    with get_session() as db:
        task = _require(db, ResearchTask, task_id, "task")
        dependency = _require(db, ResearchTask, depends_on_task_id, "dependency task")
        _same_project(task.project_id, dependency.project_id, "dependency task")
        if task.id == dependency.id:
            raise repo.LabValidationError("a task cannot depend on itself")
        duplicate = db.exec(
            select(TaskDependency).where(
                TaskDependency.task_id == task.id,
                TaskDependency.depends_on_task_id == dependency.id,
            )
        ).first()
        if duplicate is not None:
            raise repo.LabConflictError("task dependency already exists")
        graph = _dependency_graph(db, task.project_id)
        if _reaches(graph, dependency.id, task.id):
            raise repo.LabValidationError("task dependency would create a cycle")
        edge = TaskDependency(
            project_id=task.project_id,
            task_id=task.id,
            depends_on_task_id=dependency.id,
        )
        db.add(edge)
        _record(db, "task.dependency_added", "task", task.id, details={"depends_on": dependency.id})
        db.commit()
        db.refresh(edge)
        return edge


def remove_dependency(dependency_id: str) -> None:
    with get_session() as db:
        edge = _require(db, TaskDependency, dependency_id, "task dependency")
        task_id = edge.task_id
        dependency_id_value = edge.depends_on_task_id
        db.delete(edge)
        _record(
            db,
            "task.dependency_removed",
            "task",
            task_id,
            details={"depends_on": dependency_id_value},
        )
        db.commit()


def task_readiness(task_id: str) -> dict[str, object]:
    with get_session() as db:
        task = _require(db, ResearchTask, task_id, "task")
        edges = list(db.exec(select(TaskDependency).where(TaskDependency.task_id == task.id)))
        dependencies = []
        blockers = []
        for edge in edges:
            dependency = _require(db, ResearchTask, edge.depends_on_task_id, "dependency task")
            detail = {
                "dependency_id": edge.id,
                "task_id": dependency.id,
                "title": dependency.title,
                "status": dependency.status,
            }
            dependencies.append(detail)
            if dependency.status != "completed":
                blockers.append(detail)
        return {
            "task_id": task.id,
            "ready": not blockers,
            "dependencies": dependencies,
            "blockers": blockers,
        }


def assert_task_ready(task_id: str) -> None:
    readiness = task_readiness(task_id)
    if not readiness["ready"]:
        raise repo.LabConflictError("task has incomplete dependencies")


# ── Traceability, history, and dossiers ------------------------------------


_TRACE_MODELS: dict[str, type[SQLModel]] = {
    "project": ResearchProject,
    "task": ResearchTask,
    "finding": Finding,
    "meeting": ResearchMeeting,
    "source": SourceDocument,
    "claim": ResearchClaim,
    "action": ActionItem,
    "workspace": Workspace,
    "artifact": Artifact,
}


def _require_trace_entity(db: Session, kind: str, row_id: str) -> SQLModel:
    model = _TRACE_MODELS.get(kind)
    if model is None:
        raise repo.LabValidationError(f"unsupported trace entity type: {kind}")
    key: str | int = row_id
    if model is Artifact:
        try:
            key = int(row_id)
        except ValueError as error:
            raise repo.LabValidationError("artifact id must be an integer") from error
    return _require(db, model, key, kind)


def create_trace_link(values: dict[str, Any]) -> TraceLink:
    with get_session() as db:
        _project(db, values["project_id"])
        source = _require_trace_entity(db, values["source_type"], values["source_id"])
        target = _require_trace_entity(db, values["target_type"], values["target_id"])
        for label, kind, row in (
            ("source", values["source_type"], source),
            ("target", values["target_type"], target),
        ):
            entity_project_id = (
                row.id if kind == "project" else getattr(row, "project_id", None)
            )
            if entity_project_id is not None:
                _same_project(values["project_id"], str(entity_project_id), label)
        duplicate = db.exec(
            select(TraceLink).where(
                TraceLink.source_type == values["source_type"],
                TraceLink.source_id == values["source_id"],
                TraceLink.target_type == values["target_type"],
                TraceLink.target_id == values["target_id"],
                TraceLink.relationship == values.get("relationship", "informs"),
            )
        ).first()
        if duplicate is not None:
            raise repo.LabConflictError("trace link already exists")
        link = TraceLink(**values)
        db.add(link)
        _record(
            db,
            "trace.link_created",
            "trace_link",
            link.id,
            details={
                "source": f"{link.source_type}:{link.source_id}",
                "target": f"{link.target_type}:{link.target_id}",
            },
        )
        db.commit()
        db.refresh(link)
        return link


def list_trace_links(project_id: str) -> list[TraceLink]:
    with get_session() as db:
        _project(db, project_id)
        return list(
            db.exec(
                select(TraceLink)
                .where(TraceLink.project_id == project_id)
                .order_by(TraceLink.created_at)
            )
        )


def project_history(project_id: str, limit: int = 250) -> dict[str, list[SQLModel]]:
    with get_session() as db:
        _project(db, project_id)
        return {
            "runs": list(
                db.exec(
                    select(LabRun)
                    .where(LabRun.project_id == project_id)
                    .order_by(LabRun.started_at.desc())
                    .limit(limit)
                )
            ),
            "model_calls": list(
                db.exec(
                    select(ModelCall)
                    .where(ModelCall.project_id == project_id)
                    .order_by(ModelCall.created_at.desc())
                    .limit(limit)
                )
            ),
            "activity": list(
                db.exec(
                    select(ActivityRecord)
                    .where(
                        (ActivityRecord.entity_id == project_id)
                        | (
                            ActivityRecord.run_id.in_(
                                select(LabRun.id).where(LabRun.project_id == project_id)
                            )
                        )
                    )
                    .order_by(ActivityRecord.created_at.desc())
                    .limit(limit)
                )
            ),
        }


def project_dossier(project_id: str) -> dict[str, Any]:
    with get_session() as db:
        project = _project(db, project_id)
        policy = _policy(db, project_id)

        def rows(model: type[SQLModel], order: Any) -> list[SQLModel]:
            return list(
                db.exec(
                    select(model).where(getattr(model, "project_id") == project_id).order_by(order)
                )
            )

        return {
            "project": project.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"),
            "sources": [
                r.model_dump(mode="json") for r in rows(SourceDocument, SourceDocument.created_at)
            ],
            "excerpts": [
                r.model_dump(mode="json") for r in rows(SourceExcerpt, SourceExcerpt.created_at)
            ],
            "source_links": [
                r.model_dump(mode="json") for r in rows(TaskSourceLink, TaskSourceLink.created_at)
            ],
            "tasks": [
                r.model_dump(mode="json") for r in rows(ResearchTask, ResearchTask.created_at)
            ],
            "results": [r.model_dump(mode="json") for r in rows(TaskResult, TaskResult.created_at)],
            "findings": [r.model_dump(mode="json") for r in rows(Finding, Finding.created_at)],
            "finding_reviews": [
                r.model_dump(mode="json") for r in rows(FindingReview, FindingReview.created_at)
            ],
            "claims": [
                r.model_dump(mode="json") for r in rows(ResearchClaim, ResearchClaim.created_at)
            ],
            "claim_evidence": [
                r.model_dump(mode="json") for r in rows(ClaimEvidence, ClaimEvidence.created_at)
            ],
            "dependencies": [
                r.model_dump(mode="json") for r in rows(TaskDependency, TaskDependency.created_at)
            ],
            "meetings": [
                r.model_dump(mode="json") for r in rows(ResearchMeeting, ResearchMeeting.created_at)
            ],
            "outcomes": [
                r.model_dump(mode="json") for r in rows(MeetingOutcome, MeetingOutcome.created_at)
            ],
            "actions": [r.model_dump(mode="json") for r in rows(ActionItem, ActionItem.created_at)],
            "runs": [r.model_dump(mode="json") for r in rows(LabRun, LabRun.started_at)],
            "trace_links": [
                r.model_dump(mode="json") for r in rows(TraceLink, TraceLink.created_at)
            ],
        }


def render_dossier_markdown(project_id: str) -> str:
    dossier = project_dossier(project_id)
    project = dossier["project"]
    lines = [
        f"# {project['name']}",
        "",
        project.get("description", ""),
        "",
        "## Objective",
        "",
        project["objective"],
        "",
        "## Sources",
        "",
    ]
    sources = dossier["sources"]
    lines.extend(
        f"- **{source['title']}** ({source['source_type']}) — {source['origin'] or 'local capture'}"
        for source in sources
    )
    if not sources:
        lines.append("_No sources captured._")
    lines.extend(["", "## Findings", ""])
    findings = dossier["findings"]
    for finding in findings:
        lines.extend([f"### {finding['title']}", "", finding["content"], ""])
    if not findings:
        lines.append("_No findings recorded._")
    lines.extend(["", "## Claims and evidence", ""])
    excerpts = {excerpt["id"]: excerpt for excerpt in dossier["excerpts"]}
    sources_by_id = {source["id"]: source for source in sources}
    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    for evidence in dossier["claim_evidence"]:
        evidence_by_claim.setdefault(evidence["claim_id"], []).append(evidence)
    for claim in dossier["claims"]:
        confidence = (
            f" (confidence {claim['confidence']:.0%})"
            if claim["confidence"] is not None
            else ""
        )
        lines.extend([f"### {claim['statement']}{confidence}", ""])
        for evidence in evidence_by_claim.get(claim["id"], []):
            excerpt = excerpts.get(evidence["excerpt_id"])
            if excerpt is None:
                continue
            source = sources_by_id.get(excerpt["source_id"])
            source_title = source["title"] if source else "Unknown source"
            locator = f", {excerpt['locator']}" if excerpt["locator"] else ""
            lines.append(
                f"- **{evidence['stance']}** — {source_title}{locator}: “{excerpt['quote']}”"
            )
        lines.append("")
    if not dossier["claims"]:
        lines.append("_No claims recorded._")
    lines.extend(["", "## Decisions and actions", ""])
    for outcome in dossier["outcomes"]:
        lines.extend([outcome["summary"], ""])
        lines.extend(f"- Decision: {item}" for item in outcome["decisions"])
    for action in dossier["actions"]:
        lines.append(f"- [{'x' if action['status'] == 'completed' else ' '}] {action['title']}")
    lines.extend(["", "## Trace links", ""])
    lines.extend(
        f"- `{link['source_type']}:{link['source_id']}` {link['relationship']} "
        f"`{link['target_type']}:{link['target_id']}`"
        for link in dossier["trace_links"]
    )
    return "\n".join(lines).rstrip() + "\n"


# ── Templates ---------------------------------------------------------------


def create_template(values: dict[str, Any]) -> LabTemplate:
    with get_session() as db:
        template = LabTemplate(**values)
        db.add(template)
        _record(db, "template.created", "template", template.id, details={"kind": template.kind})
        db.commit()
        db.refresh(template)
        return template


def list_templates(kind: str | None = None) -> list[LabTemplate]:
    with get_session() as db:
        query = select(LabTemplate).where(LabTemplate.status == "active")
        if kind is not None:
            query = query.where(LabTemplate.kind == kind)
        return list(db.exec(query.order_by(LabTemplate.created_at.desc())))


def archive_template(template_id: str) -> LabTemplate:
    with get_session() as db:
        template = _require(db, LabTemplate, template_id, "template")
        template.status = "archived"
        template.updated_at = _now()
        db.add(template)
        _record(db, "template.archived", "template", template.id)
        db.commit()
        db.refresh(template)
        return template


def get_template(template_id: str) -> LabTemplate:
    with get_session() as db:
        template = _require(db, LabTemplate, template_id, "template")
        if template.status != "active":
            raise repo.LabConflictError("archived templates cannot be instantiated")
        return template


def record_template_instantiation(template_id: str, entity_id: str) -> None:
    with get_session() as db:
        template = _require(db, LabTemplate, template_id, "template")
        _record(
            db,
            "template.instantiated",
            "template",
            template.id,
            details={"kind": template.kind, "entity_id": entity_id},
        )
        db.commit()


# ── Model evaluation --------------------------------------------------------


def create_evaluation(values: dict[str, Any]) -> EvaluationExperiment:
    with get_session() as db:
        _project(db, values["project_id"])
        experiment = EvaluationExperiment(**values)
        db.add(experiment)
        db.flush()
        for model in experiment.models:
            db.add(
                EvaluationCandidate(
                    experiment_id=experiment.id,
                    project_id=experiment.project_id,
                    model=model,
                )
            )
        _record(db, "evaluation.created", "evaluation", experiment.id)
        db.commit()
        db.refresh(experiment)
        return experiment


def get_evaluation(
    experiment_id: str,
) -> tuple[EvaluationExperiment, list[EvaluationCandidate], list[EvaluationScore]]:
    with get_session() as db:
        experiment = _require(db, EvaluationExperiment, experiment_id, "evaluation")
        candidates = list(
            db.exec(
                select(EvaluationCandidate)
                .where(EvaluationCandidate.experiment_id == experiment.id)
                .order_by(EvaluationCandidate.created_at)
            )
        )
        candidate_ids = [candidate.id for candidate in candidates]
        scores = (
            list(
                db.exec(
                    select(EvaluationScore)
                    .where(EvaluationScore.candidate_id.in_(candidate_ids))
                    .order_by(EvaluationScore.created_at)
                )
            )
            if candidate_ids
            else []
        )
        return experiment, candidates, scores


def list_evaluations(project_id: str) -> list[EvaluationExperiment]:
    with get_session() as db:
        _project(db, project_id)
        return list(
            db.exec(
                select(EvaluationExperiment)
                .where(EvaluationExperiment.project_id == project_id)
                .order_by(EvaluationExperiment.created_at.desc())
            )
        )


def mark_evaluation_running(
    experiment_id: str,
) -> tuple[EvaluationExperiment, list[EvaluationCandidate]]:
    with get_session() as db:
        experiment = _require(db, EvaluationExperiment, experiment_id, "evaluation")
        if experiment.status == "running":
            raise repo.LabConflictError("evaluation is already running")
        if experiment.status == "completed":
            raise repo.LabConflictError(
                "completed evaluations are immutable; create a new experiment"
            )
        candidates = list(
            db.exec(
                select(EvaluationCandidate).where(
                    EvaluationCandidate.experiment_id == experiment.id
                )
            )
        )
        experiment.status = "running"
        experiment.updated_at = _now()
        for candidate in candidates:
            candidate.status = "queued"
            candidate.response = ""
            candidate.tokens_in = 0
            candidate.tokens_out = 0
            candidate.usd = 0.0
            candidate.latency_ms = None
            candidate.error = None
            candidate.completed_at = None
            db.add(candidate)
        db.add(experiment)
        _record(db, "evaluation.started", "evaluation", experiment.id)
        db.commit()
        db.refresh(experiment)
        for candidate in candidates:
            db.refresh(candidate)
        return experiment, candidates


def mark_evaluation_candidate_running(candidate_id: str) -> None:
    with get_session() as db:
        candidate = _require(db, EvaluationCandidate, candidate_id, "evaluation candidate")
        candidate.status = "running"
        db.add(candidate)
        db.commit()


def complete_evaluation_candidate(
    candidate_id: str,
    response: str,
    *,
    tokens_in: int,
    tokens_out: int,
    usd: float,
    latency_ms: int,
) -> None:
    with get_session() as db:
        candidate = _require(db, EvaluationCandidate, candidate_id, "evaluation candidate")
        candidate.response = response
        candidate.tokens_in = tokens_in
        candidate.tokens_out = tokens_out
        candidate.usd = usd
        candidate.latency_ms = latency_ms
        candidate.status = "completed"
        candidate.completed_at = _now()
        db.add(candidate)
        db.commit()


def fail_evaluation_candidate(candidate_id: str, message: str) -> None:
    with get_session() as db:
        candidate = _require(db, EvaluationCandidate, candidate_id, "evaluation candidate")
        candidate.status = "failed"
        candidate.error = message[:500]
        candidate.completed_at = _now()
        db.add(candidate)
        db.commit()


def finish_evaluation(experiment_id: str) -> EvaluationExperiment:
    with get_session() as db:
        experiment = _require(db, EvaluationExperiment, experiment_id, "evaluation")
        statuses = list(
            db.exec(
                select(EvaluationCandidate.status).where(
                    EvaluationCandidate.experiment_id == experiment.id
                )
            )
        )
        experiment.status = (
            "completed" if statuses and all(s == "completed" for s in statuses) else "failed"
        )
        experiment.updated_at = _now()
        db.add(experiment)
        _record(db, f"evaluation.{experiment.status}", "evaluation", experiment.id)
        db.commit()
        db.refresh(experiment)
        return experiment


def cancel_evaluation(experiment_id: str) -> EvaluationExperiment:
    with get_session() as db:
        experiment = _require(db, EvaluationExperiment, experiment_id, "evaluation")
        if experiment.status == "cancelled":
            return experiment
        if experiment.status not in {"draft", "running", "failed"}:
            raise repo.LabConflictError("evaluation cannot be cancelled in its current state")
        experiment.status = "cancelled"
        experiment.updated_at = _now()
        candidates = list(
            db.exec(
                select(EvaluationCandidate).where(
                    EvaluationCandidate.experiment_id == experiment.id,
                    EvaluationCandidate.status.in_(["queued", "running"]),
                )
            )
        )
        for candidate in candidates:
            candidate.status = "failed"
            candidate.error = "evaluation cancelled"
            candidate.completed_at = _now()
            db.add(candidate)
        db.add(experiment)
        _record(db, "evaluation.cancelled", "evaluation", experiment.id)
        db.commit()
        db.refresh(experiment)
        return experiment


def score_candidate(candidate_id: str, values: dict[str, Any]) -> EvaluationScore:
    with get_session() as db:
        candidate = _require(db, EvaluationCandidate, candidate_id, "evaluation candidate")
        experiment = _require(db, EvaluationExperiment, candidate.experiment_id, "evaluation")
        if values["criterion"] not in experiment.criteria:
            raise repo.LabValidationError("criterion is not configured for this experiment")
        score = EvaluationScore(candidate_id=candidate.id, **values)
        db.add(score)
        _record(
            db,
            "evaluation.candidate_scored",
            "evaluation",
            experiment.id,
            details={
                "candidate_id": candidate.id,
                "criterion": score.criterion,
                "score": score.score,
            },
        )
        db.commit()
        db.refresh(score)
        return score


# ── Model-call provenance ---------------------------------------------------


def model_call_totals(
    *, run_id: str | None = None, project_id: str | None = None
) -> tuple[int, float]:
    """Return completed provider usage for one run or one project.

    The orchestrators call this before every turn so multi-turn meetings obey one
    cumulative run budget rather than accidentally receiving a fresh allowance for
    every participant.
    """
    if (run_id is None) == (project_id is None):
        raise ValueError("supply exactly one of run_id or project_id")
    with get_session() as db:
        query = select(
            func.coalesce(func.sum(ModelCall.tokens_in + ModelCall.tokens_out), 0),
            func.coalesce(func.sum(ModelCall.usd), 0.0),
        )
        if run_id is not None:
            query = query.where(ModelCall.run_id == run_id)
        else:
            query = query.where(ModelCall.project_id == project_id)
        tokens, usd = db.exec(query).one()
        return int(tokens), float(usd)


def begin_model_call(
    *,
    project_id: str,
    run_id: str | None,
    agent_id: str | None,
    stage: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    policy: ProjectPolicy,
) -> ModelCall:
    with get_session() as db:
        call = ModelCall(
            project_id=project_id,
            run_id=run_id,
            agent_id=agent_id,
            stage=stage,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            policy_snapshot={
                "data_classification": policy.data_classification,
                "allowed_models": policy.allowed_models,
                "max_run_tokens": policy.max_run_tokens,
                "max_run_usd": policy.max_run_usd,
                "max_project_usd": policy.max_project_usd,
            },
        )
        db.add(call)
        db.commit()
        db.refresh(call)
        return call


def finish_model_call(
    call_id: str,
    *,
    status: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    usd: float = 0.0,
    latency_ms: int | None = None,
    error: str | None = None,
) -> None:
    with get_session() as db:
        call = _require(db, ModelCall, call_id, "model call")
        call.status = status
        call.tokens_in = tokens_in
        call.tokens_out = tokens_out
        call.usd = usd
        call.latency_ms = latency_ms
        call.error = error[:500] if error else None
        call.completed_at = _now()
        db.add(call)
        db.commit()


def recover_interrupted_work() -> dict[str, int]:
    """Fail advanced jobs left active by an unclean backend shutdown.

    Background asyncio tasks do not survive a process restart. Keeping their durable
    rows in ``running`` would make the UI lie and, for evaluations, permanently consume
    one of the project's concurrency slots. Recovery is intentionally idempotent so it
    is safe to run at every startup after the schema is ready.
    """
    with get_session() as db:
        interrupted_at = _now()
        model_calls = list(db.exec(select(ModelCall).where(ModelCall.status == "running")))
        evaluations = list(
            db.exec(
                select(EvaluationExperiment).where(EvaluationExperiment.status == "running")
            )
        )
        automations = list(
            db.exec(select(AutomationRun).where(AutomationRun.status == "running"))
        )

        for call in model_calls:
            call.status = "failed"
            call.error = "model call was interrupted by a previous server shutdown"
            call.completed_at = interrupted_at
            db.add(call)

        for experiment in evaluations:
            experiment.status = "failed"
            experiment.updated_at = interrupted_at
            db.add(experiment)
            candidates = list(
                db.exec(
                    select(EvaluationCandidate).where(
                        EvaluationCandidate.experiment_id == experiment.id,
                        EvaluationCandidate.status.in_(["queued", "running"]),
                    )
                )
            )
            for candidate in candidates:
                candidate.status = "failed"
                candidate.error = "evaluation was interrupted by a previous server shutdown"
                candidate.completed_at = interrupted_at
                db.add(candidate)
            _record(
                db,
                "evaluation.recovered_as_failed",
                "evaluation",
                experiment.id,
                details={"reason": "previous server shutdown"},
            )

        for automation in automations:
            automation.status = "failed"
            automation.error = "automation was interrupted by a previous server shutdown"
            automation.completed_at = interrupted_at
            db.add(automation)
            _record(
                db,
                "automation.recovered_as_failed",
                "automation",
                automation.id,
                details={"reason": "previous server shutdown"},
            )

        if model_calls or evaluations or automations:
            db.commit()
        return {
            "model_calls": len(model_calls),
            "evaluations": len(evaluations),
            "automations": len(automations),
        }


# ── Approval-gated automation ----------------------------------------------


def create_automation_plan(values: dict[str, Any]) -> AutomationRun:
    with get_session() as db:
        project_id = values.get("project_id")
        workspace_id = values.get("workspace_id")
        if project_id is not None:
            _project(db, project_id)
        if workspace_id is not None:
            _require(db, Workspace, workspace_id, "workspace")
        if project_id is None and workspace_id is None:
            raise repo.LabValidationError("automation requires a project or workspace")
        allowed_capabilities = {"read_workspace", "write_workspace", "run_checks"}
        requested = set(values.get("capabilities", []))
        if not requested <= allowed_capabilities:
            raise repo.LabValidationError("automation requested an unsupported capability")
        automation = AutomationRun(**values)
        db.add(automation)
        _record(
            db,
            "automation.planned",
            "automation",
            automation.id,
            details={"provider": automation.provider, "capabilities": automation.capabilities},
        )
        db.commit()
        db.refresh(automation)
        return automation


def decide_automation(automation_id: str, decision: str, note: str) -> AutomationRun:
    with get_session() as db:
        automation = _require(db, AutomationRun, automation_id, "automation plan")
        if automation.status != "planned":
            raise repo.LabConflictError("automation plan has already been decided")
        automation.status = "approved" if decision == "approve" else "rejected"
        automation.approval_note = note
        automation.approved_at = _now() if decision == "approve" else None
        db.add(automation)
        _record(
            db,
            f"automation.{automation.status}",
            "automation",
            automation.id,
            details={"note": note},
        )
        db.commit()
        db.refresh(automation)
        return automation


def get_automation(automation_id: str) -> AutomationRun:
    with get_session() as db:
        return _require(db, AutomationRun, automation_id, "automation plan")


def list_automations() -> list[AutomationRun]:
    with get_session() as db:
        return list(
            db.exec(select(AutomationRun).order_by(AutomationRun.created_at.desc()).limit(250))
        )


def begin_automation(automation_id: str) -> tuple[AutomationRun, Workspace]:
    with get_session() as db:
        automation = _require(db, AutomationRun, automation_id, "automation plan")
        if automation.status != "approved":
            raise repo.LabConflictError("automation must be approved before execution")
        if automation.workspace_id is None:
            raise repo.LabValidationError("headless execution requires a workspace")
        workspace = _require(db, Workspace, automation.workspace_id, "workspace")
        if workspace.status != "active":
            raise repo.LabValidationError("automation workspace must be active")
        if automation.project_id is not None:
            policy = _policy(db, automation.project_id, create=True)
            if policy.data_classification != "public":
                raise repo.LabValidationError(
                    "project-scoped external headless automation requires public classification"
                )
        automation.status = "running"
        db.add(automation)
        _record(
            db,
            "automation.started",
            "automation",
            automation.id,
            details={"workspace_id": workspace.id, "provider": automation.provider},
        )
        db.commit()
        db.refresh(automation)
        return automation, workspace


def assert_automation_allowed(project_id: str | None) -> None:
    """Recheck project classification immediately before external automation."""
    if project_id is None:
        return
    with get_session() as db:
        policy = _policy(db, project_id, create=True)
        if policy.data_classification != "public":
            raise repo.LabValidationError(
                "project-scoped external headless automation requires public classification"
            )
        db.commit()


def complete_automation(automation_id: str, output: str) -> AutomationRun:
    with get_session() as db:
        automation = _require(db, AutomationRun, automation_id, "automation plan")
        if automation.status != "running":
            raise repo.LabConflictError("automation is not running")
        automation.status = "completed"
        automation.output = output
        automation.error = None
        automation.completed_at = _now()
        db.add(automation)
        _record(db, "automation.completed", "automation", automation.id)
        db.commit()
        db.refresh(automation)
        return automation


def fail_automation(automation_id: str, message: str, output: str = "") -> AutomationRun:
    with get_session() as db:
        automation = _require(db, AutomationRun, automation_id, "automation plan")
        if automation.status not in {"approved", "running"}:
            return automation
        automation.status = "failed"
        automation.output = output
        automation.error = message[:500]
        automation.completed_at = _now()
        db.add(automation)
        _record(
            db,
            "automation.failed",
            "automation",
            automation.id,
            details={"error": automation.error},
        )
        db.commit()
        db.refresh(automation)
        return automation
