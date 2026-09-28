"""Production Host returns a rejected real Git candidate to Coder, then verifies v2."""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import (
    AgentRole,
    QaCriterionStatus,
    QaReportArtifact,
    QaReportStatus,
)
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_host import TeamHost
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
    _ScriptedDeliveryFactory,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn


@pytest.mark.mysql
def test_rejected_candidate_returns_through_production_queue_and_verifies_new_revision(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n", encoding="utf-8")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    calls: list[tuple[AgentRole, int, str]] = []
    original = _ScriptedDeliveryAdapter.run

    def reject_once(adapter: _ScriptedDeliveryAdapter, request: AgentRequest) -> AgentResult:
        assert _git_output("rev-parse", "HEAD", cwd=adapter._workspace) == request.source_revision
        result = original(adapter, request)
        calls.append((request.role, request.attempt, request.source_revision))
        if request.role is AgentRole.QA and request.attempt == 1:
            artifact = result.artifact
            assert isinstance(artifact, QaReportArtifact)
            content = artifact.content.model_copy(
                update={
                    "status": QaReportStatus.FAIL,
                    "criteria_results": tuple(
                        item.model_copy(update={"status": QaCriterionStatus.FAIL})
                        for item in artifact.content.criteria_results
                    ),
                }
            )
            return result.model_copy(
                update={"artifact": artifact.model_copy(update={"content": content})}
            )
        return result

    monkeypatch.setattr(_ScriptedDeliveryAdapter, "run", reject_once)

    def versioned_greeting(adapter: _ScriptedDeliveryAdapter, request: AgentRequest) -> str:
        del adapter
        return f"hello from the team v{request.attempt}\n"

    # Only this scenario makes every Coder round a different candidate. Verification
    # retries elsewhere may increment execution identity without changing code.
    monkeypatch.setattr(_ScriptedDeliveryAdapter, "_greeting", versioned_greeting)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test Project",
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="fixture", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
        live_model_execution=True,
    )
    host = TeamHost(
        config=config,
        environment={"ASE_MYSQL_DSN": mysql_dsn, "PATH": os.environ.get("PATH", "")},
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    )
    service = host.project_entry()
    started = service.start(
        StartProjectDelivery(repository_root=str(repository), requirement="Change the greeting.")
    )
    finished = service.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="fixture-exact-product-approval",
        )
    )
    assert finished.checkpoint.stage is DeliveryStage.DONE
    assert [(role, attempt) for role, attempt, _ in calls] == [
        (AgentRole.CODER, 1),
        (AgentRole.QA, 1),
        (AgentRole.CODER, 2),
        (AgentRole.QA, 2),
        (AgentRole.REVIEWER, 2),
    ]
    assert calls[1][2] != calls[3][2] == calls[4][2] == finished.checkpoint.candidate_revision
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    assert (repository / "hello.txt").read_text(encoding="utf-8") == "hello\n"
