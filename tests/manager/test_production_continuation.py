"""The public native entry continues a stopped Coder through real production seams."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Mapping
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
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.agent import ROLE_OUTPUTS
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
def test_public_native_entry_continues_stopped_coder_and_independently_verifies(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
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
                if request.attempt == 1:
                    assert (cwd / "hello.txt").read_text() == "hello\n"
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
            for model in ("gpt-primary", "gpt-fallback")
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
    assert approved.checkpoint.stage is DeliveryStage.DONE, (
        approved.checkpoint.failure_summary,
        approved.checkpoint.failure_code,
        [(result.role, result.error) for result in results],
    )
    assert isinstance(approved.delivery, RetryDeliveryResult)
    task = approved.delivery.task
    assert task.status is TaskStatus.DONE
    assert task.attempts == 2 and task.work_attempt == 2
    assert task.interruption_continuation_policy is not None
    assert task.transient_failures(AgentRole.CODER) == 0
    assert not task.retry_failures
    assert [call.request.role for call in calls] == [
        AgentRole.CODER,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    first, continued, qa, review = calls
    assert first.request.run_id != continued.request.run_id
    assert first.request.context_manifest_id != continued.request.context_manifest_id
    assert first.claim.lease.id != continued.claim.lease.id
    assert first.claim.work_item.id != continued.claim.work_item.id
    assert continued.claim.work_item.parent_work_item_id == first.claim.work_item.id
    assert first.request.permissions == continued.request.permissions
    assert first.workspace == continued.workspace
    assert first.branch == continued.branch == task.branch_name
    assert first.input_head == continued.input_head == source
    assert len({call.claim.lease.id for call in calls}) == 4
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
    assert results[0].error is not None and results[0].error.code is AgentErrorCode.WORK_INTERRUPTED
    assert all(result.status is AgentRunStatus.SUCCEEDED for result in results[1:])
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
    candidate = approved.checkpoint.candidate_revision
    assert candidate and candidate != source
    assert implementation.source_revision == implementation.content.commit_sha == candidate
    assert qa.input_head == review.input_head == candidate
    assert qa.request.source_revision == review.request.source_revision == candidate
    assert _git_output("rev-parse", "HEAD", cwd=repository) == source
    assert (repository / "hello.txt").read_text() == "hello\n"
    assert _git_output("show", f"{candidate}:hello.txt", cwd=repository) == "hello from the team"
    route_store = FileModelRouteAttemptStore(model_route_root(sidecar), read_only=True)
    for call in calls:
        attempts = route_store.list_for_run(call.request.run_id)
        assert len(attempts) == 1 and attempts[0].route_index == 1
        assert attempts[0].model == "gpt-primary"
    assert all(
        item.status is WorkItemStatus.CLOSED for item in host.work_queue.items_for_task(task.id)
    )
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    assert not (repository / ".ase").exists()
