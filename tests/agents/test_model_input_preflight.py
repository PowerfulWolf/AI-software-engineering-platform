"""Final provider material is prepared without execution or continuation consumption."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import (
    AgentRequest,
    CodexCliAgentAdapter,
    CodexInvocationResult,
    FallbackAgentAdapter,
    FileModelRouteAttemptStore,
    HttpResponse,
    PromptMessage,
    PromptPayload,
    ProviderAgentRoute,
    ResponsesAgentAdapter,
    StoredContextResolver,
)
from ai_software_engineer.agents.continuation import InterruptionObservation
from ai_software_engineer.agents.execution import ExecutionStop
from ai_software_engineer.agents.model_input import BoundModelInputBudget
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import (
    ContextBudget,
    ContextBudgetExceeded,
    ContextBundle,
    InMemoryContextStore,
)
from ai_software_engineer.context.builder import estimate_input_tokens
from ai_software_engineer.context.models import ContextSection
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.domain.continuation import ContinuationCause
from ai_software_engineer.git import WorkspacePolicyError
from ai_software_engineer.git.mutation import WorkspaceMutationInventory
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.preflight_gate import PreflightInvocationControl
from ai_software_engineer.orchestration import (
    BlockedResult,
    FileRunContextBuilder,
    RetryingOrchestrator,
)
from ai_software_engineer.store import SqliteTaskRepository
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
    DurableInvocationControl,
)
from ai_software_engineer.work_queue.worker import WorkerDeliveryFailureControl
from tests.agents.test_codex_cli import _repository
from tests.agents.test_native_python_tooling import _fake_tools, _project
from tests.agents.test_openai_compatible import (
    RecordingContextResolver,
    RecordingTransport,
    StaticPromptBuilder,
    _coder_request,
)
from tests.agents.test_responses import _request as responses_request
from tests.domain.factories import NOW, make_implementation_artifact
from tests.manager.test_verifier_preparation import _Failure
from tests.orchestration.test_retry import AttemptIdentityFactory, ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions, _task
from tests.work_queue.test_invocation_journal import guard


def _budget(request: AgentRequest, limit: int) -> BoundModelInputBudget:
    text = "small complete original context"
    section = ContextSection(
        name="policy",
        uri="policy://test",
        content=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        tokens=8,
        priority=1,
    )
    context = ContextBundle(
        context_id=request.context_manifest_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        sections=(section,),
        budget=ContextBudget(
            max_input_tokens=limit, reserved_output_tokens=10, used_input_tokens=8
        ),
        built_at=NOW,
    )
    return BoundModelInputBudget(RecordingContextResolver(context, make_implementation_artifact()))


class _Runner:
    def __init__(self, stderr: str = "authentication failed") -> None:
        self.calls = 0
        self.stdin = ""
        self.stderr = stderr
        self.environment: Mapping[str, str] = {}

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        self.calls += 1
        self.stdin = stdin
        self.environment = dict(environment)
        return CodexInvocationResult(1, stderr=self.stderr)


def test_native_wrapper_overflow_is_detected_before_runner_and_releases_resources(
    tmp_path: Path,
) -> None:
    root, revision = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": revision})
    runner = _Runner()
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="test",
        agent_id="agent_test",
        agent_version="v1",
        runner=runner,
        prompt_builder=StaticPromptBuilder(),
        input_budget=_budget(request, 8),
    )
    with pytest.raises(ContextBudgetExceeded, match="final provider input"):
        adapter.prepare_input(request)
    assert runner.calls == 0
    assert not adapter._prepared_inputs


def test_native_uses_exact_prepared_string_once_and_cleans_up(tmp_path: Path) -> None:
    root, revision = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": revision})
    builder = StaticPromptBuilder(
        PromptPayload(
            messages=(
                PromptMessage(role="system", content="policy"),
                PromptMessage(role="user", content='{"quoted":"Unicode 中文\\nvalue"}'),
            )
        )
    )
    runner = _Runner()
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="test",
        agent_id="agent_test",
        agent_version="v1",
        runner=runner,
        prompt_builder=builder,
        input_budget=_budget(request, 100_000),
    )
    adapter.prepare_input(request)
    prepared = adapter._prepared_inputs[request.run_id]
    expected = prepared.compiled_prompt
    assert prepared.schema_path.is_file()
    assert len(builder.requests) == 1 and runner.calls == 0
    adapter.run(request)
    assert runner.stdin == expected and len(builder.requests) == 1
    assert not prepared.schema_path.exists() and not adapter._prepared_inputs


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_final_native_input_uses_shared_estimator_at_exact_boundary(
    tmp_path: Path,
    delta: int,
) -> None:
    root, revision = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": revision})
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="test",
        agent_id="agent_test",
        agent_version="v1",
        runner=_Runner(),
        prompt_builder=StaticPromptBuilder(),
    )
    adapter.prepare_input(request)
    size = estimate_input_tokens(adapter._prepared_inputs[request.run_id].budget_content)
    adapter.discard_prepared_input(request)
    adapter._input_budget = _budget(request, size + delta)
    if delta < 0:
        with pytest.raises(ContextBudgetExceeded):
            adapter.prepare_input(request)
    else:
        adapter.prepare_input(request)
    adapter.discard_prepared_input(request)


class _PreviewControl:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prepares = self.starts = 0

    def preview(self, request: AgentRequest, root: Path) -> str:
        return self.text

    def prepare(self, request: AgentRequest, root: Path) -> str:
        self.prepares += 1
        return self.text

    def started(self, request: AgentRequest, root: Path) -> WorkspaceMutationInventory | None:
        self.starts += 1
        return None

    def finished(
        self, request: AgentRequest, root: Path, *, before: WorkspaceMutationInventory
    ) -> None:
        raise AssertionError("the fixture returns no initial inventory")

    def interrupted(
        self,
        request: AgentRequest,
        root: Path,
        *,
        before: WorkspaceMutationInventory,
        cause: ContinuationCause,
        original_error_code: AgentErrorCode,
        process_stop: ExecutionStop | None,
        output_present: bool,
    ) -> InterruptionObservation:
        raise AssertionError("the fixture returns no initial inventory")


def test_full_continuation_overflow_does_not_consume_admission_or_publish_capture_start(
    tmp_path: Path,
) -> None:
    root, revision = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": revision})
    control = _PreviewControl("complete old patch\n" * 100_000)
    runner = _Runner()
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="test",
        agent_id="agent_test",
        agent_version="v1",
        runner=runner,
        prompt_builder=StaticPromptBuilder(),
        input_budget=_budget(request, 100_000),
        interruption_control=control,
    )
    with pytest.raises(ContextBudgetExceeded):
        adapter.prepare_input(request)
    assert control.prepares == control.starts == runner.calls == 0


def test_changed_continuation_refuses_before_one_use_publication_or_runner(tmp_path: Path) -> None:
    root, revision = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": revision})
    control = _PreviewControl("complete old patch")
    runner = _Runner()
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="test",
        agent_id="agent_test",
        agent_version="v1",
        runner=runner,
        prompt_builder=StaticPromptBuilder(),
        input_budget=_budget(request, 100_000),
        interruption_control=control,
    )
    adapter.prepare_input(request)
    control.text = "different patch"
    result = adapter.run(request)
    assert result.error is not None and result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert control.prepares == control.starts == runner.calls == 0
    assert not adapter._prepared_inputs


def test_unused_fallback_routes_and_overflow_resources_are_cleaned_up(tmp_path: Path) -> None:
    root, revision = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": revision})
    runners = (_Runner(), _Runner())
    adapters = tuple(
        CodexCliAgentAdapter(
            workspace_root=root,
            model=str(index),
            agent_id="agent_test",
            agent_version="v1",
            runner=runner,
            prompt_builder=StaticPromptBuilder(),
            input_budget=_budget(request, 100_000),
        )
        for index, runner in enumerate(runners)
    )
    fallback = FallbackAgentAdapter(
        tuple(
            ProviderAgentRoute("test", str(index), adapter)
            for index, adapter in enumerate(adapters)
        ),
        attempt_store=FileModelRouteAttemptStore(tmp_path / "routes"),
    )
    fallback.prepare_input(request)
    paths = tuple(adapter._prepared_inputs[request.run_id].schema_path for adapter in adapters)
    assert all(path.exists() for path in paths)
    assert not fallback._attempt_store.list_for_run(request.run_id)
    fallback.run(request)
    assert runners[0].calls == 1 and runners[1].calls == 0
    assert all(not path.exists() for path in paths)
    assert all(not adapter._prepared_inputs for adapter in adapters)

    # A later route cannot escape the original budget after durable start.
    next_request = request.model_copy(update={"run_id": "run_later_001"})
    adapters[1]._input_budget = _budget(next_request, 8)
    with pytest.raises(ContextBudgetExceeded):
        fallback.prepare_input(next_request)
    assert all(not adapter._prepared_inputs for adapter in adapters)
    assert not fallback._attempt_store.list_for_run(next_request.run_id)


@pytest.mark.parametrize("limit", [8, 100_000])
def test_responses_prepares_and_reuses_the_complete_initial_body(
    tmp_path: Path, limit: int
) -> None:
    root, revision = _repository(tmp_path)
    request, definition = responses_request(revision)
    builder = StaticPromptBuilder()
    transport = RecordingTransport(HttpResponse(status_code=401, body=b"{}"))
    adapter = ResponsesAgentAdapter(
        workspace_root=root,
        endpoint="https://fixture.invalid/v1",
        api_key="fixture-key",
        model="test",
        agent=definition,
        prompt_builder=builder,
        transport=transport,
        input_budget=_budget(request, limit),
    )
    if limit == 8:
        with pytest.raises(ContextBudgetExceeded):
            adapter.prepare_input(request)
        assert not transport.calls and not adapter._prepared_inputs
    else:
        adapter.prepare_input(request)
        expected = adapter._prepared_inputs[request.run_id].body
        assert b'"tools"' in expected and b'"schema"' in expected and not transport.calls
        adapter.run(request)
        assert transport.calls[0][2] == expected and len(builder.requests) == 1
        assert not adapter._prepared_inputs


def test_context_scope_error_remains_policy_refusal(tmp_path: Path) -> None:
    request = _coder_request()
    budget = _budget(request, 8)
    with pytest.raises(WorkspacePolicyError, match="Context differs"):
        budget.check(request.model_copy(update={"task_id": "task_another_001"}), "x" * 1_000)


def test_native_known_output_schema_cannot_escape_stdin_budget(tmp_path: Path) -> None:
    root, revision = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": revision})
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="test",
        agent_id="agent_test",
        agent_version="v1",
        runner=_Runner(),
        prompt_builder=StaticPromptBuilder(),
    )
    adapter.prepare_input(request)
    prepared = adapter._prepared_inputs[request.run_id]
    assert prepared.schema_path.read_text() == prepared.schema_content
    stdin_tokens = estimate_input_tokens(prepared.compiled_prompt)
    assert estimate_input_tokens(prepared.budget_content) > stdin_tokens + 1
    adapter.discard_prepared_input(request)
    adapter._input_budget = _budget(request, stdin_tokens + 1)
    with pytest.raises(ContextBudgetExceeded):
        adapter.prepare_input(request)
    assert not adapter._prepared_inputs


def test_native_actual_random_launcher_paths_are_reused_and_removed(tmp_path: Path) -> None:
    registered, worktree, revision = _project(tmp_path)
    _fake_tools(registered)
    request = _coder_request().model_copy(update={"source_revision": revision})
    runner = _Runner()
    adapter = CodexCliAgentAdapter(
        workspace_root=worktree,
        model="test",
        agent_id="agent_test",
        agent_version="v1",
        runner=runner,
        prompt_builder=StaticPromptBuilder(),
        input_budget=_budget(request, 100_000),
    )
    adapter.prepare_input(request)
    prepared = adapter._prepared_inputs[request.run_id]
    launcher = Path(prepared.environment["ASE_PROJECT_PYTHON"])
    scratch = Path(prepared.environment["TMPDIR"])
    assert launcher.exists() and scratch.exists()
    assert str(launcher) in prepared.compiled_prompt
    adapter.run(request)
    assert runner.stdin == prepared.compiled_prompt
    assert runner.environment["ASE_PROJECT_PYTHON"] == str(launcher)
    assert runner.environment["TMPDIR"] == str(scratch)
    assert not launcher.exists() and not scratch.exists()


def test_real_final_compilation_blocks_in_retry_engine_without_durable_start_or_provider(
    tmp_path: Path,
) -> None:
    scripted = ScriptedAdapter()
    root = tmp_path / "project"
    root.mkdir()
    task = _task(root).model_copy(update={"base_ref": "b" * 40})
    repository = SqliteTaskRepository(tmp_path / "tasks.sqlite")
    repository.create(task)
    contexts = InMemoryContextStore()
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    records = KnowledgeRecordStore(tmp_path / "invocations")
    bound_guard = guard(_coder_request().model_copy(update={"task_id": task.id}))
    native_runner = _Runner()
    native = CodexCliAgentAdapter(
        workspace_root=tmp_path / "project",
        model="test",
        agent_id="agent_test",
        agent_version="v1",
        runner=native_runner,
        prompt_builder=StaticPromptBuilder(
            PromptPayload(
                messages=(
                    PromptMessage(role="system", content="original policy"),
                    PromptMessage(role="user", content="complete final payload" * 10_000),
                )
            )
        ),
        input_budget=BoundModelInputBudget(StoredContextResolver(contexts, artifacts)),
    )
    gate = PreflightInvocationControl(
        delegate=DurableInvocationControl(records, bound_guard),
        guard=bound_guard,
        task_reader=lambda: repository.get(task.id),
        inspect=lambda *_: None,
        records=records,
        failure_control=cast(WorkerDeliveryFailureControl, _Failure()),
        prepare_input=native.prepare_input,
        discard_prepared_input=native.discard_prepared_input,
    )
    runner = RetryingOrchestrator(
        repository=repository,
        artifact_store=artifacts,
        context_builder=FileRunContextBuilder(
            tmp_path / "project",
            context_store=contexts,
            budget=ContextBudget(max_input_tokens=32_000, reserved_output_tokens=4000),
        ),
        agent_adapter=scripted,
        agent_definitions=_definitions(),
        invocation_control=gate,
        identities=AttemptIdentityFactory(),
        clock=_clock,
    )
    try:
        result = runner.run_task(task.id)
        assert isinstance(result, BlockedResult)
        assert result.classification.value == "BUDGET_EXHAUSTED"
        assert result.task.status is TaskStatus.BLOCKED
        assert [request.role for request in scripted.requests] == [AgentRole.ORCHESTRATOR]
        assert native_runner.calls == 0 and not native._prepared_inputs
        assert records.list("invocation-starts", DeliveryInvocationStart) == ()
        assert records.list("invocation-outcomes", DeliveryInvocationOutcome) == ()
        assert repository.list_events(task.id)[-1].reason.startswith("BUDGET_EXHAUSTED:")
    finally:
        repository.close()
