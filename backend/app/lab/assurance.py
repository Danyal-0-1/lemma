"""Frozen research protocols and evidence-based acceptance gates.

Exploratory task execution remains available without a protocol.  This module gates
only the stronger claim that a completed task is *accepted research*: the protocol
must have been approved before that run began, the result must be human-reviewed,
and every active claim must have intact support with no unresolved contradiction.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from app.db import get_session
from app.lab import repo
from app.lab.integrity import (
    MAX_TASK_SOURCE_CONTEXT,
    MAX_TASK_SOURCE_COUNT,
    agent_system_prompt,
    canonical_sha256,
    model_call_provenance_sha256,
    project_execution_payload,
    protocol_content_sha256,
    protocol_execution_payload,
    protocol_hash_payload,
    source_execution_payload,
    task_input_payload,
    task_user_prompt,
)
from app.models import (
    ActivityRecord,
    ClaimEvidence,
    Finding,
    FindingReview,
    LabRun,
    ModelCall,
    ResearchAssuranceAcceptance,
    ResearchClaim,
    ResearchProject,
    ResearchProtocol,
    ResearchTask,
    SourceDocument,
    SourceExcerpt,
    TaskResult,
    TaskSourceLink,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


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
) -> None:
    db.add(
        ActivityRecord(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            run_id=run_id,
            details=details or {},
        )
    )


def create_protocol(project_id: str, values: dict[str, Any]) -> ResearchProtocol:
    """Create the next immutable draft; an existing draft must be resolved first."""
    with get_session() as db:
        project = _require(db, ResearchProject, project_id, "project")
        draft = db.exec(
            select(ResearchProtocol).where(
                ResearchProtocol.project_id == project_id,
                ResearchProtocol.status == "draft",
            )
        ).first()
        if draft is not None:
            raise repo.LabConflictError(
                "this project already has a draft protocol; approve it before creating a revision"
            )
        latest = db.exec(
            select(ResearchProtocol)
            .where(ResearchProtocol.project_id == project_id)
            .order_by(ResearchProtocol.version.desc())
        ).first()
        version = int(
            db.exec(
                select(func.coalesce(func.max(ResearchProtocol.version), 0)).where(
                    ResearchProtocol.project_id == project_id
                )
            ).one()
        ) + 1
        protocol_values = {
            **values,
            "project_id": project_id,
            "version": version,
            "supersedes_id": latest.id if latest is not None else None,
            "project_objective": project.objective,
            "limitations": values.get("limitations", []),
            "created_by": values.get("created_by", "founder"),
        }
        protocol = ResearchProtocol(
            **protocol_values,
            content_sha256=protocol_content_sha256(protocol_values),
        )
        db.add(protocol)
        _record(
            db,
            "protocol.created",
            "protocol",
            protocol.id,
            details={"project_id": project_id, "version": version},
        )
        db.commit()
        db.refresh(protocol)
        return protocol


def list_protocols(project_id: str) -> list[ResearchProtocol]:
    with get_session() as db:
        _require(db, ResearchProject, project_id, "project")
        return list(
            db.exec(
                select(ResearchProtocol)
                .where(ResearchProtocol.project_id == project_id)
                .order_by(ResearchProtocol.version.desc())
            )
        )


def approve_protocol(protocol_id: str, approved_by: str) -> ResearchProtocol:
    """Freeze a draft and supersede the prior approved version atomically."""
    with get_session() as db:
        protocol = _require(db, ResearchProtocol, protocol_id, "protocol")
        if protocol.status == "approved":
            return protocol
        if protocol.status != "draft":
            raise repo.LabConflictError("only a draft protocol can be approved")
        latest = db.exec(
            select(ResearchProtocol)
            .where(ResearchProtocol.project_id == protocol.project_id)
            .order_by(ResearchProtocol.version.desc())
        ).first()
        if latest is None or latest.id != protocol.id:
            raise repo.LabConflictError("only the latest protocol version can be approved")
        project = _require(db, ResearchProject, protocol.project_id, "project")
        if project.objective != protocol.project_objective:
            raise repo.LabConflictError(
                "the project objective changed after this draft was created; create a new revision"
            )
        if protocol_content_sha256(protocol) != protocol.content_sha256:
            raise repo.LabConflictError("protocol integrity check failed")
        previous = list(
            db.exec(
                select(ResearchProtocol).where(
                    ResearchProtocol.project_id == protocol.project_id,
                    ResearchProtocol.status == "approved",
                )
            )
        )
        for row in previous:
            row.status = "superseded"
            db.add(row)
        protocol.status = "approved"
        protocol.approved_by = approved_by
        protocol.approved_at = _now()
        db.add(protocol)
        _record(
            db,
            "protocol.approved",
            "protocol",
            protocol.id,
            details={"version": protocol.version, "approved_by": approved_by},
        )
        db.commit()
        db.refresh(protocol)
        return protocol


def withdraw_protocol(protocol_id: str, withdrawn_by: str, note: str = "") -> ResearchProtocol:
    """Withdraw a draft that should not be approved, preserving it for audit."""
    with get_session() as db:
        protocol = _require(db, ResearchProtocol, protocol_id, "protocol")
        if protocol.status != "draft":
            raise repo.LabConflictError("only a draft protocol can be withdrawn")
        protocol.status = "withdrawn"
        db.add(protocol)
        _record(
            db,
            "protocol.withdrawn",
            "protocol",
            protocol.id,
            details={
                "project_id": protocol.project_id,
                "version": protocol.version,
                "withdrawn_by": withdrawn_by,
                "note": note,
            },
        )
        db.commit()
        db.refresh(protocol)
        return protocol


def _check(
    checks: list[dict[str, object]],
    issues: list[str],
    code: str,
    passed: bool,
    success: str,
    failure: str,
) -> None:
    message = success if passed else failure
    checks.append({"code": code, "passed": passed, "message": message})
    if not passed:
        issues.append(failure)


def _source_integrity(source: SourceDocument) -> bool:
    return hashlib.sha256(source.content.encode("utf-8")).hexdigest() == source.content_sha256


def _excerpt_integrity(excerpt: SourceExcerpt, source: SourceDocument) -> bool:
    start = excerpt.start_offset
    end = excerpt.end_offset
    return (
        hashlib.sha256(excerpt.quote.encode("utf-8")).hexdigest() == excerpt.quote_sha256
        and start is not None
        and end is not None
        and 0 <= start < end <= len(source.content)
        and source.content[start:end] == excerpt.quote
        and excerpt.project_id == source.project_id
    )


def _latest_protocols(
    db: Session, project_id: str
) -> tuple[ResearchProtocol | None, ResearchProtocol | None]:
    protocols = list(
        db.exec(
            select(ResearchProtocol)
            .where(ResearchProtocol.project_id == project_id)
            .order_by(ResearchProtocol.version.desc())
        )
    )
    latest = next((row for row in protocols if row.status != "withdrawn"), None)
    approved = next((row for row in protocols if row.status == "approved"), None)
    return latest, approved


def _latest_completed_run(db: Session, task_id: str) -> LabRun | None:
    return db.exec(
        select(LabRun)
        .where(LabRun.task_id == task_id, LabRun.status == "completed")
        .order_by(LabRun.started_at.desc())
    ).first()


def _assess(db: Session, task: ResearchTask) -> dict[str, Any]:
    project = _require(db, ResearchProject, task.project_id, "project")
    checks: list[dict[str, object]] = []
    issues: list[str] = []
    all_source_links = list(
        db.exec(
            select(TaskSourceLink)
            .where(TaskSourceLink.task_id == task.id)
            .order_by(TaskSourceLink.created_at, TaskSourceLink.id)
        )
    )
    # Match run creation exactly: archived sources are excluded before the stable
    # source-count cap, then the total prompt text is bounded by the context cap.
    active_candidate_links: list[TaskSourceLink] = []
    sources_by_link: dict[str, SourceDocument | None] = {}
    for link in all_source_links:
        source = db.get(SourceDocument, link.source_id)
        sources_by_link[link.id] = source
        if (
            source is not None
            and source.status == "active"
            and len(active_candidate_links) < MAX_TASK_SOURCE_COUNT
        ):
            active_candidate_links.append(link)
    active_candidate_ids = {link.id for link in active_candidate_links}
    valid_source_links: list[TaskSourceLink] = []
    invalid_packet_refs: list[dict[str, str]] = []
    excluded_packet_refs: list[dict[str, str]] = []
    packet_entries: list[dict[str, object]] = []
    current_source_packet: list[dict[str, Any]] = []
    remaining_source_chars = MAX_TASK_SOURCE_CONTEXT
    for link in all_source_links:
        source = sources_by_link[link.id]
        reason: str | None = None
        usable = False
        if source is None:
            reason = "missing_source"
            invalid_packet_refs.append({"link_id": link.id, "reason": reason})
        elif source.status != "active":
            reason = "source_archived"
            excluded_packet_refs.append({"link_id": link.id, "reason": reason})
        elif link.id not in active_candidate_ids:
            reason = "outside_runtime_limit"
            excluded_packet_refs.append({"link_id": link.id, "reason": reason})
        elif source.project_id != task.project_id:
            reason = "different_project"
            invalid_packet_refs.append({"link_id": link.id, "reason": reason})
        elif not _source_integrity(source):
            reason = "source_integrity"
            invalid_packet_refs.append({"link_id": link.id, "reason": reason})
        elif remaining_source_chars <= 0:
            reason = "outside_runtime_context_limit"
            excluded_packet_refs.append({"link_id": link.id, "reason": reason})
        else:
            usable = True
            valid_source_links.append(link)
            content = source.content[:remaining_source_chars]
            current_source_packet.append(source_execution_payload(link, source, content))
            remaining_source_chars -= len(content)
        packet_entries.append(
            {
                "link_id": link.id,
                "source_id": link.source_id,
                "purpose": link.purpose,
                "created_at": link.created_at.isoformat(),
                "source_status": source.status if source is not None else "missing",
                "source_sha256": source.content_sha256 if source is not None else None,
                "usable": usable,
                "exclusion_reason": reason,
            }
        )
    packet_source_ids = {str(entry["source_id"]) for entry in current_source_packet}
    packet_by_source_id = {
        str(entry["source_id"]): entry for entry in current_source_packet
    }
    _check(
        checks,
        issues,
        "source_packet",
        bool(current_source_packet),
        "The task has at least one usable source in its runtime packet.",
        "Link at least one active, intact source to the task before acceptance.",
    )
    _check(
        checks,
        issues,
        "source_packet_integrity",
        not invalid_packet_refs,
        "The runtime source packet contains no invalid source references.",
        "Repair invalid or corrupted source references in the task packet.",
    )
    run = _latest_completed_run(db, task.id)
    _check(
        checks,
        issues,
        "completed_run",
        run is not None,
        "A completed run is available.",
        "Run the task to completion before accepting its research.",
    )
    run_input_current = (
        run is not None
        and bool(run.input_snapshot)
        and run.input_sha256 is not None
        and canonical_sha256(run.input_snapshot) == run.input_sha256
        and run.input_snapshot.get("task") == task_input_payload(task)
        and run.input_snapshot.get("project") == project_execution_payload(project)
        and isinstance(run.input_snapshot.get("agent"), dict)
        and run.input_snapshot["agent"].get("id") == task.assigned_agent_id
    )
    _check(
        checks,
        issues,
        "run_input_snapshot",
        run_input_current,
        "Current task inputs match the immutable run snapshot.",
        "Task inputs changed after this run; run the current task again.",
    )
    source_packet_bound_to_run = (
        run is not None
        and run.input_snapshot.get("source_packet") == current_source_packet
    )
    _check(
        checks,
        issues,
        "source_packet_run_binding",
        source_packet_bound_to_run,
        "The accepted run used the exact current bounded source packet.",
        "The source packet changed after this run; run the task again.",
    )
    source_packet_precedes_run = (
        bool(current_source_packet)
        and run is not None
        and all(_aware(link.created_at) <= _aware(run.started_at) for link in valid_source_links)
    )
    _check(
        checks,
        issues,
        "source_packet_before_run",
        source_packet_precedes_run,
        "The source packet was fixed before the accepted run began.",
        "Re-run the task after finalizing its source packet.",
    )

    latest_protocol, protocol = _latest_protocols(db, task.project_id)
    _check(
        checks,
        issues,
        "approved_protocol",
        protocol is not None,
        "An approved research protocol is available.",
        "Approve a research protocol before accepting this task.",
    )
    protocol_integrity = (
        protocol is not None and protocol_content_sha256(protocol) == protocol.content_sha256
    )
    _check(
        checks,
        issues,
        "protocol_integrity",
        protocol_integrity,
        "The approved protocol matches its frozen hash.",
        "The approved protocol failed its integrity check.",
    )
    scope_current = protocol is not None and protocol.project_objective == project.objective
    _check(
        checks,
        issues,
        "protocol_scope",
        scope_current,
        "The project objective still matches the approved protocol.",
        "The project objective drifted; create and approve a new protocol revision.",
    )
    no_pending_revision = (
        protocol is not None and latest_protocol is not None and latest_protocol.id == protocol.id
    )
    _check(
        checks,
        issues,
        "protocol_revision",
        no_pending_revision,
        "The approved protocol is the latest revision.",
        "A newer draft protocol is pending approval.",
    )
    protocol_precedes_run = (
        protocol is not None
        and protocol.approved_at is not None
        and run is not None
        and _aware(protocol.approved_at) <= _aware(run.started_at)
    )
    _check(
        checks,
        issues,
        "protocol_before_run",
        protocol_precedes_run,
        "The protocol was approved before the accepted run began.",
        "Re-run the task after approving the current protocol.",
    )
    protocol_bound_to_run = (
        run is not None
        and protocol is not None
        and run.input_snapshot.get("protocol") == protocol_execution_payload(protocol)
    )
    _check(
        checks,
        issues,
        "protocol_run_binding",
        protocol_bound_to_run,
        "The accepted run used this exact frozen protocol.",
        "Re-run the task with the current approved protocol bound to its prompt.",
    )

    results: list[TaskResult] = []
    if run is not None:
        results = list(
            db.exec(
                select(TaskResult)
                .where(
                    TaskResult.task_id == task.id, TaskResult.run_id == run.id
                )
                .order_by(TaskResult.created_at, TaskResult.id)
            )
        )
    result_ids = [result.id for result in results]
    frozen_agent = run.input_snapshot.get("agent") if run is not None else None
    frozen_agent_id = frozen_agent.get("id") if isinstance(frozen_agent, dict) else None
    frozen_model = frozen_agent.get("model") if isinstance(frozen_agent, dict) else None
    task_results_bound = bool(results) and all(
        result.project_id == task.project_id
        and result.task_id == task.id
        and result.agent_id == frozen_agent_id
        for result in results
    )
    _check(
        checks,
        issues,
        "task_result",
        bool(results),
        "The completed run has a persisted task result.",
        "The completed run has no persisted task result.",
    )
    _check(
        checks,
        issues,
        "task_result_binding",
        task_results_bound,
        "Every task result is bound to the run's frozen task and agent.",
        "A task result does not match the run's frozen task or agent.",
    )
    model_calls: list[ModelCall] = []
    if run is not None:
        model_calls = list(
            db.exec(
                select(ModelCall)
                .where(
                    ModelCall.run_id == run.id,
                    ModelCall.stage == "task_result",
                    ModelCall.status == "completed",
                )
                .order_by(ModelCall.created_at, ModelCall.id)
            )
        )
    expected_user_prompt = task_user_prompt(run.input_snapshot) if run is not None else None
    expected_system_prompt = (
        agent_system_prompt(
            frozen_agent,
            str(run.input_snapshot.get("task", {}).get("objective") or ""),
        )
        if run is not None and isinstance(frozen_agent, dict)
        else None
    )

    def call_matches_run(call: ModelCall) -> bool:
        return bool(
            call.project_id == task.project_id
            and call.agent_id == frozen_agent_id
            and call.model == frozen_model
            and call.system_prompt == expected_system_prompt
            and call.user_prompt == expected_user_prompt
            and call.completed_at is not None
        )

    model_call_provenance_ok = len(model_calls) == 1 and call_matches_run(model_calls[0])
    _check(
        checks,
        issues,
        "model_call_provenance",
        model_call_provenance_ok,
        "The accepted run has complete prompt and model-call provenance.",
        "The completed run lacks a complete task-result model-call record.",
    )
    findings = (
        list(
            db.exec(
                select(Finding)
                .where(Finding.result_id.in_(result_ids))
                .order_by(Finding.created_at, Finding.id)
            )
        )
        if result_ids
        else []
    )
    _check(
        checks,
        issues,
        "findings_present",
        bool(findings),
        "The completed run produced reviewable findings.",
        "The completed run has no reviewable finding.",
    )

    finding_snapshots: list[dict[str, Any]] = []
    claims: list[ResearchClaim] = []
    unreviewed_findings: list[str] = []
    findings_without_claims: list[str] = []
    for finding in findings:
        review = db.exec(
            select(FindingReview)
            .where(FindingReview.finding_id == finding.id)
            .order_by(FindingReview.created_at.desc(), FindingReview.id.desc())
        ).first()
        if review is None or review.decision != "accepted":
            unreviewed_findings.append(finding.id)
        finding_claims = list(
            db.exec(
                select(ResearchClaim)
                .where(
                    ResearchClaim.finding_id == finding.id,
                    ResearchClaim.status != "retired",
                )
                .order_by(ResearchClaim.created_at, ResearchClaim.id)
            )
        )
        if not finding_claims:
            findings_without_claims.append(finding.id)
        claims.extend(finding_claims)
        finding_snapshots.append(
            {
                "id": finding.id,
                "result_id": finding.result_id,
                "content_sha256": hashlib.sha256(finding.content.encode("utf-8")).hexdigest(),
                "review": (
                    {
                        "id": review.id,
                        "decision": review.decision,
                        "reviewer": review.reviewer,
                        "notes": review.notes,
                    }
                    if review is not None
                    else None
                ),
            }
        )

    _check(
        checks,
        issues,
        "findings_reviewed",
        bool(findings) and not unreviewed_findings,
        "Every finding has a current accepted human review.",
        "Every finding must have a latest review decision of accepted.",
    )
    _check(
        checks,
        issues,
        "claims_present",
        bool(claims) and not findings_without_claims,
        "Every finding is expressed as at least one active claim.",
        "Add at least one active claim for every finding.",
    )
    unaccepted_claim_ids = [claim.id for claim in claims if claim.status != "accepted"]
    _check(
        checks,
        issues,
        "claims_accepted",
        bool(claims) and not unaccepted_claim_ids,
        "Every active claim has an explicit accepted status.",
        "Accept each evidence-reviewed claim before accepting the task.",
    )

    claim_results: list[dict[str, Any]] = []
    claim_snapshots: list[dict[str, Any]] = []
    supported_count = 0
    contradicted_count = 0
    invalid_evidence_count = 0
    disputed_count = 0
    supporting_source_ids: set[str] = set()
    unseen_supporting_evidence_ids: list[str] = []
    for claim in claims:
        links = list(
            db.exec(
                select(ClaimEvidence)
                .where(ClaimEvidence.claim_id == claim.id)
                .order_by(ClaimEvidence.created_at, ClaimEvidence.id)
            )
        )
        link_snapshots: list[dict[str, Any]] = []
        supporting_evidence_ids: list[str] = []
        contradicting_evidence_ids: list[str] = []
        has_support = False
        has_contradiction = False
        claim_integrity = True
        for link in links:
            excerpt = db.get(SourceExcerpt, link.excerpt_id)
            source = db.get(SourceDocument, excerpt.source_id) if excerpt is not None else None
            intact = (
                excerpt is not None
                and source is not None
                and source.project_id == task.project_id
                and source.status == "active"
                and _source_integrity(source)
                and _excerpt_integrity(excerpt, source)
            )
            if not intact:
                claim_integrity = False
                invalid_evidence_count += 1
            if link.stance == "supports" and intact:
                has_support = True
                supporting_source_ids.add(source.id)
                supporting_evidence_ids.append(link.id)
                packet_entry = packet_by_source_id.get(source.id)
                if (
                    packet_entry is None
                    or excerpt.end_offset is None
                    or excerpt.end_offset > int(packet_entry["included_chars"])
                ):
                    unseen_supporting_evidence_ids.append(link.id)
            if link.stance == "contradicts":
                has_contradiction = True
                contradicting_evidence_ids.append(link.id)
            link_snapshots.append(
                {
                    "id": link.id,
                    "stance": link.stance,
                    "note": link.note,
                    "excerpt_id": link.excerpt_id,
                    "excerpt_sha256": excerpt.quote_sha256 if excerpt is not None else None,
                    "source_id": source.id if source is not None else None,
                    "source_sha256": source.content_sha256 if source is not None else None,
                    "intact": intact,
                }
            )
        if has_support:
            supported_count += 1
        if has_contradiction:
            contradicted_count += 1
        if claim.status == "disputed":
            disputed_count += 1
        claim_result = {
            "claim_id": claim.id,
            "statement": claim.statement,
            "status": claim.status,
            "supported": has_support,
            "contradicted": has_contradiction,
            "evidence_count": len(links),
            "evidence_ids": [link.id for link in links],
            "supporting_evidence_ids": supporting_evidence_ids,
            "contradicting_evidence_ids": contradicting_evidence_ids,
            "integrity_ok": claim_integrity,
        }
        claim_results.append(claim_result)
        claim_snapshots.append(
            {
                "id": claim.id,
                "finding_id": claim.finding_id,
                "statement": claim.statement,
                "confidence": claim.confidence,
                "status": claim.status,
                "evidence": link_snapshots,
            }
        )

    total_claims = len(claims)
    unsupported_count = total_claims - supported_count
    coverage_percent = round((supported_count / total_claims) * 100, 1) if total_claims else 0.0
    _check(
        checks,
        issues,
        "claim_coverage",
        total_claims > 0 and unsupported_count == 0,
        "Every active claim has exact supporting evidence.",
        "Every active claim must link to at least one intact supporting excerpt.",
    )
    _check(
        checks,
        issues,
        "contradictions_resolved",
        total_claims > 0 and contradicted_count == 0 and disputed_count == 0,
        "No active claim has unresolved contradictory evidence.",
        "Resolve contradicted or disputed claims before acceptance.",
    )
    _check(
        checks,
        issues,
        "evidence_integrity",
        total_claims > 0 and invalid_evidence_count == 0,
        "All linked evidence matches its captured source hashes and offsets.",
        "One or more evidence links failed source or excerpt integrity checks.",
    )
    unlinked_supporting_source_ids = sorted(supporting_source_ids - packet_source_ids)
    _check(
        checks,
        issues,
        "evidence_in_source_packet",
        total_claims > 0
        and not unlinked_supporting_source_ids
        and not unseen_supporting_evidence_ids,
        "Every supporting excerpt was visible in the task's bounded source packet.",
        "Re-run with every supporting excerpt inside the bounded task source packet.",
    )

    snapshot = {
        "project_id": project.id,
        "project_objective": project.objective,
        "task": task_input_payload(task) | {"id": task.id},
        "run": (
            {
                "id": run.id,
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "input_snapshot": run.input_snapshot,
                "input_sha256": run.input_sha256,
            }
            if run is not None
            else None
        ),
        "protocol": protocol_hash_payload(protocol)
        | {
            "id": protocol.id,
            "status": protocol.status,
            "content_sha256": protocol.content_sha256,
            "approved_by": protocol.approved_by,
            "approved_at": protocol.approved_at.isoformat() if protocol.approved_at else None,
        }
        if protocol is not None
        else None,
        "latest_protocol": (
            {
                "id": latest_protocol.id,
                "version": latest_protocol.version,
                "status": latest_protocol.status,
                "content_sha256": latest_protocol.content_sha256,
            }
            if latest_protocol is not None
            else None
        ),
        "source_packet": packet_entries,
        "task_results": [
            {
                "id": result.id,
                "agent_id": result.agent_id,
                "content_sha256": hashlib.sha256(result.content.encode("utf-8")).hexdigest(),
                "created_at": result.created_at.isoformat(),
            }
            for result in results
        ],
        "model_calls": [
            {
                "id": call.id,
                "provenance_sha256": model_call_provenance_sha256(call),
            }
            for call in model_calls
        ],
        "findings": finding_snapshots,
        "claims": claim_snapshots,
    }
    snapshot_sha256 = canonical_sha256(snapshot)
    latest_acceptance = db.exec(
        select(ResearchAssuranceAcceptance)
        .where(ResearchAssuranceAcceptance.task_id == task.id)
        .order_by(
            ResearchAssuranceAcceptance.created_at.desc(),
            ResearchAssuranceAcceptance.id.desc(),
        )
    ).first()
    ready = all(bool(check["passed"]) for check in checks)
    accepted = (
        ready
        and latest_acceptance is not None
        and latest_acceptance.snapshot_sha256 == snapshot_sha256
        and canonical_sha256(latest_acceptance.snapshot_json)
        == latest_acceptance.snapshot_sha256
        and run is not None
        and latest_acceptance.run_id == run.id
        and protocol is not None
        and latest_acceptance.protocol_id == protocol.id
        and latest_acceptance.confirmed_criteria == protocol.acceptance_criteria
    )
    if accepted:
        status = "accepted"
    elif latest_acceptance is not None:
        status = "stale"
    elif ready:
        status = "ready"
    else:
        status = "blocked"

    return {
        "task_id": task.id,
        "project_id": task.project_id,
        "run_id": run.id if run is not None else None,
        "status": status,
        "ready": ready,
        "snapshot_sha256": snapshot_sha256,
        "snapshot": snapshot,
        "protocol": protocol.model_dump(mode="json") if protocol is not None else None,
        "latest_protocol": (
            latest_protocol.model_dump(mode="json") if latest_protocol is not None else None
        ),
        "coverage": {
            "total_claims": total_claims,
            "supported_claims": supported_count,
            "unsupported_claims": unsupported_count,
            "contradicted_claims": contradicted_count,
            "coverage_percent": coverage_percent,
            "unique_supporting_sources": len(supporting_source_ids),
            "source_packet_count": len(valid_source_links),
            "source_packet_candidate_count": len(active_candidate_links),
            "source_packet_link_count": len(all_source_links),
            "invalid_source_packet_refs": invalid_packet_refs,
            "excluded_source_packet_refs": excluded_packet_refs,
            "unlinked_supporting_source_ids": unlinked_supporting_source_ids,
            "unseen_supporting_evidence_ids": unseen_supporting_evidence_ids,
        },
        "checks": checks,
        "issues": issues,
        "claim_results": claim_results,
        "acceptance": (
            {
                key: value
                for key, value in latest_acceptance.model_dump(mode="json").items()
                if key != "snapshot_json"
            }
            if latest_acceptance is not None
            else None
        ),
    }


def assess_task(task_id: str) -> dict[str, Any]:
    with get_session() as db:
        task = _require(db, ResearchTask, task_id, "task")
        return _assess(db, task)


def accept_task(task_id: str, values: dict[str, Any]) -> dict[str, Any]:
    """Accept the exact current snapshot, or explain why the gate is blocked."""
    with get_session() as db:
        task = _require(db, ResearchTask, task_id, "task")
        assessment = _assess(db, task)
        if not assessment["ready"]:
            issues = assessment["issues"]
            detail = "; ".join(str(issue) for issue in issues[:3])
            raise repo.LabConflictError(f"research assurance gate is blocked: {detail}")
        protocol = assessment["protocol"]
        run_id = assessment["run_id"]
        if protocol is None or run_id is None:  # guarded by ready; defensive for corrupt rows
            raise repo.LabConflictError("research assurance gate has no protocol or completed run")
        if values.get("confirmed_criteria") != protocol["acceptance_criteria"]:
            raise repo.LabConflictError(
                "confirm every current protocol acceptance criterion in protocol order"
            )
        if assessment["status"] == "accepted":
            return assessment
        acceptance = ResearchAssuranceAcceptance(
            project_id=task.project_id,
            task_id=task.id,
            run_id=run_id,
            protocol_id=protocol["id"],
            snapshot_sha256=assessment["snapshot_sha256"],
            snapshot_json=assessment["snapshot"],
            **values,
        )
        db.add(acceptance)
        _record(
            db,
            "research.accepted",
            "task",
            task.id,
            run_id=run_id,
            details={
                "protocol_id": protocol["id"],
                "snapshot_sha256": assessment["snapshot_sha256"],
                "reviewer": acceptance.reviewer,
            },
        )
        try:
            db.commit()
        except IntegrityError:
            # Concurrent local clients accepting the same immutable snapshot are
            # idempotent under the database uniqueness constraint.
            db.rollback()
            task = _require(db, ResearchTask, task_id, "task")
        return _assess(db, task)


def list_acceptances(project_id: str) -> list[ResearchAssuranceAcceptance]:
    with get_session() as db:
        _require(db, ResearchProject, project_id, "project")
        return list(
            db.exec(
                select(ResearchAssuranceAcceptance)
                .where(ResearchAssuranceAcceptance.project_id == project_id)
                .order_by(ResearchAssuranceAcceptance.created_at, ResearchAssuranceAcceptance.id)
            )
        )
