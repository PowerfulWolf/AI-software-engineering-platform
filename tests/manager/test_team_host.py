"""Real preparation/Product wiring; only DB connectivity and model calls are stubbed."""

import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents import StructuredModelClient, StructuredModelResult
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import Task, TeamRole
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    DeliveryResponsibility,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import HandleDeliveryWait
from ai_software_engineer.domain.engineering_authority import (
    EngineeringCapability,
    EngineeringGrant,
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.enums import AgentRole, WorkItemStatus
from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised
from ai_software_engineer.knowledge_documents import (
    ProjectKnowledgeDocumentStore,
    TeamKnowledgeDocumentStore,
)
from ai_software_engineer.knowledge_selection import (
    ProjectKnowledgeSelectionStore,
    TeamKnowledgeSelectionStore,
)
from ai_software_engineer.manager.delivery import (
    ReplyToProduct,
    ResumeProjectDelivery,
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    ProjectDeliveryCheckpointNotFound,
)
from ai_software_engineer.manager.production_backend import StructuredClientFactory
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.multi_directory.errors import RequirementSourceRevisionDrift
from ai_software_engineer.multi_directory.models import JointDeliveryResult, JointStage
from ai_software_engineer.multi_directory.production import ProductionJointBackend
from ai_software_engineer.multi_directory.service import CreateRequirement
from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry
from ai_software_engineer.spec_documents import (
    CreateSpecDocument,
    ProjectSpecDocumentStore,
    TeamSpecDocumentStore,
)
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.domain.factories import make_task
from tests.manager.test_production_backend import _git, _git_output, _ScriptedStructuredClient


class _ConnectivityStub:
    def __init__(self, dsn: str) -> None:
        assert dsn == "connectivity-only"

    def close(self) -> None:
        pass


class _RecordingFactory(StructuredClientFactory, StructuredModelClient):
    def __init__(self) -> None:
        self.payloads: list[Mapping[str, object]] = []
        self.project_roots: list[tuple[Path, ...]] = []

    def for_project(
        self,
        repository_root: Path,
        role: TeamRole = TeamRole.PRODUCT,
    ) -> StructuredModelClient:
        del role
        assert repository_root.is_dir()
        self.project_roots.append((repository_root,))
        return self

    def for_projects(
        self,
        repository_roots: tuple[Path, ...],
        role: TeamRole = TeamRole.PRODUCT,
    ) -> StructuredModelClient:
        del role
        assert repository_roots
        assert all(root.is_dir() for root in repository_roots)
        self.project_roots.append(repository_roots)
        return self

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        del input_images
        self.payloads.append(input_payload)
        return _ScriptedStructuredClient().complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
        )


class _TaskRepositoryStub(_ConnectivityStub):
    def __init__(self, dsn: str, task: Task) -> None:
        super().__init__(dsn)
        self.task = task
        self.requested: list[str] = []

    def get(self, task_id: str) -> Task:
        self.requested.append(task_id)
        assert task_id == self.task.id
        return self.task


def _wait_host_fixture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stage: DeliveryStage = DeliveryStage.DELIVERING,
    engineering_policy: EngineeringPolicy | None = None,
) -> tuple[TeamHost, SimpleNamespace, HandleDeliveryWait, list[object]]:
    """Build only the public-host facts; DB access remains connectivity-only."""
    base = _config_task()
    frozen_policy = engineering_policy or EngineeringPolicy.bounded_local(
        scope=EngineeringScope(
            team_id="team_alpha",
            project_id="project_alpha",
            repository_id="repository_current",
            repository_root=base.repository,
        ),
        principal=LocalOperatorPrincipal.trusted_local(),
    )
    task = Task.model_validate({**base.to_wire(), "engineering_policy": frozen_policy.to_wire()})
    checkpoint = SimpleNamespace(
        delivery_id="delivery_current_wait",
        stage=stage,
        task_id=task.id,
        repository_id="repository_current",
    )
    facts = DeliveryFailureFacts(
        task_id=task.id,
        work_item_id="work_current_wait",
        role=AgentRole.CODER,
        classification="EXECUTION_UNCERTAIN",
        source_revision=task.base_ref,
        task_intent_sha256=task_intent_sha256(task),
        checkpoint_sequence=1,
        budget_available=True,
    )
    disposition = decide_delivery_disposition(facts)
    assert disposition.responsibility is DeliveryResponsibility.ENGINEERING
    item = SimpleNamespace(
        id=facts.work_item_id,
        task_id=task.id,
        repository_id=checkpoint.repository_id,
        status=WorkItemStatus.WAITING_HUMAN,
        wait_disposition=disposition,
    )
    queue = SimpleNamespace(items_for_task=lambda task_id: (item,) if task_id == task.id else ())
    runtime = SimpleNamespace(
        entry=SimpleNamespace(status=lambda delivery_id: SimpleNamespace(checkpoint=checkpoint))
    )
    host = object.__new__(TeamHost)
    host._config = SimpleNamespace(require_mysql_dsn=lambda environment: "connectivity-only")
    host._environment = {"ASE_MYSQL_DSN": "connectivity-only"}
    host._work_queue = queue
    host._operator_principal = LocalOperatorPrincipal.trusted_local()
    host._runtime = lambda project_id: runtime
    host._resolve_project_id = lambda project_id, delivery_id=None: project_id or "project_alpha"
    captured: list[object] = []

    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlTaskRepository",
        lambda dsn: _TaskRepositoryStub(dsn, task),
    )
    command = HandleDeliveryWait(
        work_item_id=item.id,
        expected_disposition_sha256=disposition.disposition_sha256,
        expected_task_intent_sha256=facts.task_intent_sha256,
        expected_source_revision=facts.source_revision,
        expected_checkpoint_sequence=facts.checkpoint_sequence,
    )
    return host, checkpoint, command, captured


def _config_task() -> Task:
    """Keep the fixture's task fully typed while avoiding a production workspace."""
    return make_task()


def _config(root: Path, team_id: str, paths: tuple[str, ...] = ()) -> ProductionConfig:
    return ProductionConfig(
        platform_root=str(root),
        team_id=team_id,
        team_name=team_id,
        team_knowledge_paths=paths,
        default_project_id="project_alpha",
        default_project_name="Alpha Project",
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )


def test_recovery_uses_current_project_backend_when_child_delivery_is_frozen(
    tmp_path: Path,
) -> None:
    host = object.__new__(TeamHost)
    host._config = _config(tmp_path / "platform", "team_alpha")
    host._environment = {"ASE_MYSQL_DSN": "connectivity-only"}
    host._team = TeamWorkspace.initialize(
        tmp_path / "platform", team_id="team_alpha", name="team_alpha"
    )
    host._operator_principal = LocalOperatorPrincipal.trusted_local()
    current_backend = cast(Any, SimpleNamespace(_delivery_route_adapters=None))
    frozen_child_backend = cast(Any, SimpleNamespace(_delivery_route_adapters=None))
    runtime = cast(Any, SimpleNamespace(backend=current_backend, entry=object()))

    controller = host._resume_controller(
        runtime,
        backend=frozen_child_backend,
        entry=cast(Any, object()),
    )

    assert controller._backend is frozen_child_backend
    assert controller._recovery.backend is current_backend
    assert controller._verification.backend is current_backend


@pytest.mark.parametrize("knowledge_gap", [False, True])
def test_joint_resume_syncs_parent_after_non_done_child_recovery(
    monkeypatch: pytest.MonkeyPatch,
    knowledge_gap: bool,
) -> None:
    """A child recovery result must be observed by the parent journal."""

    host = object.__new__(TeamHost)
    child_checkpoint = SimpleNamespace(
        delivery_id="delivery_child_blocked",
        stage=DeliveryStage.BLOCKED,
        task_id="task_successor",
    )
    child = SimpleNamespace(unit_id="unit_child", checkpoint=child_checkpoint)
    joint = SimpleNamespace(
        stage=JointStage.BLOCKED,
        integration=None,
        children=(child,),
    )
    parent_result = JointDeliveryResult.model_construct(checkpoint=joint)
    child_result = SimpleNamespace(
        checkpoint=SimpleNamespace(stage=DeliveryStage.BLOCKED),
        outcome="WAITING_HUMAN",
    )
    calls: list[tuple[str, object]] = []
    gap = Mock(gap_id="a" * 64, binding=SimpleNamespace(task_id="task_successor"))
    records = Mock()
    records.get.return_value = gap
    monkeypatch.setattr(
        "ai_software_engineer.knowledge.administration.find_gap_records",
        lambda *args, **kwargs: records,
    )

    def resume_parent(command: ResumeProjectDelivery) -> object:
        calls.append(("parent", command))
        return parent_result

    def resume_child(command: ResumeProjectDelivery) -> SimpleNamespace:
        calls.append(("child", command))
        if knowledge_gap:
            raise KnowledgeGapRaised(gap)
        return child_result

    backend = object.__new__(ProductionJointBackend)
    child_entry = SimpleNamespace(
        status=lambda delivery_id: SimpleNamespace(checkpoint=child_checkpoint)
    )
    monkeypatch.setattr(
        backend, "delivery_runtime", lambda checkpoint, unit_id: (None, child_entry)
    )
    requirements = SimpleNamespace(
        backend=backend,
        journal=SimpleNamespace(current=lambda delivery_id: None),
        status=lambda delivery_id: SimpleNamespace(checkpoint=joint),
        resume=resume_parent,
    )
    runtime = SimpleNamespace(requirements=requirements, project=Mock())
    controller = SimpleNamespace(
        resume=resume_child,
    )
    monkeypatch.setattr(host, "_resolve_project_id", lambda project_id, delivery_id=None: "project")
    monkeypatch.setattr(host, "_runtime", lambda project_id: runtime)
    monkeypatch.setattr(
        host,
        "_resume_controller",
        lambda runtime, **kwargs: controller,
    )

    result = host.resume_delivery(ResumeProjectDelivery(delivery_id="delivery_multi_joint_resume"))

    assert result is parent_result
    assert [kind for kind, _ in calls] == ["child", "parent"]


def test_resume_delivery_handles_one_current_wait_then_resumes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, checkpoint, command, captured = _wait_host_fixture(monkeypatch)
    resume_calls: list[ResumeProjectDelivery] = []
    service_bindings: list[dict[str, object]] = []

    def resume_once(
        current: ResumeProjectDelivery, *, project_id: str | None = None
    ) -> SimpleNamespace:
        del project_id
        resume_calls.append(current)
        return SimpleNamespace(checkpoint=checkpoint)

    class ResolvedService:
        def handle(self, current: HandleDeliveryWait) -> SimpleNamespace:
            captured.append(current)
            return SimpleNamespace(status="RESOLVED")

    host._resume_delivery_once = resume_once

    def delivery_wait_service(current: HandleDeliveryWait, **kwargs: object) -> ResolvedService:
        del current
        service_bindings.append(kwargs)
        return ResolvedService()

    host._delivery_wait_service = delivery_wait_service

    result = host.resume_delivery(
        ResumeProjectDelivery(delivery_id=checkpoint.delivery_id), project_id="project_alpha"
    )

    assert result.checkpoint is checkpoint
    assert len(resume_calls) == 2
    assert all(call.delivery_id == checkpoint.delivery_id for call in resume_calls)
    assert captured == [command]
    assert service_bindings[0]["project_id"] == "project_alpha"
    assert service_bindings[0]["delivery_id"] == checkpoint.delivery_id


def test_resume_delivery_does_not_recurse_when_handling_stays_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, checkpoint, command, captured = _wait_host_fixture(monkeypatch)
    resume_calls: list[ResumeProjectDelivery] = []

    def resume_once(
        current: ResumeProjectDelivery, *, project_id: str | None = None
    ) -> SimpleNamespace:
        del project_id
        resume_calls.append(current)
        return SimpleNamespace(checkpoint=checkpoint)

    class WaitingService:
        def handle(self, current: HandleDeliveryWait) -> SimpleNamespace:
            captured.append(current)
            return SimpleNamespace(status="WAITING_EXECUTION")

    host._resume_delivery_once = resume_once
    host._delivery_wait_service = lambda current, **kwargs: WaitingService()

    host.resume_delivery(
        ResumeProjectDelivery(delivery_id=checkpoint.delivery_id), project_id="project_alpha"
    )

    assert len(resume_calls) == 1
    assert captured == [command]


def test_resume_delivery_does_not_handle_non_delivering_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, checkpoint, _, _ = _wait_host_fixture(monkeypatch, stage=DeliveryStage.PLANNING)
    handle_calls: list[object] = []
    resume_calls: list[ResumeProjectDelivery] = []

    def resume_once(
        current: ResumeProjectDelivery, *, project_id: str | None = None
    ) -> SimpleNamespace:
        del project_id
        resume_calls.append(current)
        return SimpleNamespace(checkpoint=checkpoint)

    def unexpected_handle(project_id: str, delivery_id: str) -> bool:
        handle_calls.append((project_id, delivery_id))
        return True

    host._resume_delivery_once = resume_once
    host._handle_current_wait_once = unexpected_handle

    host.resume_delivery(
        ResumeProjectDelivery(delivery_id=checkpoint.delivery_id), project_id="project_alpha"
    )

    assert len(resume_calls) == 1
    assert handle_calls == []


def test_current_wait_without_frozen_delivery_wait_grant_does_not_call_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _config_task()
    policy = EngineeringPolicy(
        scope=EngineeringScope(
            team_id="team_alpha",
            project_id="project_alpha",
            repository_id="repository_current",
            repository_root=base.repository,
        ),
        issued_by=LocalOperatorPrincipal.trusted_local(),
        grants=(
            EngineeringGrant(
                capability=EngineeringCapability.VERIFICATION_REFRESH,
                max_admissions=1,
            ),
        ),
    )
    host, checkpoint, _, _ = _wait_host_fixture(monkeypatch, engineering_policy=policy)
    service_calls: list[object] = []
    host._delivery_wait_service = lambda current, **kwargs: service_calls.append(current)

    assert host._handle_current_wait_once("project_alpha", checkpoint.delivery_id) is False
    assert service_calls == []


def test_explicit_handle_delivery_wait_resumes_exactly_once_after_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, checkpoint, command, captured = _wait_host_fixture(monkeypatch)
    resume_calls: list[ResumeProjectDelivery] = []
    service_bindings: list[dict[str, object]] = []

    class ResolvedService:
        def handle(self, current: HandleDeliveryWait) -> SimpleNamespace:
            captured.append(current)
            return SimpleNamespace(status="RESOLVED")

    def delivery_wait_service(current: HandleDeliveryWait, **kwargs: object) -> ResolvedService:
        del current
        service_bindings.append(kwargs)
        return ResolvedService()

    host._delivery_wait_service = delivery_wait_service

    def resume_once(
        current: ResumeProjectDelivery, *, project_id: str | None = None
    ) -> SimpleNamespace:
        del project_id
        resume_calls.append(current)
        return SimpleNamespace(checkpoint=checkpoint)

    host._resume_delivery_once = resume_once

    result = host.handle_delivery_wait(
        command, project_id="project_alpha", delivery_id=checkpoint.delivery_id
    )

    assert result.status == "RESOLVED"
    assert captured == [command]
    assert len(resume_calls) == 1
    assert resume_calls[0].delivery_id == checkpoint.delivery_id
    assert service_bindings[0]["project_id"] == "project_alpha"
    assert service_bindings[0]["delivery_id"] == checkpoint.delivery_id


def test_joint_wait_service_binds_continuation_to_native_child_and_exact_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform = tmp_path / "platform"
    team = TeamWorkspace.initialize(platform, team_id="team_alpha", name="Alpha")
    project = ProjectWorkspaceRegistry(team).register(project_id="project_alpha", name="Alpha")
    code = tmp_path / "code"
    code.mkdir()
    _git("init", cwd=code)
    (code / "hello.txt").write_text("hello\n", encoding="utf-8")
    _git("add", "hello.txt", cwd=code)
    _git("commit", "-m", "base", cwd=code)
    workspace = project.repository_registry().register(code)
    task = Task.model_validate(
        {
            **make_task().to_wire(),
            "repository": str(code),
            "base_ref": _git_output("rev-parse", "HEAD", cwd=code),
        }
    )
    parent_id, child_id = "delivery_multi_parent_wait", "delivery_child_wait"
    native = SimpleNamespace(
        delivery_id=child_id,
        task_id=task.id,
        repository_id=workspace.repository_id,
        repository_root=str(code),
        dispatch_commit_sha256="d" * 64,
    )
    current = SimpleNamespace(
        id="work_child_wait", task_id=task.id, repository_id=workspace.repository_id
    )
    command = HandleDeliveryWait(
        work_item_id=current.id,
        expected_disposition_sha256="a" * 64,
        expected_task_intent_sha256=task_intent_sha256(task),
        expected_source_revision=task.base_ref,
        expected_checkpoint_sequence=1,
    )
    requested: list[str] = []
    collectors: list[DeliveryWaitFactCollector] = []
    queue = SimpleNamespace(get=lambda work_item_id: current)

    def requirement_status(delivery_id: str) -> SimpleNamespace:
        requested.append(delivery_id)
        assert delivery_id == parent_id
        return SimpleNamespace(
            checkpoint=SimpleNamespace(children=(SimpleNamespace(checkpoint=native),))
        )

    runtime = SimpleNamespace(
        project=project,
        requirements=SimpleNamespace(status=requirement_status),
        backend=SimpleNamespace(),
    )
    host = object.__new__(TeamHost)
    host._config = _config(platform, "team_alpha")
    host._environment = {"ASE_MYSQL_DSN": "connectivity-only"}
    host._team = team
    host._operator_principal = LocalOperatorPrincipal.trusted_local()
    host._work_queue = queue
    monkeypatch.setattr(host, "_runtime", lambda project_id: runtime)

    class RecordingCollector(DeliveryWaitFactCollector):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            collectors.append(self)

    monkeypatch.setattr(
        "ai_software_engineer.manager.wait_fact_collection.DeliveryWaitFactCollector",
        RecordingCollector,
    )
    repository = _TaskRepositoryStub("connectivity-only", task)

    service = host._delivery_wait_service(
        command,
        project_id=project.manifest.project_id,
        delivery_id=parent_id,
        repository=repository,
    )

    assert requested == [parent_id]
    assert repository.requested == [task.id]
    assert len(collectors) == 1
    collector = collectors[0]
    assert collector.scope == EngineeringScope(
        team_id=team.manifest.team_id,
        project_id=project.manifest.project_id,
        repository_id=workspace.repository_id,
        repository_root=str(code),
    )
    assert collector.expected_continuation_scope.requirement_id == child_id
    assert collector.expected_continuation_scope.requirement_id != parent_id
    assert collector.expected_continuation_scope.dispatch_sha256 == native.dispatch_commit_sha256
    assert collector.expected_continuation_scope.team_id == team.manifest.team_id
    assert collector.expected_continuation_scope.project_id == project.manifest.project_id
    assert collector.expected_continuation_scope.repository_id == workspace.repository_id
    assert collector.state == workspace.directory("state")
    assert service.scope == collector.scope
    assert service.queue is queue and service.repository is repository
    assert service.fact_collector is not None
    assert (code / "hello.txt").read_text(encoding="utf-8") == "hello\n"
    assert not (code / ".ase").exists()


def test_team_host_scopes_product_catalog_and_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlTaskRepository",
        _ConnectivityStub,
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlPersistentWorkQueue",
        _ConnectivityStub,
    )
    repo = tmp_path / "code"
    repo.mkdir()
    _git("init", cwd=repo)
    (repo / "hello.txt").write_text("hello\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "base", cwd=repo)
    platform = tmp_path / "platform"
    team = TeamWorkspace.initialize(platform, team_id="team_alpha", name="team_alpha")
    rule = team.root / "knowledge" / "workflow.md"
    rule.write_text("ALPHA REVIEW RULE password=do-not-persist\n")
    (team.root / "knowledge" / "unselected.md").write_text("UNSELECTED PRIVATE DATA")
    models = _RecordingFactory()
    config = _config(platform, "team_alpha", ("workflow.md",))
    config = ProductionConfig.model_validate(
        {
            **config.to_wire(),
            "execution_retry_policy": {
                "designer": {"max_attempts": 7, "max_transient_failures": 12}
            },
        }
    )
    host = TeamHost(
        config=config, environment={"ASE_MYSQL_DSN": "connectivity-only"}, structured_clients=models
    )
    command = StartProjectDelivery(repository_root=str(repo), requirement="Update the greeting")
    assert host.requirement_entry().design_retry_policy == config.design_retry_policy
    first = host.project_entry().start(command)
    assert first.checkpoint.stage is DeliveryStage.WAITING_PRODUCT_APPROVAL
    alpha_repositories = platform / "projects" / "project_alpha" / "repositories"
    assert (alpha_repositories / first.checkpoint.repository_id).is_dir()
    payload = json.dumps(models.payloads)
    assert "ALPHA REVIEW RULE" in payload
    assert "do-not-persist" not in payload
    assert "UNSELECTED PRIVATE DATA" not in payload
    assert (platform / "team").is_dir()
    beta = host.create_project(name="Beta Project", project_id="project_beta")
    second = host.project_entry(beta.manifest.project_id).start(command)
    assert first.checkpoint.repository_id != second.checkpoint.repository_id
    assert first.checkpoint.delivery_id != second.checkpoint.delivery_id
    with pytest.raises(ProjectDeliveryCheckpointNotFound):
        host.project_entry(beta.manifest.project_id).status(first.checkpoint.delivery_id)
    # No extra model call for same team replay.
    replay = host.project_entry().start(command)
    assert replay.checkpoint == first.checkpoint
    assert len(models.payloads) == 2
    rule.write_text("CHANGED TEAM POLICY")
    drifted = host.project_entry().status(first.checkpoint.delivery_id)
    assert drifted.checkpoint == first.checkpoint
    assert drifted.diagnostic is not None
    assert "代码基线已漂移" in drifted.diagnostic
    reopened = TeamHost(
        config=config, environment={"ASE_MYSQL_DSN": "connectivity-only"}, structured_clients=models
    )
    reopened_drifted = reopened.project_entry().status(first.checkpoint.delivery_id)
    assert reopened_drifted.checkpoint == first.checkpoint
    assert reopened_drifted.diagnostic is not None
    assert len(models.payloads) == 2
    assert (repo / "hello.txt").read_text() == "hello\n"


def test_requirement_product_keeps_its_source_baseline_after_checkout_advances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlTaskRepository",
        _ConnectivityStub,
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlPersistentWorkQueue",
        _ConnectivityStub,
    )
    repo = tmp_path / "code"
    repo.mkdir()
    _git("init", cwd=repo)
    (repo / "hello.txt").write_text("requirement baseline\n", encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "base", cwd=repo)
    original_revision = _git_output("rev-parse", "HEAD", cwd=repo)
    models = _RecordingFactory()
    host = TeamHost(
        config=_config(tmp_path / "platform", "team_alpha"),
        environment={"ASE_MYSQL_DSN": "connectivity-only"},
        structured_clients=models,
    )
    service = host.requirement_entry()
    created = service.create(
        CreateRequirement(name="Pinned source", repository_roots=(str(repo),))
    ).checkpoint

    (repo / "hello.txt").write_text("new master\n", encoding="utf-8")
    _git("add", "hello.txt", cwd=repo)
    _git("commit", "-m", "advance master", cwd=repo)
    discussed = service.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Keep working on the original requirement.",
        )
    ).checkpoint

    assert discussed.stage is JointStage.WAITING_PRODUCT_APPROVAL
    assert created.scope.units[0].base_revision == original_revision
    assert models.project_roots
    product_root = models.project_roots[-1][0]
    assert product_root != repo
    assert (product_root / "hello.txt").read_text(encoding="utf-8") == "requirement baseline\n"
    assert _git_output("rev-parse", "HEAD", cwd=product_root) == original_revision

    later = service.create(
        CreateRequirement(name="New source", repository_roots=(str(repo),))
    ).checkpoint
    service.reply(
        ReplyToProduct(
            delivery_id=later.delivery_id,
            expected_checkpoint_sha256=later.checkpoint_sha256,
            message="Discuss the requirement against the newer source.",
        )
    )
    later_product_root = models.project_roots[-1][0]
    assert later_product_root != product_root
    assert (later_product_root / "hello.txt").read_text(encoding="utf-8") == "new master\n"
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "new master\n"


def test_requirement_rejects_a_modified_retained_source_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlTaskRepository",
        _ConnectivityStub,
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlPersistentWorkQueue",
        _ConnectivityStub,
    )
    repo = tmp_path / "code"
    repo.mkdir()
    _git("init", cwd=repo)
    (repo / "hello.txt").write_text("baseline\n", encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "base", cwd=repo)
    platform = tmp_path / "platform"
    service = TeamHost(
        config=_config(platform, "team_alpha"),
        environment={"ASE_MYSQL_DSN": "connectivity-only"},
        structured_clients=_RecordingFactory(),
    ).requirement_entry()
    created = service.create(
        CreateRequirement(name="Pinned source", repository_roots=(str(repo),))
    ).checkpoint
    baseline = next((platform / "worktrees" / "requirements").rglob("reviewer-attempt-01"))
    (baseline / "hello.txt").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(RequirementSourceRevisionDrift, match="baseline worktree changed"):
        service.status(created.delivery_id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("team_id", "../other"),
        ("team_name", ""),
        ("team_knowledge_paths", ["../other/rules.md"]),
        ("team_knowledge_paths", ["a.md", "a.md"]),
    ],
)
def test_team_config_rejects_invalid_selection(tmp_path: Path, field: str, value: object) -> None:
    payload: dict[str, object] = dict(_config(tmp_path, "team_alpha").to_wire())
    payload[field] = value
    with pytest.raises(ValueError):
        ProductionConfig.model_validate(payload)


def test_team_host_hot_reloads_scope_owned_knowledge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlTaskRepository",
        _ConnectivityStub,
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlPersistentWorkQueue",
        _ConnectivityStub,
    )
    platform = tmp_path / "platform"
    host = TeamHost(
        config=_config(platform, "team_alpha"),
        environment={"ASE_MYSQL_DSN": "connectivity-only"},
        structured_clients=_RecordingFactory(),
    )
    alpha = host.project_registry.open("project_alpha")
    host.create_project(name="Beta", project_id="project_beta")
    alpha_entry = host.project_entry("project_alpha")
    beta_entry = host.project_entry("project_beta")
    alpha_document = ProjectKnowledgeDocumentStore(alpha).import_document(
        filename="alpha.md", content=b"# Alpha\n"
    )

    ProjectKnowledgeSelectionStore(alpha).save((alpha_document.normalized_relative_path,))

    assert host.project_entry("project_alpha") is not alpha_entry
    assert host.project_entry("project_beta") is beta_entry

    team_document = TeamKnowledgeDocumentStore(host.team_workspace).import_document(
        filename="team.md", content=b"# Team\n"
    )
    TeamKnowledgeSelectionStore(host.team_workspace).save((team_document.normalized_relative_path,))

    assert host.project_entry("project_beta") is not beta_entry


def test_team_host_hot_reloads_active_specs_at_their_owner_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlTaskRepository",
        _ConnectivityStub,
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_host.MySqlPersistentWorkQueue",
        _ConnectivityStub,
    )
    platform = tmp_path / "platform"
    host = TeamHost(
        config=_config(platform, "team_alpha"),
        environment={"ASE_MYSQL_DSN": "connectivity-only"},
        structured_clients=_RecordingFactory(),
    )
    alpha = host.project_registry.open("project_alpha")
    host.create_project(name="Beta", project_id="project_beta")
    alpha_entry = host.project_entry("project_alpha")
    beta_entry = host.project_entry("project_beta")
    command = CreateSpecDocument(
        spec_key="python.testing",
        title="Python testing",
        body_markdown="# Testing\n",
        verification="Record passing pytest evidence.",
    )
    project_store = ProjectSpecDocumentStore(alpha)
    project_spec = project_store.create(command)
    project_store.activate((project_spec.spec_id,))

    assert host.project_entry("project_alpha") is not alpha_entry
    assert host.project_entry("project_beta") is beta_entry

    team_store = TeamSpecDocumentStore(host.team_workspace)
    team_spec = team_store.create(command)
    team_store.activate((team_spec.spec_id,))

    assert host.project_entry("project_beta") is not beta_entry
