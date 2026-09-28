"""Source-changing prerequisites must have an explicit, separate approval gate."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.prerequisite_repair import (
    PrerequisiteRepairPlan,
    PrerequisiteRepairRequest,
)
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.recovery.context import (
    prerequisite_repair_context,
    preserved_prerequisite_context,
)
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryAuthorization,
    RecoveryRejected,
    VerifiedRecoveryDecision,
)
from ai_software_engineer.recovery.remediation import require_repair_authority
from ai_software_engineer.recovery.resume import DeliveryResumeController, DeliveryResumeOutcome
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.web_console.models import ContinueDeliveryIntent
from tests.recovery.test_verification_environment import _admitted


def test_console_can_propose_repair_without_reusing_verification_approval() -> None:
    intent = ContinueDeliveryIntent.model_validate(
        {
            "action": "CONTINUE_DELIVERY",
            "project_id": "project_alpha",
            "delivery_id": "delivery_alpha",
            "expected_checkpoint_sha256": "a" * 64,
            "prerequisite_repair": {
                "objective": "Add isolated mock UI acceptance without real account access.",
                "write_paths": ["Sources/App/**", "Tests/**", "Package.swift"],
            },
        }
    )
    assert intent.prerequisite_repair is not None
    assert intent.approved_plan_sha256 is None
    assert intent.approved_repair_sha256 is None


@pytest.mark.parametrize(
    "path",
    [
        "/**",
        "../escape",
        ".trellis/**",
        "Sources/../Secrets",
        "**",
        "AGENTS.md",
        "Sources/.hidden/**",
    ],
)
def test_repair_scope_is_not_ambient_authority(path: str) -> None:
    with pytest.raises(ValueError):
        PrerequisiteRepairRequest(objective="An isolated UI test entry", write_paths=(path,))


def test_proposal_and_authority_are_exclusive() -> None:
    with pytest.raises(ValueError):
        ContinueDeliveryIntent.model_validate(
            {
                "project_id": "project_alpha",
                "delivery_id": "delivery_alpha",
                "expected_checkpoint_sha256": "a" * 64,
                "approved_plan_sha256": "b" * 64,
                "approved_repair_sha256": "c" * 64,
            }
        )
    with pytest.raises(ValueError):
        ResumeProjectDelivery(delivery_id="delivery_alpha", approved_repair_sha256="c" * 64)


def test_repair_plan_and_authority_reopen_tamper_and_stale_candidate(tmp_path: Path) -> None:
    plan, store, _, _, completion = _admitted(tmp_path, environment_error=True)
    incident = store.record_verification_incident(completion)
    repair = PrerequisiteRepairPlan(
        repository_root=plan.scope.repository_root,
        delivery_id=plan.scope.delivery_id,
        source_task_id=plan.inputs.task_id,
        source_plan_sha256=plan.plan_sha256,
        completion_sha256=completion.completion_sha256,
        incident_sha256=incident.incident_sha256,
        native_checkpoint_sha256=plan.native_checkpoint_sha256,
        candidate_revision=plan.inputs.candidate_revision,
        target_base_revision="d" * 40,
        target_preparation_sha256="e" * 64,
        request=PrerequisiteRepairRequest(
            objective="Add isolated acceptance UI", write_paths=("Sources/App/**",)
        ),
        created_at=completion.completed_at,
        plan_sha256="0" * 64,
    )
    repair = repair.model_copy(update={"plan_sha256": repair.recompute_sha256()})
    assert store.put_repair_plan(repair) == repair
    reopened = FileRecoveryStore(tmp_path / "verification", scope=plan.scope)
    assert reopened.get_repair_plan(repair.plan_sha256) == repair
    with pytest.raises(RecoveryRecordMissing):
        require_repair_authority(reopened, repair, plan, completion, plan.native_checkpoint_sha256)
    command = RecoveryApprovalCommand(
        operation_id="repair_test",
        plan_sha256=repair.plan_sha256,
        approval_reference="delegated-human-test",
        submitted_at=completion.completed_at,
    )
    authorization = RecoveryAuthorization.create(
        command,
        VerifiedRecoveryDecision(
            plan_sha256=repair.plan_sha256,
            approval_reference=command.approval_reference,
            approved=True,
            operator_id="test",
            rationale="Test exact source repair approval",
            decided_at=command.submitted_at,
        ),
    )
    assert reopened.put_repair_authorization(authorization) == authorization
    require_repair_authority(reopened, repair, plan, completion, plan.native_checkpoint_sha256)
    source = prerequisite_repair_context(repair)
    section = Mock(truncated=False, uri=source.uri, content=source.content)
    section.name = "source:manager.prerequisite_repair"
    previous = Mock(task_id=plan.inputs.task_id, role=AgentRole.CODER, sections=(section,))
    contexts = Mock(spec=FileContextStore)
    contexts.get.return_value = previous
    recovery = Mock()
    recovery.source.task_id = plan.inputs.task_id
    recovery.source.failed_context_id = "ctx_prior"
    assert preserved_prerequisite_context(recovery, contexts, reopened) == (source,)
    section.truncated = True
    with pytest.raises(RecoveryRejected, match="incomplete"):
        preserved_prerequisite_context(recovery, contexts, reopened)
    section.truncated = False
    section.content = "unapproved substitute objective"
    with pytest.raises(RecoveryRejected, match="authority"):
        preserved_prerequisite_context(recovery, contexts, reopened)
    with pytest.raises(RecoveryRejected, match="authority"):
        require_repair_authority(reopened, repair, plan, completion, "f" * 64)
    changed = repair.model_copy(update={"candidate_revision": "f" * 40})
    changed = changed.model_copy(update={"plan_sha256": changed.recompute_sha256()})
    with pytest.raises(RecoveryRejected, match="incident"):
        reopened.put_repair_plan(changed)
    (tmp_path / "verification" / f"prerequisite-repair-{repair.plan_sha256}.json").write_text("{}")
    with pytest.raises(RecoveryRejected):
        reopened.get_repair_plan(repair.plan_sha256)


def test_proposal_is_idempotent_and_never_calls_coder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, store, _, _, completion = _admitted(tmp_path, environment_error=True)
    incident = store.record_verification_incident(completion)
    from ai_software_engineer.recovery.verification_records import CandidateVerificationPlan

    latest = CandidateVerificationPlan.create(
        **{
            **plan.model_dump(exclude={"plan_sha256"}),
            "prerequisite_incident_sha256": incident.incident_sha256,
        }
    )
    store.put_verification_plan(latest)
    backend = Mock()
    backend.prepare.return_value.preparation.preparation_sha256 = "e" * 64
    backend.delivery_base_revision.return_value = "d" * 40
    verification = Mock(backend=backend)
    controller = DeliveryResumeController(
        config=Mock(),
        environment={},
        backend=backend,
        entry=Mock(),
        recovery=Mock(),
        verification=verification,
    )
    source = Mock()
    source.inputs.task_id = plan.inputs.task_id
    monkeypatch.setattr(controller, "_native_source", lambda _: source)
    # Use a real checkpoint from the production-shaped continuation fixture.
    from tests.recovery.test_delivery_continuation import _service
    from tests.recovery.test_execution_records import continuation_allocation

    fixture_root = tmp_path / "checkpoint-fixture"
    fixture_root.mkdir()
    allocation = continuation_allocation(fixture_root)
    _, checkpoints = _service(fixture_root, allocation)
    current = checkpoints.list(allocation.source_delivery_id)[0].model_copy(
        update={
            "repository_root": plan.scope.repository_root,
            "delivery_id": plan.scope.delivery_id,
            "checkpoint_sha256": plan.native_checkpoint_sha256,
        }
    )
    request = PrerequisiteRepairRequest(
        objective="Add isolated UI acceptance", write_paths=("Sources/App/**",)
    )
    command = ResumeProjectDelivery(delivery_id=plan.scope.delivery_id, prerequisite_repair=request)
    first = controller._continue_prerequisite_repair(current, command, store, latest)
    second = controller._continue_prerequisite_repair(
        current,
        command.model_copy(update={"submitted_at": command.submitted_at + timedelta(seconds=5)}),
        store,
        latest,
    )
    assert first == second
    assert first.outcome is DeliveryResumeOutcome.REPAIR_APPROVAL_REQUIRED
    backend.run_prepared_allocation.assert_not_called()
    assert first.prerequisite_repair_plan is not None
    with pytest.raises(RecoveryRecordMissing):
        store.get_repair_authorization(first.prerequisite_repair_plan.plan_sha256)
