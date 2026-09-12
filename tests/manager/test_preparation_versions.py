"""Production's opt-in preparation epochs do not rewrite the legacy baseline."""

from pathlib import Path

import pytest

from ai_software_engineer.manager.baseline import FileProjectBaselineCompilationStore
from ai_software_engineer.manager.preparation import (
    ManagerSkillService,
    PrepareProjectRequest,
    ProjectPreparationDrift,
)
from ai_software_engineer.manager.store import FileProjectPreparationStore
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.manager.test_preparation import (
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
    request = PrepareProjectRequest(repository_root=str(project.resolve()))
    first = service(tmp_path).prepare_project(request)
    assert first.preparation is not None
    old_bytes = {
        p: p.read_bytes() for p in Path(first.preparation.repository_workspace_root).rglob("*.json")
    }
    team = TeamWorkspace.initialize(
        tmp_path / "platform",
        team_id="team_preparation_001",
        name="Preparation Team",
    )
    project_workspace = team.project_registry().open("project_preparation_001")
    skill = ManagerSkillService(
        organization=organization(tmp_path),
        registry=project_workspace.repository_registry(),
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
    assert second.repository_id == first.repository_id and second != first
    assert skill.prepare_project(request) == second
    assert skill.require_product_context(second) == second.preparation
    with pytest.raises(ProjectPreparationDrift):
        skill.require_product_context(first)
    assert all(p.read_bytes() == content for p, content in old_bytes.items())
