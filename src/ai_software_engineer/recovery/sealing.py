"""Durable carry-forward of an approved Task draft with current-fact admission."""

from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.records import RecoveryTaskRecord
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.task import AuthorizedRecoveryTaskBuilder


class RecoveryTaskSealingService:
    def __init__(self, store: FileRecoveryStore, builder: AuthorizedRecoveryTaskBuilder) -> None:
        self._store, self._builder = store, builder

    def seal(self, plan_sha256: str) -> RecoveryTaskRecord:
        return self._store.put_task_record(self._current_record(plan_sha256))

    def require_current(self, plan_sha256: str) -> RecoveryTaskRecord:
        stored = self._store.get_task_record(plan_sha256)
        if stored != self._current_record(plan_sha256):
            raise RecoveryRejected("sealed recovery Task no longer matches current approved facts")
        return stored

    def _current_record(self, plan_sha256: str) -> RecoveryTaskRecord:
        draft = self._builder.build(plan_sha256)
        return RecoveryTaskRecord.create(draft, self._store.get_authorization(plan_sha256))
