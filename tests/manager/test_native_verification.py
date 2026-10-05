"""Normal role authority and durable controlled receipts through real Git/sidecar.

Only Docker/sandbox subprocess ports are faked. No production model, DSN, external
service, whole-suite invocation, terminal Task or recovery Task is used.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Never

import pytest

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    BrainTier,
    ImplementationReportArtifact,
    ModelRouteReason,
    ModelSelection,
    NetworkAccess,
    PlanArtifact,
    RiskTier,
    RoleAssignment,
    Task,
    TaskLease,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.execution_window import PlannedVerificationRequirement
from ai_software_engineer.domain.native_verification import (
    NativeRoleVerificationAdmission,
    NativeRoleVerificationPlan,
    NativeVerificationWaiting,
    NativeVerificationWaitReason,
)
from ai_software_engineer.execution import CommandResult, SubprocessCommandExecutor
from ai_software_engineer.manager.delivery_preflight import DeliveryPreflightScope
from ai_software_engineer.manager.native_verification import (
    NativePythonVerificationEvidence,
    NativeRoleVerificationInputs,
    RegisteredNativePythonVerifier,
    exact_python_selections,
)
from ai_software_engineer.manager.python_mysql_execution import (
    PythonMysqlExecutionIdentity,
    PythonMysqlExecutionJournal,
)
from ai_software_engineer.manager.python_mysql_proxy import MysqlUnixProxy
from ai_software_engineer.manager.python_mysql_resources import IsolatedMysqlResource
from ai_software_engineer.manager.python_verification import (
    PytestSelection,
    PythonMysqlHostPrerequisites,
    PythonMysqlSandboxCapability,
)
from ai_software_engineer.recovery.python_mysql_records import MysqlResourceIntent
from ai_software_engineer.recovery.verification_records import VerificationExecutionRecord
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueLeaseLost
from tests.domain.factories import NOW, make_implementation_artifact, make_plan_artifact, make_task
from tests.manager.test_python_verification import capability

_PREFIX = "ai_software_engineer.manager.native_verification."


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("/usr/bin/git", "-c", "core.hooksPath=/dev/null", *args),
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    ).stdout.strip()


class _Guard:
    inherited_fds: tuple[int, ...] = ()
    lease: SimpleNamespace | None = None

    def __init__(self, claim: QueueClaim) -> None:
        self.claim, self.active = claim, True

    def check(self) -> None:
        if not self.active:
            raise QueueLeaseLost("test owner expired")

    @contextmanager
    def write_scope(self) -> Iterator[None]:
        self.check()
        yield
        self.check()


class _Facts:
    def __init__(self, task: Task, request: AgentRequest, guard: _Guard) -> None:
        self.task, self.request, self.guard = task, request, guard
        self.context = request.context_manifest_id
        self.reads = 0

    def validate(
        self,
        *,
        plan: NativeRoleVerificationPlan,
        admission: NativeRoleVerificationAdmission,
        request: AgentRequest,
        workspace_root: Path,
        guard: ExecutionGuard,
    ) -> None:
        self.reads += 1
        guard.check()
        if (
            request != self.request
            or self.context != request.context_manifest_id
            or guard is not self.guard
            or plan.claim.lease_id != self.guard.claim.lease.id
            or self.task.status
            is not (TaskStatus.QA if request.role is AgentRole.QA else TaskStatus.REVIEW)
            or plan.workspace_root != str(workspace_root)
            or plan.plan_sha256 != admission.plan_sha256
        ):
            raise ValueError("current Task/Context/claim changed")


@dataclass(frozen=True)
class _Fixture:
    task: Task
    request: AgentRequest
    plan: PlanArtifact
    implementation: ImplementationReportArtifact
    claim: QueueClaim
    guard: _Guard
    facts: _Facts
    registry: RegisteredNativePythonVerifier
    root: Path
    cap: PythonMysqlSandboxCapability

    def bind(self) -> NativePythonVerificationEvidence | None:
        return self.registry.bind(
            task=self.task,
            request=self.request,
            plan_artifact=self.plan,
            implementation=self.implementation,
            claim=self.claim,
            facts=self.facts,
            workspace_root=self.root,
            guard=self.guard,
        )


def _fixture(tmp_path: Path, role: AgentRole = AgentRole.QA) -> _Fixture:
    repository = (tmp_path / "repository").resolve()
    if not repository.exists():
        repository.mkdir()
        (repository / "tests").mkdir()
        (repository / "tests/test_case.py").write_text(
            "def test_models():\n    raise AssertionError('preflight must not execute target')\n"
        )
        _git(repository, "init", "-q")
        _git(repository, "add", "tests/test_case.py")
        _git(
            repository,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "candidate",
        )
    revision = _git(repository, "rev-parse", "HEAD")
    root = (tmp_path / (role.value + "-worktree")).resolve()
    _git(repository, "worktree", "add", "--detach", str(root), revision)
    engineering_scope = EngineeringScope(
        team_id="team_native_001",
        project_id="project_native_001",
        repository_id="repository_native_001",
        repository_root=str(repository),
    )
    scope = DeliveryPreflightScope(
        team_id=engineering_scope.team_id,
        project_id=engineering_scope.project_id,
        repository_id=engineering_scope.repository_id,
        requirement_id="delivery_native_001",
    )
    base_task = make_task()
    task = Task.model_validate(
        {
            **base_task.to_wire(),
            "repository": str(repository),
            "base_ref": revision,
            "status": (TaskStatus.QA if role is AgentRole.QA else TaskStatus.REVIEW).value,
            "attempts": 1,
            "engineering_policy": EngineeringPolicy.bounded_local(
                scope=engineering_scope,
                principal=LocalOperatorPrincipal.trusted_local(),
            ).to_wire(),
        }
    )
    check = PlannedVerificationRequirement(
        id="verify_native",
        role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        argv=("pytest", "tests/test_case.py::test_models", "-q"),
        controlled_capability_kind="codex_sandbox_pytest_mysql_v1",
    )
    base_plan = make_plan_artifact()
    plan = base_plan.model_copy(
        update={
            "source_revision": revision,
            "content": base_plan.content.model_copy(update={"verification_requirements": (check,)}),
        }
    )
    base_implementation = make_implementation_artifact()
    implementation = base_implementation.model_copy(
        update={
            "source_revision": revision,
            "content": base_implementation.content.model_copy(update={"commit_sha": revision}),
        }
    )
    request = AgentRequest(
        run_id=f"run_native_{role.value}_001",
        task_id=task.id,
        role=role,
        attempt=1,
        source_revision=revision,
        context_manifest_id="ctx_" + ("a" * 64 if role is AgentRole.QA else "b" * 64),
        input_artifact_ids=(plan.artifact_id, implementation.artifact_id),
        permissions=AgentPermissions(
            read_paths=("**",), write_paths=(), commands=("pytest",), network=NetworkAccess.NONE
        ),
        output_schema="schemas/qa-report.schema.json"
        if role is AgentRole.QA
        else "schemas/review-report.schema.json",
        timeout_seconds=120,
    )
    assignment = RoleAssignment(
        id=f"assignment_native_{role.value}_001",
        repository_id=scope.repository_id,
        task_id=task.id,
        agent_id=f"agent_native_{role.value}_001",
        role=role,
        attempt=1,
        lease_id=f"lease_native_{role.value}_001",
        assigned_at=NOW,
    )
    claim = QueueClaim(
        work_item=QueuedWorkItem(
            id=f"work_native_{role.value}_001",
            task_id=task.id,
            repository_id=scope.repository_id,
            role=role,
            attempt=1,
            repository_scopes=(str(repository),),
            status=WorkItemStatus.LEASED,
            priority=500,
            risk=RiskTier.LOW,
            created_at=NOW,
            updated_at=NOW,
        ),
        assignment=assignment,
        lease=TaskLease(
            id=assignment.lease_id,
            assignment_id=assignment.id,
            task_id=task.id,
            agent_id=assignment.agent_id,
            acquired_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
        ),
        model_selection=ModelSelection(
            policy_id="model_policy_native_001",
            policy_version="v1",
            provider="fixture",
            model="fixture",
            tier=BrainTier.STANDARD,
            reasons=(ModelRouteReason.DEFAULT,),
            selected_at=NOW,
        ),
        worker_id="worker_native_001",
        claimed_at=NOW,
    )
    guard = _Guard(claim)
    facts = _Facts(task, request, guard)

    class Reader:
        def read(
            self,
            *,
            request: AgentRequest,
            workspace_root: Path,
            guard: ExecutionGuard,
        ) -> NativeRoleVerificationInputs:
            if request != facts.request or workspace_root != root or guard is not facts.guard:
                raise ValueError("reader request changed")
            return NativeRoleVerificationInputs(task, plan, implementation, claim, facts)

    registry = RegisteredNativePythonVerifier(
        scope=scope,
        engineering_scope=engineering_scope,
        repository_workspace_root=tmp_path / "sidecar",
        codex_executable="fixture-codex",
        clock=lambda: NOW,
        inputs_reader=Reader(),
    )
    cap = capability(tmp_path).model_copy(
        update={
            "selections": (
                PytestSelection(
                    node_id="tests/test_case.py::test_models", criterion_ids=("ac_models_01",)
                ),
            )
        }
    )
    return _Fixture(task, request, plan, implementation, claim, guard, facts, registry, root, cap)


def _fake_ports(
    monkeypatch: pytest.MonkeyPatch,
    fixture: _Fixture,
    *,
    returncode: int = 0,
) -> tuple[list[MysqlResourceIntent], list[tuple[str, ...]], list[str]]:
    cap = fixture.cap
    fields = cap.to_wire()
    host = PythonMysqlHostPrerequisites.model_validate(
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
    monkeypatch.setattr(_PREFIX + "discover_python_mysql_host_prerequisites", lambda **kwargs: host)
    monkeypatch.setattr(_PREFIX + "discover_python_mysql_capability", lambda *args, **kwargs: cap)
    resources: list[MysqlResourceIntent] = []
    passwords: list[str] = []
    executions: list[tuple[str, ...]] = []

    def start(resource: IsolatedMysqlResource, guard: Callable[[], None]) -> None:
        guard()
        resources.append(resource.intent)
        resource._record("INTENT")
        resource.container_id, resource.configuration_sha256 = "c" * 64, "d" * 64
        resource._record("CREATED")

    def close(resource: IsolatedMysqlResource) -> None:
        resource._record("CLEANED")
        resource._docker_config.cleanup()

    def run(executor: SubprocessCommandExecutor, argv: tuple[str, ...]) -> CommandResult:
        executions.append(argv)
        private = json.loads(Path(argv[-2]).read_text())
        passwords.append(private["password"])
        assert private["node_ids"] == ["tests/test_case.py::test_models"]
        return CommandResult(
            argv=argv,
            cwd=str(executor._workspace_root),
            returncode=returncode,
            stdout=private["password"],
            stderr="",
            duration_ms=1,
        )

    monkeypatch.setattr(IsolatedMysqlResource, "start", start)
    monkeypatch.setattr(IsolatedMysqlResource, "verify_principal", lambda *args: None)
    monkeypatch.setattr(IsolatedMysqlResource, "close", close)
    monkeypatch.setattr(MysqlUnixProxy, "__init__", lambda *args, **kwargs: None)
    monkeypatch.setattr(MysqlUnixProxy, "close", lambda *args: None)
    monkeypatch.setattr(SubprocessCommandExecutor, "run", run)
    return resources, executions, passwords


def _interrupt_native_execution(tmp_path: Path) -> Callable[..., VerificationExecutionRecord]:
    def interrupted(
        *,
        identity: PythonMysqlExecutionIdentity,
        records: PythonMysqlExecutionJournal,
        cap: PythonMysqlSandboxCapability,
        source: Path,
        guard: ExecutionGuard | None,
        clock: Callable[[], datetime],
        validate_facts: Callable[[], None],
        require_clean_candidate: Callable[[Path, str], None],
    ) -> Never:
        records.put_verification_execution(
            VerificationExecutionRecord.create(
                phase="STARTED",
                plan_sha256=identity.plan_sha256,
                invocation_sha256=identity.invocation_sha256,
                authorization_sha256=identity.authorization_sha256,
                candidate_revision=identity.candidate_revision,
                role=identity.role,
                capability=cap,
                source_root=str(source),
                scratch_root=str(tmp_path / "interrupted-scratch"),
                private_root=str(tmp_path / "interrupted-private"),
                mysql_resource_id="e" * 64,
                recorded_at=NOW,
            )
        )
        raise KeyboardInterrupt()

    return interrupted


def test_normal_role_durable_receipt_is_reused_without_new_task_or_recovery_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, passwords = _fake_ports(monkeypatch, fixture)
    before = fixture.task.to_wire()
    receipt = fixture.registry.discover(fixture.task, fixture.plan, fixture.registry.scope)
    assert {item.role for item in receipt} == {AgentRole.QA, AgentRole.REVIEWER}
    assert not resources and not executions
    provider = fixture.bind()
    assert provider is not None
    evidence = provider.evidence_for(fixture.request, fixture.root, fixture.guard)
    assert "不是 QA/Review 结论" in evidence.text
    assert all(password not in evidence.text for password in passwords)
    assert provider.evidence_for(fixture.request, fixture.root, fixture.guard) == evidence
    reopened = fixture.bind()
    assert reopened is not None
    assert reopened.evidence_for(fixture.request, fixture.root, fixture.guard) == evidence
    assert len(resources) == len(executions) == 1
    assert fixture.task.to_wire() == before
    assert fixture.task.status is TaskStatus.QA
    assert not list((tmp_path / "sidecar").rglob("engineering-admission-*.json"))
    sealed = json.loads(evidence.text.split("\n", 1)[1])
    plan = NativeRoleVerificationPlan.model_validate(sealed["plan"])
    admission = NativeRoleVerificationAdmission.model_validate(sealed["admission"])
    plan.validate_integrity()
    admission.validate_integrity()
    assert plan.task_id == admission.task_id == fixture.task.id
    assert plan.run_id == admission.run_id == fixture.request.run_id
    assert admission.authorization_source == "frozen_task_role_authorization"
    assert plan.claim.lease_id == fixture.claim.lease.id


def test_qa_and_reviewer_use_separate_claims_contexts_resources_and_same_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qa = _fixture(tmp_path, AgentRole.QA)
    review = _fixture(tmp_path, AgentRole.REVIEWER)
    resources, executions, _ = _fake_ports(monkeypatch, qa)
    qa_provider = qa.bind()
    review_provider = review.bind()
    assert qa_provider is not None and review_provider is not None
    qa_evidence = qa_provider.evidence_for(qa.request, qa.root, qa.guard)
    review_evidence = review_provider.evidence_for(review.request, review.root, review.guard)
    assert len(resources) == len(executions) == 2
    assert len({resource.resource_id for resource in resources}) == 2
    assert {resource.role for resource in resources} == {"qa", "reviewer"}
    assert qa.request.source_revision == review.request.source_revision
    assert qa.request.context_manifest_id != review.request.context_manifest_id
    assert qa.claim.assignment.agent_id != review.claim.assignment.agent_id
    assert qa_evidence != review_evidence


def test_interrupted_started_execution_survives_restart_and_is_not_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    provider = fixture.bind()
    assert provider is not None

    monkeypatch.setattr(
        _PREFIX + "execute_python_mysql_verification", _interrupt_native_execution(tmp_path)
    )
    with pytest.raises(KeyboardInterrupt):
        provider.evidence_for(fixture.request, fixture.root, fixture.guard)
    reopened = fixture.bind()
    assert reopened is not None
    with pytest.raises(NativeVerificationWaiting) as failure:
        reopened.evidence_for(fixture.request, fixture.root, fixture.guard)
    assert failure.value.reason is NativeVerificationWaitReason.EXECUTION_UNCERTAIN
    assert failure.value.record_sha256 is not None
    assert not resources and not executions


@pytest.mark.parametrize("change", ["request", "context", "claim", "task_stage", "guard"])
def test_current_request_context_claim_and_task_checkpoint_are_rechecked_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    provider = fixture.bind()
    assert provider is not None
    request = fixture.request
    if change == "request":
        request = request.model_copy(update={"context_manifest_id": "ctx_different_001"})
    elif change == "context":
        fixture.facts.context = "ctx_changed_after_admission"
    elif change == "claim":
        fixture.guard.claim = fixture.claim.model_copy(
            update={"lease": fixture.claim.lease.model_copy(update={"id": "lease_changed_001"})}
        )
    elif change == "task_stage":
        fixture.facts.task = fixture.task.model_copy(update={"status": TaskStatus.IMPLEMENTING})
    else:
        fixture.guard.active = False
    with pytest.raises((NativeVerificationWaiting, QueueLeaseLost)):
        provider.evidence_for(request, fixture.root, fixture.guard)
    assert not resources and not executions


def test_nonzero_test_is_evidence_for_independent_verdict_not_engineering_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    _fake_ports(monkeypatch, fixture, returncode=1)
    provider = fixture.bind()
    assert provider is not None
    evidence = provider.evidence_for(fixture.request, fixture.root, fixture.guard)
    sealed = json.loads(evidence.text.split("\n", 1)[1])
    assert sealed["receipt"]["phase"] == "COMPLETED"
    assert sealed["receipt"]["results"][0]["returncode"] == 1
    assert fixture.task.status is TaskStatus.QA


@pytest.mark.parametrize(
    "argv",
    [
        ("pytest", "tests/test_case.py"),
        ("pytest", "tests/test_case.py::test_models", "-k", "models"),
        ("pytest", "tests"),
        ("python", "-c", "print('not a test')"),
    ],
)
def test_registered_executor_rejects_nonexact_or_changed_pytest_selection(
    argv: tuple[str, ...],
) -> None:
    check = PlannedVerificationRequirement(
        id="invalid",
        role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        argv=argv,
        controlled_capability_kind="codex_sandbox_pytest_mysql_v1",
    )
    with pytest.raises(NativeVerificationWaiting) as failure:
        exact_python_selections((check,))
    assert failure.value.reason is NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT


def test_swift_filter_is_explicit_engineering_wait_before_host_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)

    def never_discover(**kwargs: object) -> Never:
        raise AssertionError("unsupported Swift must not be advertised as executable")

    monkeypatch.setattr(_PREFIX + "discover_python_mysql_host_prerequisites", never_discover)
    check = PlannedVerificationRequirement(
        id="swift",
        role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        argv=("swift", "test", "--filter", "FocusedTest"),
        controlled_capability_kind="codex_sandbox_swiftpm_v1",
    )
    plan = fixture.plan.model_copy(
        update={
            "content": fixture.plan.content.model_copy(
                update={"verification_requirements": (check,)}
            )
        }
    )
    with pytest.raises(NativeVerificationWaiting) as failure:
        fixture.registry.discover(fixture.task, plan, fixture.registry.scope)
    assert failure.value.reason is NativeVerificationWaitReason.UNSUPPORTED_SWIFT_FILTER


def test_discovery_uses_current_exact_source_without_rewriting_approved_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    _fake_ports(monkeypatch, fixture)
    before = fixture.plan.to_wire()
    current_source = "f" * 40
    receipt = fixture.registry.discover(
        fixture.task, fixture.plan, fixture.registry.scope, source_revision=current_source
    )
    assert all(item.source_revision == current_source for item in receipt)
    assert fixture.plan.to_wire() == before


def test_legacy_authority_and_wrong_candidate_are_denied_before_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    old_task = fixture.task.model_copy(update={"engineering_policy": None})
    with pytest.raises(NativeVerificationWaiting) as failure:
        fixture.registry.discover(old_task, fixture.plan, fixture.registry.scope)
    assert failure.value.reason is NativeVerificationWaitReason.LEGACY_AUTHORITY
    wrong = fixture.request.model_copy(update={"source_revision": "f" * 40})
    with pytest.raises(NativeVerificationWaiting) as failure:
        fixture.registry.bind(
            task=fixture.task,
            request=wrong,
            plan_artifact=fixture.plan,
            implementation=fixture.implementation,
            claim=fixture.claim,
            facts=fixture.facts,
            workspace_root=fixture.root,
            guard=fixture.guard,
        )
    assert failure.value.reason is NativeVerificationWaitReason.FACTS_CHANGED
    assert not resources and not executions


def test_dirty_candidate_is_retained_and_never_sent_to_controlled_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    (fixture.root / "unexpected.py").write_text("DIRTY = True\n")
    with pytest.raises(NativeVerificationWaiting) as failure:
        fixture.bind()
    assert failure.value.reason is NativeVerificationWaitReason.FACTS_CHANGED
    assert (fixture.root / "unexpected.py").exists()
    assert not resources and not executions


@pytest.mark.parametrize("route_kind", ["codex_cli", "responses"])
def test_public_route_factory_preserves_registration_and_supplies_dynamic_native_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_kind: str,
) -> None:
    from unittest.mock import MagicMock

    from ai_software_engineer.agents.openai_compatible import (
        PromptBuilder,
        PromptMessage,
        PromptPayload,
    )
    from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
    from ai_software_engineer.domain import AgentDefinition, ArtifactKind
    from ai_software_engineer.manager.production_delivery import (
        ConfiguredDeliveryRouteAdapterFactory,
    )
    from tests.domain.factories import make_agent

    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)

    class StaticPrompt:
        def __init__(self, resolver: object) -> None:
            pass

        def build(self, request: AgentRequest) -> PromptPayload:
            return PromptPayload(
                messages=(PromptMessage(role="user", content="Exact original role context"),)
            )

    captured: list[PromptBuilder] = []

    def adapter(*, prompt_builder: PromptBuilder, **kwargs: object) -> MagicMock:
        captured.append(prompt_builder)
        return MagicMock()

    monkeypatch.setattr(
        "ai_software_engineer.manager.production_delivery.ContextPromptBuilder", StaticPrompt
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_delivery.CodexCliAgentAdapter", adapter
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_delivery.ResponsesAgentAdapter", adapter
    )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="fixture",
                model="fixture",
                kind=ModelProviderKind(route_kind),
                endpoint="https://fixture.invalid/v1/responses"
                if route_kind == "responses"
                else None,
                api_key_env="ASE_NATIVE_TOKEN" if route_kind == "responses" else None,
            ),
        ),
    )
    base = make_agent()
    qa = AgentDefinition.model_validate(
        {
            **base.to_wire(),
            "id": "agent_native_qa_001",
            "role": AgentRole.QA.value,
            "input_artifacts": [ArtifactKind.PLAN.value, ArtifactKind.IMPLEMENTATION_REPORT.value],
            "output_artifacts": [ArtifactKind.QA_REPORT.value],
            "permissions": fixture.request.permissions.to_wire(),
        }
    )
    binding = MagicMock()
    binding.worktree.path = str(fixture.root)
    factory = ConfiguredDeliveryRouteAdapterFactory().with_registered_verifier(fixture.registry)
    factory = factory.with_execution_guard(fixture.guard).with_interruption_control(MagicMock())
    factory.create(
        route=config.model_routes[0],
        definition=qa,
        binding=binding,
        context_resolver=MagicMock(),
        config=config,
        environment={"ASE_NATIVE_TOKEN": "fixture-unused"},
    )
    with pytest.raises(NativeVerificationWaiting) as failure:
        captured[-1].build(fixture.request)
    assert failure.value.reason is NativeVerificationWaitReason.FACTS_CHANGED
    assert not resources and not executions
    factory.prepare_verifier(
        request=fixture.request, route=config.model_routes[0], binding=binding, config=config
    )
    prompt = captured[-1].build(fixture.request)
    assert prompt.messages[0].content == "Exact original role context"
    assert "native-role-verification://" in prompt.messages[-1].content
    assert len(resources) == len(executions) == 1
    # Registration alone cannot cause Coder to execute verification checks.
    factory.create(
        route=config.model_routes[0],
        definition=base,
        binding=binding,
        context_resolver=MagicMock(),
        config=config,
        environment={"ASE_NATIVE_TOKEN": "fixture-unused"},
    )
    assert isinstance(captured[-1], StaticPrompt)
    assert len(resources) == len(executions) == 1


@pytest.mark.parametrize("change", ["context", "claim", "candidate", "none"])
def test_prepared_receipt_rechecks_facts_without_rediscovery_or_reexecution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    fixture.registry.prepare_verifier(
        request=fixture.request, workspace_root=fixture.root, guard=fixture.guard
    )
    provider = fixture.registry.provider_for(
        workspace_root=fixture.root, guard=fixture.guard, require_prepared=True
    )
    before_reads = fixture.facts.reads

    def no_discovery(*args: object, **kwargs: object) -> Never:
        raise AssertionError("prepared sealed receipt cannot require host rediscovery")

    monkeypatch.setattr(_PREFIX + "discover_python_mysql_capability", no_discovery)
    if change == "context":
        fixture.facts.context = "ctx_" + "f" * 64
    elif change == "claim":
        fixture.guard.claim = fixture.claim.model_copy(
            update={"lease": fixture.claim.lease.model_copy(update={"id": "lease_changed_001"})}
        )
    elif change == "candidate":
        (fixture.root / "new_dirty.txt").write_text("must be retained")
    if change != "none":
        with pytest.raises(NativeVerificationWaiting) as failure:
            provider.evidence_for(fixture.request, fixture.root, fixture.guard)
        assert failure.value.reason is NativeVerificationWaitReason.FACTS_CHANGED
    else:
        assert provider.evidence_for(
            fixture.request, fixture.root, fixture.guard
        ) == provider.evidence_for(fixture.request, fixture.root, fixture.guard)
        assert fixture.facts.reads > before_reads
    assert len(resources) == len(executions) == 1


def test_ordinary_responses_plan_uses_original_tools_without_registered_command_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    assert fixture.plan.content.verification_requirements is not None
    ordinary = fixture.plan.model_copy(
        update={
            "content": fixture.plan.content.model_copy(
                update={
                    "verification_requirements": tuple(
                        item.model_copy(update={"controlled_capability_kind": None})
                        for item in fixture.plan.content.verification_requirements
                    ),
                }
            )
        }
    )

    class Reader:
        def read(
            self,
            *,
            request: AgentRequest,
            workspace_root: Path,
            guard: ExecutionGuard,
        ) -> NativeRoleVerificationInputs:
            if (
                request != fixture.request
                or workspace_root != fixture.root
                or guard is not fixture.guard
            ):
                raise ValueError("changed ordinary role request")
            return NativeRoleVerificationInputs(
                fixture.task, ordinary, fixture.implementation, fixture.claim, fixture.facts
            )

    monkeypatch.setattr(fixture.registry, "_inputs_reader", Reader())
    fixture.registry.prepare_verifier(
        request=fixture.request,
        workspace_root=fixture.root,
        guard=fixture.guard,
        allow_ordinary_commands=True,
    )
    provider = fixture.registry.provider_for(
        workspace_root=fixture.root,
        guard=fixture.guard,
        allow_ordinary_commands=True,
        require_prepared=True,
    )
    text = provider.evidence_for(fixture.request, fixture.root, fixture.guard).text
    assert "普通受限验证工具" in text and "不得把本准备说明当作测试结果" in text
    assert not resources and not executions
    # The ordinary-tool grant cannot leak into a Codex route of the same Run.
    codex = fixture.registry.provider_for(
        workspace_root=fixture.root, guard=fixture.guard, require_prepared=True
    )
    with pytest.raises(NativeVerificationWaiting):
        codex.evidence_for(fixture.request, fixture.root, fixture.guard)


def test_interrupted_native_preparation_cannot_become_a_ready_cached_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)

    monkeypatch.setattr(
        _PREFIX + "execute_python_mysql_verification", _interrupt_native_execution(tmp_path)
    )
    with pytest.raises(KeyboardInterrupt):
        fixture.registry.prepare_verifier(
            request=fixture.request, workspace_root=fixture.root, guard=fixture.guard
        )
    assert not fixture.registry._prepared
    with pytest.raises(NativeVerificationWaiting) as failure:
        fixture.registry.prepare_verifier(
            request=fixture.request, workspace_root=fixture.root, guard=fixture.guard
        )
    assert failure.value.reason is NativeVerificationWaitReason.EXECUTION_UNCERTAIN
    assert not fixture.registry._prepared and not resources and not executions
