"""Infrastructure failures and artifact corrections have independent durable allowances."""

from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentErrorCode, StructuredModelError
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.multi_directory.service import JointDeliveryService
from tests.manager.test_joint_designer_feedback import setup_design
from tests.manager.test_joint_planner_feedback import DeliveryReached


@pytest.mark.parametrize(
    "code",
    [
        AgentErrorCode.TIMEOUT,
        AgentErrorCode.PROVIDER_UNAVAILABLE,
        AgentErrorCode.RATE_LIMITED,
        AgentErrorCode.QUOTA_EXHAUSTED,
    ],
)
def test_typed_transient_failure_refunds_design_but_survives_restart(
    tmp_path: Path, code: AgentErrorCode
) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    valid = backend.designs[1]
    error = StructuredModelError(code, "temporary provider failure", transient=True)
    backend.designs = [error, valid]
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    with pytest.raises(StructuredModelError) as raised:
        service.resume(command)
    assert raised.value is error
    failed = service.status(seed.delivery_id).checkpoint
    assert failed.attempts == {"design": 0, "design_transient": 1}
    assert failed.approval == seed.approval
    assert failed.next_action == seed.next_action
    history = service.journal.history(seed.delivery_id)
    assert history[-2].attempts == {"design": 1}, "reserve before invocation for crash safety"
    reopened = JointDeliveryService(backend=backend, team=service.team, project=service.project)
    with pytest.raises(DeliveryReached):
        reopened.resume(command)
    assert reopened.status(seed.delivery_id).checkpoint.attempts == {
        "design": 1,
        "design_transient": 1,
        "plan": 1,
    }


@pytest.mark.parametrize(
    ("code", "transient"),
    [(AgentErrorCode.INVALID_OUTPUT, True), (AgentErrorCode.PROVIDER_UNAVAILABLE, False)],
)
def test_non_retryable_failures_do_not_receive_free_design_attempts(
    tmp_path: Path, code: AgentErrorCode, transient: bool
) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    backend.designs = [StructuredModelError(code, "rejected", transient=transient)]
    with pytest.raises(StructuredModelError):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert service.status(seed.delivery_id).checkpoint.attempts == {"design": 1}


def test_transient_failure_between_corrections_preserves_feedback_and_budget(
    tmp_path: Path,
) -> None:
    service, backend, seed, invalid = setup_design(tmp_path)
    valid = backend.designs[1]
    backend.designs = [
        invalid,
        StructuredModelError(
            AgentErrorCode.PROVIDER_UNAVAILABLE, "HTTP 504", transient=True, http_status=504
        ),
        invalid,
        valid,
    ]
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    with pytest.raises(StructuredModelError):
        service.resume(command)
    paused = service.status(seed.delivery_id).checkpoint
    assert paused.attempts == {"design": 1, "design_transient": 1}
    with pytest.raises(DeliveryReached):
        service.resume(command)
    assert backend.design_inputs[2]["next_action"] == paused.next_action
    assert service.status(seed.delivery_id).checkpoint.attempts == {
        "design": 3,
        "design_transient": 1,
        "plan": 1,
    }


def test_configured_transient_limit_is_durable_and_can_be_extended(tmp_path: Path) -> None:
    from ai_software_engineer.multi_directory.budget import DesignRetryPolicy

    service, backend, seed, _ = setup_design(tmp_path)
    valid = backend.designs[1]
    backend.designs = [
        StructuredModelError(
            AgentErrorCode.TIMEOUT, "knowledge assessment timed out", transient=True
        ),
        valid,
    ]
    limited = JointDeliveryService(
        backend=backend,
        team=service.team,
        project=service.project,
        design_retry_policy=DesignRetryPolicy(max_transient_failures=1),
    )
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    with pytest.raises(StructuredModelError):
        limited.resume(command)
    before = limited.journal.history(seed.delivery_id)
    reopened = JointDeliveryService(
        backend=backend,
        team=service.team,
        project=service.project,
        design_retry_policy=DesignRetryPolicy(max_transient_failures=1),
    )
    with pytest.raises(ValueError, match=r"transient.*budget exhausted"):
        reopened.resume(command)
    assert len(backend.design_inputs) == 1
    assert reopened.journal.history(seed.delivery_id) == before
    extended = JointDeliveryService(
        backend=backend,
        team=service.team,
        project=service.project,
        design_retry_policy=DesignRetryPolicy(max_transient_failures=2),
    )
    with pytest.raises(DeliveryReached):
        extended.resume(command)
    assert extended.status(seed.delivery_id).checkpoint.attempts["design_transient"] == 1
    assert extended.journal.history(seed.delivery_id)[: len(before)] == before


def test_legacy_exhausted_design_can_continue_after_config_increase(tmp_path: Path) -> None:
    from ai_software_engineer.multi_directory.budget import DesignRetryPolicy

    service, backend, seed, _ = setup_design(tmp_path)
    backend.designs = backend.designs[1:]
    exhausted = service._save(seed, attempts={"product": 7, "design": 3})
    before = service.journal.history(seed.delivery_id)
    extended = JointDeliveryService(
        backend=backend,
        team=service.team,
        project=service.project,
        design_retry_policy=DesignRetryPolicy(max_design_attempts=4),
    )
    with pytest.raises(DeliveryReached):
        extended.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    result = extended.status(seed.delivery_id).checkpoint
    assert result.attempts == {"product": 7, "design": 4, "plan": 1}
    assert result.approval == exhausted.approval
    assert extended.journal.history(seed.delivery_id)[: len(before)] == before


def test_pre_generation_knowledge_failure_uses_transient_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, backend, seed, _ = setup_design(tmp_path)

    def unavailable(*_args: object) -> None:
        assert service.status(seed.delivery_id).checkpoint.attempts == {"design": 1}
        raise StructuredModelError(
            AgentErrorCode.PROVIDER_UNAVAILABLE,
            "knowledge assessment HTTP 504",
            transient=True,
            http_status=504,
        )

    monkeypatch.setattr(backend, "client", unavailable)
    with pytest.raises(StructuredModelError, match="knowledge assessment"):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert backend.design_inputs == []
    assert service.status(seed.delivery_id).checkpoint.attempts == {
        "design": 0,
        "design_transient": 1,
    }


def test_recovery_cannot_erase_an_exhausted_transient_budget(tmp_path: Path) -> None:
    from ai_software_engineer.multi_directory.service import RecoverDesign

    service, backend, seed, _ = setup_design(tmp_path)
    exhausted = service._save(seed, attempts={"design": 3, "design_transient": 5})
    with pytest.raises(ValueError, match=r"transient.*budget exhausted"):
        service.recover_design(
            RecoverDesign(
                delivery_id=seed.delivery_id,
                expected_checkpoint_sha256=exhausted.checkpoint_sha256,
                operator_id="operator",
                rationale="retry",
                approval_reference="exact-human-request",
            )
        )
    assert service.status(seed.delivery_id).checkpoint == exhausted
    assert backend.design_inputs == []


def test_lowered_design_limit_prevents_another_call(tmp_path: Path) -> None:
    from ai_software_engineer.multi_directory.budget import DesignRetryPolicy

    service, backend, seed, invalid = setup_design(tmp_path)
    backend.designs = [invalid, invalid]
    limited = JointDeliveryService(
        backend=backend,
        team=service.team,
        project=service.project,
        design_retry_policy=DesignRetryPolicy(max_design_attempts=1),
    )
    with pytest.raises(ValueError, match="design attempt budget exhausted"):
        limited.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert len(backend.design_inputs) == 1
    assert limited.status(seed.delivery_id).checkpoint.attempts == {"design": 1}
