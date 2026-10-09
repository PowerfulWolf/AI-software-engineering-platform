"""Exact proposal review reads complete frozen rules without constructing a Host or writes."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.manager.baseline_native_rules import build_native_rule_change
from ai_software_engineer.manager.baseline_production import native_rules_at_revision
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.repository_workspace import RepositoryWorkspaceRegistry
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import (
    ConsoleCommandResult,
    InMemoryConsoleOperationStore,
    LocalConsoleAdministration,
    create_console_app,
)
from ai_software_engineer.web_console.models import ProposeExecutionBaselineIntent
from tests.manager.test_execution_baseline import setup
from tests.web_console.test_transport import _Console, _Reader


@pytest.mark.parametrize("changed_source_manifest", [False, True])
def test_exact_rule_review_reads_complete_before_after_and_rejects_unknown_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_source_manifest: bool
) -> None:
    git_root = tmp_path / "git"
    git_root.mkdir()
    fixture = setup(git_root)
    scope = fixture.collector.facts.scope
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        team_id=scope.team_id,
        team_name="Fixture",
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="fixture", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    project = team.project_registry().register(project_id=scope.project_id, name="Fixture")
    workspace = project.repository_registry().register(fixture.repository)
    scope = scope.model_copy(update={"repository_id": workspace.repository_id})
    fixture.collector.facts = fixture.collector.facts.model_copy(update={"scope": scope})
    store = FileExecutionBaselineStore(
        workspace.directory("state") / "execution-baselines" / fixture.worktree.task_id
    )
    fixture.service.store = store
    original = fixture.collector.facts.task.base_ref
    before = native_rules_at_revision(
        fixture.manager, repository_id=scope.repository_id, revision=original
    )
    after = native_rules_at_revision(
        fixture.manager, repository_id=scope.repository_id, revision=fixture.target
    )
    change = build_native_rule_change(
        git=fixture.manager,
        records=store.records,
        scope=scope,
        task_id=fixture.worktree.task_id,
        source_revision=original,
        target_base_ref=fixture.target,
        source_rules=before,
        target_rules=after,
    )
    assert change is not None
    if changed_source_manifest:
        change = change.model_copy(update={"source_native_rules_sha256": "e" * 64})
        change = change.model_copy(
            update={
                "change_sha256": digest(change.model_dump(mode="json", exclude={"change_sha256"}))
            }
        )
    facts = fixture.collector.facts.model_copy(
        update={
            "native_rule_change": change,
            "source_native_rules_sha256": change.source_native_rules_sha256,
            "target_native_rules_sha256": change.target_native_rules_sha256,
        }
    )
    fixture.collector.facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    plan = fixture.service.propose(fixture.target)
    intent = ProposeExecutionBaselineIntent(
        project_id=scope.project_id,
        delivery_id="delivery_" + "a" * 40,
        expected_checkpoint_sha256="1" * 64,
        task_id=fixture.worktree.task_id,
        expected_task_intent_sha256=task_intent_sha256(plan.facts.task),
        expected_task_revision=plan.facts.task_revision,
        expected_work_item_id=plan.facts.work_item_id,
        expected_source_revision=plan.dirty_capture.source_revision,
        target_base_ref=fixture.target,
    )
    operations = InMemoryConsoleOperationStore(scope.team_id)
    now = datetime.now(UTC)
    queued = operations.submit(
        intent=intent, idempotency_key="review-native-rule-exact", requested_at=now
    )
    running = operations.claim_next(at=now)
    assert running is not None
    operations.succeed(
        queued.operation_id,
        expected=running.operation_sha256,
        at=now,
        result=ConsoleCommandResult(
            project_id=scope.project_id,
            delivery_id=intent.delivery_id,
            checkpoint_sha256="1" * 64,
            stage="ENGINEERING_BASELINE_PLAN",
            next_action="审阅完整规范变更。",
            execution_baseline_plan=plan,
        ),
    )
    administration = LocalConsoleAdministration(
        runtime_config=config, config_path=tmp_path / "config.json", environment={}
    )
    monkeypatch.setattr(
        "ai_software_engineer.knowledge.index.KnowledgeIndexWorker.start", lambda _: None
    )
    monkeypatch.setattr(
        TeamHost, "__init__", lambda *_args, **_kwargs: pytest.fail("GET must not construct a Host")
    )
    monkeypatch.setattr(
        RepositoryWorkspaceRegistry,
        "register",
        lambda *_args, **_kwargs: pytest.fail("GET must not register or prepare a repository"),
    )
    saved = {path: path.read_bytes() for path in workspace.root.rglob("*") if path.is_file()}
    app = create_console_app(
        _Console(operations), _Reader(), team_id=scope.team_id, administration=administration
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.get(
            f"/api/v1/operations/{queued.operation_id}/native-rules", params={"path": "README.md"}
        )
        refused = client.get(
            f"/api/v1/operations/{queued.operation_id}/native-rules",
            params={"path": "../runtime.env"},
        )
    if changed_source_manifest:
        assert response.status_code == 409, response.json()
        assert response.json()["error"]["code"] == "NATIVE_RULE_REVIEW_UNAVAILABLE"
    else:
        assert response.status_code == 200, response.json()
        inspection = response.json()
        assert inspection["epoch"]["epoch_sha256"] == change.target.epoch_sha256
        assert inspection["delta"]["path"] == "README.md"
        assert inspection["before_body"] is not None and inspection["after_body"] is not None
        assert "+updated main prerequisite" in inspection["unified_diff"]
    assert refused.status_code == 409
    assert "runtime.env" not in refused.text
    assert saved == {
        path: path.read_bytes() for path in workspace.root.rglob("*") if path.is_file()
    }
