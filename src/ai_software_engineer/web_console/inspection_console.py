"""Existing-record Console facade with no delivery executor or worker lifecycle."""

from __future__ import annotations

from collections.abc import Callable

from ai_software_engineer.agents.model_diagnostics import ModelCallDiagnostic
from ai_software_engineer.recovery.preparation_progress import (
    PreparationProgressView,
    preparation_scope,
)

from .core import ConsoleCommandRejected
from .models import ConsoleIntent, ConsoleOperation
from .preparation_store import FilePreparationProgressStore
from .shutdown import ShutdownResult, ShutdownState
from .store import FileConsoleOperationStore
from .summary_models import OperationSummaryPage, OperationSummaryQuery

MAINTENANCE_SUMMARY = (
    "平台处于维护仅查看模式: 可以查看已保存的需求和执行记录; 交付与修改操作已暂停。"
)


class InspectionConsole:
    """A reader, never a dormant ProjectConsole that can reconcile or claim work."""

    def __init__(
        self, store: FileConsoleOperationStore, preparation_store: FilePreparationProgressStore
    ) -> None:
        if not store.read_only or not preparation_store.read_only:
            raise ValueError("仅查看控制台必须使用只读记录存储")
        self._store = store
        self._preparation_store = preparation_store

    def start(self) -> None:
        return None

    def begin_shutdown(self) -> ShutdownResult:
        return ShutdownResult(state=ShutdownState.DRAINING, safe_summary="仅查看服务正在收尾。")

    def await_shutdown(self, timeout: float) -> ShutdownResult:
        return ShutdownResult(state=ShutdownState.READY, safe_summary="本次仅查看服务已经收尾。")

    def cancel_shutdown(self, *, before_resume: Callable[[], None] | None = None) -> ShutdownResult:
        if before_resume is not None:
            before_resume()
        return ShutdownResult(state=ShutdownState.RUNNING, safe_summary="仅查看服务恢复读取。")

    def submit(self, intent: ConsoleIntent, *, idempotency_key: str) -> ConsoleOperation:
        raise ConsoleCommandRejected("SERVICE_MAINTENANCE", MAINTENANCE_SUMMARY)

    def get(self, operation_id: str) -> ConsoleOperation:
        return self._store.get(operation_id)

    def list_operations(self) -> tuple[ConsoleOperation, ...]:
        return self._store.list_current()

    def summary_page(self, query: OperationSummaryQuery) -> OperationSummaryPage:
        return self._store.summary_page(query)

    def model_calls(self, operation_id: str) -> tuple[ModelCallDiagnostic, ...]:
        return self._store.model_calls(operation_id)

    def preparation_progress(self, operation: ConsoleOperation) -> PreparationProgressView:
        scope = preparation_scope(operation)
        return (
            PreparationProgressView(scope=None)
            if scope is None
            else self._preparation_store.read(scope)
        )
