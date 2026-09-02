"""Project Manager prepare_project Skill orchestration tests."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.project_manager.baseline import (
    FileProjectBaselineCompilationStore,
    ProjectBaselineCompilation,
    ProjectSpecConflict,
)
from ai_software_engineer.project_manager.preparation import (
    PrepareProjectRequest,
    PrepareProjectStatus,
    ProductContextNotReady,
    ProjectBaselineRecordError,
    ProjectManagerSkillService,
    ProjectPreparationDrift,
)
from ai_software_engineer.project_manager.stages import ProjectStage, StageAdvanceRequest
from ai_software_engineer.project_manager.store import (
    FileProjectPreparationStore,
    ProjectPreparationCorruption,
)
from ai_software_engineer.project_profile import ProjectLanguage, ProjectProfile
from ai_software_engineer.project_workspace import ProjectWorkspace, ProjectWorkspaceRegistry
from ai_software_engineer.runtime_workspace import (
    OrganizationWorkspace,
    RuntimeWorkspaceConflict,
)
from ai_software_engineer.spec_compiler import SpecRule, SpecRuleLayer

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


class NoProjectRules:
    """Keep opaque native documents out of automatic semantic interpretation."""

    def rules_for(self, profile: ProjectProfile) -> Sequence[SpecRule]:
        del profile
        return ()


class ConflictingProjectRules:
    """Produce one explicit project rule backed by the discovered README digest."""

    def rules_for(self, profile: ProjectProfile) -> Sequence[SpecRule]:
        source = next(
            source for source in profile.native_rules if source.relative_path == "README.md"
        )
        return (
            SpecRule(
                id="rule_project_self_approval_001",
                field="safety.self_approval",
                value=True,
                layer=SpecRuleLayer.PROJECT,
                priority=20,
                source_uri=source.uri,
                source_sha256=source.sha256,
                rationale="The fixture rule intentionally conflicts with hard safety.",
            ),
        )


class MismatchedRecorder:
    """Simulate a recorder that violates the compilation identity contract."""

    def record(
        self,
        workspace: ProjectWorkspace,
        compilation: ProjectBaselineCompilation,
    ) -> ProjectBaselineCompilation:
        del workspace
        return compilation.model_copy(update={"compilation_sha256": "f" * 64})


def hard_rule() -> SpecRule:
    return SpecRule(
        id="rule_prepare_no_self_approval_001",
        field="safety.self_approval",
        value=False,
        layer=SpecRuleLayer.PLATFORM_HARD,
        priority=10,
        source_uri="platform://hard-safety/v1",
        source_sha256="a" * 64,
        rationale="No Agent may approve its own work.",
    )


def organization(tmp_path: Path) -> OrganizationWorkspace:
    return OrganizationWorkspace.initialize(
        tmp_path / "organization",
        organization_id="organization_preparation_001",
        created_at=NOW,
    )


def service(
    tmp_path: Path,
    *,
    rule_provider: NoProjectRules | ConflictingProjectRules | None = None,
    recorder: FileProjectBaselineCompilationStore | MismatchedRecorder | None = None,
    clock: datetime = NOW,
) -> ProjectManagerSkillService:
    return ProjectManagerSkillService(
        organization=organization(tmp_path),
        registry=ProjectWorkspaceRegistry(tmp_path / "sidecars"),
        platform_rules=(hard_rule(),),
        rule_provider=rule_provider or NoProjectRules(),
        preparation_store_factory=FileProjectPreparationStore,
        baseline_recorder=recorder or FileProjectBaselineCompilationStore(),
        clock=lambda: clock,
    )


def project_files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize(
    ("marker", "content", "language"),
    (
        ("pyproject.toml", "[project]\nname='fixture'\n", ProjectLanguage.PYTHON),
        ("pom.xml", "<project/>\n", ProjectLanguage.JAVA),
        ("CMakeLists.txt", "project(fixture)\n", ProjectLanguage.CPP),
    ),
)
def test_only_project_directory_prepares_language_agnostic_project_without_pollution(
    tmp_path: Path,
    marker: str,
    content: str,
    language: ProjectLanguage,
) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "README.md").write_text("project guidance\n", encoding="utf-8")
    (project / marker).write_text(content, encoding="utf-8")
    before = project_files(project)

    skill = service(tmp_path)
    result = skill.prepare_project(PrepareProjectRequest(project_root=str(project.resolve())))

    assert result.status is PrepareProjectStatus.PREPARED
    preparation = skill.require_product_context(result)
    assert preparation.project_root == str(project.resolve())
    assert preparation.organization_id == "organization_preparation_001"
    assert "platform://hard-safety/v1" in preparation.baseline_source_uris
    assert any(uri.endswith("/README.md") for uri in preparation.baseline_source_uris)
    assert project_files(project) == before
    profile = ProjectProfile.discover(
        project,
        project_id=preparation.project_id,
        observed_at=NOW,
    )
    assert language in {fact.language for fact in profile.languages}
    assert Path(preparation.project_workspace_root).is_relative_to(tmp_path / "sidecars")


def test_exact_replay_returns_first_preparation_and_timestamp(tmp_path: Path) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "README.md").write_text("stable\n", encoding="utf-8")
    first_service = service(tmp_path)
    request = PrepareProjectRequest(project_root=str(project.resolve()))

    first = first_service.prepare_project(request)
    replay = service(tmp_path, clock=NOW + timedelta(hours=1)).prepare_project(request)

    assert replay == first
    assert replay.preparation is not None
    assert replay.preparation.prepared_at == NOW
    policy_root = Path(replay.preparation.project_workspace_root) / "policy"
    assert len(tuple(policy_root.glob("project-preparation-*.json"))) == 1


def test_project_baseline_conflict_is_durable_and_blocks_product_context(tmp_path: Path) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "README.md").write_text("agents may approve their own changes\n", encoding="utf-8")

    result = service(tmp_path, rule_provider=ConflictingProjectRules()).prepare_project(
        PrepareProjectRequest(project_root=str(project.resolve()))
    )

    assert result.status is PrepareProjectStatus.WAITING_HUMAN
    assert result.preparation is None
    assert len(result.conflicts) == 1
    assert isinstance(result.conflicts[0], ProjectSpecConflict)
    assert result.route is not None
    assert result.route.product_agent_start_allowed is False
    with pytest.raises(ProductContextNotReady, match="PREPARED"):
        service(tmp_path, rule_provider=ConflictingProjectRules()).require_product_context(result)
    sidecar = next((tmp_path / "sidecars").iterdir())
    records = tuple((sidecar / "spec-conflicts").rglob("*.json"))
    assert len(records) == 1
    assert tuple((sidecar / "policy").glob("project-preparation-*.json")) == ()

    replay = service(
        tmp_path,
        rule_provider=ConflictingProjectRules(),
        clock=NOW + timedelta(hours=1),
    ).prepare_project(PrepareProjectRequest(project_root=str(project.resolve())))
    assert replay == result


def test_profile_drift_fails_closed_instead_of_reusing_preparation(tmp_path: Path) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "README.md").write_text("stable\n", encoding="utf-8")
    request = PrepareProjectRequest(project_root=str(project.resolve()))
    service(tmp_path).prepare_project(request)
    (project / "pyproject.toml").write_text("[project]\nname='drift'\n", encoding="utf-8")

    with pytest.raises(RuntimeWorkspaceConflict):
        service(tmp_path, clock=NOW + timedelta(minutes=1)).prepare_project(request)


def test_corrupted_preparation_fails_before_product_context_can_be_returned(
    tmp_path: Path,
) -> None:
    project = tmp_path / "target"
    project.mkdir()
    request = PrepareProjectRequest(project_root=str(project.resolve()))
    result = service(tmp_path).prepare_project(request)
    assert result.preparation is not None
    record = next(
        (Path(result.preparation.project_workspace_root) / "policy").glob(
            "project-preparation-*.json"
        )
    )
    record.write_text("{}", encoding="utf-8")

    with pytest.raises(ProjectPreparationCorruption):
        service(tmp_path, clock=NOW + timedelta(minutes=1)).prepare_project(request)


def test_product_context_gate_revalidates_current_project_facts(tmp_path: Path) -> None:
    project = tmp_path / "target"
    project.mkdir()
    skill = service(tmp_path)
    result = skill.prepare_project(PrepareProjectRequest(project_root=str(project.resolve())))
    (project / "pyproject.toml").write_text("[project]\nname='drift'\n", encoding="utf-8")

    with pytest.raises(RuntimeWorkspaceConflict):
        skill.require_product_context(result)


def test_product_context_gate_rejects_self_consistent_forged_checkpoint(
    tmp_path: Path,
) -> None:
    project = tmp_path / "target"
    project.mkdir()
    skill = service(tmp_path)
    result = skill.prepare_project(PrepareProjectRequest(project_root=str(project.resolve())))
    assert result.preparation is not None
    trusted = result.preparation
    forged = type(trusted).create(
        organization_id=trusted.organization_id,
        project_id=trusted.project_id,
        project_root=trusted.project_root,
        project_workspace_root=trusted.project_workspace_root,
        organization_root=trusted.organization_root,
        project_profile_sha256=trusted.project_profile_sha256,
        runtime_binding_sha256=trusted.runtime_binding_sha256,
        baseline_spec_sha256="f" * 64,
        baseline_source_uris=trusted.baseline_source_uris,
        prepared_at=trusted.prepared_at,
    )
    forged_result = result.model_copy(update={"preparation": forged})

    with pytest.raises(ProjectPreparationDrift, match="current project facts"):
        skill.require_product_context(forged_result)


def test_baseline_recorder_identity_mismatch_blocks_preparation(tmp_path: Path) -> None:
    project = tmp_path / "target"
    project.mkdir()

    with pytest.raises(ProjectBaselineRecordError, match="invalid compilation"):
        service(tmp_path, recorder=MismatchedRecorder()).prepare_project(
            PrepareProjectRequest(project_root=str(project.resolve()))
        )


def test_service_authorizes_product_context_only_from_prepared_checkpoint(
    tmp_path: Path,
) -> None:
    project = tmp_path / "target"
    project.mkdir()
    skill = service(tmp_path)
    result = skill.prepare_project(PrepareProjectRequest(project_root=str(project.resolve())))
    preparation = skill.require_product_context(result)

    authorization = skill.advance_stage(
        StageAdvanceRequest(
            target=ProjectStage.PRODUCT_DISCOVERY,
            preparation=preparation,
        )
    )

    assert authorization.target is ProjectStage.PRODUCT_DISCOVERY
    assert authorization.project_id == preparation.project_id
    assert authorization.input_sha256s == (preparation.preparation_sha256,)
    authorization.validate_integrity()


def test_request_rejects_relative_paths_unknown_fields_and_naive_clock(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="absolute"):
        PrepareProjectRequest(project_root="relative/project")
    with pytest.raises(ValidationError, match="extra"):
        PrepareProjectRequest.model_validate(
            {"project_root": str(tmp_path.resolve()), "organization_root": "/ambient"}
        )

    project = tmp_path / "target"
    project.mkdir()
    with pytest.raises(RuntimeError, match="timezone-aware"):
        service(tmp_path, clock=datetime(2026, 9, 2, 12, 0)).prepare_project(
            PrepareProjectRequest(project_root=str(project.resolve()))
        )
