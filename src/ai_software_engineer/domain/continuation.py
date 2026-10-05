"""Versioned organization engineering authority for one checked Coder continuation.

Possession of this policy is not a workspace admission. A deterministic service must
still prove stopped execution, exact mutation facts, remaining budget and a fresh
claim, and consume a separate one-use admission before another Agent invocation.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictInt, model_validator

from ai_software_engineer.domain.model import DomainModel

if TYPE_CHECKING:
    from ai_software_engineer.domain.task import Task

ContinuationCause = Literal["local_execution_limit", "provider_transient"]
ContinuationChange = Literal["text_added", "text_modified", "text_deleted", "regular_mode_changed"]


class InterruptionContinuationPolicy(DomainModel):
    """Frozen narrow capability; legacy Tasks have no implicit authorization."""

    kind: Literal["interruption_continuation_policy"] = "interruption_continuation_policy"
    schema_version: Literal["v1", "v2"] = "v1"
    authorization_source: Literal["organization_engineering_policy"] = (
        "organization_engineering_policy"
    )
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"schema_version": {"const": "v1"}}},
                    "then": {
                        "properties": {
                            "capability_id": {"const": "git-text-mutation-inventory-v1"},
                            "max_continuations": {"const": 1},
                            "allowed_changes": {"const": ["text_added", "text_modified"]},
                        }
                    },
                    "else": {
                        "required": ["capability_id", "allowed_changes"],
                        "properties": {
                            "capability_id": {"const": "git-regular-text-mutation-inventory-v2"},
                            "allowed_changes": {
                                "const": [
                                    "text_added",
                                    "text_modified",
                                    "text_deleted",
                                    "regular_mode_changed",
                                ]
                            },
                        },
                    },
                }
            ]
        }
    )
    capability_id: Literal[
        "git-text-mutation-inventory-v1", "git-regular-text-mutation-inventory-v2"
    ] = "git-text-mutation-inventory-v1"
    max_continuations: Annotated[StrictInt, Field(ge=1, le=199)] = 1
    allowed_causes: tuple[Literal["local_execution_limit"], Literal["provider_transient"]] = (
        "local_execution_limit",
        "provider_transient",
    )
    allowed_changes: tuple[ContinuationChange, ...] = (
        "text_added",
        "text_modified",
    )

    @model_validator(mode="after")
    def validate_versioned_authority(self) -> Self:
        if self.schema_version == "v1":
            if (
                self.capability_id != "git-text-mutation-inventory-v1"
                or self.max_continuations != 1
                or self.allowed_changes != ("text_added", "text_modified")
            ):
                raise ValueError("v1 continuation authority permits exactly one text continuation")
        elif (
            self.capability_id != "git-regular-text-mutation-inventory-v2"
            or self.allowed_changes
            != ("text_added", "text_modified", "text_deleted", "regular_mode_changed")
        ):
            raise ValueError("v2 continuation authority requires its exact regular-text capability")
        return self

    @classmethod
    def for_retry_budget(cls, *, max_work_attempts: int, max_coder_transient_failures: int) -> Self:
        return cls(
            schema_version="v2",
            capability_id="git-regular-text-mutation-inventory-v2",
            allowed_changes=("text_added", "text_modified", "text_deleted", "regular_mode_changed"),
            max_continuations=max(1, max_work_attempts + max_coder_transient_failures - 1),
        )

    @property
    def policy_sha256(self) -> str:
        """Bind the entire policy without changing the serialized Task payload."""
        canonical = json.dumps(
            self.to_wire(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def task_intent_sha256(task: Task) -> str:
    """Bind frozen dispatch intent while retaining independent execution accounting.

    Task status, execution reservation, timestamp and retry failures change during
    normal delivery. The retry allowance and continuation authority are frozen
    intent and remain bound together with source, scope and path permissions.
    """
    payload = task.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"status", "attempts", "updated_at", "retry_failures"},
    )
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
