"""Real preparation/Product wiring; only DB connectivity and model calls are stubbed."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import StructuredModelClient, StructuredModelResult
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
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
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    ProjectDeliveryCheckpointNotFound,
)
from ai_software_engineer.manager.production_backend import StructuredClientFactory
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.manager.test_production_backend import _git, _ScriptedStructuredClient


class _ConnectivityStub:
    def __init__(self, dsn: str) -> None:
        assert dsn == "connectivity-only"

    def close(self) -> None:
        pass


class _RecordingFactory(StructuredClientFactory, StructuredModelClient):
    def __init__(self) -> None:
        self.payloads: list[Mapping[str, object]] = []

    def for_project(self, repository_root: Path) -> StructuredModelClient:
        assert repository_root.is_dir()
        return self

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
    ) -> StructuredModelResult:
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
