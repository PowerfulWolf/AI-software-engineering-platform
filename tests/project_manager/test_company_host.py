"""Real preparation/Product wiring; only DB connectivity and model calls are stubbed."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import StructuredModelClient, StructuredModelResult
from ai_software_engineer.company_workspace import CompanyWorkspace
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.project_manager.delivery import (
    DeliveryBackendFailure,
    StartProjectDelivery,
)
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryStage,
    ProjectDeliveryCheckpointNotFound,
)
from ai_software_engineer.project_manager.production_backend import StructuredClientFactory
from ai_software_engineer.project_manager.production_host import OrganizationTeamHost
from tests.project_manager.test_production_backend import _git, _ScriptedStructuredClient


class _ConnectivityStub:
    def __init__(self, dsn: str) -> None:
        assert dsn == "connectivity-only"

    def close(self) -> None:
        pass


class _RecordingFactory(StructuredClientFactory, StructuredModelClient):
    def __init__(self) -> None:
        self.payloads: list[Mapping[str, object]] = []

    def for_project(self, project_root: Path) -> StructuredModelClient:
        assert project_root.is_dir()
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


def _config(root: Path, company_id: str, paths: tuple[str, ...] = ()) -> ProductionConfig:
    return ProductionConfig(
        platform_root=str(root),
        company_id=company_id,
        company_name=company_id,
        company_knowledge_paths=paths,
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )


def test_company_host_scopes_product_catalog_and_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.project_manager.production_host.MySqlTaskRepository",
        _ConnectivityStub,
    )
    monkeypatch.setattr(
        "ai_software_engineer.project_manager.production_host.MySqlPersistentWorkQueue",
        _ConnectivityStub,
    )
    repo = tmp_path / "code"
    repo.mkdir()
    _git("init", cwd=repo)
    (repo / "hello.txt").write_text("hello\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "base", cwd=repo)
    platform = tmp_path / "platform"
    company = CompanyWorkspace.initialize(
        platform, company_id="company_alpha", name="company_alpha"
    )
    rule = company.root / "knowledge" / "workflow.md"
    rule.write_text("ALPHA REVIEW RULE password=do-not-persist\n")
    (company.root / "knowledge" / "unselected.md").write_text("UNSELECTED PRIVATE DATA")
    models = _RecordingFactory()
    config = _config(platform, "company_alpha", ("workflow.md",))
    host = OrganizationTeamHost(
        config=config, environment={"ASE_MYSQL_DSN": "connectivity-only"}, structured_clients=models
    )
    command = StartProjectDelivery(project_root=str(repo), requirement="Update the greeting")
    first = host.project_entry().start(command)
    assert first.checkpoint.stage is DeliveryStage.WAITING_PRODUCT_APPROVAL
    assert first.checkpoint.project_id in str(next((company.root / "projects").iterdir()))
    payload = json.dumps(models.payloads)
    assert "ALPHA REVIEW RULE" in payload
    assert "do-not-persist" not in payload
    assert "UNSELECTED PRIVATE DATA" not in payload
    assert (platform / "organization").is_dir()
    assert not (platform / "projects").exists()
    beta = OrganizationTeamHost(
        config=_config(platform, "company_beta"),
        environment={"ASE_MYSQL_DSN": "connectivity-only"},
        structured_clients=_RecordingFactory(),
    )
    second = beta.project_entry().start(command)
    assert first.checkpoint.project_id != second.checkpoint.project_id
    assert first.checkpoint.delivery_id != second.checkpoint.delivery_id
    with pytest.raises(ProjectDeliveryCheckpointNotFound):
        beta.project_entry().status(first.checkpoint.delivery_id)
    # No extra model call for same company replay.
    replay = host.project_entry().start(command)
    assert replay.checkpoint == first.checkpoint
    assert len(models.payloads) == 1
    rule.write_text("CHANGED COMPANY POLICY")
    with pytest.raises(DeliveryBackendFailure):
        host.project_entry().status(first.checkpoint.delivery_id)
    reopened = OrganizationTeamHost(
        config=config, environment={"ASE_MYSQL_DSN": "connectivity-only"}, structured_clients=models
    )
    with pytest.raises(DeliveryBackendFailure):
        reopened.project_entry().status(first.checkpoint.delivery_id)
    assert len(models.payloads) == 1
    assert (repo / "hello.txt").read_text() == "hello\n"


@pytest.mark.parametrize(
    "field,value",
    [
        ("company_id", "../other"),
        ("company_name", ""),
        ("company_knowledge_paths", ["../other/rules.md"]),
        ("company_knowledge_paths", ["a.md", "a.md"]),
    ],
)
def test_company_config_rejects_invalid_selection(
    tmp_path: Path, field: str, value: object
) -> None:
    payload: dict[str, object] = dict(_config(tmp_path, "company_alpha").to_wire())
    payload[field] = value
    with pytest.raises(ValueError):
        ProductionConfig.model_validate(payload)
