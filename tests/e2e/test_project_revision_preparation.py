"""A company can prepare a later Git baseline without rewriting earlier request facts."""

from pathlib import Path

import pytest

from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.multi_directory.service import CreateRequirementProject
from ai_software_engineer.project_manager.delivery import ResumeProjectDelivery
from ai_software_engineer.project_manager.production_host import OrganizationTeamHost
from tests.e2e.test_joint_delivery import setup_host
from tests.project_manager.test_production_backend import _git


@pytest.mark.mysql
def test_new_git_baseline_prepares_but_old_request_stays_pinned(tmp_path: Path) -> None:
    config, environment, models, projects = setup_host(tmp_path)

    def host() -> OrganizationTeamHost:
        return OrganizationTeamHost(
            config=config, environment=environment, structured_clients=models
        )

    first = (
        host()
        .requirement_entry()
        .create(
            CreateRequirementProject(
                name="Before source update", project_roots=tuple(map(str, projects))
            )
        )
        .checkpoint
    )
    assert first.stage is JointStage.READY_FOR_DISCUSSION
    prior = {p: p.read_bytes() for p in Path(config.platform_root).rglob("*.json")}
    (projects[0] / "README.md").write_text("New committed native project guidance.\n")
    _git("add", "README.md", cwd=projects[0])
    _git("commit", "-m", "Update source baseline", cwd=projects[0])
    service = host().requirement_entry()
    request = CreateRequirementProject(
        name="After source update", project_roots=tuple(map(str, projects))
    )
    second = service.create(request).checkpoint
    assert second.stage is JointStage.READY_FOR_DISCUSSION
    assert second.delivery_id != first.delivery_id
    assert second.preparations[0].result.project_id == first.preparations[0].result.project_id
    assert second.preparations != first.preparations
    assert all(path.read_bytes() == body for path, body in prior.items())
    assert not models.calls
    assert host().requirement_entry().create(request).checkpoint == second
    with pytest.raises(ValueError, match="source revision drift"):
        service.resume(ResumeProjectDelivery(delivery_id=first.delivery_id))
    assert not models.calls
