"""A team can prepare a later Git baseline without rewriting earlier request facts."""

from pathlib import Path

import pytest

from ai_software_engineer.manager.delivery import ApproveProductSpec, ReplyToProduct
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.multi_directory.service import CreateRequirement
from tests.e2e.test_joint_delivery import setup_host
from tests.manager.test_production_backend import _git, _git_output, _ScriptedDeliveryFactory


@pytest.mark.mysql
def test_new_git_baseline_prepares_but_old_request_stays_pinned(tmp_path: Path) -> None:
    config, environment, models, projects = setup_host(tmp_path)

    def host() -> TeamHost:
        return TeamHost(
            config=config,
            environment=environment,
            structured_clients=models,
            delivery_route_adapters=_ScriptedDeliveryFactory(),
        )

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
    (projects[0] / "hello.txt").write_text("new master\n")
    _git("add", "hello.txt", cwd=projects[0])
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
    product = service.reply(
        ReplyToProduct(
            delivery_id=first.delivery_id,
            expected_checkpoint_sha256=first.checkpoint_sha256,
            message="Continue against this Requirement's original code baseline.",
        )
    ).checkpoint
    assert product.stage is JointStage.WAITING_PRODUCT_APPROVAL
    done = service.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="approve-original-baseline",
        )
    ).checkpoint
    assert done.stage is JointStage.DONE, [
        (
            child.checkpoint.stage,
            child.checkpoint.failure_code,
            child.checkpoint.failure_summary,
            child.checkpoint.next_action,
        )
        for child in done.children
    ]
    for child in done.children:
        candidate = child.checkpoint.candidate_revision
        assert candidate is not None
        unit = next(
            unit for unit in first.scope.units if unit.root == child.checkpoint.repository_root
        )
        assert _git_output("rev-parse", f"{candidate}^", cwd=Path(unit.root)) == unit.base_revision
    assert (projects[0] / "hello.txt").read_text() == "new master\n"
