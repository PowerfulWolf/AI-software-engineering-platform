"""Cross-stage model advice cannot become ambient execution authority."""

from collections.abc import Mapping
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents import AgentErrorCode, StructuredModelError
from ai_software_engineer.agents.structured import StructuredModelResult
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context.ports import ContextBudgetExceeded
from ai_software_engineer.domain.coordination import CoordinationAction, ManagerCoordinationDraft
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager import stage_coordination as module
from ai_software_engineer.manager.delivery import DeliveryCheckpointStale, ResumeProjectDelivery
from ai_software_engineer.manager.model_execution import ManagerExecutionRejected
from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.multi_directory.service import JointDeliveryService
from tests.manager.test_joint_designer_feedback import setup_design
from tests.manager.test_joint_planner_feedback import DeliveryReached
from tests.manager.test_manager_model_execution import Authority


def coordinator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    service: JointDeliveryService,
    action: CoordinationAction = "RETRY_STAGE",
) -> tuple[module.ProductionStageCoordinator, Mock]:
    client = Mock()
    client.complete.return_value = StructuredModelResult(
        payload=ManagerCoordinationDraft(
            action=action,
            summary="Based on the typed failure",
            next_action="Use advertised action",
            responsible_actor="Manager",
            resume_condition="Same approved source, budget available",
        ).to_wire(),
        duration_ms=1,
    )
    factory = Mock()
    factory.for_project.return_value = client
    monkeypatch.setattr(module, "MySqlManagerClaimAuthority", lambda _: Authority())
    monkeypatch.setattr(
        module, "MySqlManagerRecordStore", lambda *_: KnowledgeRecordStore(tmp_path / "runs")
    )
    config = ProductionConfig.default().model_copy(
        update={"team_id": service.team.manifest.team_id}
    )
    value = module.ProductionStageCoordinator(
        config, {"ASE_MYSQL_DSN": "mysql://test:test@localhost/test"}, factory, tmp_path
    )
    return value, client


def test_automatic_design_retry_uses_new_window_and_preserves_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    service.coordinator, manager_client = coordinator(tmp_path, monkeypatch, service)
    backend.designs = [backend.designs[1]]
    complete = backend.complete
    windows = []

    def once(
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        windows.append(timeout_seconds)
        if len(windows) == 1:
            raise StructuredModelError(
                AgentErrorCode.TIMEOUT,
                "local window",
                transient=False,
                timeout_kind="local_execution_limit",
            )
        return complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )

    monkeypatch.setattr(backend, "complete", once)
    with pytest.raises(DeliveryReached):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    current = service.status(seed.delivery_id).checkpoint
    assert windows[:2] == [600, 1200]
    assert current.approval == seed.approval
    assert current.attempts["design_capacity_timeout"] == 1
    assert current.attempts["design"] == 1
    assert "design_transient" not in current.attempts
    assert current.coordination is None, "old advice must not masquerade as current phase"
    manager_client.complete.assert_called_once()
    assert any(c.coordination is not None for c in service.journal.history(seed.delivery_id))


@pytest.mark.parametrize(
    "stage", [JointStage.PRODUCT_DISCOVERY, JointStage.DESIGNING, JointStage.PLANNING]
)
def test_upstream_diagnosis_advertises_only_bounded_authorized_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: JointStage
) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    seed = service._save(
        seed, stage=stage, design=backend.designs[1] if stage is JointStage.PLANNING else None
    )
    value, client = coordinator(tmp_path, monkeypatch, service)
    error = StructuredModelError(AgentErrorCode.PROVIDER_UNAVAILABLE, "504", transient=True)
    advice = value.diagnose(seed, error)
    assert advice.draft.action == "RETRY_STAGE"
    assert client.complete.call_args.kwargs["input_payload"]["advertised_actions"] == [
        "WAITING_HUMAN",
        "RETRY_STAGE",
    ]
    saved = service._save(seed, coordination=advice, next_action="Manager's proposal")
    assert value.diagnose(saved, error) == advice
    assert client.complete.call_count == 1


@pytest.mark.parametrize(
    "code",
    [AgentErrorCode.INVALID_OUTPUT, AgentErrorCode.POLICY_VIOLATION, AgentErrorCode.PROVIDER_ERROR],
)
def test_non_retryable_failure_cannot_acquire_retry_from_manager_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: AgentErrorCode
) -> None:
    service, _, seed, _ = setup_design(tmp_path)
    value, client = coordinator(tmp_path, monkeypatch, service)
    with pytest.raises(ManagerExecutionRejected):
        value.diagnose(seed, StructuredModelError(code, "blocked", transient=False))
    assert client.complete.call_count == 2
    assert client.complete.call_args.kwargs["input_payload"]["advertised_actions"] == [
        "WAITING_HUMAN"
    ]
    assert service.status(seed.delivery_id).checkpoint == seed


def test_exhausted_capacity_disallows_retry_and_read_only_advice_survives_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, seed, _ = setup_design(tmp_path)
    seed = service._save(seed, attempts={"design_capacity_timeout": 3})
    value, client = coordinator(tmp_path, monkeypatch, service, action="WAITING_HUMAN")
    advice = value.diagnose(
        seed,
        StructuredModelError(
            AgentErrorCode.TIMEOUT, "local", transient=False, timeout_kind="local_execution_limit"
        ),
    )
    service._save(seed, coordination=advice, next_action="Review time limits")
    current = service.journal.current(seed.delivery_id)
    assert current is not None and current.coordination == advice
    assert client.complete.call_args.kwargs["input_payload"]["advertised_actions"] == [
        "WAITING_HUMAN"
    ]
    with pytest.raises(ValueError, match="source facts"):
        service._save(
            service._current(seed.delivery_id),
            coordination=advice.model_copy(update={"source_facts_sha256": "0" * 64}),
        )


def test_context_capacity_diagnosis_cannot_retry_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, seed, _ = setup_design(tmp_path)
    value, client = coordinator(tmp_path, monkeypatch, service, action="WAITING_HUMAN")
    advice = value.diagnose(seed, ContextBudgetExceeded("required sources too large"))
    assert advice.draft.action == "WAITING_HUMAN"
    supplied = client.complete.call_args.kwargs["input_payload"]
    assert supplied["advertised_actions"] == ["WAITING_HUMAN"]
    assert supplied["failure_code"] == "CONTEXT_BUDGET_EXHAUSTED"


def test_blockage_does_not_present_product_approval_as_recovery_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, seed, _ = setup_design(tmp_path)
    value, client = coordinator(tmp_path, monkeypatch, service, action="WAITING_HUMAN")

    value.diagnose(seed, None)

    supplied = client.complete.call_args.kwargs["input_payload"]
    assert supplied.get("approval_sha256") is None
    assert supplied["product_spec_sha256"] == module.digest(seed.product_spec.to_wire())


@pytest.mark.parametrize("tamper", ["stale", "unavailable"])
def test_service_rechecks_advice_before_journal_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    service, _, seed, _ = setup_design(tmp_path)
    value, _ = coordinator(tmp_path, monkeypatch, service, action="WAITING_HUMAN")
    error = StructuredModelError(AgentErrorCode.POLICY_VIOLATION, "denied", transient=False)
    advice = value.diagnose(seed, error)
    if tamper == "stale":
        advice = advice.model_copy(update={"source_facts_sha256": "0" * 64})
    else:
        advice = advice.model_copy(
            update={"draft": advice.draft.model_copy(update={"action": "RETRY_STAGE"})}
        )
    fake = Mock()
    fake.diagnose.return_value = advice
    service.coordinator = fake
    monkeypatch.setattr(service, "_advance_once", Mock(side_effect=error))
    history = service.journal.history(seed.delivery_id)
    with pytest.raises((ValueError, DeliveryCheckpointStale)):
        service._advance(seed)
    assert service.journal.history(seed.delivery_id) == history


@pytest.mark.parametrize("stage", [JointStage.DELIVERING, JointStage.BLOCKED])
def test_delivery_findings_never_allow_automatic_stage_retry(
    tmp_path: Path, stage: JointStage
) -> None:
    service, _, seed, _ = setup_design(tmp_path)
    current = seed.model_copy(update={"stage": stage})
    error = StructuredModelError(AgentErrorCode.TIMEOUT, "transport", transient=True)
    assert "RETRY_STAGE" not in module.allowed_coordination_actions(
        service.execution_retry_policy, current, error
    )
