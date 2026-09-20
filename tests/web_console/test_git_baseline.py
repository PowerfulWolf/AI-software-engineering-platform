"""Exercise Requirement intake through the real production preparation and Console seams."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.agents import StructuredModelClient
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import TeamRole
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.production_backend import (
    ProductionProjectDeliveryBackend,
)
from ai_software_engineer.multi_directory.models import (
    JointCheckpoint,
    JointDeliveryResult,
    JointStage,
)
from ai_software_engineer.multi_directory.production import ProductionJointBackend
from ai_software_engineer.multi_directory.scope import discover_scope
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.runtime_workspace import TeamWorkforceWorkspace
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import (
    ConsoleOperationStatus,
    ContinueDeliveryIntent,
    CreateRequirementIntent,
    FileConsoleOperationStore,
    ManagerConsoleAdapter,
    ProjectConsole,
)
from ai_software_engineer.web_console.manager import TeamConsoleHost
from tests.manager.test_directory_scope import repository as committed_repository
from tests.manager.test_preparation import hard_rule
from tests.manager.test_production_backend import _git


class _NoModels:
    def for_project(
        self, repository_root: Path, role: TeamRole = TeamRole.PRODUCT
    ) -> StructuredModelClient:
        pytest.fail("Requirement preparation must not invoke a model")


def _console(tmp_path: Path) -> tuple[ProjectConsole, JointDeliveryService]:
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(provider="codex", model="test", kind=ModelProviderKind.CODEX_CLI),
        ),
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    project = team.project_registry().register(project_id="project_test", name="Test")
    # Preparation never connects to MySQL; execution is intentionally unavailable.
    environment = {"ASE_MYSQL_DSN": "mysql+pymysql://unused@127.0.0.1/unused_test"}
    native = ProductionProjectDeliveryBackend(
        config=config,
        environment=environment,
        organization=TeamWorkforceWorkspace.from_team(team),
        registry=project.repository_registry(),
        platform_rules=(hard_rule(),),
    )
    backend = ProductionJointBackend(
        native=native,
        factory=lambda *_args: pytest.fail("must not start delivery"),
        clients=_NoModels(),
        team=team,
        project=project,
        environment=environment,
    )
    entry = JointDeliveryService(backend=backend, team=team, project=project)

    class Host:
        def requirement_entry(self, project_id: str | None = None) -> JointDeliveryService:
            assert project_id == "project_test"
            return entry

        def resume_delivery(
            self, command: ResumeProjectDelivery, *, project_id: str | None = None
        ) -> JointDeliveryResult:
            assert project_id == "project_test"
            return entry.resume(command)

    return (
        ProjectConsole(
            store=FileConsoleOperationStore(tmp_path / "operations", team_id=team.manifest.team_id),
            executor=ManagerConsoleAdapter(cast(TeamConsoleHost, Host())),
        ),
        entry,
    )


@pytest.mark.parametrize("initialize_git", [False, True])
def test_missing_git_baseline_has_actionable_persisted_error(
    tmp_path: Path, initialize_git: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "codex-quota-monitor"
    repository.mkdir()
    if initialize_git:
        _git("init", cwd=repository)
    console, entry = _console(tmp_path)
    monkeypatch.setattr(entry.backend, "prepare", lambda *_: pytest.fail("must validate first"))
    monkeypatch.setattr(entry.backend, "reconcile", lambda *_: pytest.fail("must validate first"))
    queued = console.submit(
        CreateRequirementIntent(
            project_id="project_test",
            name="账号筛选页面优化",
            repository_roots=(str(repository),),
        ),
        idempotency_key="missing-git-baseline",
    )

    result = console.run_once()

    assert result is not None
    assert result.status is ConsoleOperationStatus.FAILED
    assert result.error_code == "GIT_BASELINE_REQUIRED", result.error_summary
    assert result.error_summary is not None
    assert "codex-quota-monitor" in result.error_summary
    assert "提交" in result.error_summary
    assert "重新创建需求" in result.error_summary
    expected_reason = "没有可用的提交基线" if initialize_git else "未受 Git 管理"
    assert expected_reason in result.error_summary
    assert not tuple(entry.journal.root.glob("delivery_multi_*"))
    assert (repository / ".git").exists() is initialize_git
    assert console.get(queued.operation_id) == result
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/console-operation.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(result.to_wire())


def test_mixed_selection_rejects_before_preparing_any_repository(tmp_path: Path) -> None:
    valid = committed_repository(tmp_path / "a-valid")
    invalid = tmp_path / "z-invalid"
    invalid.mkdir()
    console, entry = _console(tmp_path)
    console.submit(
        CreateRequirementIntent(
            project_id="project_test", name="Mixed", repository_roots=(str(valid), str(invalid))
        ),
        idempotency_key="mixed-git-baselines",
    )

    result = console.run_once()

    assert result is not None
    assert result.error_code == "GIT_BASELINE_REQUIRED"
    assert result.error_summary is not None and "z-invalid" in result.error_summary
    assert not tuple(entry.journal.root.glob("delivery_multi_*"))
    assert not tuple(entry.project.root.glob("repositories/*/policy/project-preparation-*.json"))


def test_long_directory_keeps_the_actionable_error(tmp_path: Path) -> None:
    repository = tmp_path
    for index in range(5):
        repository /= f"directory-{index}-" + "x" * 90
    repository /= "codex-quota-monitor"
    repository.mkdir(parents=True)
    console, _ = _console(tmp_path)
    console.submit(
        CreateRequirementIntent(
            project_id="project_test", name="Long path", repository_roots=(str(repository),)
        ),
        idempotency_key="long-git-baseline",
    )

    result = console.run_once()

    assert result is not None and result.error_code == "GIT_BASELINE_REQUIRED"
    assert result.error_summary is not None
    assert len(result.error_summary) <= 500
    assert "未受 Git 管理" in result.error_summary
    assert "codex-quota-monitor" in result.error_summary


def test_unrelated_long_error_retains_safe_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = committed_repository(tmp_path / "code")
    console, entry = _console(tmp_path)

    def fail_prepare(*_args: object) -> None:
        raise ValueError("private diagnostic " * 50)

    monkeypatch.setattr(entry.backend, "prepare", fail_prepare)
    console.submit(
        CreateRequirementIntent(
            project_id="project_test", name="Unrelated", repository_roots=(str(repository),)
        ),
        idempotency_key="unrelated-git-error",
    )

    result = console.run_once()

    assert result is not None and result.error_code == "COMMAND_REJECTED"
    assert result.error_summary == (
        "Manager rejected the operation; inspect current delivery facts."
    )


@pytest.mark.parametrize("select_module", [False, True])
def test_committed_git_directory_still_prepares_without_models(
    tmp_path: Path, select_module: bool
) -> None:
    repository = committed_repository(tmp_path / "code")
    selected = repository
    if select_module:
        selected = repository / "module"
        selected.mkdir()
    console, _ = _console(tmp_path)
    console.submit(
        CreateRequirementIntent(
            project_id="project_test", name="Valid", repository_roots=(str(selected),)
        ),
        idempotency_key="valid-git-baseline",
    )

    result = console.run_once()

    assert result is not None
    assert result.status is ConsoleOperationStatus.SUCCEEDED, result.error_summary
    assert result.result is not None and result.result.stage == "READY_FOR_DISCUSSION"


@pytest.mark.parametrize("fix_source", [False, True])
def test_historical_preparing_checkpoint_is_preserved_with_recovery_guidance(
    tmp_path: Path, fix_source: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "code"
    repository.mkdir()
    console, entry = _console(tmp_path)
    initial = JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_" + "a" * 40,
            "team_id": entry.team.manifest.team_id,
            "team_manifest_sha256": entry.team.manifest.manifest_sha256,
            "project_id": entry.project.manifest.project_id,
            "project_manifest_sha256": entry.project.manifest.manifest_sha256,
            "sequence": 1,
            "stage": JointStage.PREPARING,
            "scope": discover_scope((str(repository),)),
            "title": "账号筛选页面优化",
            "submitted_at": datetime.now(UTC),
            "next_action": "Prepare every selected directory.",
        }
    )
    entry.journal.append(initial, expected=None)
    history_path = entry.journal.directory(initial.delivery_id) / "000001.json"
    before = history_path.read_bytes()
    if fix_source:
        _git("init", cwd=repository)
        _git("commit", "--allow-empty", "-m", "initial", cwd=repository)
    console.submit(
        ContinueDeliveryIntent(
            project_id="project_test",
            delivery_id=initial.delivery_id,
            expected_checkpoint_sha256=initial.checkpoint_sha256,
        ),
        idempotency_key="legacy-git-baseline",
    )

    with monkeypatch.context() as guard:
        guard.setattr(entry.backend, "prepare", lambda *_: pytest.fail("must validate first"))
        guard.setattr(entry.backend, "reconcile", lambda *_: pytest.fail("must validate first"))
        assert entry.status(initial.delivery_id).checkpoint == initial
        result = console.run_once()

    assert result is not None
    assert result.error_code == "GIT_BASELINE_REQUIRED", result.error_summary
    assert result.error_summary is not None and "重新创建需求" in result.error_summary
    if fix_source:
        assert "未记录 Git 提交基线" in result.error_summary
        console.submit(
            CreateRequirementIntent(
                project_id="project_test", name=initial.title, repository_roots=(str(repository),)
            ),
            idempotency_key="recreated-git-baseline",
        )
        recovered = console.run_once()
        assert recovered is not None
        assert recovered.status is ConsoleOperationStatus.SUCCEEDED, recovered.error_summary
        assert recovered.result is not None
        assert recovered.result.stage == "READY_FOR_DISCUSSION"
        assert recovered.result.delivery_id != initial.delivery_id
    assert history_path.read_bytes() == before
    assert entry.journal.history(initial.delivery_id) == (initial,)
