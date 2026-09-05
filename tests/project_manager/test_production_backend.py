"""Production Team Host composition tests with an offline structured provider."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

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
    ModelProviderKind,
    ProductionConfig,
    ProviderRouteConfig,
)
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
)
from ai_software_engineer.project_manager.delivery import (
    ApproveProductSpec,
    StartProjectDelivery,
)
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryStage,
)
from ai_software_engineer.project_manager.production_backend import StructuredClientFactory
from ai_software_engineer.project_manager.production_delivery import (
    DeliveryRouteAdapterFactory,
)
from ai_software_engineer.project_manager.production_host import OrganizationTeamHost
from ai_software_engineer.role_workspace import RoleWorktreeBinding


class _ScriptedStructuredClient(StructuredModelClient):
    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
    ) -> StructuredModelResult:
        del instructions, input_payload, timeout_seconds
        properties = output_schema["properties"]
        assert isinstance(properties, Mapping)
        if "action" in properties:
            payload: Mapping[str, object] = {
                "action": "ready",
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


class _ScriptedClientFactory(StructuredClientFactory):
    def for_project(self, project_root: Path) -> StructuredModelClient:
        assert project_root.is_dir()
        return _ScriptedStructuredClient()


class _ScriptedDeliveryAdapter(AgentAdapter):
    def __init__(self, definition: AgentDefinition, workspace: Path) -> None:
        self._definition = definition
        self._workspace = workspace

    def run(self, request: AgentRequest) -> AgentResult:
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
        if request.role is AgentRole.CODER:
            (self._workspace / "hello.txt").write_text("hello from the team\n", encoding="utf-8")
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
            assert (self._workspace / "hello.txt").read_text(encoding="utf-8") == (
                "hello from the team\n"
            )
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
            assert (self._workspace / "hello.txt").read_text(encoding="utf-8") == (
                "hello from the team\n"
            )
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


@pytest.mark.mysql
def test_host_completes_isolated_scripted_delivery_without_polluting_project(
    tmp_path: Path,
    mysql_dsn: str,
) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "hello.txt").write_text("hello\n", encoding="utf-8")
    _git("init", "-b", "main", cwd=project)
    _git("add", "hello.txt", cwd=project)
    _git("commit", "-m", "initial", cwd=project)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex",
                model="gpt-5.5",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
        live_model_execution=True,
    )
    host = OrganizationTeamHost(
        config=config,
        environment={"ASE_MYSQL_DSN": mysql_dsn, "PATH": os.environ.get("PATH", "")},
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    )
    service = host.project_entry()
    started = service.start(
        StartProjectDelivery(
            project_root=str(project),
            requirement="Change the greeting.",
        )
    )
    assert started.checkpoint.stage is DeliveryStage.WAITING_PRODUCT_APPROVAL
    approved = service.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="test-approval",
        )
    )

    assert approved.checkpoint.stage is DeliveryStage.DONE
    assert approved.checkpoint.dispatch_commit_id is not None
    assert approved.checkpoint.task_id is not None
    assert approved.checkpoint.candidate_revision is not None
    assert approved.delivery is not None
    assert (project / "hello.txt").read_text(encoding="utf-8") == "hello\n"
    candidate_content = _git_output(
        "show",
        f"{approved.checkpoint.candidate_revision}:hello.txt",
        cwd=project,
    )
    assert candidate_content == "hello from the team"
    assert not (project / ".ase").exists()
