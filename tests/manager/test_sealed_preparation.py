"""Historic preparation stays readable after an independently authorized upgrade."""

from pathlib import Path

import pytest

from ai_software_engineer.manager.baseline import FileProjectBaselineCompilationStore
from ai_software_engineer.manager.preparation import (
    ManagerSkillService,
    PrepareProjectRequest,
    PrepareProjectResult,
)
from ai_software_engineer.manager.sealed_preparation import load_sealed_preparation
from ai_software_engineer.manager.store import FileProjectPreparationStore
from ai_software_engineer.repository_workspace import (
    RepositoryWorkspace,
    RepositoryWorkspaceRegistry,
)
from ai_software_engineer.runtime_workspace import (
    RUNTIME_BINDING_NAME,
    RuntimeWorkspaceCorruption,
    _record_read_path,
)
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.manager.test_preparation import NOW, NoProjectRules, hard_rule, organization, service


def prepared_workspace(
    tmp_path: Path,
) -> tuple[
    PrepareProjectResult,
    RepositoryWorkspace,
    Path,
    PrepareProjectRequest,
    RepositoryWorkspaceRegistry,
]:
    project = tmp_path / "target"
    project.mkdir()
    (project / "README.md").write_text("original frozen native instructions\n")
    request = PrepareProjectRequest(repository_root=str(project.resolve()))
    first = service(tmp_path).prepare_project(request)
    assert first.preparation is not None
    team = TeamWorkspace.initialize(
        tmp_path / "platform",
        team_id="team_preparation_001",
        name="Preparation Team",
    )
    registry = team.project_registry().open("project_preparation_001").repository_registry()
    (workspace,) = registry.discover()
    return first, workspace, project, request, registry


def test_original_preparation_is_read_only_and_does_not_rediscover_mutable_checkout(
    tmp_path: Path,
) -> None:
    first, workspace, project, request, registry = prepared_workspace(tmp_path)
    original = first.preparation
    assert original is not None
    before = {path: path.read_bytes() for path in workspace.root.rglob("*.json")}
    (project / "README.md").write_text("new mutable instructions\n")
    (project / "AGENTS.md").write_text("additional mutable instructions\n")
    result = load_sealed_preparation(
        workspace,
        original.preparation_sha256,
        organization=organization(tmp_path),
    )
    assert result == first
    assert all(path.read_bytes() == body for path, body in before.items())
    skill = ManagerSkillService(
        organization=organization(tmp_path),
        registry=registry,
        platform_rules=(hard_rule(),),
        rule_provider=NoProjectRules(),
        preparation_store_factory=FileProjectPreparationStore,
        baseline_recorder=FileProjectBaselineCompilationStore(),
        clock=lambda: NOW,
        versioned_preparations=True,
    )
    second = skill.prepare_project(request)
    assert second.preparation is not None and second.preparation != original
    assert (
        load_sealed_preparation(
            workspace,
            original.preparation_sha256,
            organization=organization(tmp_path),
        )
        == first
    )
    assert (
        load_sealed_preparation(
            workspace,
            second.preparation.preparation_sha256,
            organization=organization(tmp_path),
        )
        == second
    )
    assert all(path.read_bytes() == body for path, body in before.items())


def test_missing_or_duplicate_original_preparation_is_rejected(tmp_path: Path) -> None:
    first, workspace, _, _, _ = prepared_workspace(tmp_path)
    assert first.preparation is not None
    with pytest.raises(ValueError, match="缺失或不唯一"):
        load_sealed_preparation(workspace, "f" * 64, organization=organization(tmp_path))
    policy = workspace.directory("policy")
    source = policy / f"project-preparation-{workspace.repository_id}.json"
    duplicate = policy / "preparations-duplicate"
    duplicate.mkdir()
    (duplicate / source.name).write_bytes(source.read_bytes())
    with pytest.raises(ValueError, match="缺失或不唯一"):
        load_sealed_preparation(
            workspace,
            first.preparation.preparation_sha256,
            organization=organization(tmp_path),
        )


@pytest.mark.parametrize("target", ["preparation", "binding", "compilation"])
def test_original_preparation_never_follows_symlinked_records(
    tmp_path: Path,
    target: str,
) -> None:
    first, workspace, _, _, _ = prepared_workspace(tmp_path)
    original = first.preparation
    assert original is not None
    policy = workspace.directory("policy")
    if target == "preparation":
        path = policy / f"project-preparation-{workspace.repository_id}.json"
    elif target == "binding":
        path = _record_read_path(policy, RUNTIME_BINDING_NAME, original.runtime_binding_sha256)
    else:
        (path,) = tuple((policy / "project-baseline-compilations").glob("*.json"))
    outside = tmp_path / "outside.json"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises((ValueError, RuntimeWorkspaceCorruption), match=r"符号链接|symlink"):
        load_sealed_preparation(
            workspace,
            original.preparation_sha256,
            organization=organization(tmp_path),
        )
