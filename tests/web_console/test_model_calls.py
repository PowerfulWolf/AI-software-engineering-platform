from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_software_engineer.agents.model_diagnostics import ModelCallDiagnostic, record_model_call
from ai_software_engineer.agents.structured import (
    FallbackStructuredModelClient,
    ResponsesStructuredModelClient,
    StructuredModelRoute,
)
from ai_software_engineer.team_view.models import TeamSnapshot
from ai_software_engineer.web_console import (
    ConsoleCommandRejected,
    ConsoleCommandResult,
    ConsoleOperationConflict,
    CreateRequirementIntent,
    FileConsoleOperationStore,
    InMemoryConsoleOperationStore,
    ProjectConsole,
    create_console_app,
)
from ai_software_engineer.web_console.models import ConsoleIntent
from ai_software_engineer.web_console.store import ConsoleOperationNotFound
from tests.agents.test_model_diagnostics import Transport


def call() -> ModelCallDiagnostic:
    return ModelCallDiagnostic(
        invocation_id="a" * 32,
        route_index=1,
        started_at=datetime.now(UTC),
        role="product",
        phase="knowledge_intent",
        provider="hdl",
        model="model-test",
        reasoning_effort="medium",
        duration_ms=1234,
        outcome="FAILED",
        http_status=504,
        request_id="req-test",
        error_code="PROVIDER_UNAVAILABLE",
        error_summary="HTTP 504",
    )


def intent(tmp_path: Path) -> CreateRequirementIntent:
    return CreateRequirementIntent(
        project_id="project_test", name="Test", repository_roots=(str(tmp_path),)
    )


@pytest.mark.parametrize("kind", ["memory", "file"])
def test_diagnostics_survive_interruption_without_changing_operation_chain(
    tmp_path: Path, kind: str
) -> None:
    store = (
        InMemoryConsoleOperationStore("team_test")
        if kind == "memory"
        else FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    )
    queued = store.submit(
        intent=intent(tmp_path), idempotency_key="diagnostics-test", requested_at=datetime.now(UTC)
    )
    assert store.model_calls(queued.operation_id) == ()
    running = store.claim_next(at=datetime.now(UTC))
    assert running is not None
    record = call()
    store.record_model_call(queued.operation_id, record)
    store.record_model_call(queued.operation_id, record)
    assert store.get(queued.operation_id) == running
    assert store.model_calls(queued.operation_id) == (record,)
    store.interrupt_running(at=datetime.now(UTC))
    if kind == "file":
        store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    assert store.model_calls(queued.operation_id) == (record,)
    with pytest.raises(ConsoleOperationConflict):
        store.record_model_call(queued.operation_id, call())
    with pytest.raises(ConsoleOperationNotFound):
        store.model_calls("operation_" + "f" * 32)


@pytest.mark.parametrize("tamper", ["body", "symlink"])
def test_diagnostic_integrity_and_symlink_guard(tmp_path: Path, tamper: str) -> None:
    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    queued = store.submit(
        intent=intent(tmp_path), idempotency_key="diagnostics-test", requested_at=datetime.now(UTC)
    )
    store.claim_next(at=datetime.now(UTC))
    store.record_model_call(queued.operation_id, call())
    path = next((store.root / queued.operation_id / "model-calls").glob("*.json"))
    if tamper == "body":
        path.write_text(path.read_text().replace("req-test", "req-tampered"))
    else:
        other = tmp_path / "external.json"
        path.rename(other)
        path.symlink_to(other)
    with pytest.raises(ConsoleOperationConflict):
        store.model_calls(queued.operation_id)
    assert store.get(queued.operation_id).status == "RUNNING"


def test_diagnostic_directory_must_not_be_a_regular_file(tmp_path: Path) -> None:
    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    queued = store.submit(
        intent=intent(tmp_path), idempotency_key="diagnostics-test", requested_at=datetime.now(UTC)
    )
    (store.root / queued.operation_id / "model-calls").write_text("not a directory")
    with pytest.raises(ConsoleOperationConflict):
        store.model_calls(queued.operation_id)


class Reader:
    def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
        return TeamSnapshot(as_of=datetime.now(UTC), team_id="team_test", team_name="Test")


@pytest.mark.parametrize("failure", [False, True])
def test_console_persists_call_before_exit_and_exposes_read_only_endpoint(
    tmp_path: Path, failure: bool
) -> None:
    record = call()
    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")

    class Executor:
        def execute(self, value: ConsoleIntent) -> ConsoleCommandResult:
            record_model_call(record)
            assert store.model_calls(queued.operation_id) == (record,)
            if failure:
                raise ConsoleCommandRejected("MODEL_PROVIDER_UNAVAILABLE", "HTTP 504")
            return ConsoleCommandResult(
                project_id="project_test", stage="READY_FOR_DISCUSSION", next_action="Continue"
            )

    console = ProjectConsole(store=store, executor=Executor())
    queued = console.submit(intent(tmp_path), idempotency_key="diagnostics-test")
    console.run_once()
    record_model_call(call())  # Context is reset: this must not attach to the old operation.
    with TestClient(
        create_console_app(console, Reader(), team_id="team_test"), base_url="http://127.0.0.1:8765"
    ) as client:
        url = f"/api/v1/operations/{queued.operation_id}/model-calls"
        response = client.get(url)
        assert response.status_code == 200
        assert response.json() == [record.to_wire()]
        assert client.post(url, json={}).status_code == 405
        assert (
            client.get("/api/v1/operations/operation_" + "f" * 32 + "/model-calls").status_code
            == 404
        )
    store.get(queued.operation_id).validate_integrity()


def test_fallback_to_durable_console_diagnostics_end_to_end(tmp_path: Path) -> None:
    model = FallbackStructuredModelClient(
        tuple(
            StructuredModelRoute(
                provider="test",
                model=name,
                client=ResponsesStructuredModelClient(
                    endpoint="https://example.invalid",
                    api_key="private-key",
                    model=name,
                    transport=Transport(status, f"req-{name}"),
                ),
            )
            for name, status in (("primary", 504), ("backup", 200))
        ),
        role="product",
    )

    class Executor:
        def execute(self, value: ConsoleIntent) -> ConsoleCommandResult:
            assert model.complete(
                instructions="private prompt", input_payload={}, output_schema={}, timeout_seconds=1
            ).payload == {"ok": True}
            return ConsoleCommandResult(
                project_id="project_test", stage="READY_FOR_DISCUSSION", next_action="Continue"
            )

    directory = tmp_path / "operations"
    console = ProjectConsole(
        store=FileConsoleOperationStore(directory, team_id="team_test"), executor=Executor()
    )
    queued = console.submit(intent(tmp_path), idempotency_key="diagnostics-test")
    finished = console.run_once()
    assert finished is not None and finished.status == "SUCCEEDED"
    reopened = ProjectConsole(
        store=FileConsoleOperationStore(directory, team_id="team_test"), executor=Executor()
    )
    with TestClient(
        create_console_app(reopened, Reader(), team_id="team_test"),
        base_url="http://127.0.0.1:8765",
    ) as client:
        response = client.get(f"/api/v1/operations/{queued.operation_id}/model-calls")
        assert response.status_code == 200
        records = response.json()
        assert [(r["route_index"], r["http_status"], r["request_id"]) for r in records] == [
            (1, 504, "req-primary"),
            (2, 200, "req-backup"),
        ]
        assert all(r["role"] == "product" and r["duration_ms"] >= 0 for r in records)
        assert "private" not in response.text
        path = next((directory / queued.operation_id / "model-calls").glob("*.json"))
        path.write_text("{}")
        assert (
            client.get(f"/api/v1/operations/{queued.operation_id}/model-calls").status_code == 409
        )


def test_diagnostic_write_failure_does_not_retry_or_fail_delivery(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class Store(InMemoryConsoleOperationStore):
        def record_model_call(self, operation_id: str, call: ModelCallDiagnostic) -> None:
            raise OSError("private storage details")

    attempts = []

    class Executor:
        def execute(self, value: ConsoleIntent) -> ConsoleCommandResult:
            attempts.append(value)
            record_model_call(call())
            return ConsoleCommandResult(
                project_id="project_test", stage="READY_FOR_DISCUSSION", next_action="Continue"
            )

    console = ProjectConsole(store=Store("team_test"), executor=Executor())
    queued = console.submit(intent(tmp_path), idempotency_key="diagnostics-test")
    finished = console.run_once()
    assert finished is not None and finished.status == "SUCCEEDED"
    assert len(attempts) == 1 and console.run_once() is None
    assert queued.operation_id in caplog.text
    assert "private storage details" not in caplog.text
