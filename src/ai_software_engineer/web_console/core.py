"""Deep application module for durable browser-submitted Project Manager work."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from typing import Protocol

from .models import ConsoleCommandResult, ConsoleIntent, ConsoleOperation
from .store import ConsoleOperationStore


class ConsoleCommandRejected(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary


class ProjectManagerConsolePort(Protocol):
    def execute(self, intent: ConsoleIntent) -> ConsoleCommandResult: ...


Clock = Callable[[], datetime]


class ProjectConsole:
    """Persist user intent first, then dispatch it independently from the HTTP request."""

    def __init__(
        self,
        *,
        store: ConsoleOperationStore,
        executor: ProjectManagerConsolePort,
        clock: Clock | None = None,
        poll_seconds: float = 0.25,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("console poll interval must be positive")
        self._store = store
        self._executor = executor
        self._clock = clock or (lambda: datetime.now(UTC))
        self._poll_seconds = poll_seconds
        self._wake = Event()
        self._stop = Event()
        self._lifecycle = Lock()
        self._thread: Thread | None = None

    def submit(self, intent: ConsoleIntent, *, idempotency_key: str) -> ConsoleOperation:
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

    def run_once(self) -> ConsoleOperation | None:
        running = self._store.claim_next(at=self._clock())
        if running is None:
            return None
        try:
            result = self._executor.execute(running.intent)
        except ConsoleCommandRejected as error:
            return self._store.fail(
                running.operation_id,
                expected=running.operation_sha256,
                error_code=error.code,
                error_summary=error.safe_summary,
                at=self._clock(),
            )
        except Exception:
            return self._store.fail(
                running.operation_id,
                expected=running.operation_sha256,
                error_code="PROJECT_MANAGER_FAILURE",
                error_summary="Project Manager operation failed; inspect durable delivery facts.",
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
            if self._thread is not None and self._thread.is_alive():
                return
            self._store.interrupt_running(at=self._clock())
            self._stop.clear()
            self._thread = Thread(target=self._run, name="project-console-dispatcher", daemon=True)
            self._thread.start()

    def close(self, *, timeout: float = 5.0) -> None:
        with self._lifecycle:
            thread = self._thread
            if thread is None:
                return
            self._stop.set()
            self._wake.set()
        thread.join(timeout)
        with self._lifecycle:
            if not thread.is_alive():
                self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            if self.run_once() is None:
                self._wake.wait(self._poll_seconds)
                self._wake.clear()


__all__ = [
    "ConsoleCommandRejected",
    "ProjectConsole",
    "ProjectManagerConsolePort",
]
