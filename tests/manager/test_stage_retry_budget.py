"""Product and Planner use the same conservative durable refund boundary as Design."""

from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentErrorCode, StructuredModelError
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.multi_directory.service import JointDeliveryService
from tests.manager.test_joint_designer_feedback import setup_design
from tests.manager.test_joint_planner_feedback import DeliveryReached


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


@pytest.mark.parametrize(
    ("stage", "counter"),
    [
        (JointStage.PRODUCT_DISCOVERY, "product"),
        (JointStage.DESIGNING, "design"),
        (JointStage.PLANNING, "plan"),
    ],
)
def test_local_execution_limit_grows_without_spending_work_or_transient_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: JointStage,
    counter: str,
) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    seed = service._save(
        seed, stage=stage, design=backend.designs[1] if counter == "plan" else None
    )
    seen: list[int] = []

    def timed_out(*_args: object, **kwargs: object) -> None:
        seen.append(int(kwargs["timeout_seconds"]))
        raise StructuredModelError(
            AgentErrorCode.TIMEOUT,
            "local execution limit reached",
            transient=False,
            timeout_kind="local_execution_limit",
        )

    monkeypatch.setattr(backend, "complete", timed_out)
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    for expected in (600, 1200, 2400):
        reopened = JointDeliveryService(backend=backend, team=service.team, project=service.project)
        with pytest.raises(StructuredModelError):
            reopened.resume(command)
        assert seen[-1] == expected
    failed = service.status(seed.delivery_id).checkpoint
    assert failed.attempts == {counter: 0, counter + "_capacity_timeout": 3}
    with pytest.raises(ValueError, match=r"execution time.*exhausted"):
        service.resume(command)
    assert seen == [600, 1200, 2400]


def test_success_after_expansion_retains_only_one_design_work_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    valid = backend.designs[1]
    seen: list[int] = []

    def complete(*args: object, **kwargs: object) -> object:
        seen.append(int(kwargs["timeout_seconds"]))
        if len(seen) == 1:
            raise StructuredModelError(
                AgentErrorCode.TIMEOUT,
                "local execution limit reached",
                transient=False,
                timeout_kind="local_execution_limit",
            )
        return backend_complete(*args, **kwargs)

    backend.designs = [valid]
    backend_complete = backend.complete
    monkeypatch.setattr(backend, "complete", complete)
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    with pytest.raises(StructuredModelError):
        service.resume(command)
    with pytest.raises(DeliveryReached):
        service.resume(command)
    assert seen[:2] == [600, 1200]
    assert service.status(seed.delivery_id).checkpoint.attempts == {
        "design": 1,
        "design_capacity_timeout": 1,
        "plan": 1,
    }
