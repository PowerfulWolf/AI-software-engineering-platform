"""Immutable resource intents and observations; no execution authority."""

from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.manager.python_verification import PythonMysqlSandboxCapability
from ai_software_engineer.recovery.models import digest


class MysqlResourceIntent(DomainModel):
    plan_sha256: Sha256
    invocation_sha256: Sha256
    role: Literal["qa", "reviewer"]
    capability: PythonMysqlSandboxCapability
    recorded_at: AwareDatetime
    expires_at: AwareDatetime
    resource_id: Sha256
    container_name: str

    @classmethod
    def create(cls, **values: object) -> Self:
        timestamp = values.get("recorded_at")
        if not isinstance(timestamp, datetime):
            raise ValueError("resource requires an explicit creation time")
        content = {**values, "expires_at": timestamp + timedelta(seconds=1200)}
        provisional = cls.model_validate(
            {
                **content,
                "resource_id": "0" * 64,
                "container_name": "ase-verify-" + "0" * 32,
            }
        )
        identity = digest(
            provisional.model_dump(mode="json", exclude={"resource_id", "container_name"})
        )
        return provisional.model_copy(
            update={
                "resource_id": identity,
                "container_name": "ase-verify-" + identity[:32],
            }
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.resource_id != digest(
            self.model_dump(mode="json", exclude={"resource_id", "container_name"})
        ):
            raise ValueError("resource intent identity differs")

    @model_validator(mode="after")
    def fixed_identity(self) -> Self:
        if self.container_name != "ase-verify-" + self.resource_id[
            :32
        ] or self.expires_at - self.recorded_at != timedelta(seconds=1200):
            raise ValueError("resource name or deadline differs")
        return self


class MysqlResourceRecord(DomainModel):
    kind: Literal["python_mysql_resource"] = "python_mysql_resource"
    phase: Literal["INTENT", "CREATED", "CLEANED", "CLEANUP_FAILED"]
    intent: MysqlResourceIntent
    container_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    configuration_sha256: Sha256 | None = None
    recorded_at: AwareDatetime
    record_sha256: Sha256

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_validate({**values, "record_sha256": "0" * 64})
        return provisional.model_copy(update={"record_sha256": provisional.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude_none=True, exclude={"record_sha256"}))

    def validate_integrity(self) -> None:
        self.intent.validate_integrity()
        type(self).model_validate(self.to_wire())
        if self.record_sha256 != self.recompute_sha256():
            raise ValueError("resource record integrity differs")

    @model_validator(mode="after")
    def valid_observation(self) -> Self:
        if self.configuration_sha256 is not None and self.container_id is None:
            raise ValueError("resource configuration digest requires an observed identity")
        if self.recorded_at < self.intent.recorded_at:
            raise ValueError("resource observation predates its intent")
        if self.phase == "INTENT" and (
            self.container_id is not None or self.configuration_sha256 is not None
        ):
            raise ValueError("intent is not a container observation")
        if self.phase == "CREATED" and (
            self.container_id is None or self.configuration_sha256 is None
        ):
            raise ValueError("created resource requires exact observed container")
        return self
