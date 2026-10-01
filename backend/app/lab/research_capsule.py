"""Deterministic, offline-verifiable research capsule export and CLI.

The SHA-256 envelope detects corruption and accidental edits.  It is deliberately
not described as a signature: authenticity requires a separately trusted signing
key, while this verifier needs no network, provider credentials, or database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.lab.integrity import (
    MAX_TASK_SOURCE_CONTEXT,
    MAX_TASK_SOURCE_COUNT,
    agent_system_prompt,
    canonical_json,
    canonical_sha256,
    model_call_provenance_sha256,
    project_execution_payload,
    protocol_content_sha256,
    protocol_execution_payload,
    protocol_hash_payload,
    task_input_payload,
    task_user_prompt,
)

CAPSULE_FORMAT = "lemma.research-capsule.v1"
HASH_ALGORITHM = "sha256"
MAX_CAPSULE_BYTES = 50_000_000
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _sorted_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda row: str(row.get("id", "")))


def build_capsule(project_id: str) -> dict[str, Any]:
    """Build a stable JSON envelope containing research inputs, outputs, and approvals."""
    # Keep imports used only for export out of the offline verification path.  The
    # installed CLI can verify an artifact without opening or initializing Lemma's DB.
    from sqlmodel import select

    from app.db import get_session
    from app.lab import repo, workflows
    from app.lab.assurance import assess_task, list_acceptances, list_protocols
    from app.models import ActivityRecord, ModelCall, ResearchProject

    # Persist the default policy once so repeated exports do not manufacture new
    # default timestamps in an otherwise unchanged manifest.
    workflows.get_policy(project_id)
    dossier = workflows.project_dossier(project_id)
    for key, value in tuple(dossier.items()):
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            dossier[key] = _sorted_records(value)

    protocols = [row.model_dump(mode="json") for row in list_protocols(project_id)]
    acceptances = [row.model_dump(mode="json") for row in list_acceptances(project_id)]
    with get_session() as db:
        project = db.get(ResearchProject, project_id)
        if project is None:
            raise repo.LabNotFoundError("project not found")
        model_calls = list(
            db.exec(
                select(ModelCall)
                .where(ModelCall.project_id == project_id)
                .order_by(ModelCall.id)
            )
        )
        entity_ids = {project_id}
        for value in dossier.values():
            if isinstance(value, list):
                entity_ids.update(
                    str(record["id"])
                    for record in value
                    if isinstance(record, dict) and "id" in record
                )
        entity_ids.update(row["id"] for row in protocols)
        entity_ids.update(row["id"] for row in acceptances)
        run_ids = {str(row["id"]) for row in dossier["runs"]}
        activity = [
            row
            for row in db.exec(
                select(ActivityRecord).order_by(
                    ActivityRecord.created_at, ActivityRecord.id
                )
            )
            if row.entity_id in entity_ids or (row.run_id is not None and row.run_id in run_ids)
        ]

    task_assurance = [assess_task(task["id"]) for task in dossier["tasks"]]
    manifest = {
        **dossier,
        "protocols": _sorted_records(protocols),
        "assurance_acceptances": _sorted_records(acceptances),
        "task_assurance": sorted(task_assurance, key=lambda row: row["task_id"]),
        "model_calls": _sorted_records(
            [row.model_dump(mode="json") for row in model_calls]
        ),
        "activity": _sorted_records([row.model_dump(mode="json") for row in activity]),
    }
    capsule = {
        "format": CAPSULE_FORMAT,
        "hash_algorithm": HASH_ALGORITHM,
        "project_id": project_id,
        "manifest": manifest,
        "manifest_sha256": canonical_sha256(manifest),
    }
    if len(canonical_json(capsule)) > MAX_CAPSULE_BYTES:
        raise repo.LabPayloadTooLargeError(
            f"research capsule exceeds the {MAX_CAPSULE_BYTES}-byte export limit"
        )
    return capsule


def _add_check(
    checks: list[dict[str, object]],
    errors: list[str],
    code: str,
    passed: bool,
    success: str,
    failure: str,
) -> None:
    checks.append({"code": code, "passed": passed, "message": success if passed else failure})
    if not passed:
        errors.append(failure)


def _unique_index(
    records: Any,
    label: str,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list):
        errors.append(f"manifest field {label!r} must be a list")
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            errors.append(f"manifest field {label!r} contains a record without a string id")
            continue
        row_id = record["id"]
        if row_id in indexed:
            errors.append(f"manifest field {label!r} contains duplicate id {row_id}")
        indexed[row_id] = record
    return indexed


def verify_capsule(capsule: dict[str, Any]) -> dict[str, Any]:
    """Verify an untrusted capsule without touching the database or network."""
    checks: list[dict[str, object]] = []
    errors: list[str] = []
    manifest = capsule.get("manifest")
    format_ok = capsule.get("format") == CAPSULE_FORMAT
    _add_check(
        checks,
        errors,
        "format",
        format_ok,
        "Research capsule format is supported.",
        "Unsupported research capsule format.",
    )
    algorithm_ok = capsule.get("hash_algorithm") == HASH_ALGORITHM
    _add_check(
        checks,
        errors,
        "algorithm",
        algorithm_ok,
        "Capsule hash algorithm is supported.",
        "Unsupported capsule hash algorithm.",
    )
    manifest_ok = isinstance(manifest, dict)
    _add_check(
        checks,
        errors,
        "manifest",
        manifest_ok,
        "Capsule manifest is a JSON object.",
        "Capsule manifest must be an object.",
    )
    expected = capsule.get("manifest_sha256")
    computed = canonical_sha256(manifest) if manifest_ok else ""
    digest_ok = isinstance(expected, str) and expected == computed
    _add_check(
        checks,
        errors,
        "manifest_digest",
        digest_ok,
        "Manifest SHA-256 matches.",
        "Manifest SHA-256 does not match.",
    )

    project_id = capsule.get("project_id")
    project = manifest.get("project") if manifest_ok else None
    project_ok = (
        isinstance(project_id, str)
        and isinstance(project, dict)
        and project.get("id") == project_id
    )
    _add_check(
        checks,
        errors,
        "project_identity",
        project_ok,
        "Project identity is consistent.",
        "Project identity is inconsistent.",
    )

    sources = _unique_index(manifest.get("sources") if manifest_ok else None, "sources", errors)
    excerpts = _unique_index(
        manifest.get("excerpts") if manifest_ok else None, "excerpts", errors
    )
    claims = _unique_index(manifest.get("claims") if manifest_ok else None, "claims", errors)
    findings = _unique_index(
        manifest.get("findings") if manifest_ok else None, "findings", errors
    )
    results = _unique_index(manifest.get("results") if manifest_ok else None, "results", errors)
    evidence = _unique_index(
        manifest.get("claim_evidence") if manifest_ok else None,
        "claim_evidence",
        errors,
    )
    protocols = _unique_index(
        manifest.get("protocols") if manifest_ok else None, "protocols", errors
    )
    tasks = _unique_index(manifest.get("tasks") if manifest_ok else None, "tasks", errors)
    runs = _unique_index(manifest.get("runs") if manifest_ok else None, "runs", errors)
    source_links = _unique_index(
        manifest.get("source_links") if manifest_ok else None, "source_links", errors
    )
    model_calls = _unique_index(
        manifest.get("model_calls") if manifest_ok else None, "model_calls", errors
    )
    acceptances = _unique_index(
        manifest.get("assurance_acceptances") if manifest_ok else None,
        "assurance_acceptances",
        errors,
    )
    reviews = _unique_index(
        manifest.get("finding_reviews") if manifest_ok else None,
        "finding_reviews",
        errors,
    )
    dependencies = _unique_index(
        manifest.get("dependencies") if manifest_ok else None, "dependencies", errors
    )
    meetings = _unique_index(
        manifest.get("meetings") if manifest_ok else None, "meetings", errors
    )
    outcomes = _unique_index(
        manifest.get("outcomes") if manifest_ok else None, "outcomes", errors
    )
    actions = _unique_index(
        manifest.get("actions") if manifest_ok else None, "actions", errors
    )
    trace_links = _unique_index(
        manifest.get("trace_links") if manifest_ok else None, "trace_links", errors
    )
    activity = _unique_index(
        manifest.get("activity") if manifest_ok else None, "activity", errors
    )

    scoped_collections = {
        "sources": sources,
        "excerpts": excerpts,
        "source_links": source_links,
        "tasks": tasks,
        "results": results,
        "findings": findings,
        "finding_reviews": reviews,
        "claims": claims,
        "claim_evidence": evidence,
        "dependencies": dependencies,
        "meetings": meetings,
        "outcomes": outcomes,
        "actions": actions,
        "runs": runs,
        "trace_links": trace_links,
        "protocols": protocols,
        "assurance_acceptances": acceptances,
        "model_calls": model_calls,
    }
    project_scope_ok = True
    policy = manifest.get("policy") if manifest_ok else None
    if not isinstance(policy, dict) or policy.get("project_id") != project_id:
        project_scope_ok = False
        errors.append("project policy belongs to another project or is malformed")
    for label, records in scoped_collections.items():
        for row in records.values():
            if row.get("project_id") != project_id:
                project_scope_ok = False
                errors.append(f"{label} record {row.get('id')} belongs to another project")
    task_assurance = manifest.get("task_assurance") if manifest_ok else None
    if not isinstance(task_assurance, list) or not all(
        isinstance(row, dict)
        and row.get("project_id") == project_id
        and row.get("task_id") in tasks
        for row in task_assurance
    ):
        project_scope_ok = False
        errors.append("task assurance rows are malformed or cross project scope")
    _add_check(
        checks,
        errors,
        "project_scope",
        project_scope_ok,
        "Every exported research record stays within the capsule project.",
        "One or more exported research records cross project scope.",
    )
    task_assurance_ok = isinstance(task_assurance, list)
    assurance_task_ids = [
        row.get("task_id") for row in task_assurance if isinstance(row, dict)
    ] if isinstance(task_assurance, list) else []
    if (
        not task_assurance_ok
        or len(assurance_task_ids) != len(set(assurance_task_ids))
        or set(assurance_task_ids) != set(tasks)
    ):
        task_assurance_ok = False
        errors.append("task assurance must contain exactly one row for every exported task")
    if isinstance(task_assurance, list):
        for row in task_assurance:
            if not isinstance(row, dict):
                task_assurance_ok = False
                continue
            snapshot = row.get("snapshot")
            snapshot_hash = row.get("snapshot_sha256")
            check_rows = row.get("checks")
            calculated_ready = (
                isinstance(check_rows, list)
                and bool(check_rows)
                and all(
                    isinstance(check, dict) and check.get("passed") is True
                    for check in check_rows
                )
            )
            if (
                not isinstance(snapshot, dict)
                or not isinstance(snapshot_hash, str)
                or SHA256_PATTERN.fullmatch(snapshot_hash) is None
                or canonical_sha256(snapshot) != snapshot_hash
                or not isinstance(snapshot.get("task"), dict)
                or snapshot["task"].get("id") != row.get("task_id")
                or snapshot.get("project_id") != project_id
                or row.get("ready") is not calculated_ready
            ):
                task_assurance_ok = False
                errors.append(f"task assurance {row.get('task_id')} has an invalid snapshot")
                continue
            current_task = tasks.get(str(row.get("task_id")))
            if current_task is None or snapshot["task"] != task_input_payload(current_task):
                task_assurance_ok = False
                errors.append(
                    f"task assurance {row.get('task_id')} does not match its current task"
                )
            if (
                not isinstance(snapshot_run, dict)
                or not isinstance(snapshot_run.get("input_snapshot"), dict)
                or not isinstance(project, dict)
                or snapshot_run["input_snapshot"].get("project")
                != project_execution_payload(project)
            ):
                task_assurance_ok = False
                errors.append(
                    f"task assurance {row.get('task_id')} does not match its current project"
                )
            run_id = row.get("run_id")
            snapshot_run = snapshot.get("run")
            exported_run = runs.get(str(run_id)) if run_id is not None else None
            if run_id is None:
                if snapshot_run is not None:
                    task_assurance_ok = False
                    errors.append(
                        f"task assurance {row.get('task_id')} has inconsistent run state"
                    )
            elif (
                exported_run is None
                or not isinstance(snapshot_run, dict)
                or snapshot_run.get("id") != run_id
                or snapshot_run.get("input_snapshot") != exported_run.get("input_snapshot")
                or snapshot_run.get("input_sha256") != exported_run.get("input_sha256")
            ):
                task_assurance_ok = False
                errors.append(
                    f"task assurance {row.get('task_id')} does not match its exported run"
                )
            task_acceptances = [
                acceptance
                for acceptance in acceptances.values()
                if acceptance.get("task_id") == row.get("task_id")
            ]
            latest_acceptance = max(
                task_acceptances,
                key=lambda acceptance: (
                    _parse_time(acceptance.get("created_at"))
                    or datetime.min.replace(tzinfo=UTC),
                    str(acceptance.get("id")),
                ),
                default=None,
            )
            exact_acceptance = (
                latest_acceptance is not None
                and latest_acceptance.get("run_id") == run_id
                and latest_acceptance.get("snapshot_sha256") == snapshot_hash
                and latest_acceptance.get("snapshot_json") == snapshot
                and isinstance(snapshot.get("protocol"), dict)
                and latest_acceptance.get("protocol_id") == snapshot["protocol"].get("id")
            )
            expected_status = (
                "accepted"
                if calculated_ready and exact_acceptance
                else "stale"
                if latest_acceptance is not None
                else "ready"
                if calculated_ready
                else "blocked"
            )
            summary = row.get("acceptance")
            if row.get("status") != expected_status or (
                latest_acceptance is None and summary is not None
            ) or (
                latest_acceptance is not None
                and (
                    not isinstance(summary, dict)
                    or summary.get("id") != latest_acceptance.get("id")
                )
            ):
                task_assurance_ok = False
                errors.append(
                    f"task assurance {row.get('task_id')} has an invalid status transition"
                )
            if calculated_ready:
                snapshot_protocol = snapshot.get("protocol")
                latest_snapshot_protocol = snapshot.get("latest_protocol")
                latest_protocol = max(
                    (
                        protocol
                        for protocol in protocols.values()
                        if protocol.get("status") != "withdrawn"
                    ),
                    key=lambda protocol: (
                        protocol.get("version")
                        if isinstance(protocol.get("version"), int)
                        else -1
                    ),
                    default=None,
                )
                if (
                    not isinstance(snapshot_protocol, dict)
                    or latest_protocol is None
                    or snapshot_protocol.get("id") != latest_protocol.get("id")
                    or latest_protocol.get("status") != "approved"
                    or not isinstance(latest_snapshot_protocol, dict)
                    or latest_snapshot_protocol.get("id") != latest_protocol.get("id")
                    or not isinstance(project, dict)
                    or snapshot.get("project_objective") != project.get("objective")
                ):
                    task_assurance_ok = False
                    errors.append(
                        f"ready task assurance {row.get('task_id')} has a stale protocol"
                    )
                completed_task_runs = [
                    run
                    for run in runs.values()
                    if run.get("task_id") == row.get("task_id")
                    and run.get("status") == "completed"
                    and _parse_time(run.get("started_at")) is not None
                ]
                latest_completed_run = max(
                    completed_task_runs,
                    key=lambda run: (
                        _parse_time(run.get("started_at")),
                        str(run.get("id")),
                    ),
                    default=None,
                )
                if latest_completed_run is None or latest_completed_run.get("id") != run_id:
                    task_assurance_ok = False
                    errors.append(
                        f"ready task assurance {row.get('task_id')} does not use the latest run"
                    )
                snapshot_claims = snapshot.get("claims")
                snapshot_findings = snapshot.get("findings")
                frozen_packet = (
                    snapshot_run.get("input_snapshot", {}).get("source_packet")
                    if isinstance(snapshot_run, dict)
                    and isinstance(snapshot_run.get("input_snapshot"), dict)
                    else None
                )
                current_state_ok = (
                    isinstance(snapshot_claims, list)
                    and isinstance(snapshot_findings, list)
                    and isinstance(frozen_packet, list)
                )
                expected_packet, expected_descriptors = current_task_packets(
                    str(row.get("task_id"))
                )
                if (
                    frozen_packet != expected_packet
                    or snapshot.get("source_packet") != expected_descriptors
                ):
                    current_state_ok = False
                finding_ids = {
                    finding.get("id")
                    for finding in snapshot_findings or []
                    if isinstance(finding, dict)
                }
                current_active_claims = {
                    claim_id: claim
                    for claim_id, claim in claims.items()
                    if claim.get("finding_id") in finding_ids
                    and claim.get("status") != "retired"
                }
                frozen_claim_ids = {
                    claim.get("id")
                    for claim in snapshot_claims or []
                    if isinstance(claim, dict)
                }
                if frozen_claim_ids != set(current_active_claims):
                    current_state_ok = False
                for frozen_claim in snapshot_claims or []:
                    if not isinstance(frozen_claim, dict):
                        current_state_ok = False
                for frozen_finding in snapshot_findings or []:
                    if not isinstance(frozen_finding, dict):
                        current_state_ok = False
                        continue
                    frozen_review = frozen_finding.get("review")
                    finding_reviews = [
                        review
                        for review in reviews.values()
                        if review.get("finding_id") == frozen_finding.get("id")
                        and _parse_time(review.get("created_at")) is not None
                    ]
                    latest_review = max(
                        finding_reviews,
                        key=lambda review: (
                            _parse_time(review.get("created_at")),
                            str(review.get("id")),
                        ),
                        default=None,
                    )
                    if (
                        not isinstance(frozen_review, dict)
                        or latest_review is None
                        or latest_review.get("id") != frozen_review.get("id")
                        or latest_review.get("decision") != "accepted"
                    ):
                        current_state_ok = False
                        continue
                    current_claim = current_active_claims.get(str(frozen_claim.get("id")))
                    if current_claim is None or any(
                        frozen_claim.get(field) != current_claim.get(field)
                        for field in ("finding_id", "statement", "confidence", "status")
                    ):
                        current_state_ok = False
                    frozen_edges = frozen_claim.get("evidence")
                    current_edges = {
                        edge_id: edge
                        for edge_id, edge in evidence.items()
                        if edge.get("claim_id") == frozen_claim.get("id")
                    }
                    if not isinstance(frozen_edges, list) or {
                        edge.get("id")
                        for edge in frozen_edges
                        if isinstance(edge, dict)
                    } != set(current_edges):
                        current_state_ok = False
                        continue
                    for frozen_edge in frozen_edges:
                        if not isinstance(frozen_edge, dict):
                            current_state_ok = False
                            continue
                        current_edge = current_edges.get(str(frozen_edge.get("id")))
                        excerpt = excerpts.get(str(frozen_edge.get("excerpt_id")))
                        source = (
                            sources.get(str(excerpt.get("source_id")))
                            if excerpt is not None
                            else None
                        )
                        if (
                            current_edge is None
                            or any(
                                frozen_edge.get(field) != current_edge.get(field)
                                for field in ("excerpt_id", "stance", "note")
                            )
                            or current_edge.get("stance") == "contradicts"
                            or source is None
                            or source.get("status") != "active"
                        ):
                            current_state_ok = False
                for packet_entry in frozen_packet or []:
                    if not isinstance(packet_entry, dict):
                        current_state_ok = False
                        continue
                    source = sources.get(str(packet_entry.get("source_id")))
                    link = source_links.get(str(packet_entry.get("link_id")))
                    if (
                        source is None
                        or source.get("status") != "active"
                        or link is None
                        or link.get("task_id") != row.get("task_id")
                        or link.get("source_id") != source.get("id")
                    ):
                        current_state_ok = False
                if not current_state_ok:
                    task_assurance_ok = False
                    errors.append(
                        f"ready task assurance {row.get('task_id')} has stale evidence state"
                    )
            if row.get("status") == "accepted":
                acceptance = latest_acceptance
                if (
                    row.get("ready") is not True
                    or acceptance is None
                    or acceptance.get("task_id") != row.get("task_id")
                    or acceptance.get("run_id") != run_id
                    or acceptance.get("snapshot_sha256") != snapshot_hash
                    or acceptance.get("snapshot_json") != snapshot
                    or summary.get("snapshot_sha256") != snapshot_hash
                ):
                    task_assurance_ok = False
                    errors.append(
                        f"accepted task assurance {row.get('task_id')} lacks its exact acceptance"
                    )
    _add_check(
        checks,
        errors,
        "task_assurance",
        task_assurance_ok,
        "Task assurance rows are complete and internally bound.",
        "One or more task assurance rows are incomplete or inconsistent.",
    )

    source_hashes_ok = True
    for source in sources.values():
        content = source.get("content")
        digest = source.get("content_sha256")
        if not isinstance(content, str) or hashlib.sha256(content.encode()).hexdigest() != digest:
            source_hashes_ok = False
            errors.append(f"source {source.get('id')} failed its content SHA-256 check")
        if source.get("project_id") != project_id:
            source_hashes_ok = False
            errors.append(f"source {source.get('id')} belongs to another project")
    _add_check(
        checks,
        errors,
        "source_hashes",
        source_hashes_ok,
        "Captured source content hashes are intact.",
        "One or more captured source content hashes failed.",
    )

    excerpt_hashes_ok = True
    for excerpt in excerpts.values():
        source = sources.get(str(excerpt.get("source_id")))
        source_content = source.get("content") if source is not None else None
        quote = excerpt.get("quote")
        start = excerpt.get("start_offset")
        end = excerpt.get("end_offset")
        intact = (
            source is not None
            and isinstance(source_content, str)
            and isinstance(quote, str)
            and hashlib.sha256(quote.encode()).hexdigest() == excerpt.get("quote_sha256")
            and isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start < end <= len(source_content)
            and source_content[start:end] == quote
            and excerpt.get("project_id") == project_id
        )
        if not intact:
            excerpt_hashes_ok = False
            errors.append(f"excerpt {excerpt.get('id')} failed its source/offset/hash check")
    _add_check(
        checks,
        errors,
        "excerpt_hashes",
        excerpt_hashes_ok,
        "Excerpt hashes and source offsets are intact.",
        "One or more excerpt hashes or source offsets failed.",
    )

    protocol_hashes_ok = True
    for protocol in protocols.values():
        if (
            protocol.get("project_id") != project_id
            or protocol_content_sha256(protocol) != protocol.get("content_sha256")
        ):
            protocol_hashes_ok = False
            errors.append(f"protocol {protocol.get('id')} failed its frozen content hash check")
    _add_check(
        checks,
        errors,
        "protocol_hashes",
        protocol_hashes_ok,
        "Frozen protocol hashes are intact.",
        "One or more frozen protocol hashes failed.",
    )

    references_ok = True

    def reference_error(message: str) -> None:
        nonlocal references_ok
        references_ok = False
        errors.append(message)

    unlinked_source_records: dict[str, dict[str, Any]] = {}
    unlinked_evidence_records: dict[str, dict[str, Any]] = {}
    for row in activity.values():
        details = row.get("details")
        if not isinstance(details, dict):
            continue
        if row.get("action") == "task.source_unlinked" and isinstance(
            details.get("link_id"), str
        ):
            unlinked_source_records[details["link_id"]] = {
                **details,
                "_entity_id": row.get("entity_id"),
            }
        if row.get("action") == "claim.evidence_unlinked" and isinstance(
            details.get("evidence_id"), str
        ):
            unlinked_evidence_records[details["evidence_id"]] = {
                **details,
                "_entity_id": row.get("entity_id"),
            }

    def validate_frozen_packet(run: dict[str, Any]) -> bool:
        snapshot = run.get("input_snapshot")
        packet = snapshot.get("source_packet") if isinstance(snapshot, dict) else None
        if not isinstance(packet, list) or len(packet) > MAX_TASK_SOURCE_COUNT:
            return False
        remaining = MAX_TASK_SOURCE_CONTEXT
        seen_links: set[str] = set()
        prior_order: tuple[str, str] | None = None
        for entry in packet:
            if not isinstance(entry, dict) or remaining <= 0:
                return False
            link_id = entry.get("link_id")
            source_id = entry.get("source_id")
            source = sources.get(str(source_id))
            link = source_links.get(str(link_id))
            historical_link = unlinked_source_records.get(str(link_id))
            content = entry.get("content")
            link_created_at = entry.get("link_created_at")
            order = (str(link_created_at), str(link_id))
            if (
                not isinstance(link_id, str)
                or link_id in seen_links
                or not isinstance(link_created_at, str)
                or (prior_order is not None and order < prior_order)
                or source is None
                or not isinstance(source.get("content"), str)
                or not isinstance(content, str)
            ):
                return False
            expected_content = source["content"][:remaining]
            if (
                content != expected_content
                or entry.get("included_chars") != len(content)
                or entry.get("included_content_sha256")
                != hashlib.sha256(content.encode()).hexdigest()
                or entry.get("content_sha256") != source.get("content_sha256")
                or entry.get("title") != source.get("title")
                or entry.get("origin") != source.get("origin")
                or entry.get("truncated") != (len(content) < len(source["content"]))
            ):
                return False
            if link is not None:
                if (
                    link.get("task_id") != run.get("task_id")
                    or link.get("source_id") != source_id
                    or link.get("purpose") != entry.get("purpose")
                    or link.get("created_at") != link_created_at
                ):
                    return False
            elif (
                historical_link is None
                or historical_link.get("source_id") != source_id
                or historical_link.get("purpose") != entry.get("purpose")
                or historical_link.get("project_id") != project_id
                or historical_link.get("_entity_id") != run.get("task_id")
            ):
                return False
            seen_links.add(link_id)
            prior_order = order
            remaining -= len(content)
        return True

    def current_task_packets(
        task_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        links = sorted(
            (link for link in source_links.values() if link.get("task_id") == task_id),
            key=lambda link: (str(link.get("created_at")), str(link.get("id"))),
        )
        active_candidates: list[dict[str, Any]] = []
        for link in links:
            source = sources.get(str(link.get("source_id")))
            if (
                source is not None
                and source.get("status") == "active"
                and len(active_candidates) < MAX_TASK_SOURCE_COUNT
            ):
                active_candidates.append(link)
        candidate_ids = {link.get("id") for link in active_candidates}
        remaining = MAX_TASK_SOURCE_CONTEXT
        prompt_packet: list[dict[str, Any]] = []
        descriptors: list[dict[str, Any]] = []
        for link in links:
            source = sources.get(str(link.get("source_id")))
            reason: str | None = None
            usable = False
            if source is None:
                reason = "missing_source"
            elif source.get("status") != "active":
                reason = "source_archived"
            elif link.get("id") not in candidate_ids:
                reason = "outside_runtime_limit"
            elif source.get("project_id") != project_id:
                reason = "different_project"
            elif (
                not isinstance(source.get("content"), str)
                or hashlib.sha256(source["content"].encode()).hexdigest()
                != source.get("content_sha256")
            ):
                reason = "source_integrity"
            elif remaining <= 0:
                reason = "outside_runtime_context_limit"
            else:
                usable = True
                content = source["content"][:remaining]
                prompt_packet.append(
                    {
                        "link_id": link.get("id"),
                        "source_id": source.get("id"),
                        "purpose": link.get("purpose"),
                        "link_created_at": link.get("created_at"),
                        "title": source.get("title"),
                        "origin": source.get("origin"),
                        "content": content,
                        "content_sha256": source.get("content_sha256"),
                        "included_content_sha256": hashlib.sha256(
                            content.encode()
                        ).hexdigest(),
                        "included_chars": len(content),
                        "truncated": len(content) < len(source["content"]),
                    }
                )
                remaining -= len(content)
            descriptors.append(
                {
                    "link_id": link.get("id"),
                    "source_id": link.get("source_id"),
                    "purpose": link.get("purpose"),
                    "created_at": link.get("created_at"),
                    "source_status": source.get("status") if source is not None else "missing",
                    "source_sha256": (
                        source.get("content_sha256") if source is not None else None
                    ),
                    "usable": usable,
                    "exclusion_reason": reason,
                }
            )
        return prompt_packet, descriptors

    for excerpt in excerpts.values():
        if excerpt.get("source_id") not in sources:
            reference_error(f"excerpt {excerpt.get('id')} has a missing source")
    for link in source_links.values():
        task = tasks.get(str(link.get("task_id")))
        source = sources.get(str(link.get("source_id")))
        if task is None or source is None:
            reference_error(f"task source link {link.get('id')} has a missing task or source")
        elif task.get("project_id") != link.get("project_id") or source.get(
            "project_id"
        ) != link.get("project_id"):
            reference_error(f"task source link {link.get('id')} crosses project scope")
    for run in runs.values():
        kind = run.get("kind")
        task = tasks.get(str(run.get("task_id"))) if run.get("task_id") is not None else None
        meeting = (
            meetings.get(str(run.get("meeting_id")))
            if run.get("meeting_id") is not None
            else None
        )
        if kind == "task" and (task is None or run.get("meeting_id") is not None):
            reference_error(f"task run {run.get('id')} has inconsistent task/meeting references")
        elif kind == "meeting" and (meeting is None or run.get("task_id") is not None):
            reference_error(
                f"meeting run {run.get('id')} has inconsistent task/meeting references"
            )
        elif kind not in {"task", "meeting"}:
            reference_error(f"run {run.get('id')} has unsupported kind")
        retry_id = run.get("retry_of_run_id")
        if retry_id is not None and retry_id not in runs:
            reference_error(f"run {run.get('id')} has a missing retry predecessor")
        input_hash = run.get("input_sha256")
        input_snapshot = run.get("input_snapshot")
        if input_hash is not None and (
            not isinstance(input_hash, str)
            or SHA256_PATTERN.fullmatch(input_hash) is None
            or not isinstance(input_snapshot, dict)
            or canonical_sha256(input_snapshot) != input_hash
        ):
            reference_error(f"run {run.get('id')} has an invalid input snapshot hash")
        if kind == "task" and input_hash is not None:
            frozen_task = input_snapshot.get("task") if isinstance(input_snapshot, dict) else None
            frozen_project = (
                input_snapshot.get("project") if isinstance(input_snapshot, dict) else None
            )
            frozen_agent = (
                input_snapshot.get("agent") if isinstance(input_snapshot, dict) else None
            )
            frozen_protocol = (
                input_snapshot.get("protocol") if isinstance(input_snapshot, dict) else None
            )
            if (
                not isinstance(frozen_task, dict)
                or frozen_task.get("id") != run.get("task_id")
                or frozen_task.get("project_id") != project_id
                or not isinstance(frozen_project, dict)
                or frozen_project.get("id") != project_id
                or not isinstance(frozen_agent, dict)
                or frozen_agent.get("id") != frozen_task.get("assigned_agent_id")
                or not isinstance(frozen_agent.get("model"), str)
                or not validate_frozen_packet(run)
            ):
                reference_error(f"task run {run.get('id')} has malformed frozen inputs")
            if frozen_protocol is not None:
                protocol = (
                    protocols.get(str(frozen_protocol.get("id")))
                    if isinstance(frozen_protocol, dict)
                    else None
                )
                expected_protocol = protocol_execution_payload(protocol) if protocol else None
                if expected_protocol is not None:
                    expected_protocol["status"] = "approved"
                if (
                    not isinstance(frozen_protocol, dict)
                    or frozen_protocol.get("status") != "approved"
                    or frozen_protocol != expected_protocol
                ):
                    reference_error(f"task run {run.get('id')} has an invalid frozen protocol")
                if (
                    isinstance(frozen_project, dict)
                    and protocol is not None
                    and frozen_project.get("objective") != protocol.get("project_objective")
                ):
                    reference_error(
                        f"task run {run.get('id')} project objective differs from its protocol"
                    )
    for result in results.values():
        task = tasks.get(str(result.get("task_id")))
        run = runs.get(str(result.get("run_id")))
        if task is None or run is None or run.get("task_id") != result.get("task_id"):
            reference_error(f"task result {result.get('id')} has inconsistent task/run references")
    for finding in findings.values():
        task = tasks.get(str(finding.get("task_id")))
        result = results.get(str(finding.get("result_id")))
        if (
            task is None
            or result is None
            or result.get("task_id") != finding.get("task_id")
            or finding.get("agent_id") != result.get("agent_id")
            or finding.get("content") != result.get("content")
        ):
            reference_error(f"finding {finding.get('id')} has inconsistent task/result references")
    for review in reviews.values():
        if review.get("finding_id") not in findings:
            reference_error(f"finding review {review.get('id')} has a missing finding")
    for claim in claims.values():
        finding_id = claim.get("finding_id")
        if finding_id is not None and finding_id not in findings:
            reference_error(f"claim {claim.get('id')} has a missing finding")
    for link in evidence.values():
        if link.get("claim_id") not in claims or link.get("excerpt_id") not in excerpts:
            reference_error(f"claim evidence {link.get('id')} has a missing claim or excerpt")
    for dependency in dependencies.values():
        if (
            dependency.get("task_id") not in tasks
            or dependency.get("depends_on_task_id") not in tasks
        ):
            reference_error(f"task dependency {dependency.get('id')} has a missing task")
    for outcome in outcomes.values():
        meeting = meetings.get(str(outcome.get("meeting_id")))
        run = runs.get(str(outcome.get("run_id"))) if outcome.get("run_id") else None
        if meeting is None or (run is not None and run.get("meeting_id") != meeting.get("id")):
            reference_error(f"meeting outcome {outcome.get('id')} has invalid references")
    for action in actions.values():
        if action.get("meeting_id") is not None and action.get("meeting_id") not in meetings:
            reference_error(f"action {action.get('id')} has a missing meeting")
        if action.get("promoted_task_id") is not None and action.get(
            "promoted_task_id"
        ) not in tasks:
            reference_error(f"action {action.get('id')} has a missing promoted task")
    for call in model_calls.values():
        if call.get("run_id") is not None and call.get("run_id") not in runs:
            reference_error(f"model call {call.get('id')} has a missing run")

    semantic_acceptances = list(acceptances.values())
    if isinstance(task_assurance, list):
        for row in task_assurance:
            if not isinstance(row, dict) or row.get("ready") is not True:
                continue
            snapshot = row.get("snapshot")
            snapshot_hash = row.get("snapshot_sha256")
            if not isinstance(snapshot, dict) or not isinstance(snapshot_hash, str):
                continue
            already_covered = any(
                acceptance.get("snapshot_sha256") == snapshot_hash
                and acceptance.get("snapshot_json") == snapshot
                for acceptance in semantic_acceptances
            )
            if already_covered:
                continue
            snapshot_protocol = snapshot.get("protocol")
            protocol_id = (
                snapshot_protocol.get("id") if isinstance(snapshot_protocol, dict) else None
            )
            protocol = protocols.get(str(protocol_id))
            semantic_acceptances.append(
                {
                    "id": f"task-assurance:{row.get('task_id')}",
                    "project_id": project_id,
                    "task_id": row.get("task_id"),
                    "run_id": row.get("run_id"),
                    "protocol_id": protocol_id,
                    "snapshot_sha256": snapshot_hash,
                    "snapshot_json": snapshot,
                    "confirmed_criteria": (
                        protocol.get("acceptance_criteria") if protocol is not None else None
                    ),
                    # A current readiness assessment occurs after every exported row.
                    # This future sentinel lets the shared historical-review check
                    # select the latest exported review without trusting wall time.
                    "created_at": "9999-12-31T23:59:59+00:00",
                }
            )

    for acceptance in semantic_acceptances:
        acceptance_id = acceptance.get("id")
        task = tasks.get(str(acceptance.get("task_id")))
        run = runs.get(str(acceptance.get("run_id")))
        protocol = protocols.get(str(acceptance.get("protocol_id")))
        if task is None or run is None or protocol is None:
            reference_error(f"assurance acceptance {acceptance_id} has a missing reference")
            continue
        if run.get("task_id") != task.get("id"):
            reference_error(f"assurance acceptance {acceptance_id} crosses task/run scope")
        started_at = _parse_time(run.get("started_at"))
        completed_at = _parse_time(run.get("completed_at"))
        approved_at = _parse_time(protocol.get("approved_at"))
        accepted_at = _parse_time(acceptance.get("created_at"))
        if (
            run.get("kind") != "task"
            or run.get("status") != "completed"
            or started_at is None
            or completed_at is None
            or completed_at < started_at
            or approved_at is None
            or approved_at > started_at
            or protocol.get("status") not in {"approved", "superseded"}
            or not isinstance(protocol.get("approved_by"), str)
            or not protocol.get("approved_by", "").strip()
            or accepted_at is None
            or accepted_at < completed_at
        ):
            reference_error(
                f"assurance acceptance {acceptance_id} violates run/protocol chronology"
            )
            continue
        run_input = run.get("input_snapshot")
        run_hash = run.get("input_sha256")
        if (
            not isinstance(run_input, dict)
            or not isinstance(run_hash, str)
            or SHA256_PATTERN.fullmatch(run_hash) is None
            or canonical_sha256(run_input) != run_hash
        ):
            reference_error(f"assurance acceptance {acceptance_id} uses an unbound run input")
            continue
        frozen_agent = run_input.get("agent")
        frozen_task = run_input.get("task")
        if (
            not isinstance(frozen_agent, dict)
            or not isinstance(frozen_task, dict)
            or not isinstance(run_input.get("source_packet"), list)
            or not validate_frozen_packet(run)
        ):
            reference_error(f"assurance acceptance {acceptance_id} has malformed run inputs")
            continue
        if started_at is None or any(
            _parse_time(entry.get("link_created_at")) is None
            or _parse_time(entry.get("link_created_at")) > started_at
            for entry in run_input["source_packet"]
            if isinstance(entry, dict)
        ):
            reference_error(
                f"assurance acceptance {acceptance_id} uses a post-run source link"
            )
        snapshot_hash = acceptance.get("snapshot_sha256")
        snapshot = acceptance.get("snapshot_json")
        if (
            not isinstance(snapshot_hash, str)
            or SHA256_PATTERN.fullmatch(snapshot_hash) is None
            or not isinstance(snapshot, dict)
            or canonical_sha256(snapshot) != snapshot_hash
        ):
            reference_error(f"assurance acceptance {acceptance_id} has an invalid snapshot")
            continue
        snapshot_task = snapshot.get("task")
        snapshot_run = snapshot.get("run")
        snapshot_protocol = snapshot.get("protocol")
        expected_snapshot_run = {
            "id": run.get("id"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "input_snapshot": run_input,
            "input_sha256": run_hash,
        }
        expected_protocol = protocol_hash_payload(protocol) | {
            "id": protocol.get("id"),
            "status": "approved",
            "content_sha256": protocol.get("content_sha256"),
            "approved_by": protocol.get("approved_by"),
            "approved_at": protocol.get("approved_at"),
        }
        if (
            snapshot_task != run_input.get("task")
            or snapshot_run != expected_snapshot_run
            or snapshot_protocol != expected_protocol
            or snapshot.get("project_id") != project_id
            or snapshot.get("project_objective") != protocol.get("project_objective")
        ):
            reference_error(f"assurance acceptance {acceptance_id} snapshot inputs do not match")
        if acceptance.get("confirmed_criteria") != protocol.get("acceptance_criteria"):
            reference_error(
                f"assurance acceptance {acceptance_id} lacks exact criterion confirmations"
            )

        result_snapshots = snapshot.get("task_results")
        expected_result_ids = {
            row["id"] for row in results.values() if row.get("run_id") == run.get("id")
        }
        if not isinstance(result_snapshots, list) or not result_snapshots:
            reference_error(f"assurance acceptance {acceptance_id} has malformed results")
            result_snapshots = []
        if {row.get("id") for row in result_snapshots if isinstance(row, dict)} != (
            expected_result_ids
        ):
            reference_error(f"assurance acceptance {acceptance_id} omits or adds task results")
        for result_snapshot in result_snapshots:
            if not isinstance(result_snapshot, dict):
                reference_error(f"assurance acceptance {acceptance_id} has an invalid result")
                continue
            result = results.get(str(result_snapshot.get("id")))
            if (
                result is None
                or result.get("run_id") != run.get("id")
                or result.get("agent_id") != frozen_agent.get("id")
                or _parse_time(result.get("created_at")) is None
                or _parse_time(result.get("created_at")) < started_at
                or _parse_time(result.get("created_at")) > completed_at
                or not isinstance(result.get("content"), str)
                or hashlib.sha256(result["content"].encode()).hexdigest()
                != result_snapshot.get("content_sha256")
                or result_snapshot.get("agent_id") != result.get("agent_id")
                or result_snapshot.get("created_at") != result.get("created_at")
            ):
                reference_error(f"assurance acceptance {acceptance_id} has an invalid result")

        call_snapshots = snapshot.get("model_calls")
        expected_calls = {
            row["id"]
            for row in model_calls.values()
            if row.get("run_id") == run.get("id")
            and row.get("stage") == "task_result"
            and row.get("status") == "completed"
        }
        if not isinstance(call_snapshots, list) or not call_snapshots:
            reference_error(f"assurance acceptance {acceptance_id} has malformed model provenance")
            call_snapshots = []
        if len(expected_calls) != 1:
            reference_error(
                f"assurance acceptance {acceptance_id} must bind one completed task call"
            )
        if {row.get("id") for row in call_snapshots if isinstance(row, dict)} != expected_calls:
            reference_error(f"assurance acceptance {acceptance_id} omits or adds model calls")
        expected_system = agent_system_prompt(
            frozen_agent, str(frozen_task.get("objective") or "")
        )
        expected_user = task_user_prompt(run_input)
        for call_snapshot in call_snapshots:
            call = model_calls.get(str(call_snapshot.get("id"))) if isinstance(
                call_snapshot, dict
            ) else None
            call_checks = {
                "record": call is not None,
                "run": call is not None and call.get("run_id") == run.get("id"),
                "agent": call is not None
                and call.get("agent_id") == frozen_agent.get("id"),
                "model": call is not None
                and call.get("model") == frozen_agent.get("model"),
                "stage": call is not None and call.get("stage") == "task_result",
                "status": call is not None and call.get("status") == "completed",
                "completed_at": call is not None
                and _parse_time(call.get("completed_at")) is not None,
                "chronology": call is not None
                and _parse_time(call.get("created_at")) is not None
                and _parse_time(call.get("completed_at")) is not None
                and started_at
                <= _parse_time(call.get("created_at"))
                <= _parse_time(call.get("completed_at"))
                <= completed_at,
                "system_prompt": call is not None
                and call.get("system_prompt") == expected_system,
                "user_prompt": call is not None and call.get("user_prompt") == expected_user,
                "hash": call is not None
                and model_call_provenance_sha256(call)
                == call_snapshot.get("provenance_sha256"),
            }
            if not all(call_checks.values()):
                failures = ", ".join(
                    name for name, passed in call_checks.items() if not passed
                )
                reference_error(
                    f"assurance acceptance {acceptance_id} has invalid model provenance: "
                    f"{failures}"
                )

        finding_snapshots = snapshot.get("findings")
        snapshot_finding_ids = {
            row.get("id")
            for row in finding_snapshots
            if isinstance(row, dict)
        } if isinstance(finding_snapshots, list) else set()
        expected_finding_ids = {
            row["id"]
            for row in findings.values()
            if row.get("result_id") in expected_result_ids
        }
        if not snapshot_finding_ids or snapshot_finding_ids != expected_finding_ids:
            reference_error(f"assurance acceptance {acceptance_id} has no frozen findings")
        else:
            for finding_snapshot in finding_snapshots:
                if not isinstance(finding_snapshot, dict):
                    reference_error(
                        f"assurance acceptance {acceptance_id} has invalid findings"
                    )
                    continue
                finding = findings.get(str(finding_snapshot.get("id")))
                review = finding_snapshot.get("review")
                exported_review = (
                    reviews.get(str(review.get("id"))) if isinstance(review, dict) else None
                )
                historical_reviews = [
                    row
                    for row in reviews.values()
                    if row.get("finding_id") == finding_snapshot.get("id")
                    and _parse_time(row.get("created_at")) is not None
                    and accepted_at is not None
                    and _parse_time(row.get("created_at")) <= accepted_at
                ]
                latest_review = max(
                    historical_reviews,
                    key=lambda row: (_parse_time(row.get("created_at")), str(row.get("id"))),
                    default=None,
                )
                if (
                    finding is None
                    or finding.get("result_id") not in expected_result_ids
                    or finding_snapshot.get("result_id") != finding.get("result_id")
                    or _parse_time(finding.get("created_at")) is None
                    or _parse_time(finding.get("created_at")) < started_at
                    or _parse_time(finding.get("created_at")) > completed_at
                    or not isinstance(finding.get("content"), str)
                    or hashlib.sha256(finding["content"].encode()).hexdigest()
                    != finding_snapshot.get("content_sha256")
                    or exported_review is None
                    or exported_review.get("finding_id") != finding.get("id")
                    or latest_review is None
                    or latest_review.get("id") != exported_review.get("id")
                    or review.get("decision") != "accepted"
                    or any(
                        review.get(field) != exported_review.get(field)
                        for field in ("decision", "reviewer", "notes")
                    )
                ):
                    reference_error(f"assurance acceptance {acceptance_id} has invalid findings")
        claim_snapshots = snapshot.get("claims")
        if not isinstance(claim_snapshots, list) or not claim_snapshots:
            reference_error(f"assurance acceptance {acceptance_id} has no frozen claims")
            claim_snapshots = []
        claims_by_finding = {
            finding_id: 0 for finding_id in snapshot_finding_ids
        }
        for claim_snapshot in claim_snapshots:
            snapshot_evidence = claim_snapshot.get("evidence") if isinstance(
                claim_snapshot, dict
            ) else None
            supported = False
            all_support_bounded = True
            contradicted = False
            if (
                not isinstance(claim_snapshot, dict)
                or claim_snapshot.get("status") != "accepted"
                or claim_snapshot.get("finding_id") not in snapshot_finding_ids
                or not isinstance(snapshot_evidence, list)
            ):
                reference_error(f"assurance acceptance {acceptance_id} has an invalid claim")
                continue
            exported_claim = claims.get(str(claim_snapshot.get("id")))
            if (
                exported_claim is None
                or exported_claim.get("finding_id") != claim_snapshot.get("finding_id")
                or _parse_time(exported_claim.get("created_at")) is None
                or _parse_time(exported_claim.get("created_at")) > accepted_at
            ):
                reference_error(
                    f"assurance acceptance {acceptance_id} has an unbound frozen claim"
                )
            if claim_snapshot["finding_id"] in claims_by_finding:
                claims_by_finding[claim_snapshot["finding_id"]] += 1
            for frozen_evidence in snapshot_evidence:
                if not isinstance(frozen_evidence, dict):
                    reference_error(
                        f"assurance acceptance {acceptance_id} has invalid frozen evidence"
                    )
                    continue
                excerpt = excerpts.get(str(frozen_evidence.get("excerpt_id")))
                source = sources.get(str(frozen_evidence.get("source_id")))
                current_edge = evidence.get(str(frozen_evidence.get("id")))
                removed_edge = unlinked_evidence_records.get(str(frozen_evidence.get("id")))
                edge_history_ok = (
                    current_edge is not None
                    and current_edge.get("claim_id") == claim_snapshot.get("id")
                    and current_edge.get("excerpt_id") == frozen_evidence.get("excerpt_id")
                    and current_edge.get("stance") == frozen_evidence.get("stance")
                    and current_edge.get("note") == frozen_evidence.get("note")
                    and _parse_time(current_edge.get("created_at")) is not None
                    and _parse_time(current_edge.get("created_at")) <= accepted_at
                ) or (
                    removed_edge is not None
                    and removed_edge.get("excerpt_id") == frozen_evidence.get("excerpt_id")
                    and removed_edge.get("stance") == frozen_evidence.get("stance")
                    and removed_edge.get("note") == frozen_evidence.get("note")
                    and removed_edge.get("project_id") == project_id
                    and removed_edge.get("_entity_id") == claim_snapshot.get("id")
                )
                intact = (
                    excerpt is not None
                    and source is not None
                    and excerpt.get("source_id") == source.get("id")
                    and frozen_evidence.get("intact") is True
                    and frozen_evidence.get("excerpt_sha256") == excerpt.get("quote_sha256")
                    and frozen_evidence.get("source_sha256") == source.get("content_sha256")
                    and edge_history_ok
                )
                if not intact:
                    reference_error(
                        f"assurance acceptance {acceptance_id} has invalid frozen evidence"
                    )
                if frozen_evidence.get("stance") == "supports" and intact:
                    supported = True
                    packet_entry = next(
                        (
                            row
                            for row in run_input.get("source_packet", [])
                            if isinstance(row, dict)
                            and row.get("source_id") == frozen_evidence.get("source_id")
                        ),
                        None,
                    )
                    excerpt_end = excerpt.get("end_offset") if excerpt is not None else None
                    bounded = (
                        packet_entry is not None
                        and isinstance(excerpt_end, int)
                        and isinstance(packet_entry.get("included_chars"), int)
                        and excerpt_end <= packet_entry["included_chars"]
                    )
                    all_support_bounded = all_support_bounded and bounded
                if frozen_evidence.get("stance") == "contradicts":
                    contradicted = True
            if not supported or not all_support_bounded or contradicted:
                reference_error(
                    f"assurance acceptance {acceptance_id} claim lacks bounded support"
                )
        if any(count == 0 for count in claims_by_finding.values()):
            reference_error(
                f"assurance acceptance {acceptance_id} has a finding without a claim"
            )

        snapshot_packet = snapshot.get("source_packet")
        usable_snapshot_links = {
            (row.get("link_id"), row.get("source_id"), row.get("source_sha256"))
            for row in snapshot_packet
            if isinstance(row, dict) and row.get("usable") is True
        } if isinstance(snapshot_packet, list) else set()
        frozen_packet_links = {
            (row.get("link_id"), row.get("source_id"), row.get("content_sha256"))
            for row in run_input.get("source_packet", [])
            if isinstance(row, dict)
        }
        if usable_snapshot_links != frozen_packet_links:
            reference_error(
                f"assurance acceptance {acceptance_id} source packet does not match its run"
            )
    _add_check(
        checks,
        errors,
        "references",
        references_ok,
        "Evidence and acceptance references are internally complete.",
        "One or more evidence or acceptance references are inconsistent.",
    )

    # _unique_index may have added structural errors outside an individual check.
    valid = not errors and all(bool(check["passed"]) for check in checks)
    return {
        "valid": valid,
        "manifest_sha256": expected if isinstance(expected, str) else None,
        "computed_sha256": computed or None,
        "checks": checks,
        "errors": errors,
    }


def _read_capsule(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    if size > MAX_CAPSULE_BYTES:
        raise ValueError(f"capsule exceeds the {MAX_CAPSULE_BYTES}-byte verification limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("capsule root must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a Lemma research capsule offline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify", help="verify a capsule JSON file")
    verify_parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_capsule(_read_capsule(args.path))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(json.dumps({"valid": False, "errors": [str(error)]}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
