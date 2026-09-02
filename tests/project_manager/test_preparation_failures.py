"""Fail-closed integration tests for Project Manager project preparation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.project_manager.baseline import (
    FileProjectBaselineCompilationStore,
)
from ai_software_engineer.project_manager.preparation import (
    PrepareProjectRequest,
    ProjectManagerSkillService,
    ProjectPreparationCompositionError,
)
from ai_software_engineer.project_manager.store import FileProjectPreparationStore
from ai_software_engineer.project_profile import ProjectProfile
from ai_software_engineer.project_workspace import (
    ProjectWorkspaceRegistry,
    WorkspacePlacementError,
    WorkspaceRootError,
)
from ai_software_engineer.runtime_workspace import (
    OrganizationWorkspace,
    RuntimeWorkspaceCorruption,
)
from ai_software_engineer.spec_compiler import SpecRule, SpecRuleLayer

NOW = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


class NoProjectRules:
    """Leave discovered project-native documents opaque during preparation."""

    def rules_for(self, profile: ProjectProfile) -> Sequence[SpecRule]:
        del profile
        return ()


def hard_rule() -> SpecRule:
    return SpecRule(
        id="rule_failure_no_self_approval_001",
        field="safety.self_approval",
        value=False,
        layer=SpecRuleLayer.PLATFORM_HARD,
        priority=10,
        source_uri="platform://hard-safety/v1",
        source_sha256="a" * 64,
        rationale="No Agent may approve its own work.",
    )


def service(
    organization: OrganizationWorkspace,
    registry_root: Path,
    *,
    clock: datetime = NOW,
) -> ProjectManagerSkillService:
    return ProjectManagerSkillService(
        organization=organization,
        registry=ProjectWorkspaceRegistry(registry_root),
        platform_rules=(hard_rule(),),
        rule_provider=NoProjectRules(),
        preparation_store_factory=FileProjectPreparationStore,
        baseline_recorder=FileProjectBaselineCompilationStore(),
        clock=lambda: clock,
    )


def organization(root: Path) -> OrganizationWorkspace:
    return OrganizationWorkspace.initialize(
        root,
        organization_id="organization_failure_001",
        created_at=NOW,
    )


def project_files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_prepare_rejects_registry_inside_target_without_writing_ai_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "README.md").write_text("project-owned\n", encoding="utf-8")
    before = project_files(project)
    skill = service(organization(tmp_path / "organization"), project / ".ai-sidecars")

    with pytest.raises(WorkspacePlacementError, match="outside the target project"):
        skill.prepare_project(PrepareProjectRequest(project_root=str(project.resolve())))

    assert project_files(project) == before


def test_prepare_rejects_symlink_registry_root_without_writing_target(
    tmp_path: Path,
) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "README.md").write_text("project-owned\n", encoding="utf-8")
    before = project_files(project)
    actual_registry = tmp_path / "actual-sidecars"
    actual_registry.mkdir()
    linked_registry = tmp_path / "linked-sidecars"
    linked_registry.symlink_to(actual_registry, target_is_directory=True)
    skill = service(organization(tmp_path / "organization"), linked_registry)

    with pytest.raises(WorkspaceRootError, match="symlink"):
        skill.prepare_project(PrepareProjectRequest(project_root=str(project.resolve())))

    assert project_files(project) == before


def test_prepare_replay_rejects_tampered_runtime_binding_as_corruption(
    tmp_path: Path,
) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "README.md").write_text("project-owned\n", encoding="utf-8")
    before = project_files(project)
    organization_workspace = organization(tmp_path / "organization")
    registry_root = tmp_path / "sidecars"
    first = service(organization_workspace, registry_root).prepare_project(
        PrepareProjectRequest(project_root=str(project.resolve()))
    )
    assert first.preparation is not None
    binding_path = (
        Path(first.preparation.project_workspace_root) / "policy" / "runtime-workspace-binding.json"
    )
    binding_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeWorkspaceCorruption, match="workspace record is invalid"):
        service(
            organization_workspace,
            registry_root,
            clock=NOW + timedelta(minutes=1),
        ).prepare_project(PrepareProjectRequest(project_root=str(project.resolve())))

    assert project_files(project) == before


@pytest.mark.parametrize("overlap", ("project", "sidecar"))
def test_prepare_fails_closed_when_organization_overlaps_runtime_roots(
    tmp_path: Path,
    overlap: str,
) -> None:
    organization_root = tmp_path / "organization"
    organization_workspace = organization(organization_root)
    if overlap == "project":
        project = organization_root / "target"
        registry_root = tmp_path / "sidecars"
    else:
        project = tmp_path / "target"
        registry_root = organization_root / "sidecars"
    project.mkdir()
    (project / "README.md").write_text("project-owned\n", encoding="utf-8")
    before = project_files(project)

    with pytest.raises(ProjectPreparationCompositionError, match="cannot overlap"):
        service(organization_workspace, registry_root).prepare_project(
            PrepareProjectRequest(project_root=str(project.resolve()))
        )

    assert project_files(project) == before
