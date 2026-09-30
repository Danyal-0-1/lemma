"""Validated JSON request shapes for the configurable research lab.

The database models describe durable rows; these models are the stricter trust
boundary for browser input. Text and collection limits keep prompts, audit rows,
and meeting fan-out bounded before any model call begins.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, ClassVar
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4_000)]
Mission = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)]
Objective = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6_000)]
Context = Annotated[str, StringConstraints(strip_whitespace=True, max_length=12_000)]
Agenda = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)]
ModelId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]


class DepartmentKind(StrEnum):
    """Whether a group is permanent or assembled for a temporary mission."""

    DEPARTMENT = "department"
    MISSION_TEAM = "mission_team"


class DepartmentStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class AgentStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class CommunicationScope(StrEnum):
    ISOLATED = "isolated"
    DEPARTMENT = "department"
    ORGANIZATION = "organization"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MeetingStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PatchRequest(BaseModel):
    """Reject empty PATCH objects so an update always records a real change."""

    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _must_change_something(self) -> PatchRequest:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        invalid_nulls = sorted(
            field
            for field in self.model_fields_set
            if getattr(self, field) is None and field not in self.nullable_fields
        )
        if invalid_nulls:
            raise ValueError(f"fields may not be null: {', '.join(invalid_nulls)}")
        return self


class DepartmentCreate(BaseModel):
    name: Name
    description: Description = ""
    kind: DepartmentKind = DepartmentKind.DEPARTMENT
    status: DepartmentStatus = DepartmentStatus.ACTIVE


class DepartmentUpdate(PatchRequest):
    name: Name | None = None
    description: Description | None = None
    kind: DepartmentKind | None = None
    status: DepartmentStatus | None = None


class AgentCreate(BaseModel):
    department_id: UUID | None = None
    name: Name
    role: Name
    mission: Mission
    duties: list[ShortText] = Field(default_factory=list, max_length=16)
    focus: list[ShortText] = Field(default_factory=list, max_length=16)
    priorities: list[ShortText] = Field(default_factory=list, max_length=16)
    model: ModelId | None = None
    status: AgentStatus = AgentStatus.ACTIVE
    communication_scope: CommunicationScope = CommunicationScope.DEPARTMENT


class AgentUpdate(PatchRequest):
    nullable_fields: ClassVar[frozenset[str]] = frozenset({"department_id", "model"})

    department_id: UUID | None = None
    name: Name | None = None
    role: Name | None = None
    mission: Mission | None = None
    duties: list[ShortText] | None = Field(default=None, max_length=16)
    focus: list[ShortText] | None = Field(default=None, max_length=16)
    priorities: list[ShortText] | None = Field(default=None, max_length=16)
    model: ModelId | None = None
    status: AgentStatus | None = None
    communication_scope: CommunicationScope | None = None


class ProjectCreate(BaseModel):
    name: Name
    description: Description = ""
    objective: Objective
    status: ProjectStatus = ProjectStatus.ACTIVE


class ProjectUpdate(PatchRequest):
    name: Name | None = None
    description: Description | None = None
    objective: Objective | None = None
    status: ProjectStatus | None = None


class TaskCreate(BaseModel):
    project_id: UUID
    department_id: UUID | None = None
    assigned_agent_id: UUID
    title: Name
    objective: Objective
    context: Context = ""
    expected_output: Description = ""
    status: TaskStatus = TaskStatus.QUEUED


class TaskUpdate(PatchRequest):
    nullable_fields: ClassVar[frozenset[str]] = frozenset({"department_id"})

    department_id: UUID | None = None
    assigned_agent_id: UUID | None = None
    title: Name | None = None
    objective: Objective | None = None
    context: Context | None = None
    expected_output: Description | None = None
    status: TaskStatus | None = None


class MeetingCreate(BaseModel):
    project_id: UUID
    department_id: UUID | None = None
    title: Name
    agenda: Agenda
    facilitator_agent_id: UUID
    participant_ids: list[UUID] = Field(min_length=1, max_length=12)
    status: MeetingStatus = MeetingStatus.PLANNED

    @field_validator("participant_ids")
    @classmethod
    def _participants_are_unique(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("participant_ids must be unique")
        return value


class MeetingUpdate(PatchRequest):
    nullable_fields: ClassVar[frozenset[str]] = frozenset({"department_id"})

    department_id: UUID | None = None
    title: Name | None = None
    agenda: Agenda | None = None
    facilitator_agent_id: UUID | None = None
    participant_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=12)
    status: MeetingStatus | None = None

    @field_validator("participant_ids")
    @classmethod
    def _participants_are_unique(cls, value: list[UUID] | None) -> list[UUID] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("participant_ids must be unique")
        return value


class RunRequest(BaseModel):
    """Optional founder direction added to one run, kept short and untrusted."""

    instructions: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=4_000)
    ] = ""
