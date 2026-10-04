"""Versioned organization engineering authority for one checked Coder continuation.

Possession of this policy is not a workspace admission. A deterministic service must
still prove stopped execution, exact mutation facts, remaining budget and a fresh
claim, and consume a separate one-use admission before another Agent invocation.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, StrictInt

from ai_software_engineer.domain.model import DomainModel

if TYPE_CHECKING:
    from ai_software_engineer.domain.task import Task

ContinuationCause = Literal["local_execution_limit", "provider_transient"]
ContinuationChange = Literal["text_added", "text_modified"]


class InterruptionContinuationPolicy(DomainModel):
    """Frozen narrow capability; legacy Tasks have no implicit authorization."""

    kind: Literal["interruption_continuation_policy"] = "interruption_continuation_policy"
    schema_version: Literal["v1"] = "v1"
    authorization_source: Literal["organization_engineering_policy"] = (
        "organization_engineering_policy"
    )
    capability_id: Literal["git-text-mutation-inventory-v1"] = "git-text-mutation-inventory-v1"
    max_continuations: Annotated[StrictInt, Field(ge=1, le=1, json_schema_extra={"const": 1})] = 1
    allowed_causes: tuple[Literal["local_execution_limit"], Literal["provider_transient"]] = (
        "local_execution_limit",
        "provider_transient",
    )
    allowed_changes: tuple[Literal["text_added"], Literal["text_modified"]] = (
        "text_added",
        "text_modified",
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
