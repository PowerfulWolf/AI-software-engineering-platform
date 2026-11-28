"""Production Team Host composition tests with an offline structured provider."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Never, cast

import pytest

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    StoredContextResolver,
    StructuredModelClient,
    StructuredModelResult,
)
from ai_software_engineer.config import (
    ProductionConfig,
    ProductionConfigError,
    ProviderRouteConfig,
)
from ai_software_engineer.design import DesignerOutputRejected
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentProducer,
    AgentRole,
    Artifact,
    ArtifactIntegrity,
    ChangedFile,
    ChangeType,
    ImplementationAcceptanceMapping,
    ImplementationReportArtifact,
    ImplementationReportContent,
    QaCriterionResult,
    QaCriterionStatus,
    QaReportArtifact,
    QaReportContent,
    QaReportStatus,
    ReviewDimension,
    ReviewReportArtifact,
    ReviewReportContent,
    ReviewVerdict,
    TeamRole,
)
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy
from ai_software_engineer.manager import production_backend
from ai_software_engineer.manager.delivery import (
    DeliveryBackendFailure,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.dispatch import DispatchStoreUnavailable
from ai_software_engineer.manager.production_backend import (
    ConfiguredStructuredClientFactory,
    ProductionProjectDeliveryBackend,
    StructuredClientFactory,
)
from ai_software_engineer.manager.production_delivery import (
    DeliveryRouteAdapterFactory,
)
from ai_software_engineer.planning import PlannerRunOutcome
from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.role_workspace import RoleWorktreeBinding


class _ScriptedStructuredClient(StructuredModelClient):
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
        del instructions, timeout_seconds
        if output_schema.get("title") == "KnowledgeIntent":
            return StructuredModelResult(payload={"queries": []}, duration_ms=0)
        properties = output_schema["properties"]
        assert isinstance(properties, Mapping)
        if "action" in properties:
            product_request = input_payload.get("project_request", {})
            title = (
                product_request.get("title", "greeting")
                if isinstance(product_request, Mapping)
                else "greeting"
            )
            slug = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-") or "greeting"
            payload: Mapping[str, object] = {
                "action": "ready",
                "branch_name": f"ai/feature/{slug}",
                "summary": "Change the greeting",
                "goals": ["The greeting is updated."],
                "requirements": [
                    {
                        "statement": "Update hello.txt.",
                        "priority": "MUST",
                        "rationale": "Requested by the user.",
                        "acceptance": [
                            {
                                "description": "hello.txt contains the new greeting.",
                                "verification": "Read hello.txt.",
                            }
                        ],
                    }
                ],
            }
        elif "components" in properties:
            payload = {
                "summary": "Update the greeting file.",
                "components": [
                    {
                        "key": "greeting",
                        "name": "Greeting",
                        "responsibility": "Store the greeting.",
                        "affected_paths": ["hello.txt"],
                    }
                ],
                "requirement_mappings": [
                    {
                        "requirement_id": "req_001",
                        "component_keys": ["greeting"],
                        "approach": "Edit the text file.",
                    }
                ],
                "acceptance_mappings": [
                    {
                        "acceptance_criterion_id": "ac_001_001",
                        "verification_strategy": "Read and compare the file.",
                        "test_levels": ["acceptance"],
                    }
                ],
                "implementation_steps": [
                    {
                        "key": "edit",
                        "description": "Edit hello.txt.",
                        "component_keys": ["greeting"],
                        "verification": "Read hello.txt.",
                    }
                ],
            }
        else:
            payload = {
                "phases": [
                    {
                        "role": "coder",
                        "objective": "Implement the approved greeting change.",
                        "required_capabilities": ["implementation"],
                        "risk": "normal",
                        "minimum_brain_tier": "standard",
                        "checkpoints": ["candidate commit"],
                    },
                    {
                        "role": "qa",
                        "objective": "Verify every acceptance criterion.",
                        "required_capabilities": ["testing"],
                        "risk": "normal",
                        "minimum_brain_tier": "standard",
                        "checkpoints": ["qa report"],
                    },
                    {
                        "role": "reviewer",
                        "objective": "Independently review the candidate.",
                        "required_capabilities": ["review"],
                        "risk": "normal",
                        "minimum_brain_tier": "standard",
                        "checkpoints": ["review report"],
                    },
                ]
            }
        return StructuredModelResult(payload=payload, duration_ms=1)


def test_planner_retry_uses_a_new_run_identity_after_a_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed Planner receipt cannot be replayed with a changed checkpoint input."""

    delivery_id = "delivery_planner_retry"
    base_run_id = f"run_planner_{delivery_id.removeprefix('delivery_')}"
    prior = SimpleNamespace(outcome=PlannerRunOutcome.FAILED)
    captured: list[_Command] = []
    facts = SimpleNamespace(
        design=SimpleNamespace(
            get_run=lambda run_id: SimpleNamespace(
                technical_design=SimpleNamespace(),
                planning_authorization=SimpleNamespace(),
                next_request_revision=SimpleNamespace(),
            ),
            get_checkpoint=lambda run_id: SimpleNamespace(run_id=run_id),
        ),
        product=SimpleNamespace(
            current_request_revision=lambda request_id: SimpleNamespace(),
            find_product_spec=lambda spec_id: SimpleNamespace(),
            find_approval=lambda approval_id: SimpleNamespace(),
        ),
        planning=SimpleNamespace(find_run=lambda run_id: prior if run_id == base_run_id else None),
        workspace=SimpleNamespace(repository_root=tmp_path),
    )

    class _PlannerStage:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def produce(self, command: _Command) -> _Command:
            captured.append(command)
            return command

    class _Command:
        def __init__(self, *, run_id: str, **values: object) -> None:
            del values
            self.run_id = run_id

    monkeypatch.setattr(production_backend, "PlannerStageService", _PlannerStage)
    monkeypatch.setattr(production_backend, "ProduceExecutionPlanCommand", _Command)
    backend = object.__new__(ProductionProjectDeliveryBackend)
    monkeypatch.setattr(backend, "_facts_for_checkpoint", lambda checkpoint: facts)
    backend._structured_clients = SimpleNamespace(for_project=lambda *args: object())
    backend._trusted_plan_projection = False
    backend._config = cast(
        ProductionConfig, SimpleNamespace(execution_retry_policy=ExecutionRetryPolicy())
    )
    checkpoint = ProjectDeliveryCheckpoint.create(
        delivery_id=delivery_id,
        repository_id="repository_planner_retry",
        repository_root=str(tmp_path),
        previous_checkpoint_sha256="1" * 64,
        stage=DeliveryStage.PLANNING,
        stage_attempts=DeliveryStageAttempts(),
        next_action=DeliveryNextAction.RUN_PLANNER,
        product_spec_id="product_spec",
        product_spec_sha256="2" * 64,
        approval_id="approval",
        approval_sha256="3" * 64,
        checkpointed_at=datetime.now(UTC),
        sequence=9,
    )

    backend.run_planner(checkpoint)

    assert len(captured) == 1
    command = captured[0]
    assert command.run_id != base_run_id


def test_task_source_revision_reads_only_the_exact_task_repository_and_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Historical Git-worktree preparations can recover from the successor Task base."""

    class _TaskStore:
        def __init__(self, dsn: str) -> None:
            assert dsn == "mysql://test"

        def get(self, task_id: str) -> object:
            assert task_id == "task_successor"
            return SimpleNamespace(
                repository=str(tmp_path / "repository"),
                base_ref="a" * 40,
            )

        def close(self) -> None:
            pass

    monkeypatch.setattr(production_backend, "MySqlTaskRepository", _TaskStore)
    backend = object.__new__(ProductionProjectDeliveryBackend)
    backend._dsn = "mysql://test"

    assert (
        backend.task_source_revision("task_successor", repository_root=str(tmp_path / "repository"))
        == "a" * 40
    )

    with pytest.raises(ValueError, match="another repository"):
        backend.task_source_revision("task_successor", repository_root=str(tmp_path / "other"))


class _ScriptedClientFactory(StructuredClientFactory):
    def for_project(
        self,
        repository_root: Path,
        role: TeamRole = TeamRole.PRODUCT,
    ) -> StructuredModelClient:
        del role
        assert repository_root.is_dir()
        return _ScriptedStructuredClient()


class _ScriptedDeliveryAdapter(AgentAdapter):
    def __init__(self, definition: AgentDefinition, workspace: Path) -> None:
        self._definition = definition
        self._workspace = workspace

    def _greeting(self, request: AgentRequest) -> str:
        del request
        return "hello from the team\n"

    def run(self, request: AgentRequest) -> AgentResult:
        assert (
            self._definition.timeout_seconds
            == {
                AgentRole.CODER: 1_800,
                AgentRole.QA: 1_200,
                AgentRole.REVIEWER: 1_200,
            }[request.role]
        )
        now = datetime.now(UTC)
        identity = request.run_id.removeprefix("run_")
        producer = AgentProducer(
            role=request.role,
            agent_id=self._definition.id,
            agent_version=self._definition.version,
            run_id=request.run_id,
        )
        integrity = ArtifactIntegrity(sha256="0" * 64, validated=False)
        artifact: Artifact
        greeting = self._greeting(request)
        if request.role is AgentRole.CODER:
            (self._workspace / "hello.txt").write_text(greeting, encoding="utf-8")
            _git("add", "hello.txt", cwd=self._workspace)
            _git("commit", "-m", "Update greeting", cwd=self._workspace)
            candidate = _git_output("rev-parse", "HEAD", cwd=self._workspace)
            artifact = ImplementationReportArtifact(
                artifact_id=f"art_impl_{identity}",
                task_id=request.task_id,
                schema_version="v0.1",
                producer=producer,
                source_revision=candidate,
                context_manifest_id=request.context_manifest_id,
                created_at=now,
                parent_artifact_ids=request.input_artifact_ids,
                evidence=(),
                content=ImplementationReportContent(
                    commit_sha=candidate,
                    changed_files=(
                        ChangedFile(
                            path="hello.txt",
                            change=ChangeType.MODIFIED,
                            lines_added=1,
                            lines_deleted=1,
                        ),
                    ),
                    acceptance_mapping=(
                        ImplementationAcceptanceMapping(
                            criterion_id="ac_001_001",
                            implementation="Updated the greeting file.",
                            tests=(),
                        ),
                    ),
                    tests_run=(),
                    known_risks=(),
                ),
                integrity=integrity,
            )
        elif request.role is AgentRole.QA:
            assert (self._workspace / "hello.txt").read_text(encoding="utf-8") == greeting
            artifact = QaReportArtifact(
                artifact_id=f"art_qa_{identity}",
                task_id=request.task_id,
                schema_version="v0.1",
                producer=producer,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                created_at=now,
                parent_artifact_ids=(request.input_artifact_ids[-1],),
                evidence=(),
                content=QaReportContent(
                    status=QaReportStatus.PASS,
                    criteria_results=(
                        QaCriterionResult(
                            criterion_id="ac_001_001",
                            status=QaCriterionStatus.PASS,
                            evidence_ids=(),
                        ),
                    ),
                    tests_run=(),
                    findings=(),
                    environment={"provider": "scripted"},
                ),
                integrity=integrity,
            )
        else:
            assert request.role is AgentRole.REVIEWER
            assert (self._workspace / "hello.txt").read_text(encoding="utf-8") == greeting
            artifact = ReviewReportArtifact(
                artifact_id=f"art_review_{identity}",
                task_id=request.task_id,
                schema_version="v0.1",
                producer=producer,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                created_at=now,
                parent_artifact_ids=(request.input_artifact_ids[-1],),
                evidence=(),
                content=ReviewReportContent(
                    verdict=ReviewVerdict.APPROVE,
                    findings=(),
                    checked_dimensions=(
                        ReviewDimension.CORRECTNESS,
                        ReviewDimension.ACCEPTANCE,
                    ),
                    evidence=(),
                    summary="The candidate satisfies the approved requirement.",
                ),
                integrity=integrity,
            )
        artifact = artifact.model_copy(
            update={"supersedes": (request.expected_supersedes_by_kind or {}).get(artifact.kind)}
        )
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=artifact,
            duration_ms=1,
        )


class _ScriptedDeliveryFactory(DeliveryRouteAdapterFactory):
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
        return _ScriptedDeliveryAdapter(definition, binding.worktree.path)


def test_upstream_codex_factory_receives_local_proxy_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[object] = []

    def make_client(**kwargs: object) -> StructuredModelClient:
        captured.append(kwargs["proxy_base_url"])
        return _ScriptedStructuredClient()

    monkeypatch.setattr(production_backend, "CodexCliStructuredModelClient", make_client)
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "live_model_execution": True,
            "codex_cli_proxy_base_url": "http://127.0.0.1:8317/v1",
            "model_routes": [{"provider": "codex", "model": "gpt-test", "kind": "codex_cli"}],
        }
    )

    assert ConfiguredStructuredClientFactory(config, {}).for_project(tmp_path) is not None
    assert captured == ["http://127.0.0.1:8317/v1"]


def test_upstream_codex_proxy_managed_key_requires_runtime_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[object] = []

    def make_client(**kwargs: object) -> StructuredModelClient:
        captured.append(kwargs["proxy_api_key_env"])
        return _ScriptedStructuredClient()

    monkeypatch.setattr(production_backend, "CodexCliStructuredModelClient", make_client)
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "live_model_execution": True,
            "codex_cli_proxy_base_url": "http://127.0.0.1:8317/v1",
            "codex_cli_proxy_api_key_env": "ASE_CODEX_PROXY_API_KEY",
            "model_routes": [{"provider": "codex", "model": "gpt-test", "kind": "codex_cli"}],
        }
    )
    with pytest.raises(ProductionConfigError, match="ASE_CODEX_PROXY_API_KEY"):
        ConfiguredStructuredClientFactory(config, {}).for_project(tmp_path)
    assert (
        ConfiguredStructuredClientFactory(
            config, {"ASE_CODEX_PROXY_API_KEY": "test-proxy-secret"}
        ).for_project(tmp_path)
        is not None
    )
    assert captured == ["ASE_CODEX_PROXY_API_KEY"]


def test_upstream_direct_route_does_not_require_or_forward_proxy_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[dict[str, object]] = []

    def make_client(**kwargs: object) -> StructuredModelClient:
        captured.append(kwargs)
        return _ScriptedStructuredClient()

    monkeypatch.setattr(production_backend, "CodexCliStructuredModelClient", make_client)
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "live_model_execution": True,
            "codex_cli_proxy_base_url": "http://127.0.0.1:8317/v1",
            "codex_cli_proxy_api_key_env": "ASE_CODEX_PROXY_API_KEY",
            "model_routes": [
                {
                    "provider": "codex",
                    "model": "gpt-test",
                    "kind": "codex_cli",
                    "connection_mode": "direct",
                }
            ],
        }
    )
    ConfiguredStructuredClientFactory(config, {}).for_project(tmp_path)
    assert captured[0]["proxy_base_url"] is None
    assert captured[0]["proxy_api_key_env"] is None


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (AgentRole.CODER, 1_800),
        (AgentRole.QA, 1_200),
        (AgentRole.REVIEWER, 1_200),
    ],
)
def test_production_delivery_timeout_is_bounded_by_role(role: AgentRole, expected: int) -> None:
    assert production_backend._delivery_timeout_seconds(role) == expected


def test_production_delivery_timeout_rejects_unsupported_role() -> None:
    with pytest.raises(ValueError, match="unsupported production delivery role: orchestrator"):
        production_backend._delivery_timeout_seconds(AgentRole.ORCHESTRATOR)


def test_mysql_dispatch_unavailable_is_classified_as_retryable() -> None:
    def fail() -> Never:
        raise DispatchStoreUnavailable("private MySQL details")

    with pytest.raises(DeliveryBackendFailure) as caught:
        production_backend.ProductionProjectDeliveryBackend._guard("Dispatch", fail)

    assert caught.value.code is DeliveryFailureCode.RESOURCE_UNAVAILABLE
    assert caught.value.safe_summary == "Dispatch is temporarily unavailable"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "TechnicalDesign affected paths must be canonical repository-relative paths",
            "技术设计的文件路径必须是规范的仓库相对路径。",
        ),
        (
            "TechnicalDesign lineage or requirement/acceptance coverage is invalid",
            "技术设计的来源链、需求或验收条件覆盖不正确。",
        ),
        (
            "private provider response api_key=do-not-leak",
            "技术设计输出未通过契约校验，请检查设计及失败记录。",  # noqa: RUF001
        ),
    ],
)
def test_designer_rejection_exposes_only_safe_contract_diagnostics(
    message: str,
    expected: str,
) -> None:
    def fail() -> Never:
        raise DesignerOutputRejected(message)

    with pytest.raises(DeliveryBackendFailure) as caught:
        production_backend.ProductionProjectDeliveryBackend._guard("Designer", fail)

    assert caught.value.code is DeliveryFailureCode.INVARIANT_VIOLATION
    assert caught.value.safe_summary == (
        f"技术设计已安全停止（DesignerOutputRejected）：{expected}"  # noqa: RUF001
    )
    assert "do-not-leak" not in caught.value.safe_summary


@pytest.fixture
def mysql_dsn() -> str:
    value = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not value:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    return value


def _git(*arguments: str, cwd: Path) -> None:
    subprocess.run(
        ("git", *arguments),
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "PATH": os.environ.get("PATH", os.defpath),
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_AUTHOR_NAME": "ASE Test",
            "GIT_AUTHOR_EMAIL": "ase@example.test",
            "GIT_COMMITTER_NAME": "ASE Test",
            "GIT_COMMITTER_EMAIL": "ase@example.test",
        },
    )


def _git_output(*arguments: str, cwd: Path) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", os.defpath),
            "LANG": "C",
            "LC_ALL": "C",
        },
    )
    return completed.stdout.strip()


def test_swift_profile_adds_only_restricted_verification_commands(tmp_path: Path) -> None:
    project = tmp_path / "swift"
    project.mkdir()
    (project / "Package.swift").write_text("// swift-tools-version: 6.0\n", encoding="utf-8")
    profile = RepositoryProfile.discover(project)

    commands = production_backend._task_commands(profile)

    assert "swift test --disable-automatic-resolution --skip-update" in commands
    assert "swift build --disable-automatic-resolution --skip-update" in commands
    assert "swift" not in commands
    assert "xcodebuild" not in commands
    assert "bash" not in commands
    assert "open" not in commands
