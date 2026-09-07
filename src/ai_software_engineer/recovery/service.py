"""Policy-bound recovery authorization; deliberately no execution or model port."""

from typing import Protocol

from pydantic import ValidationError

from ai_software_engineer.domain import AgentPermissions
from ai_software_engineer.git import WorktreeChangeCapture
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryAuthorization,
    RecoveryConflict,
    RecoveryPlan,
    RecoveryRejected,
    VerifiedRecoveryDecision,
)


class RecoveryStore(Protocol):
    def put_plan(self, plan: RecoveryPlan) -> RecoveryPlan: ...
    def get_plan(self, plan_sha256: str) -> RecoveryPlan: ...
    def put_authorization(self, authorization: RecoveryAuthorization) -> RecoveryAuthorization: ...
    def find_authorization(self, plan_sha256: str) -> RecoveryAuthorization | None: ...
    def get_authorization(self, plan_sha256: str) -> RecoveryAuthorization: ...


class RecoveryFactsVerifier(Protocol):
    """Trusted composition must resolve native facts, not trust supplied hashes.

    Validate company/project/current failed checkpoint and terminal Task, dispatch,
    approved Product/Design/Plan, failed run/context and effective permissions. Also
    resolve target preparation/base and detect rule/approval drift. No Agent can
    implement/inject this port. Validation must have no state mutation side effects.
    """

    def validate(self, plan: RecoveryPlan) -> None: ...


class RecoveryCaptureVerifier(Protocol):
    def verify_capture(
        self,
        capture: WorktreeChangeCapture,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> None: ...


class HumanRecoveryVerifier(Protocol):
    """Trusted channel; exact command replay must be idempotent across process loss."""

    def verify(self, command: RecoveryApprovalCommand) -> VerifiedRecoveryDecision: ...


class RecoveryAuthorizationService:
    def __init__(
        self,
        store: RecoveryStore,
        *,
        facts: RecoveryFactsVerifier,
        captures: RecoveryCaptureVerifier,
        human: HumanRecoveryVerifier,
    ) -> None:
        self._store, self._facts, self._captures, self._human = store, facts, captures, human

    def propose(self, plan: RecoveryPlan) -> RecoveryPlan:
        self._require_current(plan)
        return self._store.put_plan(plan)

    def authorize(self, command: RecoveryApprovalCommand) -> RecoveryAuthorization:
        command = RecoveryApprovalCommand.model_validate(command.to_wire())
        plan = self._store.get_plan(command.plan_sha256)
        plan.validate_integrity()
        if plan.plan_sha256 != command.plan_sha256:
            raise RecoveryRejected("recovery store returned another plan")
        existing = self._store.find_authorization(command.plan_sha256)
        if existing is not None:
            existing.validate_integrity()
            if existing.command != command:
                raise RecoveryConflict("recovery plan already has a different decision command")
            return existing
        if command.submitted_at < plan.created_at:
            raise RecoveryRejected("recovery approval predates the plan")
        self._require_current(plan)
        decision = self._human.verify(command)
        try:
            receipt = RecoveryAuthorization.create(command, decision)
            receipt.validate_integrity()
        except (ValueError, ValidationError) as error:
            raise RecoveryRejected(
                "human verifier returned an unrelated recovery decision"
            ) from error
        self._require_current(plan)
        return self._store.put_authorization(receipt)

    def require_current_authorization(self, plan_sha256: str) -> RecoveryPlan:
        """Execution admission must call this, never treat receipt replay as freshness."""
        plan = self._store.get_plan(plan_sha256)
        receipt = self._store.find_authorization(plan_sha256)
        if receipt is None:
            raise RecoveryRejected("recovery has no approved human decision")
        receipt.validate_integrity()
        if not receipt.decision.approved:
            raise RecoveryRejected("recovery has no approved human decision")
        if receipt.command.plan_sha256 != plan.plan_sha256:
            raise RecoveryRejected("recovery receipt belongs to another plan")
        self._require_current(plan)
        return plan

    def _require_current(self, plan: RecoveryPlan) -> None:
        plan.validate_integrity()
        self._facts.validate(plan)
        self._captures.verify_capture(
            plan.capture.to_capture(),
            plan.permissions,
            denied_paths=plan.denied_paths,
        )
        self._facts.validate(plan)
