"""Product and Planner use the same conservative durable refund boundary as Design."""

from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentErrorCode, StructuredModelError
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.multi_directory.service import JointDeliveryService
from tests.manager.test_joint_designer_feedback import setup_design


@pytest.mark.parametrize(
    ("stage", "key", "role"),
    [
        (JointStage.PRODUCT_DISCOVERY, "product", "product"),
        (JointStage.PLANNING, "plan", "planner"),
    ],
)
@pytest.mark.parametrize("transient", [True, False])
def test_stage_failure_counts_survive_restart_and_policy_increase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: JointStage,
    key: str,
    role: str,
    transient: bool,
) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    seed = service._save(seed, stage=stage, design=backend.designs[1] if key == "plan" else None)
    policy = ExecutionRetryPolicy.model_validate(
        {role: StageRetryPolicy(max_attempts=1, max_transient_failures=1).to_wire()}
    )
    calls = []

    def unavailable(*args: object) -> None:
        calls.append(args)
        raise StructuredModelError(
            AgentErrorCode.PROVIDER_UNAVAILABLE, "fixture outage", transient=transient
        )

    monkeypatch.setattr(backend, "client", unavailable)
    limited = JointDeliveryService(
        backend=backend, team=service.team, project=service.project, execution_retry_policy=policy
    )
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    with pytest.raises(StructuredModelError):
        limited.resume(command)
    failed = limited.status(seed.delivery_id).checkpoint
    assert failed.attempts == ({key: 0, key + "_transient": 1} if transient else {key: 1})
    before = limited.journal.history(seed.delivery_id)
    reopened = JointDeliveryService(
        backend=backend, team=service.team, project=service.project, execution_retry_policy=policy
    )
    with pytest.raises(ValueError, match="budget exhausted"):
        reopened.resume(command)
    assert len(calls) == 1
    assert reopened.journal.history(seed.delivery_id) == before
    raised = ExecutionRetryPolicy.model_validate(
        {role: {"max_attempts": 2, "max_transient_failures": 2}}
    )
    extended = JointDeliveryService(
        backend=backend, team=service.team, project=service.project, execution_retry_policy=raised
    )
    with pytest.raises(StructuredModelError):
        extended.resume(command)
    assert len(calls) == 2
    assert extended.journal.history(seed.delivery_id)[: len(before)] == before


def test_knowledge_gate_before_planner_reservation_cannot_refund_old_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised

    service, backend, seed, _ = setup_design(tmp_path)
    seed = service._save(
        seed, stage=JointStage.PLANNING, design=backend.designs[1], attempts={"plan": 2}
    )

    class Gap:
        gap_id = "a" * 64

    class Gate:
        def require(self, *_args: object, **_kwargs: object) -> None:
            raise KnowledgeGapRaised(Gap())  # type: ignore[arg-type]

    monkeypatch.setattr(service, "_stage_workflow", lambda _: Gate())
    result = service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id)).checkpoint
    assert result.stage is JointStage.WAITING_HUMAN
    assert result.attempts == {"plan": 2}, "no new invocation was reserved to refund"
