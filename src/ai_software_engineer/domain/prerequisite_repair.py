"""Explicit source-changing prerequisite proposals, separate from QA verdicts."""

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.project_delivery import StageSha256, _stage_digest


class PrerequisiteRepairRequest(DomainModel):
    objective: Annotated[str, StringConstraints(min_length=10, max_length=8000)]
    write_paths: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def bounded_scope(self) -> Self:
        ensure_unique(self.write_paths, "repair write paths")
        for value in self.write_paths:
            path = value.removesuffix("/**")
            if (
                PurePosixPath(path).is_absolute()
                or any(part in {"", ".", ".."} or part.startswith(".") for part in path.split("/"))
                or any(c in path for c in "\\*?[")
                or any(ord(c) < 32 for c in value)
                or path in {"AGENTS.md", "CONTEXT.md"}
            ):
                raise ValueError("repair scope requires explicit safe files or subdirectories")
        return self


class PrerequisiteRepairPlan(DomainModel):
    kind: Literal["prerequisite_repair_plan"] = "prerequisite_repair_plan"
    repository_root: NonEmptyStr
    delivery_id: NonEmptyStr
    source_task_id: NonEmptyStr
    source_plan_sha256: StageSha256
    completion_sha256: StageSha256 | None = None
    incident_sha256: StageSha256 | None = None
    executor_prerequisite_sha256: StageSha256 | None = None
    manager_advice_input_sha256: StageSha256 | None = None
    native_checkpoint_sha256: StageSha256
    candidate_revision: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40}$")]
    target_base_revision: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40}$")]
    target_preparation_sha256: StageSha256
    request: PrerequisiteRepairRequest
    created_at: AwareDatetime
    plan_sha256: StageSha256

    @model_validator(mode="after")
    def one_evidence_source(self) -> Self:
        if self.executor_prerequisite_sha256 is None:
            if self.completion_sha256 is None or self.incident_sha256 is None:
                raise ValueError("repair requires a complete QA source or executor prerequisite")
        elif self.completion_sha256 is not None or self.incident_sha256 is not None:
            raise ValueError("repair evidence sources are mutually exclusive")
        return self

    @property
    def source_evidence_sha256(self) -> str:
        value = self.executor_prerequisite_sha256 or self.completion_sha256
        assert value is not None
        return value

    def recompute_sha256(self) -> str:
        return _stage_digest(self, "plan_sha256")

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.recompute_sha256() != self.plan_sha256:
            raise ValueError("prerequisite repair plan digest mismatch")
