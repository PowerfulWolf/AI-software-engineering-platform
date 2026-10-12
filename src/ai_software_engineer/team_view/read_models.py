"""Versioned current-fact summaries and exact, complete read-only resource details."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator
from pydantic.json_schema import JsonSchemaValue

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.coordination import ManagerCoordinationAdvice
from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import ProductSpecId
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.knowledge.gaps import GapRoute
from ai_software_engineer.knowledge.views import KnowledgeGapView
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.multi_directory.budget import DesignBudget, StageBudget

from .models import (
    AgentView,
    AssignmentView,
    DeliveryExecutionView,
    ProjectView,
    RequestView,
    RoleQueueView,
    ScopeView,
    TaskView,
    TeamReadError,
)

TEAM_READ_CONTRACT_VERSION = "v0.1"
ResourceId = Annotated[
    str,
    StringConstraints(pattern=r"^(?:delivery_[a-z0-9][a-z0-9_-]{2,95}|verification_[a-f0-9]{32})$"),
]
TaskRevision = Annotated[int, Field(strict=True, ge=0)]
WorkKind = Literal["delivery", "candidate_verification", "remediation"]


def _locator_schema(schema: JsonSchemaValue, *, query: bool = False) -> None:
    """Keep the statically expressible variant gates in every generated schema."""
    kind = "kind" if query else "resource_kind"
    identity = "id" if query else "resource_id"
    prefix = "expected_" if query else ""
    work = prefix + "work_kind"
    task = tuple(prefix + key for key in ("task_id", "task_revision", "task_intent_sha256"))
    verification = tuple(prefix + key for key in ("source_task_id", "verification_plan_sha256"))
    empty = {field: {"type": "null"} for field in (work, *task, *verification)}
    schema["allOf"] = [
        {
            "oneOf": [
                {
                    "properties": {
                        kind: {"const": "request"},
                        identity: {"pattern": r"^delivery_"},
                        **empty,
                    }
                },
                {
                    "required": [work],
                    "properties": {
                        kind: {"const": "task"},
                        identity: {"pattern": r"^delivery_"},
                        work: {"enum": ["delivery", "remediation"]},
                        **{field: {"type": "null"} for field in verification},
                    },
                    "oneOf": [
                        {"properties": {field: {"type": "null"} for field in task}},
                        {
                            "required": list(task),
                            "properties": {
                                task[0]: {"type": "string"},
                                task[1]: {"type": "integer"},
                                task[2]: {"type": "string"},
                            },
                        },
                    ],
                },
                {
                    "required": [work, task[0], *verification],
                    "properties": {
                        kind: {"const": "task"},
                        identity: {"pattern": r"^verification_"},
                        work: {"const": "candidate_verification"},
                        task[0]: {"type": "string"},
                        task[1]: {"type": "null"},
                        task[2]: {"type": "null"},
                        **{field: {"type": "string"} for field in verification},
                    },
                },
            ]
        }
    ]


def _query_schema(schema: JsonSchemaValue) -> None:
    _locator_schema(schema, query=True)


def _source_schema(schema: JsonSchemaValue) -> None:
    _locator_schema(schema)


class TeamDetailSource(DomainModel):
    """Reading locator only; no approval or permission can be inferred from it."""

    model_config = ConfigDict(json_schema_extra=_source_schema)

    team_id: TeamId
    project_id: ProjectId
    request_id: DeliveryId
    resource_kind: Literal["request", "task"]
    resource_id: ResourceId
    requirement_checkpoint_sha256: Sha256
    resource_checkpoint_sha256: Sha256
    resource_state_sha256: Sha256
    work_kind: WorkKind | None = None
    task_id: TaskId | None = None
    task_revision: TaskRevision | None = None
    task_intent_sha256: Sha256 | None = None
    source_task_id: TaskId | None = None
    verification_plan_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def exact_variant(self) -> Self:
        if self.resource_kind == "request":
            if (
                self.resource_id != self.request_id
                or self.resource_checkpoint_sha256 != self.requirement_checkpoint_sha256
                or any(
                    value is not None
                    for value in (
                        self.work_kind,
                        self.task_id,
                        self.task_revision,
                        self.task_intent_sha256,
                        self.source_task_id,
                        self.verification_plan_sha256,
                    )
                )
            ):
                raise ValueError("request reading locator contains foreign Task facts")
        elif self.work_kind == "candidate_verification":
            if (
                self.task_id is None
                or self.source_task_id is None
                or self.task_id == self.source_task_id
                or self.verification_plan_sha256 is None
                or self.task_revision is not None
                or self.task_intent_sha256 is not None
                or self.resource_id != "verification_" + self.verification_plan_sha256[:32]
            ):
                raise ValueError("verification reading locator must use its real reservation")
        else:
            identity = (self.task_id, self.task_revision, self.task_intent_sha256)
            if (
                self.work_kind not in {"delivery", "remediation"}
                or (any(value is not None for value in identity) and None in identity)
                or self.source_task_id is not None
                or self.verification_plan_sha256 is not None
                or not self.resource_id.startswith("delivery_")
            ):
                raise ValueError("delivery reading locator has incomplete or foreign Task facts")
        return self


class TeamDetailQuery(DomainModel):
    model_config = ConfigDict(json_schema_extra=_query_schema)

    team_id: TeamId
    project_id: ProjectId
    request_id: DeliveryId
    kind: Literal["request", "task"]
    id: ResourceId
    expected_requirement_checkpoint_sha256: Sha256
    expected_resource_checkpoint_sha256: Sha256
    expected_resource_state_sha256: Sha256
    expected_work_kind: WorkKind | None = None
    expected_task_id: TaskId | None = None
    expected_task_revision: TaskRevision | None = None
    expected_task_intent_sha256: Sha256 | None = None
    expected_source_task_id: TaskId | None = None
    expected_verification_plan_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def exact_variant(self) -> Self:
        self.source()
        return self

    def source(self) -> TeamDetailSource:
        return TeamDetailSource(
            team_id=self.team_id,
            project_id=self.project_id,
            request_id=self.request_id,
            resource_kind=self.kind,
            resource_id=self.id,
            requirement_checkpoint_sha256=self.expected_requirement_checkpoint_sha256,
            resource_checkpoint_sha256=self.expected_resource_checkpoint_sha256,
            resource_state_sha256=self.expected_resource_state_sha256,
            work_kind=self.expected_work_kind,
            task_id=self.expected_task_id,
            task_revision=self.expected_task_revision,
            task_intent_sha256=self.expected_task_intent_sha256,
            source_task_id=self.expected_source_task_id,
            verification_plan_sha256=self.expected_verification_plan_sha256,
        )

    @classmethod
    def from_source(cls, source: TeamDetailSource) -> Self:
        return cls(
            team_id=source.team_id,
            project_id=source.project_id,
            request_id=source.request_id,
            kind=source.resource_kind,
            id=source.resource_id,
            expected_requirement_checkpoint_sha256=source.requirement_checkpoint_sha256,
            expected_resource_checkpoint_sha256=source.resource_checkpoint_sha256,
            expected_resource_state_sha256=source.resource_state_sha256,
            expected_work_kind=source.work_kind,
            expected_task_id=source.task_id,
            expected_task_revision=source.task_revision,
            expected_task_intent_sha256=source.task_intent_sha256,
            expected_source_task_id=source.source_task_id,
            expected_verification_plan_sha256=source.verification_plan_sha256,
        )


def _product_spec_source_schema(schema: JsonSchemaValue) -> None:
    schema["oneOf"] = [
        {
            "required": ["spec_id"],
            "properties": {
                "spec_id": {"type": "string"},
                "version": {"type": "null"},
                "source_uri": {"pattern": r"^ProductSpec://product_spec_"},
            },
        },
        {
            "required": ["version"],
            "properties": {
                "spec_id": {"type": "null"},
                "version": {"type": "integer"},
                "source_uri": {"pattern": r"^request://delivery_"},
            },
        },
    ]


class ProductSpecSource(DomainModel):
    model_config = ConfigDict(json_schema_extra=_product_spec_source_schema)

    spec_id: ProductSpecId | None = None
    version: Annotated[int, Field(strict=True, ge=1)] | None = None
    sha256: Sha256
    source_uri: str

    @model_validator(mode="after")
    def exact_original_kind(self) -> Self:
        if (self.spec_id is None) == (self.version is None):
            raise ValueError("ProductSpec source must retain its real native ID or joint version")
        if self.spec_id is not None:
            if self.source_uri != f"ProductSpec://{self.spec_id}":
                raise ValueError("native ProductSpec source changed its actual identity")
        elif not self.source_uri.startswith("request://delivery_") or not self.source_uri.endswith(
            "/ProductSpec"
        ):
            raise ValueError("joint ProductSpec source has no real Request document identity")
        return self


class RequestSummary(DomainModel):
    id: str
    project_id: str
    title: str
    stage: str
    scopes: tuple[ScopeView, ...]
    next_action: str
    blocker: str | None = None
    execution: DeliveryExecutionView | None = None
    failed_stages: tuple[str, ...] = ()
    checkpoint_sha256: str
    knowledge_gap: KnowledgeGapView | None = None
    knowledge_wait_stage: str | None = None
    knowledge_route: GapRoute | None = None
    design_recheck_available: bool = False
    design_recheck_pending: bool = False
    knowledge_rechecked_gap_ids: tuple[str, ...] = ()
    design_recovery_available: bool = False
    design_budget: DesignBudget | None = None
    stage_budget: StageBudget | None = None
    coordination: ManagerCoordinationAdvice | None = None
    detail_source: TeamDetailSource
    product_spec_source: ProductSpecSource | None = None

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        _require_request_source(self.detail_source, self)
        spec = self.product_spec_source
        if spec is not None and spec.source_uri != (
            f"request://{self.id}/ProductSpec"
            if spec.spec_id is None
            else f"ProductSpec://{spec.spec_id}"
        ):
            raise ValueError("ProductSpec reading locator changed its exact source")
        return self


class TaskSummary(DomainModel):
    id: str
    project_id: str
    request_id: str
    work_kind: WorkKind = "delivery"
    task_id: str | None = None
    task_revision: int | None = None
    task_intent_sha256: str | None = None
    source_delivery_id: str | None = None
    source_task_id: str | None = None
    plan_sha256: str | None = None
    title: str
    scope: ScopeView
    status: str
    checkpoint_stage: str
    terminal: bool
    last_activity: AwareDatetime
    execution_liveness: Literal["UNKNOWN"] = "UNKNOWN"
    execution: DeliveryExecutionView | None = None
    failure_code: str | None = None
    blocker: str | None = None
    next_action: str
    candidate_revision: str | None = None
    candidate_branch: str | None = None
    role_queue: tuple[RoleQueueView, ...] = ()
    assignments: tuple[AssignmentView, ...] = ()
    history_task_ids: tuple[str, ...] = ()
    detail_source: TeamDetailSource

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        _require_task_source(self.detail_source, self)
        return self


class TeamSummary(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    as_of: AwareDatetime
    team_id: str
    team_name: str
    selected_project_id: str | None = None
    projects: tuple[ProjectView, ...] = ()
    agents: tuple[AgentView, ...] = ()
    requests: tuple[RequestSummary, ...] = ()
    tasks: tuple[TaskSummary, ...] = ()

    @model_validator(mode="after")
    def exact_inventory(self) -> Self:
        requests = {item.id: item for item in self.requests}
        if len(requests) != len(self.requests) or len({item.id for item in self.tasks}) != len(
            self.tasks
        ):
            raise ValueError("duplicate Team summary resource identity")
        resources: tuple[RequestSummary | TaskSummary, ...] = (*self.requests, *self.tasks)
        for resource in resources:
            source = resource.detail_source
            owner = requests.get(source.request_id)
            if (
                source.team_id != self.team_id
                or source.project_id != self.selected_project_id
                or owner is None
                or owner.checkpoint_sha256 != source.requirement_checkpoint_sha256
            ):
                raise ValueError("Team summary resource changed its verified owner")
        return self


class RequestDetail(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    kind: Literal["request"] = "request"
    as_of: AwareDatetime
    scope: TeamDetailSource
    resource: RequestView

    @model_validator(mode="after")
    def exact_resource(self) -> Self:
        _require_request_source(self.scope, self.resource)
        return self


class TaskDetail(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    kind: Literal["task"] = "task"
    as_of: AwareDatetime
    scope: TeamDetailSource
    resource: TaskView

    @model_validator(mode="after")
    def exact_resource(self) -> Self:
        _require_task_source(self.scope, self.resource)
        return self


def _require_request_source(
    source: TeamDetailSource, resource: RequestSummary | RequestView
) -> None:
    if (
        source.resource_kind != "request"
        or source.resource_id != resource.id
        or source.project_id != resource.project_id
        or source.requirement_checkpoint_sha256 != resource.checkpoint_sha256
    ):
        raise ValueError("request changed its reading source")


def _require_task_source(source: TeamDetailSource, resource: TaskSummary | TaskView) -> None:
    if (
        source.resource_kind != "task"
        or source.resource_id != resource.id
        or source.project_id != resource.project_id
        or source.request_id != resource.request_id
        or source.work_kind != resource.work_kind
        or source.task_id != resource.task_id
        or source.task_revision != resource.task_revision
        or source.task_intent_sha256 != resource.task_intent_sha256
        or (
            resource.work_kind == "candidate_verification"
            and (
                source.verification_plan_sha256 != resource.plan_sha256
                or source.source_task_id != resource.source_task_id
            )
        )
    ):
        raise ValueError("task changed its reading source")


TeamDetail = Annotated[RequestDetail | TaskDetail, Field(discriminator="kind")]


class TeamDetailNotFound(TeamReadError):
    """The requested object is absent from the verified selected inventory."""


class TeamDetailStale(TeamReadError):
    """The exact reading source changed; no stale body was returned."""
