"""A team can prepare a later Git baseline without rewriting earlier request facts."""

from pathlib import Path

import pytest

from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.multi_directory.service import CreateRequirement
from tests.e2e.test_joint_delivery import setup_host
from tests.manager.test_production_backend import _git


@pytest.mark.mysql
def test_new_git_baseline_prepares_but_old_request_stays_pinned(tmp_path: Path) -> None:
    config, environment, models, projects = setup_host(tmp_path)

    def host() -> TeamHost:
        return TeamHost(config=config, environment=environment, structured_clients=models)

    first = (
        host()
        .requirement_entry()
        .create(
            CreateRequirement(
                name="Before source update", repository_roots=tuple(map(str, projects))
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
    request = CreateRequirement(
        name="After source update", repository_roots=tuple(map(str, projects))
    )
    second = service.create(request).checkpoint
    assert second.stage is JointStage.READY_FOR_DISCUSSION
    assert second.delivery_id != first.delivery_id
    assert second.preparations[0].result.repository_id == first.preparations[0].result.repository_id
    assert second.preparations != first.preparations
    assert all(path.read_bytes() == body for path, body in prior.items())
    assert not models.calls
    assert host().requirement_entry().create(request).checkpoint == second
    with pytest.raises(ValueError, match="source revision drift"):
        service.resume(ResumeProjectDelivery(delivery_id=first.delivery_id))
    assert not models.calls
