"""Production's opt-in preparation epochs do not rewrite the legacy baseline."""

from pathlib import Path

import pytest

from ai_software_engineer.project_manager.baseline import FileProjectBaselineCompilationStore
from ai_software_engineer.project_manager.preparation import (
    PrepareProjectRequest,
    ProjectManagerSkillService,
    ProjectPreparationDrift,
)
from ai_software_engineer.project_manager.store import FileProjectPreparationStore
from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry
from tests.project_manager.test_preparation import (
    NOW,
    NoProjectRules,
    hard_rule,
    organization,
    service,
)


def test_new_preparation_keeps_legacy_facts_and_product_gate(tmp_path: Path) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "README.md").write_text("first baseline\n")
    request = PrepareProjectRequest(project_root=str(project.resolve()))
    first = service(tmp_path).prepare_project(request)
    assert first.preparation is not None
    old_bytes = {
        p: p.read_bytes() for p in Path(first.preparation.project_workspace_root).rglob("*.json")
    }
    skill = ProjectManagerSkillService(
        organization=organization(tmp_path),
        registry=ProjectWorkspaceRegistry(tmp_path / "sidecars"),
        platform_rules=(hard_rule(),),
        rule_provider=NoProjectRules(),
        preparation_store_factory=FileProjectPreparationStore,
        baseline_recorder=FileProjectBaselineCompilationStore(),
        clock=lambda: NOW,
        versioned_preparations=True,
    )
    assert skill.prepare_project(request) == first
    (project / "README.md").write_text("second baseline\n")
    second = skill.prepare_project(request)
    assert second.project_id == first.project_id and second != first
    assert skill.prepare_project(request) == second
    assert skill.require_product_context(second) == second.preparation
    with pytest.raises(ProjectPreparationDrift):
        skill.require_product_context(first)
    assert all(p.read_bytes() == content for p, content in old_bytes.items())
