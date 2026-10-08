"""Deep application module for durable browser-submitted Manager work."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from threading import Condition, Event, Lock, Thread, current_thread
from time import monotonic
from typing import Protocol

from ai_software_engineer.agents.model_diagnostics import ModelCallDiagnostic, capture_model_calls

from .models import ConsoleCommandResult, ConsoleIntent, ConsoleOperation
from .shutdown import ShutdownResult, ShutdownState, shutdown_deadline
from .store import ConsoleOperationError, ConsoleOperationStore

_LOGGER = logging.getLogger(__name__)


class ConsoleCommandRejected(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary


class ManagerConsolePort(Protocol):
    def execute(self, intent: ConsoleIntent) -> ConsoleCommandResult: ...


Clock = Callable[[], datetime]


class ProjectConsole:
    """Persist user intent first, then dispatch it independently from the HTTP request."""

    def __init__(
        self,
        *,
        store: ConsoleOperationStore,
        executor: ManagerConsolePort,
        clock: Clock | None = None,
        poll_seconds: float = 0.25,
        operation_scope: Callable[[str], AbstractContextManager[None]] | None = None,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("console poll interval must be positive")
        self._store = store
        self._executor = executor
        self._clock = clock or (lambda: datetime.now(UTC))
        self._poll_seconds = poll_seconds
        self._operation_scope = operation_scope or (lambda _: nullcontext())
        self._wake = Event()
        self._stop = Event()
        self._lifecycle = Lock()
        self._condition = Condition(self._lifecycle)
        self._thread: Thread | None = None
        self._threads: set[Thread] = set()
        self._started = False
        self._draining = False
        self._ready = False
        self._timed_out = False
        self._shutdown_failure: str | None = None
        self._active_operations = 0

    def submit(self, intent: ConsoleIntent, *, idempotency_key: str) -> ConsoleOperation:
        with self._lifecycle:
            self._require_admission_locked()
            operation = self._store.submit(
                intent=intent,
                idempotency_key=idempotency_key,
                requested_at=self._clock(),
            )
        self._wake.set()
        return operation

    def get(self, operation_id: str) -> ConsoleOperation:
        return self._store.get(operation_id)

    def list_operations(self) -> tuple[ConsoleOperation, ...]:
        return self._store.list_current()

    def model_calls(self, operation_id: str) -> tuple[ModelCallDiagnostic, ...]:
        return self._store.model_calls(operation_id)

    def _record_model_call(self, operation_id: str, call: ModelCallDiagnostic) -> None:
        try:
            self._store.record_model_call(operation_id, call)
        except (ConsoleOperationError, OSError, ValueError):
            # Observability must not turn successful delivery into a retry/billing risk.
            _LOGGER.error("Model call diagnostics could not be stored for %s", operation_id)

    def run_once(self) -> ConsoleOperation | None:
        with self._condition:
            if self._draining or self._active_operations:
                return None
            try:
                running = self._store.claim_next(at=self._clock())
            except BaseException:
                self._refuse_locked(
                    "操作领取记录未能可靠保存, 不能确认安全停止; 服务保留, 需检查记录保存故障。"
                )
                raise
            if running is None:
                return None
            self._active_operations += 1
        persisted = False
        try:
            # Keep process ownership attached through both execution and durable
            # operation finalization. Scope exit itself is not process-stop proof.
            with self._operation_scope(running.operation_id):
                completed = self._execute_operation(running)
            persisted = True
            return completed
        finally:
            with self._condition:
                self._active_operations -= 1
                if not persisted:
                    self._refuse_locked(
                        "操作最终记录未能可靠保存, 不能确认安全停止; 服务保留, 需检查记录保存故障。"
                    )
                self._condition.notify_all()

    def _execute_operation(self, running: ConsoleOperation) -> ConsoleOperation:
        try:
            with capture_model_calls(
                lambda call: self._record_model_call(running.operation_id, call)
            ):
                result = self._executor.execute(running.intent)
        except ConsoleCommandRejected as error:
            return self._store.fail(
                running.operation_id,
                expected=running.operation_sha256,
                error_code=error.code,
                error_summary=error.safe_summary,
                at=self._clock(),
            )
        except Exception as error:
            # Correlate unknown failures without serializing payloads, secrets or traceback.
            error_type = type(error).__name__
            if not error_type.isascii() or not error_type.isidentifier():
                error_type = "Exception"
            error_type = error_type[:80]
            locations = []
            frame = error.__traceback__
            while frame is not None:
                module = frame.tb_frame.f_globals.get("__name__", "")
                if isinstance(module, str) and module.startswith("ai_software_engineer."):
                    locations.append(f"{module}:{frame.tb_lineno}")
                frame = frame.tb_next
            _LOGGER.error(
                "Console operation %s failed with %s; locations=%s",
                running.operation_id,
                error_type,
                ", ".join(locations[-4:]),
            )
            return self._store.fail(
                running.operation_id,
                expected=running.operation_sha256,
                error_code="MANAGER_FAILURE",
                error_summary=f"Manager 执行异常({error_type}); "
                "尚未获得具体原因。请提供此操作编号排查, 不要反复重试。",
                at=self._clock(),
            )
        return self._store.succeed(
            running.operation_id,
            expected=running.operation_sha256,
            result=result,
            at=self._clock(),
        )

    def start(self) -> None:
        with self._lifecycle:
            self._require_admission_locked()
            if self._thread is not None and self._thread.is_alive():
                return
            if self._active_operations:
                raise RuntimeError(
                    "console cannot start while a directly claimed operation is active"
                )
            try:
                self._store.interrupt_running(at=self._clock())
            except BaseException:
                self._refuse_locked(
                    "启动时无法可靠核验遗留操作记录, 不能确认安全停止; 服务保留, 需检查执行记录。"
                )
                raise
            self._stop.clear()
            self._started = True
            self._start_thread_locked()

    def begin_shutdown(self) -> ShutdownResult:
        with self._condition:
            self._draining = True
            self._stop.set()
            self._wake.set()
            return self._result_locked()

    def await_shutdown(self, timeout: float) -> ShutdownResult:
        deadline = shutdown_deadline(timeout)
        while True:
            with self._condition:
                if not self._draining or self._shutdown_failure is not None:
                    return self._result_locked()
                if self._active_operations:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        self._timed_out = True
                        return self._result_locked()
                    self._condition.wait(remaining)
                    continue
                threads = tuple(thread for thread in self._threads if thread.is_alive())
                if not threads:
                    self._threads.clear()
                    self._ready = True
                    self._timed_out = False
                    return self._result_locked()
            for thread in threads:
                remaining = max(0.0, deadline - monotonic())
                if thread is current_thread():
                    with self._condition:
                        self._timed_out = True
                        return self._result_locked()
                thread.join(remaining)
            if monotonic() >= deadline:
                with self._condition:
                    if any(thread.is_alive() for thread in self._threads):
                        self._timed_out = True
                        return self._result_locked()

    def cancel_shutdown(self, *, before_resume: Callable[[], None] | None = None) -> ShutdownResult:
        with self._condition:
            if self._shutdown_failure is not None:
                return self._result_locked()
            try:
                if self._started and self._thread is None:
                    # Prepare a fallible thread while admission is still closed.
                    # Its first claim must wait for this same condition lock.
                    self._start_thread_locked()
                if before_resume is not None:
                    before_resume()
            except Exception:
                self._refuse_locked("解除安全停止记录未能可靠保存, 服务保持只读。")
                return self._result_locked()
            self._draining = False
            self._ready = False
            self._timed_out = False
            self._stop.clear()
            self._wake.set()
            self._condition.notify_all()
            return self._result_locked()

    def shutdown_status(self) -> ShutdownResult:
        with self._condition:
            return self._result_locked()

    def close(self, *, timeout: float = 5.0) -> ShutdownResult:
        shutdown_deadline(timeout)
        self.begin_shutdown()
        return self.await_shutdown(timeout)

    def _require_admission_locked(self) -> None:
        if self._draining:
            raise ConsoleCommandRejected(
                "SERVICE_DRAINING",
                "ASE 正在安全停止, 暂不接收新的操作; 请等待收尾或解除安全停止后重试。",
            )

    def _start_thread_locked(self) -> None:
        self._threads = {thread for thread in self._threads if thread.is_alive()}
        self._thread = Thread(target=self._run, name="project-console-dispatcher", daemon=True)
        self._threads.add(self._thread)
        self._thread.start()

    def _refuse_locked(self, safe_summary: str) -> None:
        self._shutdown_failure = safe_summary
        self._draining = True
        self._stop.set()
        self._wake.set()
        self._condition.notify_all()

    def _result_locked(self) -> ShutdownResult:
        if self._shutdown_failure is not None:
            state = ShutdownState.REFUSED
            summary = self._shutdown_failure
        elif not self._draining:
            state = ShutdownState.RUNNING
            summary = "ASE 正常接收操作。"
        elif self._ready:
            state = ShutdownState.READY
            summary = "当前操作最终记录已保存, 执行调度线程已安全停止。"
        elif self._timed_out:
            state = ShutdownState.REFUSED
            summary = "当前操作仍在收尾, 未安全停止; 服务保留, 可稍后重试或解除安全停止。"
        else:
            state = ShutdownState.DRAINING
            summary = "已停止接收新操作, 正在等待当前操作保存结果并收尾。"
        return ShutdownResult(
            state=state, safe_summary=summary, active_operations=self._active_operations
        )

    def _run(self) -> None:
        try:
            while True:
                with self._condition:
                    if self._stop.is_set():
                        if self._thread is current_thread():
                            self._thread = None
                        self._condition.notify_all()
                        return
                if self.run_once() is None:
                    self._wake.wait(self._poll_seconds)
                    self._wake.clear()
        except BaseException:
            # A dead dispatcher is never accepted as evidence of completed work.
            # Do not log exception payloads or a traceback containing secrets.
            _LOGGER.error("Console dispatcher stopped before safe finalization")
            with self._condition:
                if self._shutdown_failure is None:
                    self._refuse_locked(
                        "执行调度意外停止, 不能确认操作已可靠保存; 服务保留, 需检查执行记录。"
                    )
                if self._thread is current_thread():
                    self._thread = None
                self._condition.notify_all()


__all__ = [
    "ConsoleCommandRejected",
    "ManagerConsolePort",
    "ProjectConsole",
]
