"""Exact human authority to start after a proven pre-execution context failure."""

from typing import Literal, Self

from pydantic import AwareDatetime, model_validator

from ai_software_engineer.context import ContextBudget, ContextSource
from ai_software_engineer.domain.branch import BranchName
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.recovery.models import FullCommit, RecoveryRejected, RecoveryScope, digest


class PreExecutionRestartPlan(DomainModel):
    kind: Literal["pre_execution_restart"] = "pre_execution_restart"
    schema_version: Literal["v0.1"] = "v0.1"
    # Historical plans omit this field.  The preparation-rebind variant uses the
    # same exact approval/storage contract while making its source/target intent
    # explicit and preserving the old digest for legacy records.
    restart_kind: Literal["preparation_rebind", "pre_agent_worktree_conflict"] | None = None
    scope: RecoveryScope
    source_task_id: TaskId
    source_task_sha256: StageSha256
    source_events_sha256: StageSha256
    source_checkpoint_sha256: StageSha256
    source_dispatch_id: NonEmptyStr
    source_dispatch_sha256: StageSha256
    approved_stages_sha256: StageSha256
    parent_delivery_id: NonEmptyStr | None = None
    parent_checkpoint_sha256: StageSha256 | None = None
    target_preparation_sha256: StageSha256
    target_base_revision: FullCommit
    target_branch_name: BranchName | None = None
    config_sha256: StageSha256
    context_policy: Literal["frozen-native-reference-v1"] = "frozen-native-reference-v1"
    context_budget: ContextBudget
    context_sources: tuple[ContextSource, ...] = ()
    created_at: AwareDatetime
    plan_sha256: StageSha256

    @model_validator(mode="after")
    def require_parent_pair(self) -> Self:
        if (self.parent_delivery_id is None) != (self.parent_checkpoint_sha256 is None):
            raise ValueError("restart parent identity must be complete")
        if self.context_budget.used_input_tokens != 0:
            raise ValueError("restart declares a budget, not fabricated context usage")
        return self

    def recompute_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"plan_sha256"})
        # Keep the historical digest shape byte-for-byte when the new mode is
        # absent; only preparation-rebind plans add the discriminator.
        if self.restart_kind is None:
            payload.pop("restart_kind", None)
        return digest(payload)

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.plan_sha256 != self.recompute_sha256():
            raise RecoveryRejected("pre-execution restart plan digest mismatch")
