"""Public production claims, immutable feedback and repeated Coder continuation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import pytest

from ai_software_engineer.agents import (
    AgentRequest,
    AgentResult,
    ContextPromptBuilder,
    StructuredModelResult,
)
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
    CodexInvocationResult,
)
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentRole,
    ArtifactKind,
    CoderProgressArtifact,
    CoderProgressContent,
    ImplementationReportArtifact,
    PlanArtifact,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.manager import production_backend, production_delivery
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
    _ScriptedStructuredClient,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_production_continuation import _coder_draft

Scenario = Literal["repeat", "progress", "qa_feedback", "review_feedback"]
DESIRED = "hello from the team\n"
DRAFT = "hello from the team draft\n"


class _ReportTemplate(_ScriptedDeliveryAdapter):
    """Template construction is separate from the independent command verdict below."""

    def __init__(self, definition: AgentDefinition, workspace: Path, expected: str) -> None:
        super().__init__(definition, workspace)
        self._expected = expected

    def _greeting(self, request: AgentRequest) -> str:
        del request
        return self._expected


def _progress(adapter: CodexCliAgentAdapter, request: AgentRequest) -> CoderProgressArtifact:
    assert isinstance(adapter._prompt_builder, ContextPromptBuilder)
    plan = next(
        item
        for item in (
            adapter._prompt_builder._resolver.get_artifact(identity)
            for identity in request.input_artifact_ids
        )
        if isinstance(item, PlanArtifact)
    )
    draft = cast(ImplementationReportArtifact, _coder_draft(adapter, request))
    return CoderProgressArtifact.model_validate(
        {
            **draft.to_wire(),
            "artifact_id": f"art_progress_{request.run_id.removeprefix('run_')}",
            "kind": ArtifactKind.CODER_PROGRESS,
            "supersedes": (request.expected_supersedes_by_kind or {}).get(
                ArtifactKind.CODER_PROGRESS
            ),
            "content": CoderProgressContent(
                checkpoint_sequence=request.attempt,
                summary="The greeting is partially implemented and needs another bounded run.",
                changed_files=draft.content.changed_files,
                completed_step_ids=(),
                remaining_step_ids=tuple(step.step_id for step in plan.content.steps),
                tests_run=(),
                next_actions=("Complete the greeting and independently verify it.",),
            ).to_wire(),
        }
    )


@pytest.mark.mysql
def test_public_native_preflight_allows_coder_but_waits_before_qa_without_executor(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool presence and model prose cannot substitute for an executable registration."""
    from ai_software_engineer.domain.delivery_disposition import DeliveryResponsibility
    from ai_software_engineer.knowledge.store import KnowledgeRecordStore
    from ai_software_engineer.manager.delivery_preflight import (
        DeliveryPreflightCheckpoint,
        DeliveryPreflightReceipt,
    )

    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    (repository / "pyproject.toml").write_text('[project]\nname = "greeting"\nversion = "0.1.0"\n')
    (repository / "tests").mkdir()
    (repository / "tests/test_greeting.py").write_text("def test_greeting():\n    assert True\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", "pyproject.toml", "tests/test_greeting.py", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    source = _git_output("rev-parse", "HEAD", cwd=repository)
    original_complete = _ScriptedStructuredClient.complete
    calls: list[AgentRequest] = []

    def planned_test(
        self: _ScriptedStructuredClient,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        result = original_complete(
            self,
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )
        if output_schema.get("title") == "TechnicalDesignDraft":
            payload = dict(result.payload)
            payload["acceptance_mappings"] = [
                {
                    "acceptance_criterion_id": "ac_001_001",
                    "verification_strategy": "Run the exact greeting acceptance test.",
                    "test_levels": ["unit"],
                    "verification_argv": ["pytest", "tests/test_greeting.py::test_greeting"],
                    "controlled_capability_kind": "unregistered_greeting_executor_v1",
                }
            ]
            return StructuredModelResult(payload=payload, duration_ms=result.duration_ms)
        return result

    class Runner:
        def __init__(self, adapter: CodexCliAgentAdapter, request: AgentRequest) -> None:
            self.adapter, self.request = adapter, request

        def run(
            self,
            argv: tuple[str, ...],
            *,
            cwd: Path,
            environment: Mapping[str, str],
            stdin: str,
            timeout_seconds: float,
        ) -> CodexInvocationResult:
            request = self.request
            assert request.role is AgentRole.CODER
            guard = cast(WorkerExecutionGuard, self.adapter._execution_guard)
            guard.check()
            calls.append(request)
            (cwd / "hello.txt").write_text(DESIRED)
            artifact = _coder_draft(self.adapter, request)
            output = Path(argv[argv.index("--output-last-message") + 1])
            output.write_text(artifact.model_dump_json())
            return CodexInvocationResult(returncode=0, stdout="", stderr="")

    class ObservedCoder(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            assert request.role is AgentRole.CODER
            self._runner = Runner(self, request)
            return super().run(request)

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", planned_test)
    monkeypatch.setattr(
        production_backend, "ConfiguredStructuredClientFactory", lambda *_: _ScriptedClientFactory()
    )
    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", ObservedCoder)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test Project",
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-primary", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
        live_model_execution=True,
    )
    host = TeamHost(
        config=config,
        environment={
            "ASE_MYSQL_DSN": mysql_dsn,
            "PATH": os.environ.get("PATH", os.defpath),
            "GIT_AUTHOR_NAME": "ASE Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "ASE Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        },
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
    )
    service = host.project_entry()
    product = service.start(
        StartProjectDelivery(
            repository_root=str(repository),
            requirement="Update the greeting.",
            title="Preflight controlled executor wait",
        )
    ).checkpoint
    approved = service.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-preflight-product-approval",
        )
    )
    assert len(calls) == 1 and calls[0].role is AgentRole.CODER
    checkpoint = approved.checkpoint
    assert checkpoint.stage is DeliveryStage.DELIVERING
    assert checkpoint.task_id is not None and checkpoint.task_status is TaskStatus.QA
    (waiting,) = tuple(
        item
        for item in host.work_queue.items_for_task(checkpoint.task_id)
        if item.status is WorkItemStatus.WAITING_DEPENDENCY
    )
    assert waiting.role is AgentRole.QA and waiting.wait_disposition is not None
    assert waiting.wait_disposition.responsibility is DeliveryResponsibility.ENGINEERING
    assert waiting.wait_disposition.resume_condition == "verified_prerequisites"
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    sidecar = host.projects()[0].root / "repositories" / str(checkpoint.repository_id)
    records = KnowledgeRecordStore(sidecar / "state/delivery-preflight", read_only=True)
    (receipt,) = records.list("preflight-receipts", DeliveryPreflightReceipt)
    (claim_checkpoint,) = records.list("preflight-checkpoints", DeliveryPreflightCheckpoint)
    receipt.validate_integrity()
    claim_checkpoint.validate_integrity()
    assert receipt.task_id == checkpoint.task_id and receipt.status == "WAIT_ENGINEERING"
    assert any(
        item.reason_code == "CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED"
        for item in receipt.observations
    )
    assert claim_checkpoint.work_item_id != waiting.id
    assert claim_checkpoint.receipt_sha256 == receipt.receipt_sha256
    assert _git_output("rev-parse", "HEAD", cwd=repository) == source
    assert (repository / "hello.txt").read_text() == "hello\n"
    assert not (repository / ".ase").exists()
    reopened = KnowledgeRecordStore(sidecar / "state/delivery-preflight", read_only=True)
    assert reopened.list("preflight-receipts", DeliveryPreflightReceipt) == (receipt,)
