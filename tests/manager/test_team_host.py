"""Real preparation/Product wiring; only DB connectivity and model calls are stubbed."""

import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ai_software_engineer.agents import StructuredModelClient, StructuredModelResult
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import TeamRole
from ai_software_engineer.knowledge_documents import (
    ProjectKnowledgeDocumentStore,
    TeamKnowledgeDocumentStore,
)
from ai_software_engineer.knowledge_selection import (
    ProjectKnowledgeSelectionStore,
    TeamKnowledgeSelectionStore,
)
from ai_software_engineer.manager.delivery import (
    DeliveryBackendFailure,
    ReplyToProduct,
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    ProjectDeliveryCheckpointNotFound,
)
from ai_software_engineer.manager.production_backend import StructuredClientFactory
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.errors import RequirementSourceRevisionDrift
from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.multi_directory.service import CreateRequirement
from ai_software_engineer.spec_documents import (
    CreateSpecDocument,
    ProjectSpecDocumentStore,
    TeamSpecDocumentStore,
)
from ai_software_engineer.team_workspace import TeamWorkspace
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
    host = TeamHost(
        config=config, environment={"ASE_MYSQL_DSN": "connectivity-only"}, structured_clients=models
    )
    command = StartProjectDelivery(repository_root=str(repo), requirement="Update the greeting")
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
    with pytest.raises(DeliveryBackendFailure):
        host.project_entry().status(first.checkpoint.delivery_id)
    reopened = TeamHost(
        config=config, environment={"ASE_MYSQL_DSN": "connectivity-only"}, structured_clients=models
    )
    with pytest.raises(DeliveryBackendFailure):
        reopened.project_entry().status(first.checkpoint.delivery_id)
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
