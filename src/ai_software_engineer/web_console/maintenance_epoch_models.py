"""Exact predecessor bytes for a separately authorized local maintenance epoch."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.model import DomainModel

type MaintenanceControlName = Literal[
    "console-inspection.json",
    "console-maintenance-completed.json",
    "console-maintenance-admitted.json",
]


class MaintenanceControlFile(DomainModel):
    name: MaintenanceControlName
    sha256: Sha256
    byte_count: Annotated[StrictInt, Field(gt=0, le=2 * 1024 * 1024)]


class MaintenanceCompletionFile(DomainModel):
    plan_sha256: Sha256
    name: Literal["plan.json", "receipt.json"]
    sha256: Sha256
    byte_count: Annotated[StrictInt, Field(gt=0, le=2 * 1024 * 1024)]


class PreviousMaintenanceEpoch(DomainModel):
    marker_sha256: Sha256
    completion_sha256: Sha256
    admission_sha256: Sha256
    controls: Annotated[tuple[MaintenanceControlFile, ...], Field(min_length=3, max_length=3)]
    completion_files: Annotated[
        tuple[MaintenanceCompletionFile, ...], Field(min_length=2, max_length=2048)
    ]

    @model_validator(mode="after")
    def exact_inventory(self) -> Self:
        if tuple(ref.name for ref in self.controls) != (
            "console-inspection.json",
            "console-maintenance-completed.json",
            "console-maintenance-admitted.json",
        ):
            raise ValueError("maintenance controls must be exact")
        keys = tuple((ref.plan_sha256, ref.name) for ref in self.completion_files)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("maintenance completion inventory must be unique and sorted")
        return self
