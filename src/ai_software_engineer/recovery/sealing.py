"""Durable carry-forward of an approved Task draft with current-fact admission."""

from types import MethodType

from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.records import RecoveryTaskRecord
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.task import (
    AuthorizedRecoveryTaskBuilder,
    RecoveryTaskDraft,
    _uses_standard_builder,
)
from ai_software_engineer.redaction import source_inspection_scope


class RecoveryTaskSealingService:
    def __init__(self, store: FileRecoveryStore, builder: AuthorizedRecoveryTaskBuilder) -> None:
        self._store, self._builder = store, builder

    @source_inspection_scope()
    def seal(self, plan_sha256: str) -> RecoveryTaskRecord:
        return self._store.put_task_record(self._current_record(plan_sha256))

    @source_inspection_scope()
    def require_current(self, plan_sha256: str) -> RecoveryTaskRecord:
        stored = self._store.get_task_record(plan_sha256)
        if stored != self._current_record(plan_sha256):
            raise RecoveryRejected("sealed recovery Task no longer matches current approved facts")
        return stored

    @source_inspection_scope()
    def require_current_draft(
        self, plan_sha256: str
    ) -> tuple[RecoveryTaskRecord, RecoveryTaskDraft]:
        """Return the draft already used to verify the sealed immutable Task."""
        stored = self._store.get_task_record(plan_sha256)
        draft = self._builder.build(plan_sha256)
        current = RecoveryTaskRecord.create(draft, self._store.get_authorization(plan_sha256))
        if stored != current:
            raise RecoveryRejected("sealed recovery Task no longer matches current approved facts")
        return stored, draft

    @source_inspection_scope()
    def validate_current_against(
        self, sealed: RecoveryTaskRecord, draft: RecoveryTaskDraft
    ) -> None:
        """Fresh source and durable-record checks on both sides of a MySQL fence."""
        plan_sha256 = draft.recovery_plan_sha256
        if self._store.get_task_record(plan_sha256) != sealed:
            raise RecoveryRejected("sealed recovery Task changed inside dispatch fence")
        self._builder.validate_current_against(draft)
        if self._store.get_task_record(plan_sha256) != sealed:
            raise RecoveryRejected("sealed recovery Task changed inside dispatch fence")

    @source_inspection_scope()
    def require_current_dispatch(self, dispatch: RecoveryDispatchRecord) -> RecoveryTaskRecord:
        """Recheck one committed Task lineage and complete current facts at role admission."""
        plan_sha256 = dispatch.recovery_plan_sha256
        if not _uses_standard_sealing(self):
            return self.require_current(plan_sha256)
        dispatch.validate_integrity()
        stored = self._store.get_task_record(plan_sha256)
        if (
            dispatch.task != stored.task
            or dispatch.task_id != stored.task.id
            or dispatch.project_request_id != stored.rebound_request.id
            or dispatch.recovery_task_record_sha256 != stored.record_sha256
        ):
            raise RecoveryRejected("dispatch is not bound to current sealed Task")
        inspector = self._builder._authorization._task_facts_inspector(self._builder._facts)
        if inspector is None:
            return self.require_current(plan_sha256)
        current = inspector.inspect_current_authorization(plan_sha256)
        if current.plan.plan_sha256 != plan_sha256:
            raise RecoveryRejected("dispatch recovery plan changed during role admission")
        if self._store.get_task_record(plan_sha256) != stored:
            raise RecoveryRejected("sealed recovery Task changed during role admission")
        return stored

    def _current_record(self, plan_sha256: str) -> RecoveryTaskRecord:
        draft = self._builder.build(plan_sha256)
        return RecoveryTaskRecord.create(draft, self._store.get_authorization(plan_sha256))


_STANDARD_REQUIRE_CURRENT = RecoveryTaskSealingService.require_current
_STANDARD_CURRENT_RECORD = RecoveryTaskSealingService._current_record
_STANDARD_REQUIRE_CURRENT_DRAFT = RecoveryTaskSealingService.require_current_draft
_STANDARD_VALIDATE_CURRENT_AGAINST = RecoveryTaskSealingService.validate_current_against
_STANDARD_REQUIRE_CURRENT_DISPATCH = RecoveryTaskSealingService.require_current_dispatch


def _uses_standard_sealing(service: RecoveryTaskSealingService) -> bool:
    if type(service) is not RecoveryTaskSealingService or not _uses_standard_builder(
        service._builder
    ):
        return False
    for method, expected in (
        (service.require_current, _STANDARD_REQUIRE_CURRENT),
        (service._current_record, _STANDARD_CURRENT_RECORD),
        (service.require_current_draft, _STANDARD_REQUIRE_CURRENT_DRAFT),
        (service.validate_current_against, _STANDARD_VALIDATE_CURRENT_AGAINST),
        (service.require_current_dispatch, _STANDARD_REQUIRE_CURRENT_DISPATCH),
    ):
        if (
            not isinstance(method, MethodType)
            or method.__self__ is not service
            or method.__func__ is not expected
        ):
            return False
    return True
