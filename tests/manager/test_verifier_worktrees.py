"""Real-Git verifier lifecycle through the production delivery adapter seam."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentRequest,
    AgentResult,
    FakeAgentAdapter,
    FakeBehavior,
    FakeScenario,
    StoredContextResolver,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import (
    ModelProviderKind,
    ProductionConfig,
    ProductionConfigError,
    ProviderRouteConfig,
)
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentDefinition, AgentRole
from ai_software_engineer.git import DirtyWorktree, WorktreeRevisionDrift
from ai_software_engineer.manager.production_delivery import DispatchDeliveryAgentAdapter
from ai_software_engineer.orchestration import ExecutionPlanAgentAdapter
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from tests.agents.test_fake import _request
from tests.manager.test_dispatch import RecordingDispatchStore, _facts, _service
from tests.orchestration.test_runner import _definitions
from tests.role_workspace.test_role_workspace import _git


class ObservingAdapter:
    def __init__(self, binding: RoleWorktreeBinding) -> None:
        self.binding = binding

    def run(self, request: AgentRequest) -> AgentResult:
        assert _git(self.binding.worktree.path, "rev-parse", "HEAD") == request.source_revision
        return FakeAgentAdapter(default=FakeScenario(behavior=FakeBehavior.TIMEOUT)).run(request)


class ObservingFactory:
    def __init__(self) -> None:
        self.bindings: list[RoleWorktreeBinding] = []

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
        self.bindings.append(binding)
        return ObservingAdapter(binding)


@dataclass(frozen=True)
class VerifierFixture:
    create_adapter: Callable[[], DispatchDeliveryAgentAdapter]
    factory: ObservingFactory
    task_id: str
    first: str
    second: str
    repository: Path

    def request(
        self, role: AgentRole, attempt: int = 1, *, candidate: str | None = None
    ) -> AgentRequest:
        return _request(
            role,
            run_id=f"run_candidate_{attempt}_{role.value}",
            attempt=attempt,
            source_revision=candidate or (self.first if attempt == 1 else self.second),
        ).model_copy(update={"task_id": self.task_id})


@pytest.fixture
def verifier_fixture(tmp_path: Path) -> VerifierFixture:
    request, snapshot = _facts(tmp_path)
    dispatch = _service(RecordingDispatchStore(), snapshot, request).commit_dispatch(request)
    repository = Path(dispatch.task.repository)
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.name", "Fixture Author")
    _git(repository, "config", "user.email", "fixture@example.invalid")
    (repository / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repository, "add", "app.py")
    _git(repository, "commit", "-m", "candidate one")
    first = _git(repository, "rev-parse", "HEAD")
    (repository / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repository, "add", "app.py")
    _git(repository, "commit", "-m", "candidate two")
    second = _git(repository, "rev-parse", "HEAD")
    definitions = _definitions()
    for phase in dispatch.phases:
        definitions[phase.role] = definitions[phase.role].model_copy(
            update={
                "id": phase.agent_id,
                "provider": phase.model_selection.provider,
                "model": phase.model_selection.model,
                "reasoning_effort": phase.model_selection.reasoning_effort,
                "route_kind": phase.model_selection.route_kind,
                "connection_mode": phase.model_selection.connection_mode,
            }
        )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=tuple(
            ProviderRouteConfig(
                provider=provider,
                model=model,
                kind=ModelProviderKind.CODEX_CLI,
            )
            for provider, model in sorted(
                {
                    (phase.model_selection.provider, phase.model_selection.model)
                    for phase in dispatch.phases
                }
            )
        ),
    )
    factory = ObservingFactory()

    def create_adapter() -> DispatchDeliveryAgentAdapter:
        return DispatchDeliveryAgentAdapter(
            dispatch=dispatch,
            definitions=definitions,
            plan_adapter=cast(ExecutionPlanAgentAdapter, Mock()),
            config=config,
            repository_root=repository,
            repository_workspace_root=tmp_path / "sidecar",
            context_resolver=StoredContextResolver(
                FileContextStore(tmp_path / "contexts"), FileArtifactStore(tmp_path / "artifacts")
            ),
            environment={},
            route_adapters=factory,
            route_scope=tuple(
                route
                for route in config.model_routes
                if route.model == dispatch.phases[1].model_selection.model
            ),
        )

    return VerifierFixture(create_adapter, factory, dispatch.task_id, first, second, repository)


@pytest.mark.parametrize("restart", [False, True])
def test_new_delivery_attempt_verifies_new_candidate_without_reusing_old_checkout(
    verifier_fixture: VerifierFixture, restart: bool
) -> None:
    fixture = verifier_fixture
    adapter = fixture.create_adapter()
    for attempt in (1, 2):
        if restart:
            adapter = fixture.create_adapter()
        for role in (AgentRole.QA, AgentRole.REVIEWER):
            adapter.run(fixture.request(role, attempt))

    assert len(fixture.factory.bindings) == 4
    assert len({binding.worktree.path for binding in fixture.factory.bindings}) == 4
    assert [binding.worktree.head_revision for binding in fixture.factory.bindings] == [
        fixture.first,
        fixture.first,
        fixture.second,
        fixture.second,
    ]
    assert all(
        _git(binding.worktree.path, "rev-parse", "HEAD") == binding.worktree.head_revision
        for binding in fixture.factory.bindings
    )
    assert _git(fixture.repository, "status", "--porcelain") == ""


def test_verifiers_reopen_independently_after_only_qa_was_created(
    verifier_fixture: VerifierFixture,
) -> None:
    fixture = verifier_fixture
    fixture.create_adapter().run(fixture.request(AgentRole.QA))
    qa = fixture.factory.bindings[0].worktree.path
    assert not (qa.parent / "reviewer-attempt-01").exists()
    fixture.create_adapter().run(fixture.request(AgentRole.REVIEWER))
    assert fixture.factory.bindings[-1].worktree.head_revision == fixture.first
    fixture.create_adapter().run(fixture.request(AgentRole.QA))
    assert fixture.factory.bindings[-1].worktree.path == qa


def test_foreign_task_is_rejected_before_checkout_or_provider(
    verifier_fixture: VerifierFixture,
) -> None:
    fixture = verifier_fixture
    request = fixture.request(AgentRole.QA).model_copy(update={"task_id": "task_foreign"})
    with pytest.raises(ProductionConfigError, match="does not belong"):
        fixture.create_adapter().run(request)
    assert fixture.factory.bindings == []
    assert not (fixture.repository.parent / "platform" / "worktrees").exists()


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
def test_same_attempt_cannot_change_candidate_or_hide_dirty_evidence(
    verifier_fixture: VerifierFixture, restart: bool, role: AgentRole
) -> None:
    fixture = verifier_fixture
    adapter = fixture.create_adapter()
    adapter.run(fixture.request(role))
    binding = fixture.factory.bindings[0]
    if restart:
        adapter = fixture.create_adapter()
    with pytest.raises(WorktreeRevisionDrift):
        adapter.run(fixture.request(role, candidate=fixture.second))
    assert len(fixture.factory.bindings) == 1
    evidence = binding.worktree.path / "uncommitted.txt"
    evidence.write_text("preserve failure evidence", encoding="utf-8")
    with pytest.raises(DirtyWorktree):
        adapter.run(fixture.request(role))
    adapter.close_clean_worktrees()
    assert evidence.read_text(encoding="utf-8") == "preserve failure evidence"
    assert len(fixture.factory.bindings) == 1
