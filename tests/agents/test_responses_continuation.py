"""Responses uses real restricted tools and durable same-Task continuation facts."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator, Mapping
from datetime import datetime, tzinfo
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    FallbackAgentAdapter,
    FileModelRouteAttemptStore,
    HttpResponse,
    ProviderAgentRoute,
    ResponsesAgentAdapter,
)
from ai_software_engineer.agents.continuation import ContinuationExecutionUncertain
from ai_software_engineer.agents.execution import SynchronousToolLoopStop
from ai_software_engineer.agents.openai_compatible import StoredContextResolver
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentRole,
    Artifact,
    ChangedFile,
    ChangeType,
)
from ai_software_engineer.domain.agent import DELIVERY_ROLE_INPUTS, ROLE_OUTPUTS
from ai_software_engineer.execution import (
    CommandExecutionUncertain,
    CommandResult,
    SubprocessCommandExecutor,
)
from ai_software_engineer.manager.production_delivery import ConfiguredDeliveryRouteAdapterFactory
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from ai_software_engineer.tools import PolicyBoundToolRegistry, ToolRequest, ToolResult
from ai_software_engineer.work_queue.ports import QueueLeaseLost
from tests.agents.test_openai_compatible import StaticPromptBuilder
from tests.domain.factories import make_implementation_artifact
from tests.git.test_worktree import _git
from tests.orchestration.test_native_continuation import NOW, Guard
from tests.orchestration.test_native_continuation_v2 import V2Fixture


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _FixedDatetime:
        del tz
        return cls.fromtimestamp(NOW.timestamp(), NOW.tzinfo)


@pytest.fixture
def native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[V2Fixture]:
    fd = os.open(tmp_path / "owned-lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    fixture = V2Fixture(tmp_path, Guard(fd))
    monkeypatch.setattr("ai_software_engineer.agents.responses.datetime", _FixedDatetime)
    try:
        yield fixture
    finally:
        fixture.repository.close()
        os.close(fd)


def _definition(request: AgentRequest) -> AgentDefinition:
    return AgentDefinition(
        id="agent_native_coder",
        role=request.role,
        version="v0.1",
        model="fixture",
        provider="fixture",
        permissions=request.permissions,
        input_artifacts=DELIVERY_ROLE_INPUTS[request.role],
        output_artifacts=ROLE_OUTPUTS[request.role],
        max_retries=0,
        timeout_seconds=request.timeout_seconds,
    )


def _call(name: str, **arguments: object) -> dict[str, object]:
    return {
        "type": "function_call",
        "call_id": "call_" + name,
        "name": name,
        "arguments": json.dumps(arguments),
    }


def _tools(*calls: dict[str, object]) -> HttpResponse:
    return HttpResponse(status_code=200, body=json.dumps({"output": calls}).encode())


class _DraftThenFailure:
    def __init__(
        self, kind: Literal["quota", "http", "timeout", "transport", "policy"] = "http"
    ) -> None:
        self.kind = kind
        self.calls = 0
        self.timeouts: list[float] = []

    def post(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HttpResponse:
        del url, headers, body
        self.calls += 1
        self.timeouts.append(timeout_seconds)
        if self.calls == 1:
            return _tools(
                _call("write_file", path="src/app.py", content="VALUE = 2\n"),
                {
                    **_call("write_file", path="src/created.py", content="NEW = True\n"),
                    "call_id": "call_create",
                },
            )
        if self.kind == "timeout":
            raise TimeoutError("PRIVATE_PROVIDER_SECRET")
        if self.kind == "transport":
            raise OSError("PRIVATE_PROVIDER_SECRET")
        if self.kind == "policy":
            return _tools(_call("write_file", path=".trellis/spec/bypass.md", content="unsafe"))
        code = 429 if self.kind == "quota" else 503
        return HttpResponse(status_code=code, body=b'{"error":{"code":"quota_exceeded"}}')


def _adapter(
    native: V2Fixture, transport: object, *, max_turns: int = 40, max_tool_calls: int = 100
) -> ResponsesAgentAdapter:
    from ai_software_engineer.agents.openai_compatible import HttpTransport

    return ResponsesAgentAdapter(
        workspace_root=native.worktree.path,
        endpoint="https://example.invalid/responses",
        api_key="fixture-key",
        model="fixture",
        agent=_definition(native.request),
        prompt_builder=StaticPromptBuilder(),
        transport=cast(HttpTransport, transport),
        execution_guard=native.guard,
        interruption_control=native.service(),
        max_turns=max_turns,
        max_tool_calls=max_tool_calls,
    )


@pytest.mark.parametrize("kind", ["quota", "http", "timeout", "transport"])
def test_provider_interruption_seals_sync_stop_and_complete_draft_then_resumes_new_claim(
    native: V2Fixture,
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["quota", "http", "timeout", "transport"],
) -> None:
    operations: list[str] = []
    execute = PolicyBoundToolRegistry.execute

    def record(registry: PolicyBoundToolRegistry, request: ToolRequest) -> ToolResult:
        result = execute(registry, request)
        operations.append(request.operation_id)
        return result

    monkeypatch.setattr(PolicyBoundToolRegistry, "execute", record)
    transport = _DraftThenFailure(kind)
    adapter = _adapter(native, transport)
    first_request = native.request
    outcome = adapter.run(first_request)
    assert outcome.error is not None and outcome.error.code is AgentErrorCode.WORK_INTERRUPTED
    assert not outcome.error.transient and outcome.artifact is None
    assert "PRIVATE_PROVIDER_SECRET" not in outcome.model_dump_json()
    receipt = native.store.get_receipt(first_request.run_id)
    receipt.validate_integrity()
    assert isinstance(receipt.process_stop, SynchronousToolLoopStop)
    receipt.process_stop.require_request(first_request)
    assert receipt.process_stop.completed_operation_ids == tuple(operations)
    assert receipt.process_stop.kind == "failed"
    assert receipt.cause == "provider_transient"
    assert set(receipt.capture.to_capture().changed_paths) == {"src/app.py", "src/created.py"}
    original = {path: path.read_bytes() for path in native.store_root.rglob("*.json")}
    assert adapter.run(first_request) == outcome
    assert transport.calls == 2 and len(operations) == 2
    assert _git(native.worktree.path, "rev-parse", "HEAD") == native.task.base_ref
    assert (
        native.service().next_attempt(
            native.repository.get(native.task.id), outcome, native.repository
        )
        == 2
    )
    native.restart()
    native.activate(2)
    successor = native.request
    assert successor.run_id != first_request.run_id
    assert successor.context_manifest_id != first_request.context_manifest_id
    assert native.claim.lease.id != receipt.claim_lease_id

    class Complete:
        calls = 0

        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
        ) -> HttpResponse:
            del url, headers, timeout_seconds
            self.calls += 1
            assert "完整补丁" in body.decode()
            template = make_implementation_artifact()
            report = template.model_copy(
                update={
                    "task_id": successor.task_id,
                    "source_revision": successor.source_revision,
                    "context_manifest_id": successor.context_manifest_id,
                    "parent_artifact_ids": successor.input_artifact_ids,
                    "producer": template.producer.model_copy(update={"run_id": successor.run_id}),
                    "content": template.content.model_copy(
                        update={
                            "commit_sha": successor.source_revision,
                            "changed_files": (
                                ChangedFile(
                                    path="src/app.py",
                                    change=ChangeType.MODIFIED,
                                    lines_added=1,
                                    lines_deleted=1,
                                ),
                                ChangedFile(
                                    path="src/created.py",
                                    change=ChangeType.ADDED,
                                    lines_added=1,
                                    lines_deleted=0,
                                ),
                            ),
                        }
                    ),
                }
            )
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "output_text": json.dumps({"artifact": report.to_wire()}),
                    }
                ).encode(),
            )

    final_transport = Complete()
    finished = _adapter(native, final_transport).run(successor)
    assert finished.status is AgentRunStatus.SUCCEEDED
    assert finished.artifact is not None
    assert finished.artifact.source_revision == _git(native.worktree.path, "rev-parse", "HEAD")
    assert _git(native.worktree.path, "status", "--porcelain") == ""
    assert final_transport.calls == 1
    assert all(path.read_bytes() == content for path, content in original.items())
    task = native.repository.get(native.task.id)
    assert task.work_attempt == 1 and task.transient_failures(AgentRole.CODER) == 1


def test_policy_refusal_preserves_work_without_a_fabricated_sync_stop(native: V2Fixture) -> None:
    outcome = _adapter(native, _DraftThenFailure("policy")).run(native.request)
    assert outcome.error is not None and outcome.error.code is AgentErrorCode.POLICY_VIOLATION
    assert native.store.receipts_for_task(native.task.id) == ()
    assert (native.worktree.path / "src/app.py").read_text() == "VALUE = 2\n"


def test_uncertain_command_and_lost_owner_propagate_without_stop(
    native: V2Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _DraftThenFailure()
    original = transport.post

    def post(
        url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HttpResponse:
        if transport.calls == 1:
            return _tools(_call("run_command", argv=["pytest", "tests/test_one.py"]))
        return original(url, headers, body, timeout_seconds)

    monkeypatch.setattr(transport, "post", post)

    def uncertain(*args: object, **kwargs: object) -> CommandResult:
        raise CommandExecutionUncertain("owned child did not stop")

    monkeypatch.setattr(SubprocessCommandExecutor, "run", uncertain)
    with pytest.raises(CommandExecutionUncertain):
        _adapter(native, transport).run(native.request)
    assert native.store.receipts_for_task(native.task.id) == ()

    def lost() -> None:
        raise QueueLeaseLost("test owner expired")

    monkeypatch.setattr(native.guard, "check", lost)
    with pytest.raises(QueueLeaseLost):
        _adapter(native, transport).run(native.request)
    assert native.store.receipts_for_task(native.task.id) == ()


class _Monotonic:
    value = 0.0

    def __call__(self) -> float:
        return self.value


def test_one_deadline_caps_each_http_and_command_then_consumes_work_allowance(
    native: V2Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Monotonic()
    monkeypatch.setattr("ai_software_engineer.agents.responses.time.monotonic", clock)
    native.request = native.request.model_copy(update={"timeout_seconds": 10})
    http_timeouts: list[float] = []
    command_timeouts: list[float | None] = []
    original = SubprocessCommandExecutor.run

    def command(
        executor: SubprocessCommandExecutor,
        argv: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        command_timeouts.append(timeout_seconds)
        # A real bounded command is exercised; argv stays under the real policy.
        result = original(executor, argv, timeout_seconds=timeout_seconds)
        clock.value += 3
        return result

    monkeypatch.setattr(SubprocessCommandExecutor, "run", command)
    native.request = native.request.model_copy(
        update={
            "permissions": native.request.permissions.model_copy(
                update={"commands": ("git status",)}
            ),
        }
    )

    class Transport:
        calls = 0

        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
        ) -> HttpResponse:
            del url, headers, body
            self.calls += 1
            http_timeouts.append(timeout_seconds)
            clock.value += 2
            if self.calls == 1:
                return _tools(_call("write_file", path="src/app.py", content="VALUE = 2\n"))
            return _tools(
                _call("run_command", argv=["git", "status", "--porcelain"], timeout_seconds=3600)
            )

    transport = Transport()
    outcome = _adapter(native, transport).run(native.request)
    assert outcome.error is not None and outcome.error.code is AgentErrorCode.WORK_INTERRUPTED
    assert http_timeouts == [10, 8, 3]
    assert command_timeouts == [6, 1]
    receipt = native.store.get_receipt(native.request.run_id)
    assert receipt.cause == "local_execution_limit"
    assert isinstance(receipt.process_stop, SynchronousToolLoopStop)
    assert receipt.process_stop.kind == "local_execution_limit"
    assert (
        native.service().next_attempt(
            native.repository.get(native.task.id), outcome, native.repository
        )
        == 2
    )
    task = native.repository.get(native.task.id)
    assert task.work_attempt == 2 and task.transient_failures(AgentRole.CODER) == 0


def test_dirty_work_interruption_never_falls_back_in_the_same_run(native: V2Fixture) -> None:
    transport = _DraftThenFailure()
    adapter = _adapter(native, transport)

    class Forbidden:
        def run(self, request: AgentRequest) -> AgentResult:
            raise AssertionError("same-Run dirty fallback executed")

    fallback = FallbackAgentAdapter(
        (
            ProviderAgentRoute(provider="primary", model="fixture", adapter=adapter),
            ProviderAgentRoute(provider="fallback", model="fixture", adapter=Forbidden()),
        ),
        attempt_store=FileModelRouteAttemptStore(native.store_root.parent / "routes"),
    )
    outcome = fallback.run(native.request)
    assert outcome.error is not None and outcome.error.code is AgentErrorCode.WORK_INTERRUPTED
    assert transport.calls == 2


@pytest.mark.parametrize("budget", ["turn", "tool"])
def test_bounded_loop_exhaustion_uses_local_work_budget_and_only_completed_operations(
    native: V2Fixture,
    budget: str,
) -> None:
    transport = _DraftThenFailure()
    outcome = _adapter(
        native,
        transport,
        max_turns=1 if budget == "turn" else 40,
        max_tool_calls=1 if budget == "tool" else 100,
    ).run(native.request)
    assert outcome.error is not None and outcome.error.code is AgentErrorCode.WORK_INTERRUPTED
    receipt = native.store.get_receipt(native.request.run_id)
    assert receipt.cause == "local_execution_limit"
    assert isinstance(receipt.process_stop, SynchronousToolLoopStop)
    assert receipt.process_stop.kind == "local_execution_limit"
    assert len(receipt.process_stop.completed_operation_ids) == (2 if budget == "turn" else 1)
    assert transport.calls == 1
    assert (
        native.service().next_attempt(
            native.repository.get(native.task.id), outcome, native.repository
        )
        == 2
    )
    assert native.repository.get(native.task.id).work_attempt == 2
    assert native.repository.get(native.task.id).transient_failures(AgentRole.CODER) == 0


@pytest.mark.parametrize("cause", ["timeout", "transport", "http"])
def test_provider_return_at_expired_deadline_does_not_consume_provider_failure_budget(
    native: V2Fixture,
    monkeypatch: pytest.MonkeyPatch,
    cause: str,
) -> None:
    clock = _Monotonic()
    monkeypatch.setattr("ai_software_engineer.agents.responses.time.monotonic", clock)
    native.request = native.request.model_copy(update={"timeout_seconds": 10})

    class Transport(_DraftThenFailure):
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
        ) -> HttpResponse:
            if self.calls == 1:
                clock.value = 10
                if cause == "timeout":
                    raise TimeoutError("provider timeout at deadline")
                if cause == "transport":
                    raise OSError("transport returned after execution deadline")
            return super().post(url, headers, body, timeout_seconds)

    outcome = _adapter(native, Transport()).run(native.request)
    assert outcome.error is not None and outcome.error.code is AgentErrorCode.WORK_INTERRUPTED
    assert native.store.get_receipt(native.request.run_id).cause == "local_execution_limit"
    assert (
        native.service().next_attempt(
            native.repository.get(native.task.id), outcome, native.repository
        )
        == 2
    )
    assert native.repository.get(native.task.id).work_attempt == 2
    assert native.repository.get(native.task.id).transient_failures(AgentRole.CODER) == 0


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_production_responses_factory_injects_interruption_control_only_into_coder(
    native: V2Fixture,
    role: AgentRole,
) -> None:
    request = native.request.model_copy(
        update={
            "role": role,
            "output_schema": {
                AgentRole.CODER: "schemas/coder-output.schema.json",
                AgentRole.QA: "schemas/qa-report.schema.json",
                AgentRole.REVIEWER: "schemas/review-report.schema.json",
            }[role],
        }
    )
    control = native.service()
    route = ProviderRouteConfig(
        provider="fixture",
        model="fixture",
        kind=ModelProviderKind.RESPONSES,
        api_key_env="TEST_RESPONSES_KEY",
        endpoint="https://example.invalid/responses",
    )
    config = ProductionConfig(
        platform_root=str(native.store_root.parent / "platform"), model_routes=(route,)
    )
    binding = cast(
        RoleWorktreeBinding, SimpleNamespace(worktree=SimpleNamespace(path=native.worktree.path))
    )
    result = ConfiguredDeliveryRouteAdapterFactory(interruption_control=control).create(
        route=route,
        definition=_definition(request),
        binding=binding,
        context_resolver=cast(StoredContextResolver, object()),
        config=config,
        environment={"TEST_RESPONSES_KEY": "fixture-key"},
    )
    assert isinstance(result, ResponsesAgentAdapter)
    assert result._interruption_control is (control if role is AgentRole.CODER else None)


@pytest.mark.parametrize("include_calls", [False, True])
@pytest.mark.parametrize("expire_on_response", [False, True])
def test_known_final_that_expires_during_finishing_waits_without_fabricated_unstarted_output(
    native: V2Fixture,
    monkeypatch: pytest.MonkeyPatch,
    expire_on_response: bool,
    include_calls: bool,
) -> None:
    from ai_software_engineer.agents import responses

    clock = _Monotonic()
    monkeypatch.setattr("ai_software_engineer.agents.responses.time.monotonic", clock)
    native.request = native.request.model_copy(update={"timeout_seconds": 10})

    class Final(_DraftThenFailure):
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
        ) -> HttpResponse:
            if self.calls == 1:
                self.calls += 1
                template = make_implementation_artifact()
                report = template.model_copy(
                    update={
                        "task_id": native.request.task_id,
                        "source_revision": native.request.source_revision,
                        "context_manifest_id": native.request.context_manifest_id,
                        "producer": template.producer.model_copy(
                            update={"run_id": native.request.run_id}
                        ),
                        "content": template.content.model_copy(
                            update={"commit_sha": native.request.source_revision}
                        ),
                    }
                )
                if expire_on_response:
                    clock.value = 10
                return HttpResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "output_text": json.dumps({"artifact": report.to_wire()}),
                            **(
                                {
                                    "output": [
                                        _call(
                                            "write_file", path="src/app.py", content="unexpected\n"
                                        )
                                    ]
                                }
                                if include_calls
                                else {}
                            ),
                        }
                    ).encode(),
                )
            return super().post(url, headers, body, timeout_seconds)

    original = responses._decode_artifact_output

    def expire(content: str) -> Artifact:
        report = original(content)
        if not expire_on_response:
            clock.value = 10
        return report

    monkeypatch.setattr(responses, "_decode_artifact_output", expire)
    transport = Final()
    with pytest.raises(ContinuationExecutionUncertain, match="已返回最终输出"):
        _adapter(native, transport).run(native.request)
    assert transport.calls == 2
    assert native.store.receipts_for_task(native.task.id) == ()
    assert _git(native.worktree.path, "rev-parse", "HEAD") == native.task.base_ref
    assert (native.worktree.path / "src/app.py").read_text() == "VALUE = 2\n"


@pytest.mark.parametrize("local", [False, True])
def test_tool_response_narration_is_not_a_final_artifact(
    native: V2Fixture,
    local: bool,
) -> None:
    class Narrated(_DraftThenFailure):
        def post(
            self,
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> HttpResponse:
            response = super().post(url, headers, body, timeout_seconds)
            if response.status_code == 200:
                return HttpResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            **json.loads(response.body),
                            "output_text": "I will update these files now.",
                        }
                    ).encode(),
                )
            return response

    result = _adapter(native, Narrated(), max_turns=1 if local else 40).run(native.request)
    assert result.error is not None and result.error.code is AgentErrorCode.WORK_INTERRUPTED
    receipt = native.store.get_receipt(native.request.run_id)
    receipt.validate_integrity()
    assert receipt.cause == ("local_execution_limit" if local else "provider_transient")
    assert set(receipt.capture.to_capture().changed_paths) == {"src/app.py", "src/created.py"}
