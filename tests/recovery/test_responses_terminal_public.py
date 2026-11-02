"""Public same-Requirement recovery from an actual completed Responses refusal."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

import ai_software_engineer.manager.production_delivery as production_delivery
from ai_software_engineer.agents import AgentErrorCode, HttpResponse, ResponsesAgentAdapter
from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, model_route_root
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.git import WorkspacePolicyError
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
)
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration.continuation_models import ContinuationRecordMissing
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.recovery.entry import NativeRecoveryEntry
from ai_software_engineer.recovery.resume import DeliveryResumeOutcome, DeliveryResumeResult
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.tools import PolicyBoundToolRegistry, ToolRequest
from ai_software_engineer.tools.models import ToolRejectedResult
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from tests.git.test_worktree import _git
from tests.recovery import facts_window_fixture
from tests.recovery.facts_window_fixture import modern_failed_native_fixture
from tests.recovery.test_inherited_reapply_entry import (
    _CompleteFactory,
    _two_file_failed_codex,
    _TwoFileClients,
)

pytestmark = pytest.mark.mysql


@pytest.fixture(autouse=True)
def isolated_mysql_facts() -> Iterator[None]:
    """The shared fixture owns exact exclusive test DB admission and cleanup."""
    yield


class _RefuseFirstWrite:
    def post(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HttpResponse:
        del url, headers, body, timeout_seconds
        return HttpResponse(
            status_code=200,
            body=json.dumps(
                {
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_write",
                            "name": "write_file",
                            "arguments": json.dumps(
                                {"path": "hello.txt", "content": "new greeting\n"}
                            ),
                        }
                    ]
                }
            ).encode(),
        )


class _WriteThenHistoricalUv:
    def post(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HttpResponse:
        del url, headers, body, timeout_seconds
        return HttpResponse(
            status_code=200,
            body=json.dumps(
                {
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_write",
                            "name": "write_file",
                            "arguments": json.dumps(
                                {"path": "hello.txt", "content": "new greeting\n"}
                            ),
                        },
                        {
                            "type": "function_call",
                            "call_id": "call_uv",
                            "name": "run_command",
                            "arguments": json.dumps({"argv": ["uv", "sync"]}),
                        },
                    ]
                }
            ).encode(),
        )


_real_tool_execute = PolicyBoundToolRegistry.execute


def _historical_uv_wrote_environment(
    registry: PolicyBoundToolRegistry, request: ToolRequest
) -> object:
    if request.tool != "run_command":
        return _real_tool_execute(registry, request)
    root = registry._workspace_root
    git_root = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    (git_root / "info/exclude").write_text(".venv/\n", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv/pyvenv.cfg").write_text("uv = 0.11.28\n", encoding="utf-8")
    raise WorkspacePolicyError("historical role tool created an unapproved environment")


def _refused_write(registry: PolicyBoundToolRegistry, request: ToolRequest) -> ToolRejectedResult:
    del registry
    assert request.tool == "write_file"
    return ToolRejectedResult(
        run_id=request.run_id,
        role=request.role,
        operation_id=request.operation_id,
        tool="write_file",
        error_code="PARENT_NOT_FOUND",
        error_message="fixture reproduces the historical parent refusal",
    )


@pytest.mark.parametrize("failure_mode", ["refusal", "workspace"])
def test_public_continue_reapplies_inherited_patch_after_completed_responses_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_mode: str
) -> None:
    monkeypatch.setattr(facts_window_fixture, "OfflineRecoveryClients", _TwoFileClients)
    monkeypatch.setattr(facts_window_fixture, "offline_failed_codex", _two_file_failed_codex)
    with modern_failed_native_fixture(tmp_path, monkeypatch) as native:
        route = ProviderRouteConfig(
            provider="codex",
            model="gpt-6-sol",
            kind=ModelProviderKind.RESPONSES,
            endpoint="https://example.invalid/v1/responses",
            api_key_env="ASE_FIXTURE_RESPONSES_KEY",
        )
        config = ProductionConfig.model_validate(
            {**native.config.to_wire(), "model_routes": [route.to_wire()]}
        )
        environment = {**native.environment, "ASE_FIXTURE_RESPONSES_KEY": "fixture-key"}

        def host() -> TeamHost:
            return TeamHost(
                config=config,
                environment=environment,
                structured_clients=_TwoFileClients(),
                delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
            )

        first_host = host()
        old = native.original
        assert old.source.failed_run_id is not None
        first_entry = first_host.recovery_entry()
        first_plan, _ = first_entry.propose(
            repository_root=str(native.project),
            delivery_id=old.source.scope.delivery_id,
            failed_run_id=old.source.failed_run_id,
            failed_context_id=old.source.failed_context_id,
            input_mode="coder_reapply",
        )
        real_adapter = production_delivery.ResponsesAgentAdapter

        def refused_adapter(**kwargs: object) -> ResponsesAgentAdapter:
            return real_adapter(
                **kwargs,
                transport=_RefuseFirstWrite()
                if failure_mode == "refusal"
                else _WriteThenHistoricalUv(),
            )

        with monkeypatch.context() as refusal:
            refusal.setattr(production_delivery, "ResponsesAgentAdapter", refused_adapter)
            refusal.setattr(
                PolicyBoundToolRegistry,
                "execute",
                _refused_write if failure_mode == "refusal" else _historical_uv_wrote_environment,
            )
            first_result = first_host.resume_delivery(
                ResumeProjectDelivery(
                    delivery_id=old.source.scope.delivery_id,
                    approved_plan_sha256=first_plan.plan_sha256,
                    approval_reference="exact-first-responses-plan",
                )
            )
        assert isinstance(first_result, DeliveryResumeResult)
        assert first_result.checkpoint.stage is DeliveryStage.BLOCKED
        with MySqlTaskRepository(native.config.require_mysql_dsn(native.environment)) as tasks:
            failed_task = tasks.get(first_plan.new_task_id)
        assert failed_task.status is TaskStatus.BLOCKED
        sidecar = Path(old.preparation.repository_workspace_root)
        routes = FileModelRouteAttemptStore(model_route_root(sidecar), read_only=True)
        matching = [
            item
            for run_dir in model_route_root(sidecar).iterdir()
            if run_dir.is_dir()
            for item in routes.list_for_run(run_dir.name)
            if item.task_id == failed_task.id and item.role is AgentRole.CODER
        ]
        assert len(matching) == 1
        failed_route = matching[0]
        assert failed_route.route_kind == "responses"
        assert failed_route.result.error is not None
        assert failed_route.result.error.code is AgentErrorCode.POLICY_VIOLATION
        continuation = FileContinuationStore(
            sidecar / "state/continuations" / failed_task.id, task_id=failed_task.id
        )
        start = continuation.capture_start(failed_route.run_id)
        assert start.request.run_id == failed_route.run_id
        invocation = KnowledgeRecordStore(sidecar / "state/invocations", read_only=True).get(
            "invocation-outcomes", start.claim.work_item.id, DeliveryInvocationOutcome
        )
        assert invocation.result == failed_route.result
        with pytest.raises(ContinuationRecordMissing):
            continuation.capture_stop(failed_route.run_id)

        second_host = host()
        proposed = second_host.resume_delivery(
            ResumeProjectDelivery(delivery_id=old.source.scope.delivery_id)
        )
        assert isinstance(proposed, DeliveryResumeResult)
        assert proposed.outcome is DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED
        assert proposed.recovery_plan_file is not None
        second_entry = second_host.recovery_entry()
        _, second_plan = second_entry.open_plan(Path(proposed.recovery_plan_file))
        assert second_plan.workspace_snapshot is not None
        assert second_plan.workspace_snapshot.completion_kind == (
            "responses_tool_refusal"
            if failure_mode == "refusal"
            else "responses_workspace_policy_failure"
        )
        if failure_mode == "workspace":
            assert second_plan.workspace_snapshot.schema_version == "v3"
            assert {item.path for item in second_plan.capture.files} == {"hello.txt"}
            assert {item.path for item in second_plan.workspace_snapshot.excluded_paths} == {
                ".venv/pyvenv.cfg"
            }
        assert second_plan.input_mode == "coder_reapply"
        assert len(second_plan.inherited_reapply_inputs or ()) == 1
        assert second_plan.inherited_reapply_inputs[0].patch == first_plan.capture.patch

        factories: list[_CompleteFactory] = []
        original_execute = NativeRecoveryEntry.execute

        def complete_offline(entry: NativeRecoveryEntry, path: Path) -> object:
            def make_factory(seed: RecoverySeedService) -> _CompleteFactory:
                factory = _CompleteFactory(seed)
                factories.append(factory)
                return factory

            return original_execute(entry, path, route_factory=make_factory)

        monkeypatch.setattr(NativeRecoveryEntry, "execute", complete_offline)
        completed = second_host.resume_delivery(
            ResumeProjectDelivery(
                delivery_id=old.source.scope.delivery_id,
                approved_plan_sha256=second_plan.plan_sha256,
                approval_reference="exact-completed-responses-refusal-plan",
            )
        )
        assert isinstance(completed, DeliveryResumeResult)
        assert completed.checkpoint.stage is DeliveryStage.DONE
        assert len(factories) == 1
        assert [request.role for request in factories[0].calls] == [
            AgentRole.CODER,
            AgentRole.QA,
            AgentRole.REVIEWER,
        ]
