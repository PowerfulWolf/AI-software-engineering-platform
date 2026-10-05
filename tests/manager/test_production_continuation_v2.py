"""Public production claims, immutable feedback and repeated Coder continuation."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    ContextPromptBuilder,
    StructuredModelResult,
)
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, model_route_root
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentRole,
    Artifact,
    ArtifactKind,
    CoderProgressArtifact,
    CoderProgressContent,
    Evidence,
    EvidenceType,
    Finding,
    FindingSeverity,
    ImplementationReportArtifact,
    PlanArtifact,
    QaCriterionStatus,
    QaReportArtifact,
    QaReportStatus,
    QaTestRun,
    QaTestStatus,
    ReviewReportArtifact,
    ReviewVerdict,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.agent import ROLE_OUTPUTS
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.execution import SubprocessCommandExecutor
from ai_software_engineer.git import WorkspacePolicy, WorkspacePolicyError
from ai_software_engineer.manager import production_backend, production_delivery
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration import RetryDeliveryResult
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
    _ScriptedStructuredClient,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_production_continuation import Invocation, _coder_draft

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
@pytest.mark.parametrize("scenario", ["repeat", "progress", "qa_feedback", "review_feedback"])
def test_public_native_entry_preserves_multiple_rounds_progress_and_verdicts(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    scenario: Scenario,
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    source = _git_output("rev-parse", "HEAD", cwd=repository)
    calls: list[Invocation] = []
    results: list[AgentResult] = []
    stopped_run_ids: list[str] = []
    negative_reports: list[Artifact] = []
    completed_drafts: list[Artifact] = []
    progress_id: str | None = None
    first_product = True
    original_complete = _ScriptedStructuredClient.complete

    def clarify_once(
        self: _ScriptedStructuredClient,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        nonlocal first_product
        if output_schema.get("title") == "ProductDraft" and first_product:
            first_product = False
            return StructuredModelResult(
                payload={
                    "action": "clarify",
                    "summary": "Confirm the greeting file scope.",
                    "questions": ["Is hello.txt the only production change?"],
                },
                duration_ms=0,
            )
        result = original_complete(
            self,
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )
        if output_schema.get("title") == "TechnicalDesignDraft":
            # This text-only repository is independently read from the pinned Git
            # candidate. Declare that exact inspection rather than a fictitious
            # test entrypoint; the production preflight gate remains active.
            payload = dict(result.payload)
            mappings = payload["acceptance_mappings"]
            assert isinstance(mappings, list)
            payload["acceptance_mappings"] = [
                {
                    **mapping,
                    "test_levels": ["inspection"],
                    "verification_inspection": {
                        "kind": "source",
                        "paths": ["hello.txt"],
                        "checklist": [
                            "Read the committed greeting and compare with the approved format."
                        ],
                    },
                }
                for mapping in mappings
            ]
            return StructuredModelResult(payload=payload, duration_ms=result.duration_ms)
        return result

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", clarify_once)
    monkeypatch.setattr(
        production_backend, "ConfiguredStructuredClientFactory", lambda *_: _ScriptedClientFactory()
    )

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
            nonlocal progress_id
            adapter, request = self.adapter, self.request
            guard = cast(WorkerExecutionGuard, adapter._execution_guard)
            guard.check()
            assert guard.lease is not None
            claim = guard.lease.claim
            assert claim.work_item.role is request.role
            assert claim.work_item.attempt == request.attempt
            assert claim.lease.task_id == request.task_id
            calls.append(
                Invocation(
                    request,
                    claim,
                    cwd,
                    _git_output("branch", "--show-current", cwd=cwd),
                    _git_output("rev-parse", "HEAD", cwd=cwd),
                    adapter._model,
                )
            )
            assert adapter._model == "gpt-primary"
            assert "PRIVATE_TEST_SECRET" not in environment
            policy = WorkspacePolicy(cwd, request.permissions)
            assert _git_output("rev-parse", "HEAD", cwd=cwd) == request.source_revision
            if request.role is AgentRole.CODER:
                assert isinstance(adapter._interruption_control, NativeCoderContinuation)
                policy.authorize_write("hello.txt")
                with pytest.raises(WorkspacePolicyError):
                    policy.authorize_write(".trellis/spec/core/forbidden.md")
                ordinal = sum(call.request.role is AgentRole.CODER for call in calls)
                assert request.work_slice is not None
                assert request.work_slice.attempt == request.attempt
                assert request.work_slice.source_revision == request.source_revision
                assert request.work_slice.authorized_work_remaining == 5 - ordinal + 1
                if negative_reports and ordinal >= 3:
                    assert negative_reports[0].artifact_id in request.input_artifact_ids
                    assert request.expected_parent_artifact_ids is not None
                    assert negative_reports[0].artifact_id in request.expected_parent_artifact_ids
                    assert isinstance(negative_reports[0], (QaReportArtifact, ReviewReportArtifact))
                    assert negative_reports[0].content.findings[0].message in stdin
                    assert (request.expected_supersedes_by_kind or {})[
                        ArtifactKind.IMPLEMENTATION_REPORT
                    ] == completed_drafts[-1].artifact_id
                    assert request.source_revision != source
                if scenario == "progress" and ordinal == 1:
                    (cwd / "hello.txt").write_text("progress draft\n")
                    artifact: Artifact = _progress(adapter, request)
                    progress_id = artifact.artifact_id
                else:
                    stop = (
                        (scenario == "repeat" and ordinal in (1, 2))
                        or (scenario == "progress" and ordinal == 2)
                        or (scenario in ("qa_feedback", "review_feedback") and ordinal in (1, 3))
                    )
                    if stop:
                        if ordinal > 1:
                            assert (cwd / "hello.txt").read_text() in (
                                "partial-1\n",
                                "progress draft\n",
                                DRAFT,
                            )
                            if scenario == "progress":
                                assert request.continuation_checkpoint_id == progress_id
                                assert request.continuation_changed_paths == ("hello.txt",)
                        # Actual process creation and group termination produce the stop proof.
                        outcome = SubprocessCodexCommandRunner(guard).run(
                            (
                                sys.executable,
                                "-c",
                                "from pathlib import Path; import sys,time; "
                                "sys.stdin.read(); "
                                f"Path('hello.txt').write_text('partial-{ordinal}\\n'); "
                                "time.sleep(30)",
                            ),
                            cwd=cwd,
                            environment=environment,
                            stdin=stdin,
                            timeout_seconds=min(timeout_seconds, 0.5),
                        )
                        assert outcome.timed_out and outcome.process_stop is not None
                        outcome.process_stop.validate_integrity()
                        assert outcome.process_stop.kind == "local_execution_limit"
                        with pytest.raises(ProcessLookupError):
                            os.killpg(outcome.process_stop.group_id, 0)
                        stopped_run_ids.append(request.run_id)
                        return outcome
                    expected_prior = f"partial-{ordinal - 1}\n"
                    assert (cwd / "hello.txt").read_text() == expected_prior
                    assert "完整补丁" in stdin and expected_prior.strip() in stdin
                    if scenario == "progress":
                        assert request.continuation_checkpoint_id == progress_id
                    (cwd / "hello.txt").write_text(
                        DRAFT
                        if scenario in ("qa_feedback", "review_feedback") and ordinal == 2
                        else DESIRED
                    )
                    artifact = _coder_draft(adapter, request).model_copy(
                        update={
                            "supersedes": (request.expected_supersedes_by_kind or {}).get(
                                ArtifactKind.IMPLEMENTATION_REPORT
                            ),
                        }
                    )
                    completed_drafts.append(artifact)
            else:
                assert request.role in (AgentRole.QA, AgentRole.REVIEWER)
                assert adapter._interruption_control is None
                with pytest.raises(WorkspacePolicyError):
                    policy.authorize_write("hello.txt")
                is_draft = (
                    scenario in ("qa_feedback", "review_feedback")
                    and sum(call.request.role is AgentRole.CODER for call in calls) == 2
                )
                expected_bytes = DRAFT if is_draft else DESIRED
                definition = AgentDefinition(
                    id=adapter._agent_id,
                    role=request.role,
                    version=adapter._agent_version,
                    model=adapter._model,
                    permissions=request.permissions,
                    input_artifacts=(),
                    output_artifacts=ROLE_OUTPUTS[request.role],
                    max_retries=0,
                    timeout_seconds=request.timeout_seconds,
                )
                report = _ReportTemplate(definition, cwd, expected_bytes).run(request)
                assert report.artifact is not None
                artifact = report.artifact
                command = ("git", "show", f"{request.source_revision}:hello.txt")
                checked = SubprocessCommandExecutor(
                    cwd, request.permissions, environment=environment, execution_guard=guard
                ).run(command, timeout_seconds=5)
                assert checked.returncode == 0 and checked.stdout == expected_bytes
                evidence_path = tmp_path / f"verification-{request.run_id}.json"
                evidence_path.write_text(checked.model_dump_json())
                evidence = Evidence(
                    evidence_id=f"ev_{request.run_id.removeprefix('run_')}",
                    type=EvidenceType.TEST
                    if request.role is AgentRole.QA
                    else EvidenceType.COMMAND,
                    uri=evidence_path.as_uri(),
                    description="Independent role read the exact committed candidate greeting.",
                    sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                )
                reject = is_draft and (
                    (scenario == "qa_feedback" and request.role is AgentRole.QA)
                    or (scenario == "review_feedback" and request.role is AgentRole.REVIEWER)
                )
                finding = Finding(
                    finding_id=f"finding_{request.run_id}",
                    severity=FindingSeverity.MAJOR,
                    message="Remove the draft suffix and publish the approved greeting.",
                    file="hello.txt",
                    line=1,
                    evidence_ids=(evidence.evidence_id,),
                    recommendation="Use the exact greeting and rerun independent verification.",
                )
                if isinstance(artifact, QaReportArtifact):
                    # QA in the review-rejection case verifies the separately stated basic
                    # greeting prefix; Reviewer independently enforces final format.
                    accepted = (
                        checked.stdout == DESIRED
                        if scenario != "review_feedback"
                        else checked.stdout.startswith("hello from the team")
                    )
                    assert accepted is not reject
                    artifact = artifact.model_copy(
                        update={
                            "evidence": (evidence,),
                            "content": artifact.content.model_copy(
                                update={
                                    "status": QaReportStatus.FAIL
                                    if reject
                                    else QaReportStatus.PASS,
                                    "criteria_results": tuple(
                                        item.model_copy(
                                            update={
                                                "status": QaCriterionStatus.FAIL
                                                if reject
                                                else QaCriterionStatus.PASS,
                                                "evidence_ids": (evidence.evidence_id,),
                                            }
                                        )
                                        for item in artifact.content.criteria_results
                                    ),
                                    "tests_run": (
                                        QaTestRun(
                                            command=" ".join(command),
                                            status=QaTestStatus.FAIL
                                            if reject
                                            else QaTestStatus.PASS,
                                            evidence_id=evidence.evidence_id,
                                            duration_ms=checked.duration_ms,
                                        ),
                                    ),
                                    "findings": (finding,) if reject else (),
                                }
                            ),
                        }
                    )
                else:
                    assert isinstance(artifact, ReviewReportArtifact)
                    assert (checked.stdout == DESIRED) is not reject
                    artifact = artifact.model_copy(
                        update={
                            "evidence": (evidence,),
                            "content": artifact.content.model_copy(
                                update={
                                    "verdict": ReviewVerdict.REJECT
                                    if reject
                                    else ReviewVerdict.APPROVE,
                                    "findings": (finding,) if reject else (),
                                    "evidence": (evidence.evidence_id,),
                                    "summary": finding.message
                                    if reject
                                    else "The approved greeting is complete.",
                                }
                            ),
                        }
                    )
                if reject:
                    negative_reports.append(artifact)
            output = Path(argv[argv.index("--output-last-message") + 1])
            output.write_text(artifact.model_dump_json())
            return CodexInvocationResult(returncode=0)

    class ObservedCodex(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            nonlocal progress_id
            self._runner = Runner(self, request)
            result = super().run(request)
            sealed = result.artifact
            if isinstance(sealed, CoderProgressArtifact):
                progress_id = sealed.artifact_id
            if isinstance(sealed, ImplementationReportArtifact):
                completed_drafts[-1] = sealed
            if (
                isinstance(sealed, QaReportArtifact)
                and sealed.content.status is QaReportStatus.FAIL
            ) or (
                isinstance(sealed, ReviewReportArtifact)
                and sealed.content.verdict is ReviewVerdict.REJECT
            ):
                negative_reports[-1] = sealed
            results.append(result)
            return result

    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", ObservedCodex)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test Project",
        model_routes=tuple(
            ProviderRouteConfig(provider="codex", model=model, kind=ModelProviderKind.CODEX_CLI)
            for model in ("gpt-primary", "gpt-fallback")
        ),
        live_model_execution=True,
        execution_retry_policy=ExecutionRetryPolicy(coder=StageRetryPolicy(max_attempts=5)),
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
            "PRIVATE_TEST_SECRET": "must-not-be-inherited",
        },
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
    )
    service = host.project_entry()
    started = service.start(
        StartProjectDelivery(
            repository_root=str(repository),
            requirement="Update the greeting.",
            title=f"Continuation {scenario}",
        )
    ).checkpoint
    product = service.reply(
        ReplyToProduct(
            delivery_id=started.delivery_id,
            expected_checkpoint_sha256=started.checkpoint_sha256,
            message="Confirm hello.txt is the only production change.",
        )
    ).checkpoint
    approved = service.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-v2-product-approval",
        )
    )
    assert approved.checkpoint.stage is DeliveryStage.DONE, (
        approved.checkpoint.failure_summary,
        approved.checkpoint.failure_code,
        [(result.role, result.error) for result in results],
    )
    assert isinstance(approved.delivery, RetryDeliveryResult)
    task = approved.delivery.task
    assert task.status is TaskStatus.DONE
    assert task.interruption_continuation_policy is not None
    assert task.interruption_continuation_policy.schema_version == "v2"
    coder_calls = [call for call in calls if call.request.role is AgentRole.CODER]
    expected_count = 4 if scenario in ("qa_feedback", "review_feedback") else 3
    assert len(coder_calls) == expected_count
    assert task.work_attempt == task.attempts == expected_count
    assert task.transient_failures(AgentRole.CODER) == 0 and not task.retry_failures
    assert len({call.request.run_id for call in calls}) == len(calls)
    assert len({call.request.context_manifest_id for call in calls}) == len(calls)
    assert len({call.claim.lease.id for call in calls}) == len(calls)
    assert len({call.claim.work_item.id for call in calls}) == len(calls)
    assert len({call.workspace for call in coder_calls}) == 1
    assert all(call.branch == task.branch_name for call in coder_calls)
    assert all(
        call.request.permissions == coder_calls[0].request.permissions for call in coder_calls
    )
    assert all(call.input_head == call.request.source_revision for call in calls)
    assert len({call.claim.assignment.agent_id for call in calls}) == 3
    sidecar = host.projects()[0].root / "repositories" / str(approved.checkpoint.repository_id)
    store = FileContinuationStore(sidecar / "state/continuations" / task.id, task_id=task.id)
    receipts = store.receipts_for_task(task.id)
    admissions = store.admissions_for_task(task.id)
    assert len(receipts) == len(admissions) == len(stopped_run_ids)
    assert {receipt.request.run_id for receipt in receipts} == set(stopped_run_ids)
    for receipt in receipts:
        call = next(item for item in coder_calls if item.request.run_id == receipt.request.run_id)
        admission = next(
            item for item in admissions if item.receipt_sha256 == receipt.receipt_sha256
        )
        continued = next(
            item for item in coder_calls if item.request.run_id == admission.new_request.run_id
        )
        assert receipt.schema_version == admission.schema_version == "v2"
        assert receipt.original_work_item_id == call.claim.work_item.id
        assert receipt.claim_lease_id == call.claim.lease.id
        assert receipt.capture.worktree_path == str(call.workspace)
        assert receipt.mutation_paths == ("hello.txt",)
        assert admission.new_request == continued.request
        assert admission.next_work_item_id == continued.claim.work_item.id
        assert admission.next_lease_id == continued.claim.lease.id
        assert continued.claim.work_item.parent_work_item_id == call.claim.work_item.id
    # Read again through new store instances: every immutable round remains available.
    reopened = FileContinuationStore(sidecar / "state/continuations" / task.id, task_id=task.id)
    assert reopened.receipts_for_task(task.id) == receipts
    assert reopened.admissions_for_task(task.id) == admissions
    artifacts = FileArtifactStore(sidecar / "artifacts", read_only=True).list_for_task(task.id)
    implementations = [item for item in artifacts if isinstance(item, ImplementationReportArtifact)]
    qas = [item for item in artifacts if isinstance(item, QaReportArtifact)]
    reviews = [item for item in artifacts if isinstance(item, ReviewReportArtifact)]
    candidate = approved.checkpoint.candidate_revision
    assert candidate and candidate != source
    final_implementation = next(
        item for item in implementations if item.content.commit_sha == candidate
    )
    final_qa = next(item for item in qas if item.source_revision == candidate)
    final_review = next(item for item in reviews if item.source_revision == candidate)
    assert final_qa.content.status is QaReportStatus.PASS
    assert final_review.content.verdict is ReviewVerdict.APPROVE
    assert final_implementation.source_revision == candidate
    if negative_reports:
        assert len(implementations) == len(qas) == 2
        persisted_negative = next(
            item for item in artifacts if item.artifact_id == negative_reports[0].artifact_id
        )
        assert persisted_negative.content == negative_reports[0].content
        first_implementation = next(
            item for item in implementations if item.artifact_id == completed_drafts[0].artifact_id
        )
        assert first_implementation.content.commit_sha != candidate
        assert final_implementation.supersedes == first_implementation.artifact_id
        assert persisted_negative.artifact_id in final_implementation.parent_artifact_ids
        if scenario == "review_feedback":
            assert len(reviews) == 2
            assert final_review.source_revision != persisted_negative.source_revision
            assert final_review.parent_artifact_ids == (final_qa.artifact_id,)
    if progress_id is not None:
        progress = next(item for item in artifacts if item.artifact_id == progress_id)
        assert isinstance(progress, CoderProgressArtifact)
        assert progress.source_revision == source
        assert progress.artifact_id in final_implementation.parent_artifact_ids
    assert _git_output("rev-parse", "HEAD", cwd=repository) == source
    assert (repository / "hello.txt").read_text() == "hello\n"
    assert _git_output("show", f"{candidate}:hello.txt", cwd=repository) == DESIRED.strip()
    route_store = FileModelRouteAttemptStore(model_route_root(sidecar), read_only=True)
    for call in calls:
        routes = route_store.list_for_run(call.request.run_id)
        assert len(routes) == 1 and routes[0].route_index == 1 and routes[0].model == "gpt-primary"
    stopped_results = [result for result in results if result.run_id in stopped_run_ids]
    assert all(
        result.error is not None and result.error.code is AgentErrorCode.WORK_INTERRUPTED
        for result in stopped_results
    )
    assert all(
        result.status is AgentRunStatus.SUCCEEDED
        for result in results
        if result.run_id not in stopped_run_ids
    )
    assert all(
        item.status is WorkItemStatus.CLOSED for item in host.work_queue.items_for_task(task.id)
    )
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    assert not (repository / ".ase").exists()


@pytest.mark.mysql
def test_public_native_preflight_waits_before_coder_when_executor_is_not_registered(
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

    class UninvokedCodex(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            calls.append(request)
            raise AssertionError("preflight must stop before any delivery model invocation")

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", planned_test)
    monkeypatch.setattr(
        production_backend, "ConfiguredStructuredClientFactory", lambda *_: _ScriptedClientFactory()
    )
    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", UninvokedCodex)
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
    assert not calls
    checkpoint = approved.checkpoint
    assert checkpoint.stage is DeliveryStage.DELIVERING
    assert checkpoint.task_id is not None and checkpoint.task_status is TaskStatus.IMPLEMENTING
    (waiting,) = tuple(
        item
        for item in host.work_queue.items_for_task(checkpoint.task_id)
        if item.status is WorkItemStatus.WAITING_DEPENDENCY
    )
    assert waiting.role is AgentRole.CODER and waiting.wait_disposition is not None
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
    assert claim_checkpoint.work_item_id == waiting.id
    assert claim_checkpoint.receipt_sha256 == receipt.receipt_sha256
    assert _git_output("rev-parse", "HEAD", cwd=repository) == source
    assert (repository / "hello.txt").read_text() == "hello\n"
    assert not (repository / ".ase").exists()
    reopened = KnowledgeRecordStore(sidecar / "state/delivery-preflight", read_only=True)
    assert reopened.list("preflight-receipts", DeliveryPreflightReceipt) == (receipt,)


@pytest.mark.mysql
@pytest.mark.parametrize(
    "verification_scenario",
    ["happy", "qa_timeout", "review_timeout", "qa_inconclusive", "qa_unstarted"],
)
def test_public_native_registered_python_verification_uses_original_claims_and_same_candidate(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    verification_scenario: Literal[
        "happy", "qa_timeout", "review_timeout", "qa_inconclusive", "qa_unstarted"
    ],
) -> None:
    """Only subprocess/resource ports are faked; production facts/Contexts are real."""
    import json
    from collections.abc import Callable

    from ai_software_engineer.agents.execution import ExecutionGuard
    from ai_software_engineer.domain.delivery_resolution import (
        DeliveryResolutionKind,
        InspectDeliveryWait,
        ResolveDeliveryWait,
    )
    from ai_software_engineer.domain.native_verification import (
        NativeVerificationWaiting,
        NativeVerificationWaitReason,
    )
    from ai_software_engineer.execution import CommandResult, CommandTimedOut
    from ai_software_engineer.knowledge.store import KnowledgeRecordStore
    from ai_software_engineer.manager.delivery_preflight import DeliveryPreflightReceipt
    from ai_software_engineer.manager.native_verification import RegisteredNativePythonVerifier
    from ai_software_engineer.manager.native_verification_store import NativeRoleVerificationBinding
    from ai_software_engineer.manager.python_mysql_proxy import MysqlUnixProxy
    from ai_software_engineer.manager.python_mysql_resources import IsolatedMysqlResource
    from ai_software_engineer.manager.python_verification import (
        PytestSelection,
        PythonMysqlHostPrerequisites,
    )
    from ai_software_engineer.manager.verifier_preparation import VerifierPreparationCheckpoint
    from ai_software_engineer.recovery.python_mysql_records import MysqlResourceIntent
    from ai_software_engineer.recovery.verification_records import VerificationExecutionRecord
    from ai_software_engineer.store import MySqlTaskRepository
    from ai_software_engineer.work_queue.models import QueueClaim
    from tests.manager.test_python_verification import capability

    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    (repository / "pyproject.toml").write_text('[project]\nname = "greeting"\nversion = "0.1.0"\n')
    (repository / "tests").mkdir()
    (repository / "tests/test_greeting.py").write_text(
        "from pathlib import Path\ndef test_greeting():\n"
        "    assert Path('hello.txt').read_text() == 'hello from the team\\n'\n"
    )
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", "pyproject.toml", "tests/test_greeting.py", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    source = _git_output("rev-parse", "HEAD", cwd=repository)
    node = "tests/test_greeting.py::test_greeting"
    cap = capability(tmp_path).model_copy(
        update={"selections": (PytestSelection(node_id=node, criterion_ids=("ac_001_001",)),)}
    )
    fields = cap.to_wire()
    prereqs = PythonMysqlHostPrerequisites.model_validate(
        {
            key: value
            for key, value in fields.items()
            if key
            not in {
                "selections",
                "denied_relative_paths",
                "max_cases",
                "resource_timeout_seconds",
                "transport",
                "kind",
            }
        }
        | {"kind": "python_mysql_host_prerequisites_v1"}
    )
    prefix = "ai_software_engineer.manager.native_verification."
    monkeypatch.setattr(
        prefix + "discover_python_mysql_host_prerequisites", lambda **kwargs: prereqs
    )
    monkeypatch.setattr(prefix + "discover_python_mysql_capability", lambda *args, **kwargs: cap)
    resources: list[MysqlResourceIntent] = []
    executions: list[tuple[QueueClaim, tuple[str, ...]]] = []
    preparation_timed_out = False
    calls: list[Invocation] = []
    results: list[AgentResult] = []
    receipts: list[VerificationExecutionRecord] = []
    bindings: list[NativeRoleVerificationBinding] = []
    original_command = SubprocessCommandExecutor.run
    original_complete = _ScriptedStructuredClient.complete
    original_prepare = RegisteredNativePythonVerifier.prepare_verifier
    unstarted_wait = False

    def prepare(
        registry: RegisteredNativePythonVerifier,
        *,
        request: AgentRequest,
        workspace_root: Path,
        guard: ExecutionGuard | None,
        allow_ordinary_commands: bool = False,
        route_sha256: str | None = None,
    ) -> None:
        nonlocal unstarted_wait
        if (
            verification_scenario == "qa_unstarted"
            and request.role is AgentRole.QA
            and not unstarted_wait
        ):
            unstarted_wait = True
            raise NativeVerificationWaiting(NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE)
        original_prepare(
            registry,
            request=request,
            workspace_root=workspace_root,
            guard=guard,
            allow_ordinary_commands=allow_ordinary_commands,
            route_sha256=route_sha256,
        )

    monkeypatch.setattr(RegisteredNativePythonVerifier, "prepare_verifier", prepare)

    def start(resource: IsolatedMysqlResource, guard: Callable[[], None]) -> None:
        guard()
        resource._record("INTENT")
        resource.container_id, resource.configuration_sha256 = "c" * 64, "d" * 64
        resource._record("CREATED")
        resources.append(resource.intent)

    def close(resource: IsolatedMysqlResource) -> None:
        resource._record("CLEANED")
        resource._docker_config.cleanup()

    def command(
        executor: SubprocessCommandExecutor,
        argv: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        nonlocal preparation_timed_out
        if argv[0] != cap.sandbox_executable:
            return original_command(executor, argv, timeout_seconds=timeout_seconds)
        guard = cast(WorkerExecutionGuard, executor._execution_guard)
        guard.check()
        assert guard.lease is not None
        assert guard.lease.claim.work_item.role in {AgentRole.QA, AgentRole.REVIEWER}
        private = json.loads(Path(argv[-2]).read_text())
        assert private["node_ids"] == [node]
        assert _git_output("rev-parse", "HEAD", cwd=executor._workspace_root) != source
        assert (executor._workspace_root / "hello.txt").read_text() == DESIRED
        executions.append((guard.lease.claim, argv))
        target_role = (
            AgentRole.QA
            if verification_scenario == "qa_timeout"
            else AgentRole.REVIEWER
            if verification_scenario == "review_timeout"
            else None
        )
        if guard.lease.claim.work_item.role is target_role and not preparation_timed_out:
            preparation_timed_out = True
            raise CommandTimedOut(argv, duration_ms=1000)
        return CommandResult(
            argv=argv,
            cwd=str(executor._workspace_root),
            returncode=0,
            stdout="1 passed in 0.01s",
            stderr="",
            duration_ms=10,
        )

    monkeypatch.setattr(IsolatedMysqlResource, "start", start)
    monkeypatch.setattr(IsolatedMysqlResource, "verify_principal", lambda *args: None)
    monkeypatch.setattr(IsolatedMysqlResource, "close", close)
    monkeypatch.setattr(MysqlUnixProxy, "__init__", lambda *args, **kwargs: None)
    monkeypatch.setattr(MysqlUnixProxy, "close", lambda *args: None)
    monkeypatch.setattr(SubprocessCommandExecutor, "run", command)

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
                    "verification_strategy": "Test the greeting and inspect its candidate.",
                    "test_levels": ["unit"],
                    "verification_argv": ["pytest", node],
                    "controlled_capability_kind": "codex_sandbox_pytest_mysql_v1",
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
            adapter, request = self.adapter, self.request
            guard = cast(WorkerExecutionGuard, adapter._execution_guard)
            guard.check()
            assert guard.lease is not None
            claim = guard.lease.claim
            calls.append(
                Invocation(
                    request,
                    claim,
                    cwd,
                    _git_output("branch", "--show-current", cwd=cwd),
                    _git_output("rev-parse", "HEAD", cwd=cwd),
                    adapter._model,
                )
            )
            if request.role is AgentRole.CODER:
                assert not resources and not executions
                (cwd / "hello.txt").write_text(DESIRED)
                artifact = _coder_draft(adapter, request)
            else:
                assert any(
                    existing.work_item.id == claim.work_item.id for existing, _ in executions
                )
                sidecar = host.projects()[0].root / "repositories" / claim.work_item.repository_id
                run_root = (
                    sidecar
                    / "native-role-verification"
                    / hashlib.sha256(request.task_id.encode()).hexdigest()
                    / hashlib.sha256(request.run_id.encode()).hexdigest()
                )
                binding = NativeRoleVerificationBinding.model_validate_json(
                    (run_root / "binding.json").read_text()
                )
                receipt_path = run_root / "finished.json"
                receipt = VerificationExecutionRecord.model_validate_json(receipt_path.read_text())
                binding.validate_integrity()
                receipt.validate_integrity()
                assert binding.plan.claim.lease_id == claim.lease.id
                assert binding.plan.claim.agent_id == claim.assignment.agent_id
                assert binding.plan.context_manifest_id == request.context_manifest_id
                assert receipt.candidate_revision == request.source_revision
                assert receipt.results and receipt.results[0].returncode == 0
                assert receipt.record_sha256 in stdin
                bindings.append(binding)
                receipts.append(receipt)
                # The independent role also inspects the exact candidate before
                # producing its own report; the platform command is no verdict.
                checked = SubprocessCommandExecutor(
                    cwd, request.permissions, environment=environment, execution_guard=guard
                ).run(("git", "show", f"{request.source_revision}:hello.txt"), timeout_seconds=5)
                assert checked.returncode == 0 and checked.stdout == DESIRED
                definition = AgentDefinition(
                    id=adapter._agent_id,
                    role=request.role,
                    version=adapter._agent_version,
                    model=adapter._model,
                    permissions=request.permissions,
                    input_artifacts=(),
                    output_artifacts=ROLE_OUTPUTS[request.role],
                    max_retries=0,
                    timeout_seconds=request.timeout_seconds,
                )
                draft = _ReportTemplate(definition, cwd, DESIRED).run(request)
                assert draft.artifact is not None
                artifact = draft.artifact
                artifact = artifact.model_copy(
                    update={
                        "supersedes": (request.expected_supersedes_by_kind or {}).get(
                            artifact.kind
                        ),
                        "parent_artifact_ids": request.expected_parent_artifact_ids,
                    }
                )
                evidence = Evidence(
                    evidence_id=f"ev_{request.run_id.removeprefix('run_')}",
                    type=EvidenceType.TEST,
                    uri=receipt_path.as_uri(),
                    description="This role's exact native controlled command receipt.",
                    sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                )
                if isinstance(artifact, QaReportArtifact):
                    inconclusive = (
                        verification_scenario == "qa_inconclusive"
                        and sum(call.request.role is AgentRole.QA for call in calls) == 1
                    )
                    if inconclusive:
                        # An actual independent read of a prerequisite proof fails.
                        # The native test receipt stays successful; this separate
                        # command/evidence establishes incomplete role verification.
                        probe_argv = (
                            "git",
                            "show",
                            f"{request.source_revision}:qa-environment-proof.txt",
                        )
                        probe = SubprocessCommandExecutor(
                            cwd,
                            request.permissions,
                            environment=environment,
                            execution_guard=guard,
                        ).run(probe_argv, timeout_seconds=5)
                        assert probe.returncode != 0
                        probe_path = tmp_path / f"qa-prerequisite-{request.run_id}.json"
                        probe_path.write_text(probe.model_dump_json())
                        probe_evidence = Evidence(
                            evidence_id=f"ev_environment_{request.run_id.removeprefix('run_')}",
                            type=EvidenceType.COMMAND,
                            uri=probe_path.as_uri(),
                            description="Independent QA could not read its environment proof.",
                            sha256=hashlib.sha256(probe_path.read_bytes()).hexdigest(),
                        )
                        artifact = artifact.model_copy(
                            update={
                                "evidence": (evidence, probe_evidence),
                                "content": artifact.content.model_copy(
                                    update={
                                        "status": QaReportStatus.FAIL,
                                        "criteria_results": tuple(
                                            item.model_copy(
                                                update={
                                                    "status": QaCriterionStatus.NOT_TESTED,
                                                    "evidence_ids": (probe_evidence.evidence_id,),
                                                }
                                            )
                                            for item in artifact.content.criteria_results
                                        ),
                                        "tests_run": (
                                            QaTestRun(
                                                command=" ".join(probe_argv),
                                                status=QaTestStatus.ERROR,
                                                evidence_id=probe_evidence.evidence_id,
                                                duration_ms=probe.duration_ms,
                                            ),
                                        ),
                                        "findings": (),
                                        "environment": {"prerequisite": "proof unavailable to QA"},
                                    }
                                ),
                            }
                        )
                    else:
                        artifact = artifact.model_copy(
                            update={
                                "evidence": (evidence,),
                                "content": artifact.content.model_copy(
                                    update={
                                        "criteria_results": tuple(
                                            item.model_copy(
                                                update={"evidence_ids": (evidence.evidence_id,)}
                                            )
                                            for item in artifact.content.criteria_results
                                        ),
                                        "tests_run": (
                                            QaTestRun(
                                                command=" ".join(receipt.results[0].argv),
                                                status=QaTestStatus.PASS,
                                                evidence_id=evidence.evidence_id,
                                                duration_ms=receipt.results[0].duration_ms,
                                            ),
                                        ),
                                    }
                                ),
                            }
                        )
                else:
                    assert isinstance(artifact, ReviewReportArtifact)
                    artifact = artifact.model_copy(
                        update={
                            "evidence": (evidence,),
                            "content": artifact.content.model_copy(
                                update={"evidence": (evidence.evidence_id,)}
                            ),
                        }
                    )
            Path(argv[argv.index("--output-last-message") + 1]).write_text(
                artifact.model_dump_json()
            )
            return CodexInvocationResult(returncode=0)

    class ObservedCodex(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            self._runner = Runner(self, request)
            result = super().run(request)
            results.append(result)
            return result

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", planned_test)
    monkeypatch.setattr(
        production_backend, "ConfiguredStructuredClientFactory", lambda *_: _ScriptedClientFactory()
    )
    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", ObservedCodex)
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
    runtime_environment = {
        "ASE_MYSQL_DSN": mysql_dsn,
        "PATH": os.environ.get("PATH", os.defpath),
        "GIT_AUTHOR_NAME": "ASE Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "ASE Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }

    def reopen_host() -> TeamHost:
        return TeamHost(
            config=config,
            environment=runtime_environment,
            structured_clients=_ScriptedClientFactory(),
            delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
        )

    host = reopen_host()
    service = host.project_entry()
    product = service.start(
        StartProjectDelivery(
            repository_root=str(repository),
            requirement="Update the greeting.",
            title="Registered Python native verification",
        )
    ).checkpoint
    approved = service.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-registered-test-product-approval",
        )
    )
    before_recovery = approved.checkpoint
    assert before_recovery.task_id is not None and before_recovery.repository_id is not None
    sidecar = host.projects()[0].root / "repositories" / before_recovery.repository_id
    old_bytes: dict[Path, bytes] = {}
    old_qa: QaReportArtifact | None = None
    resolution = None
    previous_claim: QueueClaim | None = None
    previous_request: AgentRequest | None = None
    if verification_scenario != "happy":
        waiting = tuple(
            item
            for item in host.work_queue.items_for_task(before_recovery.task_id)
            if item.status in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
        )
        assert len(waiting) == 1 and waiting[0].wait_disposition is not None
        item = waiting[0]
        assert item.wait_disposition is not None
        facts = item.wait_disposition.facts
        with MySqlTaskRepository(mysql_dsn) as repository_reader:
            paused_task = repository_reader.get(before_recovery.task_id)
        expected_role = (
            AgentRole.REVIEWER if verification_scenario == "review_timeout" else AgentRole.QA
        )
        assert item.role is expected_role
        assert paused_task.status is (
            TaskStatus.REVIEW if expected_role is AgentRole.REVIEWER else TaskStatus.QA
        )
        assert (
            paused_task.work_attempt == paused_task.attempts == 1 and not paused_task.retry_failures
        )
        assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
        investigation_command = InspectDeliveryWait(
            work_item_id=item.id,
            expected_disposition_sha256=item.wait_disposition.disposition_sha256,
            expected_task_intent_sha256=facts.task_intent_sha256,
            expected_source_revision=facts.source_revision,
            expected_checkpoint_sequence=facts.checkpoint_sequence,
        )
        assert facts.source_revision != source
        if verification_scenario == "qa_inconclusive":
            (old_qa,) = tuple(
                artifact
                for artifact in FileArtifactStore(
                    sidecar / "artifacts",
                    read_only=True,
                ).list_for_task(paused_task.id)
                if isinstance(artifact, QaReportArtifact)
            )
            assert old_qa.content.status is QaReportStatus.FAIL
            assert all(
                criterion.status is QaCriterionStatus.NOT_TESTED
                for criterion in old_qa.content.criteria_results
            )
            previous_request = next(
                call.request for call in calls if call.request.run_id == old_qa.producer.run_id
            )
            previous_claim = next(call.claim for call in calls if call.request == previous_request)
            from ai_software_engineer.team_view.reader import ProductionTeamReader

            projected = ProductionTeamReader(config, runtime_environment).snapshot("project_test")
            (waiting_view,) = tuple(
                view for view in projected.tasks if view.task_id == paused_task.id
            )
            assert waiting_view.execution is not None
            assert waiting_view.execution.state == "WAITING"
            old_entry = next(
                entry
                for entry in waiting_view.timeline
                if entry.run_id == old_qa.producer.run_id and entry.kind.value == "artifact"
            )
            assert old_entry.details["tests_run"] == [
                item.to_wire() for item in old_qa.content.tests_run
            ]
            assert old_entry.details["criteria_results"] == [
                item.model_dump(mode="json") for item in old_qa.content.criteria_results
            ]
            assert old_entry.details["environment"] == old_qa.content.environment
        else:
            preparations = KnowledgeRecordStore(
                sidecar / "state/delivery-preflight", read_only=True
            )
            (wait_marker,) = tuple(
                marker
                for marker in preparations.list(
                    "verifier-preparations",
                    VerifierPreparationCheckpoint,
                )
                if marker.result == "WAIT"
            )
            wait_marker.validate_integrity()
            assert wait_marker.observation.native_execution_state == (
                "NOT_STARTED" if verification_scenario == "qa_unstarted" else "FINISHED"
            )
            assert wait_marker.observation.native_failure_code == (
                None if verification_scenario == "qa_unstarted" else "COMMAND_TIMEOUT"
            )
            previous_request = wait_marker.request
            previous_claim = host.work_queue.original_claim(wait_marker.lease_id)
            assert all(call.request.run_id != previous_request.run_id for call in calls)
        old_bytes = {
            path: path.read_bytes()
            for path in (sidecar / "native-role-verification").rglob("*.json")
        }
        old_bytes.update(
            {
                path: path.read_bytes()
                for path in (sidecar / "state/delivery-preflight").rglob("*.json")
            }
        )
        # Reconstruct the production Host before investigation/consumption. Neither
        # model inactivity nor lease expiry is used as proof of native inactivity.
        call_count = len(calls)
        execution_count = len(executions)
        host = reopen_host()
        service = host.project_entry()
        proof = host.inspect_delivery_wait(
            investigation_command,
            project_id="project_test",
            delivery_id=before_recovery.delivery_id,
        )
        expected_kind = (
            DeliveryResolutionKind.REVERIFY_CANDIDATE
            if verification_scenario == "qa_inconclusive"
            else DeliveryResolutionKind.RESUME_UNINVOKED
            if verification_scenario == "qa_unstarted"
            else DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION
        )
        assert proof.permitted_resolutions == (expected_kind,) and not proof.missing
        assert len(calls) == call_count and len(executions) == execution_count
        if proof.verifier_preparation is not None:
            assert proof.verifier_preparation.budget_source == (
                None if verification_scenario == "qa_unstarted" else "frozen_work_attempt"
            )
        if proof.verification_retry is not None:
            assert proof.verification_retry.budget_source == "frozen_work_attempt"
        decision_command = ResolveDeliveryWait(
            **investigation_command.model_dump(),
            proof_sha256=proof.proof_sha256,
            resolution_kind=expected_kind,
            submitted_at=datetime.now(UTC),
        )
        resolution = host.resolve_delivery_wait(
            decision_command,
            project_id="project_test",
            delivery_id=before_recovery.delivery_id,
        )
        assert resolution.retry_failure is None and resolution.retry_cause is None
        after_calls, after_executions = len(calls), len(executions)
        assert (
            host.resolve_delivery_wait(
                decision_command,
                project_id="project_test",
                delivery_id=before_recovery.delivery_id,
            )
            == resolution
        )
        assert len(calls) == after_calls and len(executions) == after_executions
        approved = service.status(before_recovery.delivery_id)
    assert approved.checkpoint.stage is DeliveryStage.DONE, (
        approved.checkpoint.failure_summary,
        [(result.role, result.error) for result in results],
    )
    with MySqlTaskRepository(mysql_dsn) as repository_reader:
        task = repository_reader.get(before_recovery.task_id)
    expected_attempt = 1 if verification_scenario in ("happy", "qa_unstarted") else 2
    assert task.status is TaskStatus.DONE and task.work_attempt == task.attempts == expected_attempt
    expected_roles = (
        [AgentRole.CODER, AgentRole.QA, AgentRole.QA, AgentRole.REVIEWER]
        if verification_scenario == "qa_inconclusive"
        else [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER]
    )
    assert [call.request.role for call in calls] == expected_roles
    assert len({call.claim.assignment.agent_id for call in calls}) == 3
    assert len({call.request.run_id for call in calls}) == len(calls)
    assert len({call.request.context_manifest_id for call in calls}) == len(calls)
    assert len({call.claim.lease.id for call in calls}) == len(calls)
    expected_resources = 2 if verification_scenario in ("happy", "qa_unstarted") else 3
    expected_reports = 3 if verification_scenario == "qa_inconclusive" else 2
    assert len(resources) == len(executions) == expected_resources
    assert len(receipts) == len(bindings) == expected_reports
    assert len({resource.resource_id for resource in resources}) == expected_resources
    if previous_request is not None and previous_claim is not None:
        resumed_call = next(
            call
            for call in calls
            if call.request.role is previous_request.role
            and call.request.attempt == expected_attempt
        )
        assert resumed_call.request.run_id != previous_request.run_id
        assert resumed_call.request.context_manifest_id != previous_request.context_manifest_id
        assert resumed_call.claim.lease.id != previous_claim.lease.id
        if verification_scenario == "qa_unstarted":
            assert resumed_call.claim.work_item.id == previous_claim.work_item.id
            assert (
                resumed_call.claim.work_item.dispatch_sequence
                == previous_claim.work_item.dispatch_sequence + 1
            )
        else:
            assert resumed_call.claim.work_item.parent_work_item_id == previous_claim.work_item.id
        assert resumed_call.request.source_revision == previous_request.source_revision
        assert resumed_call.claim.assignment.agent_id == previous_claim.assignment.agent_id
        assert sum(call.request.role is AgentRole.CODER for call in calls) == 1
    assert all(path.read_bytes() == original for path, original in old_bytes.items())
    assert {binding.plan.task_id for binding in bindings} == {task.id}
    assert {binding.plan.candidate_revision for binding in bindings} == {
        approved.checkpoint.candidate_revision
    }
    assert {binding.admission.authorization_source for binding in bindings} == {
        "frozen_task_role_authorization"
    }
    assert max(binding.admission.work_attempt for binding in bindings) == expected_attempt
    assert not task.retry_failures
    sidecar = host.projects()[0].root / "repositories" / str(approved.checkpoint.repository_id)
    accepted = FileArtifactStore(sidecar / "artifacts", read_only=True).list_for_task(task.id)
    qas = tuple(item for item in accepted if isinstance(item, QaReportArtifact))
    reviews = tuple(item for item in accepted if isinstance(item, ReviewReportArtifact))
    assert len(qas) == (2 if verification_scenario == "qa_inconclusive" else 1)
    assert len(reviews) == 1
    (final_qa,) = tuple(qa for qa in qas if qa.content.status is QaReportStatus.PASS)
    assert reviews[0].content.verdict is ReviewVerdict.APPROVE
    assert (
        final_qa.source_revision
        == reviews[0].source_revision
        == approved.checkpoint.candidate_revision
    )
    assert final_qa.artifact_id in reviews[0].parent_artifact_ids
    if old_qa is not None:
        assert next(qa for qa in qas if qa.artifact_id == old_qa.artifact_id) == old_qa
        assert final_qa.supersedes == old_qa.artifact_id
        projected = ProductionTeamReader(config, runtime_environment).snapshot("project_test")
        (done_view,) = tuple(view for view in projected.tasks if view.task_id == task.id)
        assert done_view.execution is not None and done_view.execution.state == "COMPLETED"
        qa_history = tuple(
            entry
            for entry in done_view.timeline
            if entry.kind.value == "artifact" and entry.role is AgentRole.QA
        )
        assert {entry.run_id for entry in qa_history} == {
            old_qa.producer.run_id,
            final_qa.producer.run_id,
        }
        assert (
            next(entry.details for entry in qa_history if entry.run_id == old_qa.producer.run_id)
            == old_entry.details
        )
    preflight = KnowledgeRecordStore(sidecar / "state/delivery-preflight", read_only=True)
    assert all(
        record.status == "READY"
        for record in preflight.list("preflight-receipts", DeliveryPreflightReceipt)
    )
    assert all(
        item.status is WorkItemStatus.CLOSED for item in host.work_queue.items_for_task(task.id)
    )
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    assert not list(sidecar.rglob("engineering-admission-*.json"))
    assert _git_output("rev-parse", "HEAD", cwd=repository) == source
    assert (repository / "hello.txt").read_text() == "hello\n"
