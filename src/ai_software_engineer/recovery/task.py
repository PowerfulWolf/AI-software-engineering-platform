"""Authorized in-process Task draft; no database/dispatch or historical record writes."""

from dataclasses import dataclass

from ai_software_engineer.domain import ProjectRequest, Task
from ai_software_engineer.domain.project_delivery import derive_delivery_task
from ai_software_engineer.recovery.current import NativeRecoveryFacts, NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.service import RecoveryAuthorizationService


@dataclass(frozen=True)
class RecoveryTaskDraft:
    recovery_plan_sha256: str
    facts: NativeRecoveryFacts
    rebound_request: ProjectRequest
    task: Task


class AuthorizedRecoveryTaskBuilder:
    def __init__(
        self, authorization: RecoveryAuthorizationService, facts: NativeRecoveryFactsVerifier
    ) -> None:
        self._authorization, self._facts = authorization, facts

    def build(self, plan_sha256: str) -> RecoveryTaskDraft:
        plan = self._authorization.require_current_authorization(plan_sha256)
        facts = self._facts.inspect(plan)
        original = facts.original
        request = original.request
        if plan.created_at < request.updated_at:
            raise RecoveryRejected("recovery plan predates the approved request")
        rebound = ProjectRequest.create(
            request_id=request.id,
            project_id=request.project_id,
            preparation_sha256=facts.target.preparation_sha256,
            title=request.title,
            original_request=request.original_request,
            status=request.status,
            created_at=request.created_at,
            updated_at=plan.created_at,
        )
        task = derive_delivery_task(
            facts.target,
            rebound,
            original.product,
            original.approval,
            original.design,
            original.plan,
            task_id=plan.new_task_id,
            repository=facts.target.project_root,
            base_ref=plan.target_base_revision,
            max_attempts=original.task.max_attempts,
            created_at=plan.created_at,
            constraints=original.task.constraints,
            owner=original.task.owner,
            labels=original.task.labels,
        )
        task = Task.model_validate(
            {
                **task.to_wire(),
                "metadata": {
                    **task.metadata,
                    "recovery_plan_sha256": plan.plan_sha256,
                    "recovery_of_task_id": plan.source.task_id,
                    "recovery_of_delivery_id": plan.source.scope.delivery_id,
                    "recovery_source_checkpoint_sha256": plan.source.checkpoint_sha256,
                    "recovery_original_request_sha256": request.request_sha256,
                    "recovery_rebound_request_sha256": rebound.request_sha256,
                    "recovery_target_preparation_sha256": facts.target.preparation_sha256,
                },
            }
        )
        # A draft is deterministic data, not a durable dispatch authorization.
        if self._authorization.require_current_authorization(plan_sha256) != plan:
            raise RecoveryRejected("recovery plan changed while building Task")
        return RecoveryTaskDraft(plan.plan_sha256, facts, rebound, task)
