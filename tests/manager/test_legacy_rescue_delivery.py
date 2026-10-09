"""Legacy rescue preserves an unknown run and completes through public native gates."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentFailure,
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
from ai_software_engineer.agents.continuation import ContinuationExecutionUncertain
from ai_software_engineer.agents.fallback import (
    FileModelRouteAttemptStore,
    ModelRouteAttempt,
    model_route_root,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.context.execution_baseline import ExecutionBaselineContext
from ai_software_engineer.context.native import validate_native_rule_epoch_context
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentRole,
    ArtifactKind,
    CoderProgressArtifact,
    Evidence,
    EvidenceType,
    ImplementationReportArtifact,
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
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselineInputMode,
    BaselinePurpose,
)
from ai_software_engineer.domain.execution_native_rules import NativeRuleEpoch
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.evaluation import FileEvaluationEventStore, HumanAction, HumanActionEvent
from ai_software_engineer.execution import SubprocessCommandExecutor
from ai_software_engineer.git import WorkspacePolicy, WorkspacePolicyError
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager import production_backend, production_delivery
from ai_software_engineer.manager.baseline_production import (
    BaselineContinueCommand,
    BaselineExecuteCommand,
    BaselineProposeCommand,
    ProductionBaselineFactCollector,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.legacy_containment import (
    LocalBootObservation,
    TrustedLocalBootObserver,
)
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionSurvey,
    LegacyRescuePrerequisiteError,
    TrustedLegacyLocalExecutionObserver,
)
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.runtime import _default_case_id
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.team_view.engineering_history import engineering_history
from ai_software_engineer.web_console import (
    ConsoleOperationStatus,
    FileConsoleOperationStore,
    ManagerConsoleAdapter,
    ProjectConsole,
)
from ai_software_engineer.web_console.models import (
    ExecuteExecutionBaselineIntent,
    ProposeExecutionBaselineIntent,
)
from ai_software_engineer.work_queue.baseline import consumptions
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_legacy_local_execution import DesktopFixtureObserver
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedStructuredClient,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_production_continuation import Invocation, _coder_draft
from tests.manager.test_production_continuation_v2 import DESIRED, _progress, _ReportTemplate


@pytest.mark.mysql
@pytest.mark.parametrize(
    ("sealed_final", "crash_before_consumption", "local_stop", "first_checkpoint"),
    [
        (False, False, False, False),
        (False, True, False, False),
        (True, False, False, False),
        (False, False, True, False),
        (False, True, True, False),
        (False, False, True, True),
    ],
)
def test_public_host_rescues_original_unknown_coder_without_rewriting_history(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    sealed_final: bool,
    crash_before_consumption: bool,
    local_stop: bool,
    first_checkpoint: bool,
) -> None:
    pause_rescue = local_stop and not crash_before_consumption and not sealed_final
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    source = _git_output("rev-parse", "HEAD", cwd=repository)
    execution_base = source
    calls: list[Invocation] = []
    results: list[AgentResult] = []
    expected_binding: str | None = None
    expected_epoch: NativeRuleEpoch | None = None
    first_progress_id: str | None = None
    original_complete = _ScriptedStructuredClient.complete

    def source_inspection(
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
        if output_schema.get("title") != "TechnicalDesignDraft":
            return result
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
                    "checklist": ["Compare the committed greeting to the approved value."],
                },
            }
            for mapping in mappings
        ]
        return StructuredModelResult(payload=payload, duration_ms=result.duration_ms)

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", source_inspection)
    monkeypatch.setattr(
        production_backend, "ConfiguredStructuredClientFactory", lambda *_: _ScriptedClientFactory()
    )

    def record_call(adapter: CodexCliAgentAdapter, request: AgentRequest, cwd: Path) -> Invocation:
        guard = cast(WorkerExecutionGuard, adapter._execution_guard)
        guard.check()
        assert guard.lease is not None
        call = Invocation(
            request,
            guard.lease.claim,
            cwd,
            _git_output("branch", "--show-current", cwd=cwd),
            _git_output("rev-parse", "HEAD", cwd=cwd),
            adapter._model,
        )
        assert call.claim.work_item.attempt == request.attempt
        assert call.claim.work_item.role is request.role
        assert call.input_head == request.source_revision
        calls.append(call)
        return call

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
            nonlocal first_progress_id
            adapter, request = self.adapter, self.request
            record_call(adapter, request, cwd)
            guard = cast(WorkerExecutionGuard, adapter._execution_guard)
            if request.role is AgentRole.CODER and request.attempt == 1:
                if first_checkpoint:
                    (cwd / "hello.txt").write_text("first retained draft\n")
                    progress = _progress(adapter, request)
                    first_progress_id = progress.artifact_id
                    Path(argv[argv.index("--output-last-message") + 1]).write_text(
                        progress.model_dump_json()
                    )
                    return CodexInvocationResult(returncode=0)
                outcome = SubprocessCodexCommandRunner(guard).run(
                    (
                        sys.executable,
                        "-c",
                        "from pathlib import Path; import sys,time; sys.stdin.read(); "
                        "Path('hello.txt').write_text('first retained draft\\n'); time.sleep(30)",
                    ),
                    cwd=cwd,
                    environment=environment,
                    stdin=stdin,
                    timeout_seconds=min(timeout_seconds, 0.5),
                )
                assert outcome.timed_out and outcome.process_stop is not None
                return outcome
            assert request.execution_baseline_sha256 == expected_binding
            assert request.execution_base_ref == execution_base
            context = FileContextStore(sidecar / "contexts").get(request.context_manifest_id)
            (section,) = tuple(s for s in context.sections if s.name == "execution.baseline")
            trusted = ExecutionBaselineContext.model_validate_json(section.content)
            assert not section.truncated
            assert trusted.binding.binding_sha256 == expected_binding
            assert hashlib.sha256(trusted.complete_patch.encode()).hexdigest() == (
                trusted.binding.retained_patch.sha256
            )
            assert "+unknown retained draft" in trusted.complete_patch
            if expected_epoch is not None:
                assert trusted.binding.native_rule_epoch_sha256 == expected_epoch.epoch_sha256
                validate_native_rule_epoch_context(context, expected_epoch)
                assert (cwd / "tooling.txt").read_text() == "fixed platform prerequisite\n"
                assert (cwd / "README.md").read_text() == "Approved upgraded greeting rules.\n"
            policy = WorkspacePolicy(cwd, request.permissions)
            if request.role is AgentRole.CODER:
                assert request.attempt == 3
                assert request.continuation_checkpoint_id is None
                assert first_progress_id not in request.input_artifact_ids
                if first_checkpoint:
                    assert (request.expected_supersedes_by_kind or {}).get(
                        ArtifactKind.CODER_PROGRESS
                    ) == first_progress_id
                assert (cwd / "hello.txt").read_text() == "unknown retained draft\n"
                policy.authorize_write("hello.txt")
                with pytest.raises(WorkspacePolicyError):
                    policy.authorize_write(".trellis/spec/core/forbidden.md")
                (cwd / "hello.txt").write_text(DESIRED)
                artifact = _coder_draft(adapter, request)
            else:
                assert request.role in (AgentRole.QA, AgentRole.REVIEWER)
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
                independent = _ReportTemplate(definition, cwd, DESIRED).run(request)
                assert independent.artifact is not None
                artifact = independent.artifact
                command = ("git", "show", f"{request.source_revision}:hello.txt")
                checked = SubprocessCommandExecutor(
                    cwd, request.permissions, environment=environment, execution_guard=guard
                ).run(command, timeout_seconds=5)
                assert checked.returncode == 0 and checked.stdout == DESIRED
                evidence_path = tmp_path / f"verification-{request.run_id}.json"
                evidence_path.write_text(checked.model_dump_json())
                evidence = Evidence(
                    evidence_id=f"ev_{request.run_id.removeprefix('run_')}",
                    type=EvidenceType.TEST
                    if request.role is AgentRole.QA
                    else EvidenceType.COMMAND,
                    uri=evidence_path.as_uri(),
                    description="Independent inspection of the exact rescued candidate.",
                    sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                )
                if isinstance(artifact, QaReportArtifact):
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
                                            command=" ".join(command),
                                            status=QaTestStatus.PASS,
                                            evidence_id=evidence.evidence_id,
                                            duration_ms=checked.duration_ms,
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
            nonlocal first_progress_id
            if request.role is AgentRole.CODER and request.attempt == 2:
                # Simulate a pre-ledger local runner: it did work under a real claim,
                # but never sealed final/stop/capture records. The test process owns
                # the child and waits for it; this is not a fabricated stop artifact.
                cwd = self._workspace_root
                record_call(self, request, cwd)
                if first_checkpoint:
                    assert request.continuation_checkpoint_id == first_progress_id
                    assert (cwd / "hello.txt").read_text() == "first retained draft\n"
                with subprocess.Popen(
                    (
                        sys.executable,
                        "-c",
                        "from pathlib import Path; "
                        "Path('hello.txt').write_text('unknown retained draft\\n')",
                    ),
                    cwd=cwd,
                    env={"PATH": os.environ.get("PATH", os.defpath)},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ) as process:
                    assert process.wait(timeout=5) == 0
                raise ContinuationExecutionUncertain("fixture: old local invocation has no result")
            self._runner = Runner(self, request)
            result = super().run(request)
            if isinstance(result.artifact, CoderProgressArtifact):
                first_progress_id = result.artifact.artifact_id
            results.append(result)
            return result

    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", ObservedCodex)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test Project",
        live_model_execution=True,
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-primary", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
        execution_retry_policy=ExecutionRetryPolicy(coder=StageRetryPolicy(max_attempts=4)),
    )
    environment = {
        "ASE_MYSQL_DSN": mysql_dsn,
        "PATH": os.environ.get("PATH", os.defpath),
        "GIT_AUTHOR_NAME": "ASE Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "ASE Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
    )
    service = host.project_entry()
    product = service.start(
        StartProjectDelivery(
            repository_root=str(repository),
            requirement="Update the greeting.",
            title="Legacy rescue",
        )
    ).checkpoint
    pending = service.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-original-product-approval",
        )
    ).checkpoint
    assert pending.task_id is not None and pending.repository_id is not None
    assert len(calls) == 2, pending.failure_summary
    first, unknown = calls
    assert first.workspace == unknown.workspace and first.branch == unknown.branch
    sidecar = host.projects()[0].root / "repositories" / pending.repository_id
    records = KnowledgeRecordStore(sidecar / "state/invocations", read_only=True)
    original_start = records.get(
        "invocation-starts", unknown.claim.work_item.id, DeliveryInvocationStart
    )
    assert original_start.request == unknown.request
    assert (
        records.find("invocation-outcomes", unknown.claim.work_item.id, DeliveryInvocationOutcome)
        is None
    )
    routes = FileModelRouteAttemptStore(model_route_root(sidecar))
    assert not routes.list_for_run(unknown.request.run_id)
    continuations = FileContinuationStore(
        sidecar / "state/continuations" / pending.task_id, task_id=pending.task_id
    )
    first_receipts = continuations.receipts_for_task(pending.task_id)
    if first_checkpoint:
        assert not first_receipts
        assert first_progress_id is not None
    else:
        (first_receipt,) = first_receipts
        assert first_receipt.request == first.request
    original_artifacts = {
        path: path.read_bytes() for path in (sidecar / "artifacts").rglob("*.json")
    }
    capture_root = sidecar / "state/continuations" / pending.task_id
    assert not (capture_root / f"capture-start-{unknown.request.run_id}.json").exists()
    assert not (capture_root / f"capture-stop-{unknown.request.run_id}.json").exists()
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        frozen = tasks.get(pending.task_id)
        revision = tasks.current_revision(pending.task_id)
    (waiting,) = tuple(
        i
        for i in host.work_queue.items_for_task(frozen.id)
        if i.status is not WorkItemStatus.CLOSED
    )
    assert waiting.id == unknown.claim.work_item.id
    assert waiting.status in (
        WorkItemStatus.WAITING_DEPENDENCY,
        WorkItemStatus.WAITING_HUMAN,
    ), pending.failure_summary
    assert frozen.attempts == frozen.work_attempt == 2 and not frozen.retry_failures
    original_bytes = {path: path.read_bytes() for path in (sidecar / "policy").rglob("*.json")}
    workspace_bytes = {
        path.relative_to(unknown.workspace): path.read_bytes()
        for path in unknown.workspace.rglob("*")
        if path.is_file()
    }
    index_path = Path(_git_output("rev-parse", "--git-path", "index", cwd=unknown.workspace))
    if not index_path.is_absolute():
        index_path = unknown.workspace / index_path
    original_index = index_path.read_bytes()
    command = BaselineProposeCommand(
        purpose=BaselinePurpose.LEGACY_WORKSPACE_RESCUE,
        delivery_id=pending.delivery_id,
        task_id=frozen.id,
        expected_task_intent_sha256=task_intent_sha256(frozen),
        expected_task_revision=revision,
        expected_work_item_id=waiting.id,
        expected_source_revision=source,
        target_base_ref=source,
    )
    boot = LocalBootObservation(
        machine_sha256="a" * 64,
        boot_session_sha256="b" * 64,
        booted_at=original_start.started_at + timedelta(microseconds=1),
    )
    monkeypatch.setattr(
        TrustedLocalBootObserver,
        "observe",
        lambda _: boot.model_copy(update={"booted_at": original_start.started_at}),
    )

    native_survey = TrustedLegacyLocalExecutionObserver.observe

    def incomplete_survey(
        _self: TrustedLegacyLocalExecutionObserver,
        *,
        worktree_root: Path,
        boot: LocalBootObservation,
    ) -> LegacyLocalExecutionSurvey:
        raise LegacyRescuePrerequisiteError(
            code="LEGACY_LOCAL_SURVEY_INCOMPLETE",
            safe_message="平台尚未完成本机执行核验。",
            next_action="请修复本机读取能力后重新准备方案。",
        )

    monkeypatch.setattr(TrustedLegacyLocalExecutionObserver, "observe", incomplete_survey)
    with pytest.raises(LegacyRescuePrerequisiteError, match="本机执行核验"):
        host.propose_execution_baseline(command, project_id="project_test")
    if local_stop:
        boot = boot.model_copy(update={"booted_at": original_start.started_at - timedelta(days=1)})

    def desktop_survey(
        *,
        worktree_root: Path,
        boot: LocalBootObservation,
        retained_reference: bool = False,
    ) -> LegacyLocalExecutionSurvey:
        # Keep the real desktop CUA ancestry and independently supplied native
        # paths through the public Host, alongside the existing control facts.
        uid = os.getuid()
        observer = DesktopFixtureObserver()
        observer.native_paths.update(
            {
                106: observer.native_paths[101],
                107: observer.native_paths[103],
                108: observer.native_paths[103],
                201: "/usr/local/bin/codex",
                202: "/usr/bin/python",
                203: "/bin/zsh",
            }
        )
        observer.process_rows.update(
            {
                106: (
                    102,
                    observer.process_rows[101][1].replace("kernel.js", "trusted-worker.js"),
                ),
                107: (106, f"{observer.native_paths[107]} /tmp/trusted-worker.js"),
                108: (101, f"{observer.native_paths[108]} /tmp/kernel.js"),
                201: (1, "/usr/local/bin/codex resume maintenance"),
                202: (1, "/usr/bin/python /platform/ase-console"),
                203: (1, "/bin/zsh"),
            }
        )
        rows = "\n".join(
            f"{pid} {ppid} {uid} S Thu Oct 8 08:00:00 2026 {command}"
            for pid, (ppid, command) in observer.process_rows.items()
        )
        observer.commands = [rows, rows]
        observer.open_files = b"".join(
            f"p{pid}\0\nfcwd\0tDIR\0n/maintenance-checkout\0\n".encode()
            for pid in observer.process_rows
            if pid not in {202, 203}
        ) + (
            b"p202\0\nfcwd\0tDIR\0n/platform\0\n"
            + f"p203\0\nfcwd\0tDIR\0n{worktree_root}\0\n".encode()
        )
        if retained_reference:
            # Positive control ownership must never exempt a sandbox or its
            # tool from the retained checkout's cwd/open-file checks.
            observer.open_files += (
                f"p106\0\nf5\0tREG\0n{worktree_root}/hello.txt\0\n"
                f"p107\0\nfcwd\0tDIR\0n{worktree_root}\0\n"
            ).encode()
        with monkeypatch.context() as scoped:
            scoped.setattr(
                "ai_software_engineer.manager.legacy_local_execution.sys.platform", "darwin"
            )
            result = native_survey(observer, worktree_root=worktree_root, boot=boot)
        assert result.blockers == (("WORKTREE_PROCESS_ACTIVE",) if retained_reference else ())
        return result

    def idle_survey(
        _self: TrustedLegacyLocalExecutionObserver,
        *,
        worktree_root: Path,
        boot: LocalBootObservation,
    ) -> LegacyLocalExecutionSurvey:
        if local_stop:
            # Exercise the real attribution/path scanner through the public
            # Host collector; only the bounded OS reads use fixture facts.
            result = desktop_survey(worktree_root=worktree_root, boot=boot)
            result.require_idle()
            return result
        return LegacyLocalExecutionSurvey.create(
            worktree_path=str(worktree_root.resolve()),
            machine_sha256=boot.machine_sha256,
            boot_session_sha256=boot.boot_session_sha256,
            account_sha256="c" * 64,
            observed_at=datetime.now(UTC),
            scanner_version="local-execution-v1",
            blockers=(),
        )

    monkeypatch.setattr(TrustedLegacyLocalExecutionObserver, "observe", idle_survey)
    monkeypatch.setattr(TrustedLocalBootObserver, "observe", lambda _: boot)
    if sealed_final:
        # A genuine sealed final is already a recoverable original result. It
        # must go through ordinary outcome replay, never legacy abandonment.
        result = AgentResult(
            run_id=unknown.request.run_id,
            task_id=unknown.request.task_id,
            role=unknown.request.role,
            attempt=unknown.request.attempt,
            source_revision=unknown.request.source_revision,
            context_manifest_id=unknown.request.context_manifest_id,
            status=AgentRunStatus.TIMED_OUT,
            error=AgentFailure(
                code=AgentErrorCode.TIMEOUT, message="isolated known final", transient=True
            ),
        )
        routes.append(
            ModelRouteAttempt.create(
                request=unknown.request,
                route_index=1,
                provider="codex",
                model=unknown.model,
                route_kind="codex_cli",
                started_at=original_start.started_at,
                completed_at=datetime.now(UTC),
                result=result,
                fallback=False,
            )
        )
        with pytest.raises(ValueError, match="封存最终结果"):
            host.propose_execution_baseline(command, project_id="project_test")
        assert len(calls) == 2
        assert records.find("invocation-outcomes", waiting.id, DeliveryInvocationOutcome) is None
        assert continuations.receipts_for_task(frozen.id) == first_receipts
        assert {
            path.relative_to(unknown.workspace): path.read_bytes()
            for path in unknown.workspace.rglob("*")
            if path.is_file()
        } == workspace_bytes
        return
    console = ProjectConsole(
        store=FileConsoleOperationStore(tmp_path / "operations", team_id="team_test"),
        executor=ManagerConsoleAdapter(host),
    )
    current_checkpoint = service.status(pending.delivery_id).checkpoint
    console.submit(
        ProposeExecutionBaselineIntent.model_validate(
            {
                **command.to_wire(),
                "project_id": "project_test",
                "expected_checkpoint_sha256": current_checkpoint.checkpoint_sha256,
            }
        ),
        idempotency_key="legacy-rescue-public-proposal",
    )
    proposed = console.run_once()
    assert proposed is not None and proposed.status is ConsoleOperationStatus.SUCCEEDED, proposed
    assert proposed.result is not None and proposed.result.execution_baseline_plan is not None
    plan = proposed.result.execution_baseline_plan
    import json

    def validate_schema(value: object, name: str) -> None:
        schema = json.loads((Path(__file__).parents[2] / "schemas" / name).read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)

    validate_schema(proposed.to_wire(), "console-operation.schema.json")
    validate_schema(plan.to_wire(), "execution-baseline-plan.schema.json")
    assert plan.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE
    assert plan.input_mode is BaselineInputMode.PRESERVE_DRAFT and not plan.conflicted
    assert plan.facts.legacy_containment is not None
    assert plan.facts.legacy_containment.original_start == original_start
    assert plan.facts.legacy_containment.method == (
        "operator_confirmed_local_stop" if local_stop else "os_reboot"
    )
    assert plan.complete_capture.patch.endswith("+unknown retained draft\n")
    assert {
        path.relative_to(unknown.workspace): path.read_bytes()
        for path in unknown.workspace.rglob("*")
        if path.is_file()
    } == workspace_bytes
    assert index_path.read_bytes() == original_index
    execute = BaselineExecuteCommand(
        delivery_id=pending.delivery_id,
        task_id=frozen.id,
        expected_plan_sha256=plan.plan_sha256,
        reference="legacy-engineering-confirmation",
        confirm_legacy_containment=None if local_stop else True,
        confirm_local_execution_stopped=True if local_stop else None,
        continuation_mode=(
            BaselineContinuationMode.PAUSE if pause_rescue else BaselineContinuationMode.RESUME
        ),
    )
    with pytest.raises(ValueError, match="明确确认"):
        host.execute_execution_baseline(
            execute.model_copy(
                update={
                    "confirm_legacy_containment": None,
                    "confirm_local_execution_stopped": None,
                }
            ),
            project_id="project_test",
        )
    assert len(calls) == 2
    if local_stop:
        with pytest.raises(ValueError, match="明确确认"):
            host.execute_execution_baseline(
                execute.model_copy(
                    update={
                        "confirm_legacy_containment": True,
                        "confirm_local_execution_stopped": None,
                    }
                ),
                project_id="project_test",
            )

        def active_survey(
            _self: TrustedLegacyLocalExecutionObserver,
            *,
            worktree_root: Path,
            boot: LocalBootObservation,
        ) -> LegacyLocalExecutionSurvey:
            return desktop_survey(worktree_root=worktree_root, boot=boot, retained_reference=True)

        monkeypatch.setattr(TrustedLegacyLocalExecutionObserver, "observe", active_survey)
        with pytest.raises(LegacyRescuePrerequisiteError, match="工作区"):
            host.execute_execution_baseline(execute, project_id="project_test")
        assert len(calls) == 2
        assert not consumptions(host.work_queue, frozen.id)
        assert {
            path.relative_to(unknown.workspace): path.read_bytes()
            for path in unknown.workspace.rglob("*")
            if path.is_file()
        } == workspace_bytes
        monkeypatch.setattr(TrustedLegacyLocalExecutionObserver, "observe", idle_survey)
    expected_binding = None
    # Pause dispatch while publication verifies exact no-mutation preservation.
    from ai_software_engineer.work_queue.dispatcher import (
        DispatcherLoop,
        DispatcherTickResult,
        DispatcherTickStatus,
    )

    original_tick = DispatcherLoop.tick
    monkeypatch.setattr(
        DispatcherLoop,
        "tick",
        lambda _self, *, now, work_item_id=None: DispatcherTickResult(
            status=DispatcherTickStatus.IDLE, ticked_at=now
        ),
    )
    if crash_before_consumption:
        original_publish = ProductionBaselineFactCollector.publish_completion

        def fail_publication(*_args: object) -> None:
            raise ValueError("isolated crash after immutable binding before SQL commit")

        monkeypatch.setattr(ProductionBaselineFactCollector, "publish_completion", fail_publication)
        with pytest.raises(ValueError, match="isolated crash"):
            host.execute_execution_baseline(execute, project_id="project_test")
        assert not consumptions(host.work_queue, frozen.id)
        with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
            assert tasks.get(frozen.id).attempts == 2
        monkeypatch.setattr(ProductionBaselineFactCollector, "publish_completion", original_publish)
        new_boot = boot.model_copy(
            update={
                "boot_session_sha256": "c" * 64,
                "booted_at": boot.booted_at + timedelta(seconds=1),
            }
        )
        monkeypatch.setattr(TrustedLocalBootObserver, "observe", lambda _: new_boot)
        if local_stop:
            monkeypatch.setattr(TrustedLegacyLocalExecutionObserver, "observe", active_survey)
            with pytest.raises(LegacyRescuePrerequisiteError, match="工作区"):
                host.propose_execution_baseline(command, project_id="project_test")
            assert not consumptions(host.work_queue, frozen.id)
            assert len(calls) == 2
            assert {
                path.relative_to(unknown.workspace): path.read_bytes()
                for path in unknown.workspace.rglob("*")
                if path.is_file()
            } == workspace_bytes
            monkeypatch.setattr(TrustedLegacyLocalExecutionObserver, "observe", idle_survey)
        assert host.propose_execution_baseline(command, project_id="project_test") == plan
    console.submit(
        ExecuteExecutionBaselineIntent.model_validate(
            {
                **execute.to_wire(),
                "project_id": "project_test",
                "expected_checkpoint_sha256": service.status(
                    pending.delivery_id
                ).checkpoint.checkpoint_sha256,
            }
        ),
        idempotency_key="legacy-rescue-public-execution",
    )
    executed = console.run_once()
    assert executed is not None and executed.status is ConsoleOperationStatus.SUCCEEDED, executed
    assert executed.result is not None and executed.result.execution_baseline_binding is not None
    binding = executed.result.execution_baseline_binding
    validate_schema(executed.to_wire(), "console-operation.schema.json")
    validate_schema(binding.to_wire(), "execution-baseline.schema.json")
    expected_binding = binding.binding_sha256
    assert binding.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE
    assert binding.execution_base_ref == binding.approved_base_ref == source
    assert binding.execution_source_revision == source
    assert binding.superseded_progress_artifact_id == first_progress_id
    assert {
        path.relative_to(unknown.workspace): path.read_bytes()
        for path in unknown.workspace.rglob("*")
        if path.is_file()
    } == workspace_bytes
    assert _git_output("rev-parse", "HEAD", cwd=unknown.workspace) == source
    assert index_path.read_bytes() == original_index
    assert _git_output("branch", "--show-current", cwd=unknown.workspace) == unknown.branch
    assert records.get("invocation-starts", waiting.id, DeliveryInvocationStart) == original_start
    assert records.find("invocation-outcomes", waiting.id, DeliveryInvocationOutcome) is None
    assert continuations.receipts_for_task(frozen.id) == first_receipts
    assert not routes.list_for_run(unknown.request.run_id)
    # Full subsequent collection must still accept the independently disposed
    # old UNKNOWN while inspecting the new uninvoked successor.
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        resumed_collector = (
            host._runtime("project_test")
            .backend.execution_baseline_service(
                service.status(pending.delivery_id).checkpoint,
                repository=tasks,
                project_id="project_test",
            )
            .facts
        )
        with resumed_collector.execution_scope():
            current_facts = resumed_collector.collect(source)
            assert current_facts.continuation is not None
            assert current_facts.continuation.retry_cause == "uninvoked"
            assert current_facts.legacy_containment is None
    # Later boot changes cannot invalidate or duplicate a completed authorization.
    monkeypatch.setattr(
        TrustedLocalBootObserver,
        "observe",
        lambda _: boot.model_copy(
            update={
                "boot_session_sha256": "c" * 64,
                "booted_at": boot.booted_at + timedelta(seconds=1),
            }
        ),
    )
    monkeypatch.setattr(DispatcherLoop, "tick", original_tick)
    assert host.execute_execution_baseline(execute, project_id="project_test") == binding
    latest_binding = binding
    continue_command = None
    if pause_rescue:
        assert len(calls) == 2
        (preserved,) = tuple(
            item
            for item in host.work_queue.items_for_task(frozen.id)
            if item.status is not WorkItemStatus.CLOSED
        )
        assert preserved.status is WorkItemStatus.WAITING_HUMAN
        assert preserved.wait_disposition is not None
        assert preserved.wait_disposition.facts.classification == "EXECUTION_BASELINE_PAUSED"
        with MySqlTaskRepository(mysql_dsn) as tasks:
            assert tasks.get(frozen.id).attempts == preserved.attempt == 3
        old_continue = BaselineContinueCommand(
            delivery_id=pending.delivery_id,
            task_id=frozen.id,
            expected_task_intent_sha256=task_intent_sha256(frozen),
            expected_task_revision=revision,
            expected_work_item_id=preserved.id,
            expected_source_revision=binding.execution_source_revision,
            expected_execution_baseline_sha256=binding.binding_sha256,
            expected_disposition_sha256=preserved.wait_disposition.disposition_sha256,
            reference="superseded original rescue continuation",
        )
        (repository / "tooling.txt").write_text("fixed platform prerequisite\n")
        (repository / "README.md").write_text("Approved upgraded greeting rules.\n")
        _git("add", "tooling.txt", "README.md", cwd=repository)
        _git(
            "commit", "-m", "upgrade retained original requirement source and rules", cwd=repository
        )
        execution_base = _git_output("rev-parse", "HEAD", cwd=repository)
        upgrade_plan = host.propose_execution_baseline(
            BaselineProposeCommand(
                delivery_id=pending.delivery_id,
                task_id=frozen.id,
                expected_task_intent_sha256=task_intent_sha256(frozen),
                expected_task_revision=revision,
                expected_work_item_id=preserved.id,
                expected_source_revision=binding.execution_source_revision,
                target_base_ref=execution_base,
            ),
            project_id="project_test",
        )
        assert upgrade_plan.purpose is BaselinePurpose.SOURCE_REBIND
        assert upgrade_plan.previous_binding == binding
        assert upgrade_plan.facts.native_rule_change is not None
        assert upgrade_plan.facts.continuation is not None
        assert upgrade_plan.facts.continuation.retry_cause == "uninvoked"
        upgrade_execute = BaselineExecuteCommand(
            delivery_id=pending.delivery_id,
            task_id=frozen.id,
            expected_plan_sha256=upgrade_plan.plan_sha256,
            reference="exact latest main and native rules decision",
            continuation_mode=BaselineContinuationMode.PAUSE,
            approved_native_rule_change_sha256=(
                upgrade_plan.facts.native_rule_change.change_sha256
            ),
        )
        latest_binding = host.execute_execution_baseline(upgrade_execute, project_id="project_test")
        assert latest_binding.previous_binding_sha256 == binding.binding_sha256
        assert latest_binding.superseded_progress_artifact_id is None
        assert latest_binding.native_rule_epoch_sha256 is not None
        expected_binding = latest_binding.binding_sha256
        expected_epoch = FileExecutionBaselineStore(
            sidecar / "state/execution-baselines" / frozen.id, read_only=True
        ).native_rule_epoch(latest_binding.native_rule_epoch_sha256)
        preserved_after = host.work_queue.get(preserved.id)
        assert preserved_after.id == preserved.id and preserved_after.attempt == 3
        assert preserved_after.status is WorkItemStatus.WAITING_HUMAN
        assert preserved_after.wait_disposition is not None
        assert (
            preserved_after.wait_disposition.facts.execution_baseline_sha256
            == latest_binding.binding_sha256
        )
        assert len(calls) == 2
        with MySqlTaskRepository(mysql_dsn) as tasks:
            assert tasks.get(frozen.id).attempts == 3
            assert tasks.get(frozen.id).work_attempt == 3
        assert (unknown.workspace / "hello.txt").read_text() == "unknown retained draft\n"
        with pytest.raises(ValueError, match="已变化"):
            host.continue_execution_baseline(old_continue, project_id="project_test")
        assert host.work_queue.get(preserved.id) == preserved_after and len(calls) == 2
        continue_command = BaselineContinueCommand(
            delivery_id=pending.delivery_id,
            task_id=frozen.id,
            expected_task_intent_sha256=task_intent_sha256(frozen),
            expected_task_revision=revision,
            expected_work_item_id=preserved.id,
            expected_source_revision=latest_binding.execution_source_revision,
            expected_execution_baseline_sha256=latest_binding.binding_sha256,
            expected_disposition_sha256=preserved_after.wait_disposition.disposition_sha256,
            reference="explicit upgraded original READY plan continuation",
        )
        host.continue_execution_baseline(continue_command, project_id="project_test")
    delivered = service.status(pending.delivery_id).checkpoint
    assert delivered.stage is DeliveryStage.DONE, delivered.failure_summary
    assert [call.request.role for call in calls] == [
        AgentRole.CODER,
        AgentRole.CODER,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    rescued, qa_call, reviewer_call = calls[2:]
    assert rescued.workspace == unknown.workspace and rescued.branch == unknown.branch
    assert rescued.claim.work_item.parent_work_item_id == waiting.id
    assert rescued.request.permissions == unknown.request.permissions
    assert len({call.request.run_id for call in calls}) == len(calls)
    assert len({call.claim.lease.id for call in calls}) == len(calls)
    assert len({call.claim.assignment.agent_id for call in calls}) == 3
    candidate = delivered.candidate_revision
    assert candidate and candidate != source
    assert candidate != execution_base
    assert all(call.request.execution_base_ref == execution_base for call in calls[2:])
    assert qa_call.request.source_revision == reviewer_call.request.source_revision == candidate
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        completed = tasks.get(frozen.id)
    assert completed.status is TaskStatus.DONE
    assert completed.attempts == completed.work_attempt == 3
    assert not completed.retry_failures and completed.transient_failures(AgentRole.CODER) == 0
    assert task_intent_sha256(completed) == task_intent_sha256(frozen)
    artifacts = FileArtifactStore(sidecar / "artifacts", read_only=True).list_for_task(frozen.id)
    implementation = next(a for a in artifacts if isinstance(a, ImplementationReportArtifact))
    qa = next(a for a in artifacts if isinstance(a, QaReportArtifact))
    review = next(a for a in artifacts if isinstance(a, ReviewReportArtifact))
    if first_checkpoint:
        original_progress = next(a for a in artifacts if isinstance(a, CoderProgressArtifact))
        assert original_progress.artifact_id == first_progress_id
        assert original_progress.source_revision == source
        assert original_progress.artifact_id not in implementation.parent_artifact_ids
    assert all(path.read_bytes() == body for path, body in original_artifacts.items())
    assert (
        implementation.source_revision == qa.source_revision == review.source_revision == candidate
    )
    assert (
        qa.content.status is QaReportStatus.PASS and review.content.verdict is ReviewVerdict.APPROVE
    )
    assert all(path.read_bytes() == body for path, body in original_bytes.items())
    assert pending.approval_sha256 == delivered.approval_sha256
    assert pending.preparation_sha256 == delivered.preparation_sha256
    assert records.get("invocation-starts", waiting.id, DeliveryInvocationStart) == original_start
    assert records.find("invocation-outcomes", waiting.id, DeliveryInvocationOutcome) is None
    assert continuations.receipts_for_task(frozen.id) == first_receipts
    baseline_store = FileExecutionBaselineStore(
        sidecar / "state/execution-baselines" / frozen.id, read_only=True
    )
    expected_history = (binding, latest_binding) if pause_rescue else (binding,)
    assert baseline_store.bindings_for_task(frozen.id) == expected_history
    assert len(consumptions(host.work_queue, frozen.id)) == len(expected_history)
    for consumption in consumptions(host.work_queue, frozen.id):
        validate_schema(consumption.to_wire(), "execution-baseline-queue-consumption.schema.json")
    human_evidence = tuple(
        event
        for event in FileEvaluationEventStore(
            sidecar / "evaluations", read_only=True
        ).list_for_case(_default_case_id(frozen.id))
        if isinstance(event, HumanActionEvent) and event.action is HumanAction.SUPPLY_EVIDENCE
    )
    assert len(human_evidence) == 1
    assert human_evidence[0].note is not None
    if local_stop:
        assert (
            human_evidence[0].evidence_uri
            == (
                baseline_store.root
                / baseline_store.records._name("baseline-authorities", plan.plan_sha256)
            )
            .absolute()
            .as_uri()
        )
        assert "全部派生工具" in human_evidence[0].note
        assert "已整机重启" not in human_evidence[0].note
    else:
        assert human_evidence[0].evidence_uri == baseline_store.patch_uri(plan.plan_sha256)
    timeline = engineering_history(sidecar, completed, plan.facts.scope, pending.delivery_id)
    if pause_rescue:
        assert any("原需求保持暂停" in entry.summary for entry in timeline)
        assert any("明确继续原需求" in entry.summary for entry in timeline)
    else:
        assert any("原未知执行" in entry.summary for entry in timeline)
        assert any("下一轮使用原任务剩余工作额度" in entry.summary for entry in timeline)
    # Later baseline collection still verifies complete historical containment.
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        collector = (
            host._runtime("project_test")
            .backend.execution_baseline_service(
                service.status(pending.delivery_id).checkpoint,
                repository=tasks,
                project_id="project_test",
            )
            .facts
        )
        assert isinstance(collector, ProductionBaselineFactCollector)
        proofs = collector._invocations(
            completed,
            host.work_queue.items_for_task(completed.id),
            collector._receipts(completed),
            tuple(
                assignment
                for assignment in host.work_queue.list_assignments()
                if assignment.task_id == completed.id
            ),
        )
        proofs_by_item = {proof.work_item_id: proof for proof in proofs}
        unknown_proof = proofs_by_item[unknown.claim.work_item.id]
        assert unknown_proof.proof_kind == "legacy_execution_contained"
        assert unknown_proof.outcome_sha256 is None
        assert unknown_proof.interruption_receipt_sha256 is None
        assert unknown_proof.legacy_containment == plan.facts.legacy_containment
        assert unknown_proof.legacy_binding_sha256 == binding.binding_sha256
        for call in (rescued, qa_call, reviewer_call):
            proof = proofs_by_item[call.claim.work_item.id]
            assert proof.proof_kind == "definitive_outcome"
            assert proof.outcome_sha256 is not None
    calls_before_replay = len(calls)
    if local_stop:
        # A consumed exact engineering decision cannot become a second attempt
        # or an obsolete new wait merely because current OS queries are unavailable.
        monkeypatch.setattr(TrustedLegacyLocalExecutionObserver, "observe", incomplete_survey)
    assert host.execute_execution_baseline(execute, project_id="project_test") == binding
    if continue_command is not None:
        host.continue_execution_baseline(continue_command, project_id="project_test")
    assert len(calls) == calls_before_replay
    assert len(consumptions(host.work_queue, frozen.id)) == len(expected_history)
    assert _git_output("rev-parse", "HEAD", cwd=repository) == execution_base
    assert (
        _git_output("diff", "--name-only", execution_base, candidate, cwd=repository) == "hello.txt"
    )
    assert (repository / "hello.txt").read_text() == "hello\n"
    assert all(
        item.status is WorkItemStatus.CLOSED for item in host.work_queue.items_for_task(frozen.id)
    )
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
