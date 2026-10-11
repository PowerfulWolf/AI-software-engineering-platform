"""The public native entry continues a stopped Coder through real production seams."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    StructuredModelResult,
)
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, model_route_root
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentProducer,
    AgentRole,
    Artifact,
    ArtifactIntegrity,
    ChangedFile,
    ChangeType,
    Evidence,
    EvidenceType,
    ImplementationAcceptanceMapping,
    ImplementationReportArtifact,
    ImplementationReportContent,
    QaReportArtifact,
    QaTestRun,
    QaTestStatus,
    StateEvent,
    Task,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.agent import ROLE_OUTPUTS
from ai_software_engineer.execution import SubprocessCommandExecutor
from ai_software_engineer.git import WorkspacePolicy, WorkspacePolicyError
from ai_software_engineer.manager import (
    native_verification,
    production_backend,
    production_delivery,
)
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration import RetryDeliveryResult, RetryResult
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.recovery import RecoveryRejected, RecoveryScope
from ai_software_engineer.recovery.native import NativeRecoverySourceReader
from ai_software_engineer.recovery.verification_execution import VerificationEvidence
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.models import QueueClaim
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
    _ScriptedStructuredClient,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn


@dataclass(frozen=True)
class Invocation:
    request: AgentRequest
    claim: QueueClaim
    workspace: Path
    branch: str
    input_head: str
    model: str


def _coder_draft(adapter: CodexCliAgentAdapter, request: AgentRequest) -> Artifact:
    return ImplementationReportArtifact(
        artifact_id=f"art_impl_{request.run_id.removeprefix('run_')}",
        task_id=request.task_id,
        schema_version="v0.1",
        producer=AgentProducer(
            role=request.role,
            agent_id=adapter._agent_id,
            agent_version=adapter._agent_version,
            run_id=request.run_id,
        ),
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        created_at=datetime.now(UTC),
        parent_artifact_ids=request.input_artifact_ids,
        evidence=(),
        integrity=ArtifactIntegrity(sha256="0" * 64, validated=False),
        content=ImplementationReportContent(
            # The native executor reports a draft. Only CandidateCommitSkill
            # may replace this source with a platform-owned candidate commit.
            commit_sha=request.source_revision,
            changed_files=(
                ChangedFile(
                    path="hello.txt", change=ChangeType.MODIFIED, lines_added=1, lines_deleted=1
                ),
            ),
            acceptance_mapping=(
                ImplementationAcceptanceMapping(
                    criterion_id="ac_001_001", implementation="Updated the greeting.", tests=()
                ),
            ),
            tests_run=(),
            known_risks=(),
        ),
    )


@pytest.mark.mysql
@pytest.mark.parametrize("recover_delivery", [False, True], ids=["ordinary", "recovery"])
def test_public_native_entry_continues_stopped_coder_and_independently_verifies(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch, recover_delivery: bool
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
    recovery_started = False
    evidence_calls: list[tuple[AgentRequest, Path, QueueClaim]] = []
    prepare_calls: list[AgentRequest] = []
    original_prepare = native_verification.RegisteredNativePythonVerifier.prepare_verifier
    original_evidence = native_verification._RegisteredNativeVerificationEvidence.evidence_for

    def observed_prepare(
        registry: native_verification.RegisteredNativePythonVerifier,
        *,
        request: AgentRequest,
        workspace_root: Path,
        guard: ExecutionGuard | None,
        allow_ordinary_commands: bool = False,
        route_sha256: str | None = None,
    ) -> None:
        original_prepare(
            registry,
            request=request,
            workspace_root=workspace_root,
            guard=guard,
            allow_ordinary_commands=allow_ordinary_commands,
            route_sha256=route_sha256,
        )
        prepare_calls.append(request)

    def observed_evidence(
        provider: native_verification._RegisteredNativeVerificationEvidence,
        request: AgentRequest,
        workspace_root: Path,
        execution_guard: ExecutionGuard | None = None,
    ) -> VerificationEvidence:
        evidence = original_evidence(provider, request, workspace_root, execution_guard)
        guard = cast(WorkerExecutionGuard, execution_guard)
        guard.check()
        assert guard.lease is not None
        evidence_calls.append((request, workspace_root, guard.lease.claim))
        return evidence

    monkeypatch.setattr(
        native_verification.RegisteredNativePythonVerifier, "prepare_verifier", observed_prepare
    )
    monkeypatch.setattr(
        native_verification._RegisteredNativeVerificationEvidence, "evidence_for", observed_evidence
    )
    original_complete = _ScriptedStructuredClient.complete
    first_product_call = True

    def clarify_once(
        self: _ScriptedStructuredClient,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        nonlocal first_product_call
        if output_schema.get("title") == "ProductDraft" and first_product_call:
            first_product_call = False
            return StructuredModelResult(
                payload={
                    "action": "clarify",
                    "summary": "Confirm the requested file scope.",
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
        if output_schema.get("title") != "TechnicalDesignDraft":
            return result
        # This repository has no executable test entrypoint. Declare the exact
        # candidate inspection performed by QA rather than bypassing preflight.
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
                        "Read the exact committed greeting and compare the approved value."
                    ],
                },
            }
            for mapping in mappings
        ]
        return StructuredModelResult(payload=payload, duration_ms=result.duration_ms)

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", clarify_once)
    monkeypatch.setattr(
        production_backend,
        "ConfiguredStructuredClientFactory",
        lambda *_: _ScriptedClientFactory(),
    )

    class Runner(SubprocessCodexCommandRunner):
        def __init__(self, adapter: CodexCliAgentAdapter, request: AgentRequest) -> None:
            super().__init__(cast(ExecutionGuard, adapter._execution_guard))
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
            if request.role is AgentRole.CODER:
                assert isinstance(adapter._interruption_control, NativeCoderContinuation)
                policy.authorize_write("hello.txt")
                with pytest.raises(WorkspacePolicyError):
                    policy.authorize_write(".trellis/spec/core/forbidden.md")
                assert _git_output("rev-parse", "HEAD", cwd=cwd) == source
                if recover_delivery and not recovery_started:
                    # Produce a real terminal source, with owned native start/stop
                    # and preserved dirty progress. No fabricated stop or verdict.
                    outcome = SubprocessCodexCommandRunner(guard).run(
                        (
                            sys.executable,
                            "-c",
                            "from pathlib import Path; import sys; sys.stdin.read(); "
                            "Path('hello.txt').write_text('original preserved progress\\n'); "
                            "sys.stderr.write('error: authentication failure offline fixture\\n'); "
                            "raise SystemExit(1)",
                        ),
                        cwd=cwd,
                        environment=environment,
                        stdin=stdin,
                        timeout_seconds=5,
                    )
                    assert outcome.returncode == 1 and outcome.process_stop is not None
                    assert outcome.process_stop.kind == "failed"
                    outcome.process_stop.validate_integrity()
                    with pytest.raises(ProcessLookupError):
                        os.killpg(outcome.process_stop.group_id, 0)
                    return outcome
                if request.attempt == 1:
                    assert (cwd / "hello.txt").read_text() == (
                        "original preserved progress\n" if recover_delivery else "hello\n"
                    )
                    # Exercise the real owned subprocess runner and actual group
                    # shutdown proof, instead of fabricating a timeout receipt.
                    outcome = SubprocessCodexCommandRunner(guard).run(
                        (
                            sys.executable,
                            "-c",
                            "from pathlib import Path; import sys,time; "
                            "sys.stdin.read(); "
                            "Path('hello.txt').write_text('partially implemented\\n'); "
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
                    return outcome
                assert request.attempt == 2
                assert (cwd / "hello.txt").read_text() == "partially implemented\n"
                assert "完整补丁" in stdin and "partially implemented" in stdin
                (cwd / "hello.txt").write_text("hello from the team\n")
                artifact = _coder_draft(adapter, request)
            else:
                assert request.role in {AgentRole.QA, AgentRole.REVIEWER}
                assert request in prepare_calls
                assert any(item[0] == request for item in evidence_calls)
                assert adapter._interruption_control is None
                with pytest.raises(WorkspacePolicyError):
                    policy.authorize_write("hello.txt")
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
                report = _ScriptedDeliveryAdapter(definition, cwd).run(request)
                assert report.artifact is not None
                artifact = report.artifact
                if request.role is AgentRole.QA:
                    assert isinstance(artifact, QaReportArtifact)
                    test_argv = ("git", "show", f"{request.source_revision}:hello.txt")
                    policy.authorize_command(test_argv)
                    checked = SubprocessCommandExecutor(
                        cwd,
                        request.permissions,
                        environment=environment,
                        execution_guard=guard,
                    ).run(test_argv, timeout_seconds=5)
                    assert checked.returncode == 0 and checked.stdout == "hello from the team\n"
                    evidence_path = tmp_path / "qa-candidate-verification.txt"
                    evidence_path.write_text(checked.model_dump_json())
                    evidence = Evidence(
                        evidence_id="ev_owned_candidate_check",
                        type=EvidenceType.TEST,
                        uri=evidence_path.as_uri(),
                        description="QA independently read the exact committed candidate greeting.",
                        sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                    )
                    artifact = artifact.model_copy(
                        update={
                            "evidence": (evidence,),
                            "content": artifact.content.model_copy(
                                update={
                                    "tests_run": (
                                        QaTestRun(
                                            command=" ".join(test_argv),
                                            status=QaTestStatus.PASS,
                                            evidence_id=evidence.evidence_id,
                                            duration_ms=checked.duration_ms,
                                        ),
                                    ),
                                }
                            ),
                        }
                    )
            output = Path(argv[argv.index("--output-last-message") + 1])
            output.write_text(artifact.model_dump_json())
            return CodexInvocationResult(returncode=0)

        def run_observed(
            self,
            argv: tuple[str, ...],
            *,
            cwd: Path,
            environment: Mapping[str, str],
            stdin: str,
            timeout_seconds: float,
            observer: Callable[[CodexInvocationResult], None],
        ) -> CodexInvocationResult:
            # The fixture still executes its real owned child through ``run``;
            # this forwarding seam lets CodexCliAgentAdapter publish the same
            # native stop observer used by the production runner.
            result = self.run(
                argv,
                cwd=cwd,
                environment=environment,
                stdin=stdin,
                timeout_seconds=timeout_seconds,
            )
            observer(result)
            return result

    class ObservedCodex(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            self._runner = Runner(self, request)
            result = super().run(request)
            results.append(result)
            return result

    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", ObservedCodex)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test Project",
        model_routes=tuple(
            ProviderRouteConfig(provider="codex", model=model, kind=ModelProviderKind.CODEX_CLI)
            for model in (("gpt-primary",) if recover_delivery else ("gpt-primary", "gpt-fallback"))
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
            "PRIVATE_TEST_SECRET": "must-not-be-inherited",
        },
        structured_clients=_ScriptedClientFactory(),
        # Keep the real configured factory: it must receive the production
        # NativeCoderContinuation and ownership guard from the backend.
        delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
    )
    service = host.project_entry()
    started = service.start(
        StartProjectDelivery(
            repository_root=str(repository), requirement="Update the greeting.", title="Owned draft"
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
            approval_reference="exact-native-product-approval",
        )
    )
    original_task: Task | None = None
    original_events: tuple[StateEvent, ...] = ()
    original_workspace = None
    original_bytes: dict[str, bytes] = {}
    delivery: RetryResult | None
    if recover_delivery:
        failed = approved.checkpoint
        assert failed.stage is DeliveryStage.BLOCKED
        original = NativeRecoverySourceReader(config, host._environment).discover_failed_coder(
            RecoveryScope(
                team_id=config.team_id,
                repository_id=failed.repository_id,
                repository_root=str(repository),
                delivery_id=failed.delivery_id,
            )
        )
        original_task = original.task
        with MySqlTaskRepository(mysql_dsn) as task_repository:
            original_events = task_repository.list_events(original.task.id)
        original_workspace = calls[0].workspace
        original_bytes = {
            str(path.relative_to(original_workspace)): path.read_bytes()
            for path in original_workspace.rglob("*")
            if path.is_file()
        }
        original_continuation = FileContinuationStore(
            host.projects()[0].root
            / "repositories"
            / failed.repository_id
            / "state/continuations"
            / original.task.id,
            task_id=original.task.id,
        )
        original_start = original_continuation.capture_start(original.source.failed_run_id)
        original_stop = original_continuation.capture_stop(original.source.failed_run_id)
        assert original_stop.capture_start_sha256 == original_start.start_sha256
        assert original_stop.process_stop.kind == "failed"
        assert original_stop.original_error_code is AgentErrorCode.AUTHENTICATION_ERROR
        (repository / "platform-fix.txt").write_text("independent platform fix\n")
        _git("add", "platform-fix.txt", cwd=repository)
        _git("commit", "-m", "platform baseline fix", cwd=repository)
        source = _git_output("rev-parse", "HEAD", cwd=repository)
        recovery = host.recovery_entry()
        plan, plan_path = recovery.propose(
            repository_root=str(repository),
            delivery_id=failed.delivery_id,
            failed_run_id=original.source.failed_run_id,
            failed_context_id=original.source.failed_context_id,
        )
        authority = plan.target_authorization
        assert authority is not None
        assert plan.workspace_snapshot is not None
        assert plan.workspace_snapshot.capture_start_sha256 == original_start.start_sha256
        assert plan.workspace_snapshot.capture_stop_sha256 == original_stop.observation_sha256
        assert authority.source_retry_policy == original.task.retry_policy
        assert authority.source_max_attempts == original.task.max_attempts
        with pytest.raises(RecoveryRejected):
            recovery.execute(plan_path)
        with pytest.raises(RecoveryRejected):
            recovery.approve(plan_path, confirmed_plan="0" * 64, reference="wrong-plan")
        recovery.approve(
            plan_path, confirmed_plan=plan.plan_sha256, reference="exact-recovery-plan"
        )
        recovery_store, _ = recovery.open_plan(plan_path)
        sealed = recovery_store.get_task_record(plan.plan_sha256)
        assert sealed.task.engineering_policy == authority.engineering_policy
        assert (
            sealed.task.interruption_continuation_policy
            == authority.interruption_continuation_policy
        )
        recovery_started = True
        delivery = recovery.execute(plan_path)
        assert delivery.task.id == plan.new_task_id
        active_calls, active_results = calls[1:], results[1:]
    else:
        assert approved.checkpoint.stage is DeliveryStage.DONE, (
            approved.checkpoint.failure_summary,
            approved.checkpoint.failure_code,
            [(result.role, result.error) for result in results],
        )
        delivery = approved.delivery
        active_calls, active_results = calls, results
    assert isinstance(delivery, RetryDeliveryResult)
    task = delivery.task
    assert task.status is TaskStatus.DONE
    assert task.attempts == 2 and task.work_attempt == 2
    assert task.interruption_continuation_policy is not None
    assert task.transient_failures(AgentRole.CODER) == 0
    assert not task.retry_failures
    assert [call.request.role for call in active_calls] == [
        AgentRole.CODER,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    first, continued, qa, review = active_calls
    assert first.request.run_id != continued.request.run_id
    assert first.request.context_manifest_id != continued.request.context_manifest_id
    assert first.claim.lease.id != continued.claim.lease.id
    assert first.claim.work_item.id != continued.claim.work_item.id
    assert continued.claim.work_item.parent_work_item_id == first.claim.work_item.id
    assert first.request.permissions == continued.request.permissions
    assert first.workspace == continued.workspace
    assert first.branch == continued.branch == task.branch_name
    assert first.input_head == continued.input_head == source
    assert len({call.claim.lease.id for call in active_calls}) == 4
    assert (
        len(
            {
                qa.claim.assignment.agent_id,
                review.claim.assignment.agent_id,
                first.claim.assignment.agent_id,
            }
        )
        == 3
    )
    assert len({call.workspace for call in (continued, qa, review)}) == 3
    assert active_results[0].error is not None
    assert active_results[0].error.code is AgentErrorCode.WORK_INTERRUPTED
    assert all(result.status is AgentRunStatus.SUCCEEDED for result in active_results[1:])
    sidecar = host.projects()[0].root / "repositories" / str(approved.checkpoint.repository_id)
    store = FileContinuationStore(sidecar / "state/continuations" / task.id, task_id=task.id)
    receipt = store.get_receipt(first.request.run_id)
    admission = store.get_admission(task.id)
    assert receipt.request == first.request
    assert receipt.cause == "local_execution_limit"
    assert receipt.original_error_code is AgentErrorCode.TIMEOUT
    assert receipt.process_stop.kind == "local_execution_limit"
    assert receipt.original_work_item_id == first.claim.work_item.id
    assert receipt.claim_lease_id == first.claim.lease.id
    assert receipt.capture.worktree_path == str(first.workspace)
    assert receipt.mutation_paths == ("hello.txt",)
    assert receipt.scope.requirement_id == approved.checkpoint.delivery_id
    assert admission.new_request == continued.request
    assert admission.next_work_item_id == continued.claim.work_item.id
    assert admission.next_lease_id == continued.claim.lease.id
    assert admission.receipt_sha256 == receipt.receipt_sha256
    assert admission.policy_sha256 == task.interruption_continuation_policy.policy_sha256
    artifacts = FileArtifactStore(sidecar / "artifacts", read_only=True).list_for_task(task.id)
    implementation = next(a for a in artifacts if isinstance(a, ImplementationReportArtifact))
    candidate = implementation.content.commit_sha
    assert candidate and candidate != source
    if not recover_delivery:
        assert approved.checkpoint.candidate_revision == candidate
    else:
        assert approved.checkpoint.candidate_revision is None
    assert implementation.source_revision == implementation.content.commit_sha == candidate
    assert qa.input_head == review.input_head == candidate
    assert qa.request.source_revision == review.request.source_revision == candidate
    assert _git_output("rev-parse", "HEAD", cwd=repository) == source
    assert (repository / "hello.txt").read_text() == "hello\n"
    assert _git_output("show", f"{candidate}:hello.txt", cwd=repository) == "hello from the team"
    route_store = FileModelRouteAttemptStore(model_route_root(sidecar), read_only=True)
    for call in active_calls:
        attempts = route_store.list_for_run(call.request.run_id)
        assert len(attempts) == 1 and attempts[0].route_index == 1
        assert attempts[0].model == "gpt-primary"
    assert all(
        item.status is WorkItemStatus.CLOSED for item in host.work_queue.items_for_task(task.id)
    )
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    assert not (repository / ".ase").exists()
    assert {request.role for request in prepare_calls} == {AgentRole.QA, AgentRole.REVIEWER}
    assert {request.role for request, _, _ in evidence_calls} == {AgentRole.QA, AgentRole.REVIEWER}
    for request, root, claim in evidence_calls:
        assert request.task_id == task.id
        assert root == (qa.workspace if request.role is AgentRole.QA else review.workspace)
        assert claim.lease.id == (
            qa.claim.lease.id if request.role is AgentRole.QA else review.claim.lease.id
        )
    if original_task is not None:
        with MySqlTaskRepository(mysql_dsn) as task_repository:
            assert task_repository.get(original_task.id) == original_task
            assert task_repository.list_events(original_task.id) == original_events
        assert original_workspace is not None
        assert {
            str(path.relative_to(original_workspace)): path.read_bytes()
            for path in original_workspace.rglob("*")
            if path.is_file()
        } == original_bytes
