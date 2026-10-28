"""Policy-bound recovery authorization; deliberately no execution or model port."""

from __future__ import annotations

from dataclasses import dataclass
from types import MethodType
from typing import TYPE_CHECKING, Protocol, runtime_checkable

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

if TYPE_CHECKING:
    from ai_software_engineer.recovery.current import (
        NativeRecoveryFacts,
        NativeRecoveryFactsVerifier,
    )


@dataclass(frozen=True)
class AuthorizedRecoveryFacts:
    """Local data after a complete current gate; never durable execution authority."""

    plan: RecoveryPlan
    facts: NativeRecoveryFacts


class _AuthorizedRecoveryFactsInspector(Protocol):
    def inspect_current_authorization(self, plan_sha256: str) -> AuthorizedRecoveryFacts: ...


class RecoveryStore(Protocol):
    def put_plan(self, plan: RecoveryPlan) -> RecoveryPlan: ...
    def get_plan(self, plan_sha256: str) -> RecoveryPlan: ...
    def put_authorization(self, authorization: RecoveryAuthorization) -> RecoveryAuthorization: ...
    def find_authorization(self, plan_sha256: str) -> RecoveryAuthorization | None: ...
    def get_authorization(self, plan_sha256: str) -> RecoveryAuthorization: ...


class RecoveryFactsVerifier(Protocol):
    """Trusted composition must resolve native facts, not trust supplied hashes.

    Validate team/project/current failed checkpoint and terminal Task, dispatch,
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


@runtime_checkable
class LegacyRecoveryCaptureVerifier(Protocol):
    """Read-only audit capability; no source writes, patch application or Agent access."""

    def verify_legacy_capture(
        self,
        capture: WorktreeChangeCapture,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> None: ...


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
        plan = self._approved_plan(plan_sha256)
        self._require_current(plan)
        return plan

    def inspect_current_authorization(self, plan_sha256: str) -> AuthorizedRecoveryFacts:
        """Return the last full native observation within this synchronous gate only."""
        verifier = self._native_facts_verifier()
        if verifier is None:
            raise RecoveryRejected("recovery verifier cannot return verified native facts")
        plan = self._approved_plan(plan_sha256)
        plan.validate_integrity()
        plan.require_execution_supported()
        if (
            plan.source.stopped_unknown_settlement_sha256 is not None
            or plan.source.contained_unknown_settlement_sha256 is not None
        ):
            from ai_software_engineer.recovery.current import _uses_standard_native_capture_window

            if _uses_standard_native_capture_window(verifier):
                facts = verifier.inspect_around_capture(plan, lambda: self._verify_capture(plan))
                return AuthorizedRecoveryFacts(plan, facts)
        verifier.inspect(plan)
        self._verify_capture(plan)
        return AuthorizedRecoveryFacts(plan, verifier.inspect(plan))

    def _task_facts_inspector(
        self, verifier: NativeRecoveryFactsVerifier
    ) -> _AuthorizedRecoveryFactsInspector | None:
        # A different trusted port keeps the complete old builder path. Never accept
        # caller-supplied facts or skip a custom verifier's stronger validate policy.
        return self if self._native_facts_verifier() is verifier else None

    def _native_facts_verifier(self) -> NativeRecoveryFactsVerifier | None:
        # Import lazily: current's native composition imports the production backend.
        from ai_software_engineer.recovery.current import (
            _STANDARD_NATIVE_VALIDATE,
            NativeRecoveryFactsVerifier,
        )

        if type(self) is not RecoveryAuthorizationService:
            return None
        for method, standard in (
            (self.require_current_authorization, _STANDARD_SERVICE_AUTHORIZATION),
            (self._require_current, _STANDARD_SERVICE_CURRENT),
        ):
            if (
                not isinstance(method, MethodType)
                or method.__self__ is not self
                or method.__func__ is not standard
            ):
                return None

        if not isinstance(self._facts, NativeRecoveryFactsVerifier) or (
            type(self._facts) is not NativeRecoveryFactsVerifier
        ):
            return None
        validate = self._facts.validate
        if (
            not isinstance(validate, MethodType)
            or validate.__self__ is not self._facts
            or validate.__func__ is not _STANDARD_NATIVE_VALIDATE
        ):
            return None
        return self._facts

    def _approved_plan(self, plan_sha256: str) -> RecoveryPlan:
        plan = self._store.get_plan(plan_sha256)
        receipt = self._store.find_authorization(plan_sha256)
        if receipt is None:
            raise RecoveryRejected("recovery has no approved human decision")
        receipt.validate_integrity()
        if not receipt.decision.approved:
            raise RecoveryRejected("recovery has no approved human decision")
        if receipt.command.plan_sha256 != plan.plan_sha256:
            raise RecoveryRejected("recovery receipt belongs to another plan")
        return plan

    def _require_current(self, plan: RecoveryPlan) -> None:
        plan.validate_integrity()
        plan.require_execution_supported()
        if (
            plan.source.stopped_unknown_settlement_sha256 is not None
            or plan.source.contained_unknown_settlement_sha256 is not None
        ):
            from ai_software_engineer.recovery.current import _uses_standard_native_capture_window

            verifier = self._native_facts_verifier()
            if verifier is not None and _uses_standard_native_capture_window(verifier):
                verifier.inspect_around_capture(plan, lambda: self._verify_capture(plan))
                return
        self._facts.validate(plan)
        self._verify_capture(plan)
        self._facts.validate(plan)

    def _verify_capture(self, plan: RecoveryPlan) -> None:
        if plan.quarantined_paths:
            if not isinstance(self._captures, LegacyRecoveryCaptureVerifier):
                raise RecoveryRejected("恢复执行器缺少只读历史补丁审计能力")
            verify_capture = self._captures.verify_legacy_capture
        else:
            verify_capture = self._captures.verify_capture
        verify_capture(
            plan.capture.to_capture(),
            plan.permissions,
            denied_paths=plan.denied_paths,
        )


# Definition-time references preserve trusted public/protected validation extensions.
# Comparing a bound method to the current class attribute would accept a class override.
_STANDARD_SERVICE_AUTHORIZATION = RecoveryAuthorizationService.require_current_authorization
_STANDARD_SERVICE_CURRENT = RecoveryAuthorizationService._require_current
