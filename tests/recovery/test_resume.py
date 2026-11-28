"""One-command candidate verification and remediation on real Git/MySQL."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    CodexCliAgentAdapter,
    StoredContextResolver,
)
from ai_software_engineer.agents.continuation import CoderInterruptionControl
from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.agents.workspace_admission import (
    FirstCoderRunWorkspaceAdmission,
    InitialWorkspaceAdmission,
)
from ai_software_engineer.config import ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context.execution_baseline import ExecutionBaselineContextVerifier
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentRole,
    ImplementationReportArtifact,
    QaCriterionStatus,
    QaReportArtifact,
    QaReportStatus,
)
from ai_software_engineer.domain.artifact import Evidence, QaTestRun
from ai_software_engineer.domain.enums import EvidenceType, QaTestStatus
from ai_software_engineer.git.candidate_commit import CandidateCommitSkill
from ai_software_engineer.manager.delivery_checkpoint import (
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.native_verification import RegisteredNativePythonVerifier
from ai_software_engineer.manager.production_delivery import (
    ConfiguredDeliveryRouteAdapterFactory,
    DeliveryRouteAdapterFactory,
)
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.recovery.verification_execution import VerificationEvidenceProvider
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedDeliveryAdapter,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn


class _ResumeAdapter(AgentAdapter):
    def __init__(
        self,
        owner: _ResumeFactory,
        definition: AgentDefinition,
        workspace: Path,
    ) -> None:
        self._owner = owner
        self._delegate = _ScriptedDeliveryAdapter(definition, workspace)
        self._workspace = workspace

    def run(self, request: AgentRequest) -> AgentResult:
        self._owner.requests.append(request)
        if request.role is AgentRole.REVIEWER and request.task_id == self._owner.source_task_id:
            self._owner.reviewer_calls += 1
            if self._owner.reviewer_calls <= self._owner.reviewer_interruptions:
                return AgentResult(
                    run_id=request.run_id,
                    task_id=request.task_id,
                    role=request.role,
                    attempt=request.attempt,
                    source_revision=request.source_revision,
                    context_manifest_id=request.context_manifest_id,
                    status=AgentRunStatus.FAILED,
                    error=AgentFailure(
                        code=AgentErrorCode.RATE_LIMITED,
                        message="offline interrupted Reviewer",
                        transient=True,
                    ),
                )
        if request.role is AgentRole.CODER and self._owner.source_task_id is None:
            self._owner.source_task_id = request.task_id
        continuation = request.task_id.startswith("task_continue_")
        if request.role is AgentRole.CODER and continuation:
            self._owner.continuation_coder_calls += 1
            if (
                self._owner.continuation_coder_fails_after_feedback
                and self._owner.continuation_coder_calls > 1
            ):
                (self._workspace / "hello.txt").write_text(
                    "retained post-QA Coder work\n", encoding="utf-8"
                )
                return AgentResult(
                    run_id=request.run_id,
                    task_id=request.task_id,
                    role=request.role,
                    attempt=request.attempt,
                    source_revision=request.source_revision,
                    context_manifest_id=request.context_manifest_id,
                    status=AgentRunStatus.FAILED,
                    error=AgentFailure(
                        code=AgentErrorCode.POLICY_VIOLATION,
                        message="offline Coder interrupted after QA feedback",
                        transient=False,
                    ),
                )
        if (
            request.role is AgentRole.CODER
            and request.task_id.startswith("task_continue_")
            and self._owner.remediation_no_candidate
        ):
            (self._workspace / "hello.txt").write_text(
                "retained legacy remediation work\n", encoding="utf-8"
            )
            return AgentResult(
                run_id=request.run_id,
                task_id=request.task_id,
                role=request.role,
                attempt=request.attempt,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                status=AgentRunStatus.FAILED,
                error=AgentFailure(
                    code=AgentErrorCode.INVALID_OUTPUT,
                    message="offline Coder produced no candidate",
                    transient=False,
                ),
            )
        if request.role is AgentRole.QA and request.task_id == self._owner.source_task_id:
            self._owner.source_qa_calls += 1
            if self._owner.source_qa_calls <= self._owner.transient_qa_failures:
                return AgentResult(
                    run_id=request.run_id,
                    task_id=request.task_id,
                    role=request.role,
                    attempt=request.attempt,
                    source_revision=request.source_revision,
                    context_manifest_id=request.context_manifest_id,
                    status=AgentRunStatus.FAILED,
                    error=AgentFailure(
                        code=AgentErrorCode.RATE_LIMITED,
                        message="offline verifier quota exhausted",
                        transient=True,
                    ),
                )
            result = self._delegate.run(request)
            artifact = result.artifact
            assert isinstance(artifact, QaReportArtifact)
            if self._owner.verification_inconclusive:
                criterion = artifact.content.criteria_results[0].model_copy(
                    update={"status": QaCriterionStatus.NOT_TESTED}
                )
                return result.model_copy(
                    update={
                        "artifact": artifact.model_copy(
                            update={
                                "content": artifact.content.model_copy(
                                    update={
                                        "status": QaReportStatus.FAIL,
                                        "criteria_results": (criterion,),
                                    }
                                )
                            }
                        )
                    }
                )
            if self._owner.verification_fails:
                failed = artifact.content.criteria_results[0].model_copy(
                    update={"status": QaCriterionStatus.FAIL}
                )
                return result.model_copy(
                    update={
                        "artifact": artifact.model_copy(
                            update={
                                "content": artifact.content.model_copy(
                                    update={
                                        "status": QaReportStatus.FAIL,
                                        "criteria_results": (failed,),
                                    }
                                )
                            }
                        )
                    }
                )
        result = self._delegate.run(request)
        if request.role is AgentRole.QA and continuation and self._owner.continuation_qa_rejects:
            artifact = result.artifact
            assert isinstance(artifact, QaReportArtifact)
            failed = artifact.content.criteria_results[0].model_copy(
                update={"status": QaCriterionStatus.FAIL}
            )
            return result.model_copy(
                update={
                    "artifact": artifact.model_copy(
                        update={
                            "content": artifact.content.model_copy(
                                update={
                                    "status": QaReportStatus.FAIL,
                                    "criteria_results": (failed,),
                                }
                            )
                        }
                    )
                }
            )
        if request.role is AgentRole.CODER and request.task_id.startswith("task_continue_"):
            artifact = result.artifact
            assert isinstance(artifact, ImplementationReportArtifact)
            _git("commit", "--amend", "-m", "Remediate rejected candidate", cwd=self._workspace)
            candidate = _git_output("rev-parse", "HEAD", cwd=self._workspace)
            result = result.model_copy(
                update={
                    "artifact": artifact.model_copy(
                        update={
                            "source_revision": candidate,
                            "content": artifact.content.model_copy(
                                update={"commit_sha": candidate}
                            ),
                        }
                    )
                }
            )
        return result


class _ResumeFactory(DeliveryRouteAdapterFactory):
    def __init__(
        self,
        *,
        transient_qa_failures: int = 4,
        verification_fails: bool = True,
        verification_inconclusive: bool = False,
        remediation_no_candidate: bool = False,
        continuation_qa_rejects: bool = False,
        continuation_coder_fails_after_feedback: bool = False,
        reviewer_interruptions: int = 0,
    ) -> None:
        self.requests: list[AgentRequest] = []
        self.source_task_id: str | None = None
        self.source_qa_calls = 0
        self.transient_qa_failures = transient_qa_failures
        self.verification_fails = verification_fails
        self.verification_inconclusive = verification_inconclusive
        self.remediation_no_candidate = remediation_no_candidate
        self.continuation_qa_rejects = continuation_qa_rejects
        self.continuation_coder_fails_after_feedback = continuation_coder_fails_after_feedback
        self.continuation_coder_calls = 0
        self.reviewer_interruptions = reviewer_interruptions
        self.reviewer_calls = 0

    def create(
        self,
        *,
        route: ProviderRouteConfig,
        definition: AgentDefinition,
        binding: RoleWorktreeBinding,
        context_resolver: StoredContextResolver,
        config: ProductionConfig,
        environment: Mapping[str, str],
    ) -> AgentAdapter:
        del route, context_resolver, config, environment
        return _ResumeAdapter(self, definition, binding.worktree.path)


class _SeededInterruptedRecoveryAdapter(AgentAdapter):
    def __init__(self, seed: RecoverySeedService, workspace: Path) -> None:
        self._seed = seed
        self._workspace = workspace

    def run(self, request: AgentRequest) -> AgentResult:
        assert request.role is AgentRole.CODER
        self._seed.authorize(request, self._workspace)
        (self._workspace / "hello.txt").write_text("partially implemented\n", encoding="utf-8")
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.FAILED,
            error=AgentFailure(
                code=AgentErrorCode.POLICY_VIOLATION,
                message="offline recovery Coder interrupted",
                transient=False,
            ),
        )


class _SeededInterruptedRecoveryFactory(DeliveryRouteAdapterFactory):
    def __init__(self, seed: RecoverySeedService) -> None:
        self._seed = seed

    def create(
        self,
        *,
        route: ProviderRouteConfig,
        definition: AgentDefinition,
        binding: RoleWorktreeBinding,
        context_resolver: StoredContextResolver,
        config: ProductionConfig,
        environment: Mapping[str, str],
    ) -> AgentAdapter:
        del route, definition, context_resolver, config, environment
        return _SeededInterruptedRecoveryAdapter(self._seed, binding.worktree.path)


class _SeededNativeInterruptedRecoveryFactory(ConfiguredDeliveryRouteAdapterFactory):
    def __init__(self, seed: RecoverySeedService) -> None:
        super().__init__(initial_workspace_admission=FirstCoderRunWorkspaceAdmission(seed))


class _SeededCompleteRecoveryAdapter(AgentAdapter):
    def __init__(
        self, seed: RecoverySeedService, definition: AgentDefinition, workspace: Path
    ) -> None:
        self._seed = seed
        self._workspace = workspace
        self._delegate = _ScriptedDeliveryAdapter(definition, workspace)

    def run(self, request: AgentRequest) -> AgentResult:
        if request.role is AgentRole.CODER:
            self._seed.authorize(request, self._workspace)
        return self._delegate.run(request)


class _SeededCompleteRecoveryFactory(DeliveryRouteAdapterFactory):
    def __init__(self, seed: RecoverySeedService) -> None:
        self._seed = seed

    def create(
        self,
        *,
        route: ProviderRouteConfig,
        definition: AgentDefinition,
        binding: RoleWorktreeBinding,
        context_resolver: StoredContextResolver,
        config: ProductionConfig,
        environment: Mapping[str, str],
    ) -> AgentAdapter:
        del route, context_resolver, config, environment
        return _SeededCompleteRecoveryAdapter(self._seed, definition, binding.worktree.path)


class _OutOfScopeInterruptedAdapter(AgentAdapter):
    def __init__(
        self, owner: _OutOfScopeInterruptedFactory, delegate: CodexCliAgentAdapter
    ) -> None:
        self._owner = owner
        self._delegate = delegate

    def prepare_input(self, request: AgentRequest) -> None:
        self._delegate.prepare_input(request)

    def discard_prepared_input(self, request: AgentRequest) -> None:
        self._delegate.discard_prepared_input(request)

    def run(self, request: AgentRequest) -> AgentResult:
        assert request.role is AgentRole.CODER
        self._owner.requests.append(request)
        return self._delegate.run(request)


class _OutOfScopeInterruptedFactory(ConfiguredDeliveryRouteAdapterFactory):
    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__()
        self.requests: list[AgentRequest] = []
        executable = root / "out-of-scope-codex"
        self.executable = str(executable)
        self.knowledge_control = root / "native-knowledge-control.json"
        self.configure_knowledge_gap(None)
        executable.write_text(
            f"#!{sys.executable}\n"
            "from pathlib import Path\n"
            "import json\n"
            "import sys\n"
            "schema_path = Path(sys.argv[sys.argv.index('--output-schema') + 1])\n"
            "schema = json.loads(schema_path.read_text())\n"
            "if schema.get('title') in ('KnowledgeIntent', 'KnowledgeAssessment'):\n"
            "    prompt = sys.stdin.read()\n"
            "    payload = json.loads(prompt.rsplit('\\nINPUT=', 1)[1])\n"
            "    binding = payload['binding']\n"
            f"    control = json.loads(Path({str(self.knowledge_control)!r}).read_text())\n"
            "    gap = (control['enabled'] and binding['task_id'].startswith('task_recovery_')\n"
            "           and binding['role'] == control['role']\n"
            "           and (control['role'] != 'coder' or control['coder_progress']))\n"
            "    response = ({'queries': ['独立验收前提'] if gap else []}\n"
            "                if schema['title'] == 'KnowledgeIntent' else\n"
            "                {'status': 'GAP', 'gap_question': '请确认测试前提。'})\n"
            "    assert schema['title'] == 'KnowledgeIntent' or gap\n"
            "    output = Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
            "    output.write_text(json.dumps(response), encoding='utf-8')\n"
            "    raise SystemExit(0)\n"
            "if Path('omitted.txt').exists():\n"
            "    Path('hello.txt').write_text('partially implemented\\n', encoding='utf-8')\n"
            "else:\n"
            "    Path('omitted.txt').write_text('retained work\\n', encoding='utf-8')\n"
            "sys.stderr.write('error: authentication failure in offline fixture\\n')\n"
            "raise SystemExit(1)\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        create = ConfiguredDeliveryRouteAdapterFactory.create

        def native(
            factory: ConfiguredDeliveryRouteAdapterFactory,
            *,
            route: ProviderRouteConfig,
            definition: AgentDefinition,
            binding: RoleWorktreeBinding,
            context_resolver: StoredContextResolver,
            config: ProductionConfig,
            environment: Mapping[str, str],
        ) -> AgentAdapter:
            # Backend-installed Worker guard and interruption control remain on
            # the cloned Configured factory. Only the external model is offline;
            # the actual owned process, native stop and capture are production.
            delegate = create(
                factory,
                route=route,
                definition=definition,
                binding=binding,
                context_resolver=context_resolver,
                config=config.model_copy(update={"codex_executable": str(executable)}),
                environment=environment,
            )
            assert isinstance(delegate, CodexCliAgentAdapter)
            return _OutOfScopeInterruptedAdapter(self, delegate)

        monkeypatch.setattr(ConfiguredDeliveryRouteAdapterFactory, "create", native)

    def configure_knowledge_gap(
        self, role: str | None, *, enabled: bool = False, coder_progress: bool = False
    ) -> None:
        self.knowledge_control.write_text(
            json.dumps({"role": role, "enabled": enabled, "coder_progress": coder_progress}),
            encoding="utf-8",
        )


class _KnowledgeFixtureAdapter(AgentAdapter):
    """Keep the ordinary scripted roles, recording the QA check actually performed."""

    def __init__(self, delegate: AgentAdapter, workspace: Path) -> None:
        self.delegate, self.workspace = delegate, workspace

    def run(self, request: AgentRequest) -> AgentResult:
        result = self.delegate.run(request)
        artifact = result.artifact
        if not isinstance(artifact, QaReportArtifact):
            return result
        blob = _git_output("show", f"{request.source_revision}:hello.txt", cwd=self.workspace)
        assert blob == "hello from the team"
        evidence = Evidence(
            evidence_id="ev_fixture_greeting",
            type=EvidenceType.TEST,
            uri=f"git:{request.source_revision}:hello.txt",
            description="Offline fixture independently compared the candidate greeting.",
            sha256=hashlib.sha256(blob.encode()).hexdigest(),
        )
        content = artifact.content.model_copy(
            update={
                "tests_run": (
                    QaTestRun(
                        command=f"git show {request.source_revision}:hello.txt",
                        status=QaTestStatus.PASS,
                        evidence_id=evidence.evidence_id,
                    ),
                ),
                "criteria_results": tuple(
                    item.model_copy(update={"evidence_ids": (evidence.evidence_id,)})
                    for item in artifact.content.criteria_results
                ),
            }
        )
        return result.model_copy(
            update={
                "artifact": artifact.model_copy(
                    update={"evidence": (evidence,), "content": content}
                )
            }
        )


class _KnowledgeFixtureFactory(ConfiguredDeliveryRouteAdapterFactory):
    """Use real knowledge/queue composition with explicitly offline delivery tools."""

    def __init__(
        self,
        delegate: DeliveryRouteAdapterFactory,
        configured: ConfiguredDeliveryRouteAdapterFactory | None = None,
    ) -> None:
        if configured is None:
            super().__init__()
        else:
            super().__init__(
                initial_workspace_admission=configured._initial_admission,
                execution_guard=configured._execution_guard,
                verification_evidence=configured._verification_evidence,
                interruption_control=configured._interruption_control,
                registered_verifier=configured._registered_verifier,
                baseline_verifier=configured._baseline_verifier,
                candidate_commit_factory=configured._candidate_commit_factory,
            )
        self.delegate = delegate

    def with_execution_guard(self, guard: ExecutionGuard) -> _KnowledgeFixtureFactory:
        return _KnowledgeFixtureFactory(self.delegate, super().with_execution_guard(guard))

    def with_initial_workspace_admission(
        self, admission: InitialWorkspaceAdmission
    ) -> _KnowledgeFixtureFactory:
        return _KnowledgeFixtureFactory(
            self.delegate, super().with_initial_workspace_admission(admission)
        )

    def with_verification_evidence(
        self, provider: VerificationEvidenceProvider
    ) -> _KnowledgeFixtureFactory:
        return _KnowledgeFixtureFactory(self.delegate, super().with_verification_evidence(provider))

    def with_interruption_control(
        self, control: CoderInterruptionControl
    ) -> _KnowledgeFixtureFactory:
        return _KnowledgeFixtureFactory(self.delegate, super().with_interruption_control(control))

    def with_registered_verifier(
        self, registry: RegisteredNativePythonVerifier
    ) -> _KnowledgeFixtureFactory:
        return _KnowledgeFixtureFactory(self.delegate, super().with_registered_verifier(registry))

    def with_baseline_verifier(
        self, verifier: ExecutionBaselineContextVerifier
    ) -> _KnowledgeFixtureFactory:
        return _KnowledgeFixtureFactory(self.delegate, super().with_baseline_verifier(verifier))

    def with_candidate_commit_factory(
        self, factory: Callable[[RoleWorktreeBinding, AgentDefinition], CandidateCommitSkill]
    ) -> _KnowledgeFixtureFactory:
        return _KnowledgeFixtureFactory(
            self.delegate, super().with_candidate_commit_factory(factory)
        )

    def create(
        self,
        *,
        route: ProviderRouteConfig,
        definition: AgentDefinition,
        binding: RoleWorktreeBinding,
        context_resolver: StoredContextResolver,
        config: ProductionConfig,
        environment: Mapping[str, str],
    ) -> AgentAdapter:
        adapter = self.delegate.create(
            route=route,
            definition=definition,
            binding=binding,
            context_resolver=context_resolver,
            config=config,
            environment=environment,
        )
        return _KnowledgeFixtureAdapter(adapter, binding.worktree.path)


def _append_equivalent_delivery_checkpoint(
    config: ProductionConfig, checkpoint: ProjectDeliveryCheckpoint
) -> ProjectDeliveryCheckpoint:
    if config.default_project_id is None:
        raise AssertionError("test fixture requires a default Project")
    root = (
        Path(config.platform_root)
        / "projects"
        / config.default_project_id
        / "repositories"
        / checkpoint.repository_id
        / "state/project-deliveries"
    )
    store = FileProjectDeliveryCheckpointStore(root)
    values = checkpoint.to_wire()
    values.pop("checkpoint_sha256")
    return store.put(
        ProjectDeliveryCheckpoint.create(
            **{
                **values,
                "sequence": checkpoint.sequence + 1,
                "previous_checkpoint_sha256": checkpoint.checkpoint_sha256,
                "checkpointed_at": checkpoint.checkpointed_at + timedelta(microseconds=1),
            }
        )
    )
