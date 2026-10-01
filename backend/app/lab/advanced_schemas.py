"""Validated request shapes for evidence, workflow, evaluation, and automation APIs."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500_000)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20_000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1_000)]
EntityType = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=40,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]
ModelId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataClassification(StrEnum):
    LOCAL_ONLY = "local_only"
    CONFIDENTIAL = "confidential"
    PUBLIC = "public"


class ProjectPolicyUpdate(StrictRequest):
    data_classification: DataClassification = DataClassification.LOCAL_ONLY
    allowed_models: list[ModelId] = Field(default_factory=list, max_length=32)
    max_run_tokens: int = Field(default=50_000, ge=128, le=2_000_000)
    max_run_usd: float = Field(default=5.0, ge=0, le=10_000)
    max_project_usd: float = Field(default=100.0, ge=0, le=1_000_000)
    max_concurrent_runs: int = Field(default=2, ge=1, le=12)

    @field_validator("allowed_models")
    @classmethod
    def _unique_models(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("allowed_models must be unique")
        return value


class SourceType(StrEnum):
    NOTE = "note"
    URL = "url"
    FILE = "file"
    TRANSCRIPT = "transcript"


class SourceCreate(StrictRequest):
    project_id: UUID
    title: Name
    source_type: SourceType = SourceType.NOTE
    origin: ShortText = ""
    content: Body
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _bounded_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("metadata must be JSON serializable") from error
        if len(encoded) > 20_000:
            raise ValueError("metadata is too large")
        return value


class SourceExcerptCreate(StrictRequest):
    locator: ShortText = ""
    quote: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)


class TaskSourceCreate(StrictRequest):
    source_id: UUID
    purpose: Name = "context"


class FindingReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


class FindingReviewCreate(StrictRequest):
    decision: FindingReviewDecision
    notes: LongText = ""
    reviewer: Name = "founder"


class ClaimStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISPUTED = "disputed"
    RETIRED = "retired"


class ClaimCreate(StrictRequest):
    project_id: UUID
    finding_id: UUID | None = None
    statement: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
    ]
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: ClaimStatus = ClaimStatus.PROPOSED


class ClaimUpdate(StrictRequest):
    statement: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
    ] = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: ClaimStatus | None = None

    @model_validator(mode="after")
    def _has_update(self) -> ClaimUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one claim field must be supplied")
        if "statement" in self.model_fields_set and self.statement is None:
            raise ValueError("statement may not be null")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status may not be null")
        return self


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXTUALIZES = "contextualizes"


class ClaimEvidenceCreate(StrictRequest):
    excerpt_id: UUID
    stance: EvidenceStance = EvidenceStance.SUPPORTS
    note: LongText = ""


class ResearchProtocolCreate(StrictRequest):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
    ]
    hypothesis: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
    ]
    method: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
    ]
    acceptance_criteria: list[Name] = Field(min_length=1, max_length=20)
    limitations: list[ShortText] = Field(default_factory=list, max_length=20)
    created_by: Name = "founder"

    @field_validator("acceptance_criteria", "limitations")
    @classmethod
    def _unique_protocol_entries(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("protocol entries must be unique")
        return value


class ResearchProtocolApproval(StrictRequest):
    approved_by: Name = "founder"


class ResearchProtocolWithdrawal(StrictRequest):
    withdrawn_by: Name = "founder"
    note: LongText = ""


class ResearchAssuranceAccept(StrictRequest):
    reviewer: Name = "founder"
    notes: LongText = ""
    confirmed_criteria: list[Name] = Field(min_length=1, max_length=20)

    @field_validator("confirmed_criteria")
    @classmethod
    def _unique_confirmed_criteria(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("confirmed criteria must be unique")
        return value


class ResearchCapsuleEnvelope(StrictRequest):
    format: Literal["lemma.research-capsule.v1"]
    hash_algorithm: Literal["sha256"]
    project_id: UUID
    manifest: dict[str, Any]
    manifest_sha256: Annotated[
        str, StringConstraints(pattern=r"^[0-9a-f]{64}$")
    ]

    @field_validator("manifest")
    @classmethod
    def _bounded_manifest(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("capsule manifest must be JSON serializable") from error
        if len(encoded.encode("utf-8")) > 50_000_000:
            raise ValueError("capsule manifest is too large")
        return value


class MeetingOutcomeCreate(StrictRequest):
    run_id: UUID | None = None
    summary: LongText
    decisions: list[Name] = Field(default_factory=list, max_length=40)
    disagreements: list[Name] = Field(default_factory=list, max_length=40)


class ActionStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ActionItemCreate(StrictRequest):
    project_id: UUID
    meeting_id: UUID | None = None
    owner_agent_id: UUID | None = None
    title: Name
    details: LongText = ""
    status: ActionStatus = ActionStatus.OPEN
    due_at: datetime | None = None


class ActionItemUpdate(StrictRequest):
    owner_agent_id: UUID | None = None
    title: Name | None = None
    details: LongText | None = None
    status: ActionStatus | None = None
    due_at: datetime | None = None

    @field_validator("title", "details", "status", mode="before")
    @classmethod
    def _no_null_patch_fields(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("field may not be null")
        return value


class PromoteActionRequest(StrictRequest):
    assigned_agent_id: UUID | None = None
    department_id: UUID | None = None
    expected_output: LongText = ""


class TaskDependencyCreate(StrictRequest):
    depends_on_task_id: UUID


class TraceLinkCreate(StrictRequest):
    project_id: UUID
    source_type: EntityType
    source_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    target_type: EntityType
    target_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    relationship: Name = "informs"
    note: LongText = ""


class TemplateKind(StrEnum):
    PROJECT = "project"
    TASK = "task"
    MEETING = "meeting"
    EVALUATION = "evaluation"


class TemplateCreate(StrictRequest):
    name: Name
    kind: TemplateKind
    description: LongText = ""
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _bounded_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value)
        except (TypeError, ValueError) as error:
            raise ValueError("payload must be JSON serializable") from error
        if len(encoded) > 50_000:
            raise ValueError("payload is too large")
        return value


class TemplateInstantiateRequest(StrictRequest):
    overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("overrides")
    @classmethod
    def _bounded_overrides(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value)
        except (TypeError, ValueError) as error:
            raise ValueError("template overrides must be JSON serializable") from error
        if len(encoded) > 50_000:
            raise ValueError("template overrides are too large")
        return value


class EvaluationCreate(StrictRequest):
    project_id: UUID
    name: Name
    prompt: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
    ]
    models: list[ModelId] = Field(min_length=2, max_length=8)
    criteria: list[Name] = Field(default_factory=lambda: ["quality"], min_length=1, max_length=12)

    @field_validator("models", "criteria")
    @classmethod
    def _unique_entries(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("entries must be unique")
        return value


class EvaluationScoreCreate(StrictRequest):
    criterion: Name
    score: float = Field(ge=0, le=10)
    rationale: LongText = ""
    reviewer: Name = "founder"


class AutomationProvider(StrEnum):
    CLAUDE = "claude"


class AutomationPlanCreate(StrictRequest):
    project_id: UUID | None = None
    workspace_id: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = None
    provider: AutomationProvider = AutomationProvider.CLAUDE
    request: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
    ]
    plan: LongText = ""
    capabilities: list[EntityType] = Field(
        default_factory=lambda: ["read_workspace"], min_length=1, max_length=3
    )

    @field_validator("capabilities")
    @classmethod
    def _unique_capabilities(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("capabilities must be unique")
        return value


class AutomationDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class AutomationDecisionRequest(StrictRequest):
    decision: AutomationDecision
    note: LongText = ""


class SearchQuery(StrictRequest):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    project_id: UUID | None = None
    kinds: list[EntityType] = Field(default_factory=list, max_length=12)
    limit: int = Field(default=30, ge=1, le=100)
