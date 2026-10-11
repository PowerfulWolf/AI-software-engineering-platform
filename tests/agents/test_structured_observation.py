"""Real structured execution facts survive translation and output rejection."""

import json
import os
import signal
import subprocess
import sys
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Barrier

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.agents.codex_cli import (
    CodexCliError,
    CodexExecutionUnconfirmed,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.model_diagnostics import model_call_phase
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.openai_compatible import HttpResponse
from ai_software_engineer.agents.structured import (
    CodexCliStructuredModelClient,
    FallbackStructuredModelClient,
    ResponsesStructuredModelClient,
    StructuredModelClient,
    StructuredModelError,
    StructuredModelResult,
    StructuredModelRoute,
)
from ai_software_engineer.agents.structured_execution import run_structured_command
from ai_software_engineer.agents.structured_observation import (
    StructuredCallIdentity,
    StructuredExecutionAdmission,
    StructuredHttpRoundTripReceipt,
    StructuredNativeNotStartedReceipt,
    StructuredNativeStopReceipt,
    StructuredObservationRecord,
    StructuredObservationRejected,
    bind_structured_execution_observer,
    current_structured_execution_observer,
    structured_call_identity,
    structured_request_digest,
)
from ai_software_engineer.domain.enums import TeamRole


@dataclass
class Observer:
    admissions: list[StructuredExecutionAdmission] = field(default_factory=list)
    native: list[StructuredNativeStopReceipt] = field(default_factory=list)
    not_started: list[StructuredNativeNotStartedReceipt] = field(default_factory=list)
    http: list[StructuredHttpRoundTripReceipt] = field(default_factory=list)

    def admit(self, admission: StructuredExecutionAdmission) -> None:
        admission.validate_integrity()
        self.admissions.append(admission)

    def native_stopped(self, receipt: StructuredNativeStopReceipt) -> None:
        receipt.validate_integrity()
        self.native.append(receipt)

    def native_not_started(self, receipt: StructuredNativeNotStartedReceipt) -> None:
        receipt.validate_integrity()
        self.not_started.append(receipt)

    def http_completed(self, receipt: StructuredHttpRoundTripReceipt) -> None:
        receipt.validate_integrity()
        self.http.append(receipt)


def identity() -> StructuredCallIdentity:
    return StructuredCallIdentity(
        invocation_id="a" * 32,
        route_index=1,
        provider="fixture",
        model="fixture-model",
        reasoning_effort="medium",
        phase="knowledge_intent",
        request_sha256="b" * 64,
    )


def command(
    tmp_path: Path, source: str, *, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return run_structured_command(
        (sys.executable, "-c", source),
        cwd=tmp_path,
        env={},
        input="",
        capture_output=True,
        text=True,
        timeout=1,
        check=check,
    )


@pytest.mark.parametrize("outcome", ["success", "timeout", "nonzero"])
def test_native_bridge_preserves_actual_stop_before_translation(
    tmp_path: Path, outcome: str
) -> None:
    observer = Observer()
    with bind_structured_execution_observer(observer), structured_call_identity(identity()):
        if outcome == "timeout":
            with pytest.raises(subprocess.TimeoutExpired):
                command(tmp_path, "import time; time.sleep(4)")
        elif outcome == "nonzero":
            with pytest.raises(subprocess.CalledProcessError):
                command(tmp_path, "raise SystemExit(7)", check=True)
        else:
            assert command(tmp_path, "print('fixture')").stdout == "fixture\n"
    assert len(observer.admissions) == len(observer.native) == 1
    assert observer.http == []
    receipt = observer.native[0]
    assert receipt.admission == observer.admissions[0]
    assert (
        receipt.process_stop.kind
        == {"success": "completed", "timeout": "local_execution_limit", "nonzero": "failed"}[
            outcome
        ]
    )
    assert receipt.process_stop.process_id == receipt.process_stop.group_id


def call(client: StructuredModelClient) -> StructuredModelResult:
    return client.complete(
        instructions="private instructions",
        input_payload={"private_input": "private payload"},
        output_schema={"type": "object"},
        timeout_seconds=2,
    )


def routed(*clients: StructuredModelClient) -> FallbackStructuredModelClient:
    return FallbackStructuredModelClient(
        tuple(
            StructuredModelRoute(provider="fixture", model=f"model-{index}", client=client)
            for index, client in enumerate(clients, 1)
        ),
        role=TeamRole.CODER,
    )


class Transport:
    def __init__(self, response: HttpResponse | Exception, barrier: Barrier | None = None) -> None:
        self.response, self.barrier = response, barrier
        self.calls = 0

    def post(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HttpResponse:
        self.calls += 1
        if self.barrier is not None:
            self.barrier.wait(timeout=3)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def http_client(transport: Transport) -> ResponsesStructuredModelClient:
    return ResponsesStructuredModelClient(
        endpoint="https://example.invalid/v1",
        api_key="private-credential",
        model="fixture-model",
        transport=transport,
    )


class FencedObserver(Observer):
    def admit(self, admission: StructuredExecutionAdmission) -> None:
        closed = (
            {receipt.admission.admission_sha256 for receipt in self.native}
            | {receipt.admission.admission_sha256 for receipt in self.not_started}
            | {receipt.admission.admission_sha256 for receipt in self.http}
        )
        if any(previous.admission_sha256 not in closed for previous in self.admissions):
            raise RuntimeError("previous route has no trusted completion")
        super().admit(admission)


def test_missing_native_executable_seals_not_started_before_fallback(tmp_path: Path) -> None:
    observer = FencedObserver()
    backup = Transport(HttpResponse(status_code=200, body=b'{"output_text":"{}"}'))
    client = CodexCliStructuredModelClient(
        repository_root=tmp_path,
        model="fixture",
        executable=str(tmp_path / "missing-executable"),
        environment={},
    )
    with bind_structured_execution_observer(observer):
        assert call(routed(client, http_client(backup))).payload == {}
    assert backup.calls == 1 and len(observer.admissions) == 2
    assert observer.native == [] and len(observer.not_started) == len(observer.http) == 1
    receipt = observer.not_started[0]
    assert receipt.admission == observer.admissions[0]
    assert receipt.failure_kind == "process_spawn_failed"
    assert "process_stop" not in receipt.to_wire() and "process_id" not in receipt.to_wire()


def test_input_preparation_oserror_seals_not_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise OSError("private tempfile failure")

    monkeypatch.setattr("ai_software_engineer.agents.codex_cli.tempfile.TemporaryFile", unavailable)
    observer = Observer()
    with (
        bind_structured_execution_observer(observer),
        structured_call_identity(identity()),
        pytest.raises(OSError),
    ):
        command(tmp_path, "pass")
    assert observer.native == [] and len(observer.not_started) == 1
    assert observer.not_started[0].failure_kind == "input_preparation_failed"


def test_post_spawn_observation_failure_records_real_stop_never_not_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    children: list[subprocess.Popen[str]] = []

    def unavailable(process: subprocess.Popen[str], *, kind: str) -> None:
        children.append(process)
        raise OSError("private ownership registration failure")

    monkeypatch.setattr("ai_software_engineer.agents.codex_cli.observe_owned_process", unavailable)
    observer = Observer()
    try:
        with (
            bind_structured_execution_observer(observer),
            structured_call_identity(identity()),
            pytest.raises(CodexExecutionUnconfirmed),
        ):
            command(tmp_path, "import time; time.sleep(10)")
        assert observer.not_started == []
        assert len(observer.native) == 1
        assert observer.native[0].process_stop.process_id == children[0].pid
        assert children[0].poll() is not None
    finally:
        for process in children:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=2)


def test_untyped_runner_failure_cannot_claim_not_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(*args: object, **kwargs: object) -> None:
        raise CodexCliError("unknown runner failure")

    monkeypatch.setattr(SubprocessCodexCommandRunner, "run_observed", failed)
    observer = Observer()
    with (
        bind_structured_execution_observer(observer),
        structured_call_identity(identity()),
        pytest.raises(OSError),
    ):
        command(tmp_path, "pass")
    assert len(observer.admissions) == 1
    assert observer.not_started == [] and observer.native == []


def test_not_started_publication_failure_prevents_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = Observer()

    def rejected(record: object) -> None:
        raise OSError("private receipt store failure")

    monkeypatch.setattr(observer, "native_not_started", rejected)
    backup = Transport(HttpResponse(status_code=200, body=b'{"output_text":"{}"}'))
    client = CodexCliStructuredModelClient(
        repository_root=tmp_path,
        model="fixture",
        executable=str(tmp_path / "missing-executable"),
        environment={},
    )
    with bind_structured_execution_observer(observer), pytest.raises(StructuredObservationRejected):
        call(routed(client, http_client(backup)))
    assert len(observer.admissions) == 1 and backup.calls == 0


@pytest.mark.parametrize("failure", ["invalid", "status", "timeout", "os_error"])
def test_http_return_or_known_exception_is_not_a_native_stop(failure: str) -> None:
    response: HttpResponse | Exception
    if failure == "timeout":
        response = TimeoutError("private transport text")
    elif failure == "os_error":
        response = OSError("private transport text")
    else:
        response = HttpResponse(status_code=504 if failure == "status" else 200, body=b"bad json")
    transport, observer = Transport(response), Observer()
    with (
        bind_structured_execution_observer(observer),
        model_call_phase("knowledge_assessment"),
        pytest.raises(StructuredModelError),
    ):
        call(routed(http_client(transport)))
    assert len(observer.admissions) == len(observer.http) == 1
    assert observer.native == []
    receipt = observer.http[0]
    assert receipt.admission.call.phase == "knowledge_assessment"
    assert receipt.admission.call.role == TeamRole.CODER
    assert receipt.outcome == (
        "transport_error" if failure in {"timeout", "os_error"} else "returned"
    )
    assert "private" not in json.dumps(receipt.to_wire())
    assert "process_stop" not in receipt.to_wire()


def test_each_actual_fallback_route_has_its_own_admission_and_receipt() -> None:
    first = Transport(HttpResponse(status_code=504, body=b"gateway"))
    second = Transport(HttpResponse(status_code=200, body=b'{"output_text":"{\\"ok\\":true}"}'))
    observer = Observer()
    with bind_structured_execution_observer(observer):
        assert call(routed(http_client(first), http_client(second))).payload == {"ok": True}
    assert [admission.call.route_index for admission in observer.admissions] == [1, 2]
    assert [admission.call.model for admission in observer.admissions] == ["model-1", "model-2"]
    assert len({admission.observation_id for admission in observer.admissions}) == 2
    assert len({admission.call.invocation_id for admission in observer.admissions}) == 1
    assert [receipt.http_status for receipt in observer.http] == [504, 200]


@pytest.mark.parametrize("stage", ["admit", "native_stopped", "http_completed"])
@pytest.mark.parametrize("failure_kind", ["os_error", "provider"])
def test_observer_failure_cannot_be_swallowed_as_provider_fallback(
    tmp_path: Path, stage: str, failure_kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = Observer()
    failure = (
        OSError("private durable-write failure")
        if failure_kind == "os_error"
        else StructuredModelError(AgentErrorCode.PROVIDER_UNAVAILABLE, "fixture", transient=True)
    )

    def rejected(record: object) -> None:
        raise failure

    monkeypatch.setattr(observer, stage, rejected)
    transport = Transport(HttpResponse(status_code=504, body=b"gateway"))
    backup = Transport(HttpResponse(status_code=200, body=b'{"output_text":"{}"}'))
    with bind_structured_execution_observer(observer), pytest.raises(StructuredObservationRejected):
        if stage == "native_stopped":
            with structured_call_identity(identity()):
                command(tmp_path, "print('fixture')")
        else:
            call(routed(http_client(transport), http_client(backup)))
    assert backup.calls == 0
    if stage == "admit":
        assert transport.calls == 0
    assert current_structured_execution_observer() is None


def test_unknown_native_end_has_admission_but_no_synthetic_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unknown(*args: object, **kwargs: object) -> None:
        raise CodexExecutionUnconfirmed("fixture uncertain")

    monkeypatch.setattr(SubprocessCodexCommandRunner, "run_observed", unknown)
    observer = Observer()
    with (
        bind_structured_execution_observer(observer),
        structured_call_identity(identity()),
        pytest.raises(CodexExecutionUnconfirmed),
    ):
        command(tmp_path, "print('fixture')")
    assert len(observer.admissions) == 1 and observer.native == []


def test_missing_runner_callback_cannot_accept_an_unobserved_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unobserved(*args: object, **kwargs: object) -> CodexInvocationResult:
        return CodexInvocationResult(returncode=0, stdout="unverified")

    monkeypatch.setattr(SubprocessCodexCommandRunner, "run_observed", unobserved)
    observer = Observer()
    with (
        bind_structured_execution_observer(observer),
        structured_call_identity(identity()),
        pytest.raises(CodexExecutionUnconfirmed),
    ):
        command(tmp_path, "pass")
    assert len(observer.admissions) == 1 and observer.native == []


def test_observed_call_without_trusted_route_identity_never_starts(tmp_path: Path) -> None:
    observer = Observer()
    marker = tmp_path / "started"
    with (
        bind_structured_execution_observer(observer),
        pytest.raises(StructuredObservationRejected, match="调用身份"),
    ):
        command(tmp_path, f"from pathlib import Path; Path({str(marker)!r}).touch()")
    assert not marker.exists() and observer.admissions == []


@pytest.mark.parametrize("outcome", ["success", "invalid", "nonzero", "timeout"])
def test_real_native_client_preserves_stop_before_output_or_error(
    tmp_path: Path, outcome: str
) -> None:
    executable = tmp_path / "fixture-codex"
    body = {
        "success": "Path(sys.argv[sys.argv.index('--output-last-message') + 1]).write_text('{}')",
        "invalid": (
            "Path(sys.argv[sys.argv.index('--output-last-message') + 1]).write_text('not-json')"
        ),
        "nonzero": "raise SystemExit(7)",
        "timeout": "import time; time.sleep(4)",
    }[outcome]
    executable.write_text(f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\n{body}\n")
    executable.chmod(0o700)
    client = CodexCliStructuredModelClient(
        repository_root=tmp_path, model="fixture", executable=str(executable), environment={}
    )
    observer = Observer()
    with bind_structured_execution_observer(observer):
        if outcome == "success":
            assert call(routed(client)).payload == {}
        else:
            with pytest.raises(StructuredModelError) as error:
                call(routed(client))
            if outcome == "invalid":
                assert error.value.code == AgentErrorCode.INVALID_OUTPUT
            if outcome == "timeout":
                assert error.value.expandable_timeout and not error.value.retryable
    assert len(observer.admissions) == len(observer.native) == 1
    assert (
        observer.native[0].process_stop.kind
        == {
            "success": "completed",
            "invalid": "completed",
            "nonzero": "failed",
            "timeout": "local_execution_limit",
        }[outcome]
    )


@pytest.mark.parametrize("stage", ["admit", "native_stopped"])
def test_native_observer_write_failure_prevents_spawn_or_backup(
    tmp_path: Path, stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "fixture-codex"
    executable.write_text(
        f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\n"
        "Path('started').touch()\n"
        "Path(sys.argv[sys.argv.index('--output-last-message') + 1]).write_text('{}')\n"
    )
    executable.chmod(0o700)
    client = CodexCliStructuredModelClient(
        repository_root=tmp_path, model="fixture", executable=str(executable), environment={}
    )
    observer = Observer()

    def rejected(record: object) -> None:
        raise OSError("private store failure")

    monkeypatch.setattr(observer, stage, rejected)
    backup = Transport(HttpResponse(status_code=200, body=b'{"output_text":"{}"}'))
    with bind_structured_execution_observer(observer), pytest.raises(StructuredObservationRejected):
        call(routed(client, http_client(backup)))
    assert backup.calls == 0
    assert (tmp_path / "started").exists() == (stage == "native_stopped")


def test_unknown_http_exception_has_no_synthetic_round_trip_receipt() -> None:
    transport, observer = Transport(RuntimeError("unknown transport state")), Observer()
    with bind_structured_execution_observer(observer), pytest.raises(RuntimeError):
        call(routed(http_client(transport)))
    assert len(observer.admissions) == 1 and observer.http == [] and observer.native == []


def test_observer_context_is_nested_and_thread_isolated(tmp_path: Path) -> None:
    first, second = Observer(), Observer()
    with bind_structured_execution_observer(first), structured_call_identity(identity()):
        with bind_structured_execution_observer(second):
            command(tmp_path, "pass")
        assert current_structured_execution_observer() is first
        command(tmp_path, "pass")
    assert len(first.native) == len(second.native) == 1
    assert current_structured_execution_observer() is None
    barrier = Barrier(2)

    def execute(index: int) -> Observer:
        observer = Observer()
        transport = Transport(HttpResponse(status_code=200, body=b'{"output_text":"{}"}'), barrier)
        with bind_structured_execution_observer(observer):
            call(routed(http_client(transport)))
        return observer

    with ThreadPoolExecutor(max_workers=2) as pool:
        observers = list(pool.map(execute, (1, 2)))
    assert all(len(observer.http) == 1 for observer in observers)
    assert (
        observers[0].admissions[0].call.invocation_id
        != observers[1].admissions[0].call.invocation_id
    )


def test_schema_is_exact_and_receipt_integrity_rejects_tampering(tmp_path: Path) -> None:
    adapter: TypeAdapter[
        StructuredExecutionAdmission
        | StructuredNativeStopReceipt
        | StructuredNativeNotStartedReceipt
        | StructuredHttpRoundTripReceipt
    ] = TypeAdapter(StructuredObservationRecord)
    path = (
        Path(__file__).resolve().parents[2] / "schemas/structured-execution-observation.schema.json"
    )
    schema = json.loads(path.read_text())
    assert schema.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert schema.pop("$id").endswith("/structured-execution-observation.schema.json")
    assert schema == adapter.json_schema()
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    observer = Observer()
    with bind_structured_execution_observer(observer), structured_call_identity(identity()):
        command(tmp_path, "pass")
        with pytest.raises(OSError):
            run_structured_command(
                (str(tmp_path / "missing-executable"),),
                cwd=tmp_path,
                env={},
                input="",
                capture_output=True,
                text=True,
                timeout=1,
                check=True,
            )
    with bind_structured_execution_observer(observer):
        call(
            routed(
                http_client(Transport(HttpResponse(status_code=200, body=b'{"output_text":"{}"}')))
            )
        )
    for record in (*observer.admissions, *observer.native, *observer.not_started, *observer.http):
        validator.validate(record.to_wire())
        adapter.validate_python(record.to_wire()).validate_integrity()
    changed = observer.native[0].model_copy(update={"stdout_sha256": "c" * 64})
    with pytest.raises(ValueError, match="digest"):
        changed.validate_integrity()
    with pytest.raises(ValidationError):
        StructuredHttpRoundTripReceipt.model_validate(observer.native[0].to_wire())
    changed_startup = observer.not_started[0].model_copy(
        update={"failure_kind": "input_preparation_failed"}
    )
    with pytest.raises(ValueError, match="digest"):
        changed_startup.validate_integrity()
    with pytest.raises(ValidationError):
        StructuredNativeNotStartedReceipt.model_validate(
            {**observer.not_started[0].to_wire(), "process_id": 123}
        )
    with pytest.raises(ValidationError):
        StructuredNativeNotStartedReceipt.create(
            admission=observer.http[0].admission,
            failure_kind="process_spawn_failed",
            failed_at=observer.http[0].completed_at,
        )


def test_fallback_uses_the_shared_exact_request_digest() -> None:
    observer = Observer()
    transport = Transport(HttpResponse(status_code=200, body=b'{"output_text":"{}"}'))
    with bind_structured_execution_observer(observer):
        call(routed(http_client(transport)))
    expected = structured_request_digest(
        instructions="private instructions",
        input_payload={"private_input": "private payload"},
        output_schema={"type": "object"},
        timeout_seconds=2,
    )
    assert observer.admissions[0].call.request_sha256 == expected
    assert expected != structured_request_digest(
        instructions="private instructions",
        input_payload={"private_input": "private payload"},
        output_schema={"type": "object"},
        timeout_seconds=2,
        image_sha256s=("a" * 64,),
    )
