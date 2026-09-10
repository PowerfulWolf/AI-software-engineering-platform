"""Delivery hash-chain adoption for independently triggered successor Tasks."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.domain import (
    QaCriterionStatus,
    QaReportStatus,
    QaTestStatus,
    TaskStatus,
)
from ai_software_engineer.orchestration import (
    BlockedResult,
    RetryClassification,
    RetryDeliveryResult,
)
from ai_software_engineer.project_manager.delivery import (
    DeliveryCommandRejected,
    ProjectDeliveryCheckpointCatalog,
    UnifiedProjectEntryService,
)
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.project_manager.dispatch import (
    ContinuationDispatchRecord,
    _record_digest,
)
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.recovery.resume import (
    DeliveryResumeController,
    DeliveryResumeOutcome,
)
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationCompletion,
    CandidateVerificationInputs,
    CandidateVerificationPlan,
)
from ai_software_engineer.recovery.verification_snapshot import retained_candidate_checkpoint
from tests.domain.factories import make_qa_artifact, make_review_artifact
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _definitions
from tests.recovery.test_candidate_verification import Admission, setup_verification
from tests.recovery.test_execution_records import continuation_allocation

NOW = datetime(2026, 9, 9, 8, 0, tzinfo=UTC)


def _service(
    tmp_path: Path,
    dispatch: ContinuationDispatchRecord,
    *,
    retain_candidate: bool = True,
    retained_failure: bool = True,
) -> tuple[UnifiedProjectEntryService, FileProjectDeliveryCheckpointStore]:
    registry = tmp_path / "registry"
    state = registry / dispatch.project_id / "state"
    state.mkdir(parents=True)
    store = FileProjectDeliveryCheckpointStore(state / "project-deliveries")
    source = ProjectDeliveryCheckpoint.create(
        delivery_id=dispatch.source_delivery_id,
        sequence=1,
        project_id=dispatch.project_id,
        project_root=dispatch.task.repository,
        preparation_sha256="1" * 64,
        request_id=dispatch.project_request_id,
        request_revision=1,
        product_checkpoint_sha256="2" * 64,
        product_spec_id="product_spec_alpha",
        product_spec_sha256="3" * 64,
        approval_id="product_approval_" + "4" * 64,
        approval_sha256="5" * 64,
        technical_design_id="technical_design_alpha",
        technical_design_sha256="6" * 64,
        execution_plan_id=dispatch.execution_plan_id,
        execution_plan_sha256=dispatch.execution_plan_sha256,
        planning_preview_id="planning_preview_" + "7" * 64,
        planning_preview_sha256="8" * 64,
        dispatch_commit_id=dispatch.source_dispatch_id,
        dispatch_commit_sha256="9" * 64,
        task_id=dispatch.source_task_id,
        task_revision=7,
        task_status=TaskStatus.BLOCKED,
        candidate_revision=dispatch.source_revision if retain_candidate else None,
        stage=DeliveryStage.BLOCKED,
        stage_attempts=DeliveryStageAttempts(delivering=1),
        next_action=DeliveryNextAction.REQUEST_HUMAN,
        failure_code=DeliveryFailureCode.TRANSIENT_PROVIDER_FAILURE,
        failure_summary="QA provider stopped after the candidate was committed",
        failed_stage=DeliveryStage.DELIVERING if retained_failure else None,
        checkpointed_at=NOW,
    )
    store.put(source)
    return (
        UnifiedProjectEntryService(
            backend=Mock(),
            catalog=ProjectDeliveryCheckpointCatalog(registry),
        ),
        store,
    )


def _verification_for(
    store: FileProjectDeliveryCheckpointStore,
    dispatch: ContinuationDispatchRecord,
) -> tuple[
    ContinuationDispatchRecord,
    CandidateVerificationPlan,
    CandidateVerificationCompletion,
]:
    current = store.current(dispatch.source_delivery_id)
    assert current.dispatch_commit_sha256 is not None
    plan = CandidateVerificationPlan.create(
        scope=RecoveryScope(
            company_id="company_test",
            project_id=current.project_id,
            project_root=current.project_root,
            delivery_id=current.delivery_id,
        ),
        inputs=CandidateVerificationInputs(
            task_id=dispatch.source_task_id,
            task_revision=current.task_revision or 1,
            task_sha256="1" * 64,
            plan_id="art_plan_source",
            plan_sha256="2" * 64,
            implementation_id="art_impl_source",
            implementation_sha256="3" * 64,
            candidate_revision=dispatch.source_revision,
        ),
        native_checkpoint_sha256=current.checkpoint_sha256,
        dispatch_sha256=current.dispatch_commit_sha256,
        approved_stage_chain_sha256="5" * 64,
        current_policy_sha256="6" * 64,
        definitions=tuple(_definitions().values()),
        created_at=NOW,
    )
    qa = make_qa_artifact()
    failed_criterion = qa.content.criteria_results[0].model_copy(
        update={"status": QaCriterionStatus.FAIL}
    )
    qa = qa.model_copy(
        update={
            "task_id": dispatch.source_task_id,
            "source_revision": dispatch.source_revision,
            "parent_artifact_ids": (plan.inputs.implementation_id,),
            "content": qa.content.model_copy(
                update={
                    "status": QaReportStatus.FAIL,
                    "criteria_results": (failed_criterion,),
                }
            ),
        }
    )
    completion = CandidateVerificationCompletion.create(
        plan_sha256=plan.plan_sha256,
        authorization_sha256="7" * 64,
        qa_invocation_sha256="8" * 64,
        qa=qa,
        completed_at=NOW + timedelta(seconds=30),
    )
    task_id = f"task_continue_{completion.completion_sha256[:32]}"
    continuation_metadata = {
        "continuation_sha256": completion.completion_sha256,
        "continuation_plan_sha256": plan.plan_sha256,
    }
    task = dispatch.task.model_copy(
        update={
            "id": task_id,
            "metadata": {**dispatch.task.metadata, **continuation_metadata},
        }
    )
    phases = tuple(
        phase.model_copy(
            update={
                "assignment": phase.assignment.model_copy(update={"task_id": task_id}),
                "lease": phase.lease.model_copy(update={"task_id": task_id}),
            }
        )
        for phase in dispatch.phases
    )
    rebound = ContinuationDispatchRecord.model_validate(
        {
            **dispatch.to_wire(),
            "id": f"dispatch_commit_{completion.completion_sha256}",
            "task_id": task_id,
            "task": task.to_wire(),
            "phases": [phase.to_wire() for phase in phases],
            **continuation_metadata,
            "dispatch_sha256": "0" * 64,
        }
    )
    rebound = rebound.model_copy(update={"dispatch_sha256": _record_digest(rebound)})
    return rebound, plan, completion


def test_continuation_is_attached_once_and_seals_successor_candidate(tmp_path: Path) -> None:
    dispatch = continuation_allocation(tmp_path)
    service, store = _service(tmp_path, dispatch)
    dispatch, plan, completion = _verification_for(store, dispatch)

    started = service.begin_continuation(dispatch, plan, completion, at=NOW + timedelta(minutes=1))
    assert started.checkpoint.stage is DeliveryStage.DELIVERING
    assert started.checkpoint.task_id == dispatch.task_id
    assert started.checkpoint.dispatch_commit_id == dispatch.id
    assert started.checkpoint.candidate_revision is None
    assert (
        service.begin_continuation(dispatch, plan, completion, at=NOW + timedelta(minutes=2))
        == started
    )

    task = dispatch.task.model_copy(
        update={
            "status": TaskStatus.DONE,
            "attempts": 1,
            "updated_at": NOW + timedelta(minutes=3),
        }
    )
    delivered = RetryDeliveryResult(
        task=task,
        candidate_revision="a" * 40,
        artifact_ids=("art_plan", "art_impl", "art_qa_001", "art_review"),
        context_manifest_ids=tuple(f"ctx_{index:064x}" for index in range(1, 5)),
        run_ids=("run_plan", "run_coder", "run_qa_001", "run_review"),
        event_ids=("evt_plan", "evt_coder", "evt_qa_001", "evt_review"),
    )
    finished = service.finish_continuation(
        dispatch,
        delivered,
        at=task.updated_at,
    )

    assert finished.checkpoint.stage is DeliveryStage.DONE
    assert finished.checkpoint.candidate_revision == "a" * 40
    assert finished.checkpoint.task_status is TaskStatus.DONE
    assert len(store.list(dispatch.source_delivery_id)) == 3
    assert service.finish_continuation(dispatch, delivered, at=task.updated_at) == finished
    assert len(store.list(dispatch.source_delivery_id)) == 3


def test_continuation_accepts_retained_candidate_when_terminal_cursor_is_empty(
    tmp_path: Path,
) -> None:
    dispatch = continuation_allocation(tmp_path)
    service, store = _service(tmp_path, dispatch, retain_candidate=False)
    dispatch, plan, completion = _verification_for(store, dispatch)

    started = service.begin_continuation(
        dispatch,
        plan,
        completion,
        at=NOW + timedelta(minutes=1),
    )

    assert started.checkpoint.stage is DeliveryStage.DELIVERING
    assert started.checkpoint.task_id == dispatch.task_id


def test_continuation_rejects_empty_cursor_without_terminal_delivery_proof(
    tmp_path: Path,
) -> None:
    dispatch = continuation_allocation(tmp_path)
    service, store = _service(
        tmp_path,
        dispatch,
        retain_candidate=False,
        retained_failure=False,
    )
    dispatch, plan, completion = _verification_for(store, dispatch)

    with pytest.raises(
        DeliveryCommandRejected, match="continuation does not match the terminal candidate"
    ):
        service.begin_continuation(dispatch, plan, completion, at=NOW + timedelta(minutes=1))


def test_failed_continuation_resolves_its_retained_source_candidate(tmp_path: Path) -> None:
    dispatch = continuation_allocation(tmp_path)
    service, store = _service(tmp_path, dispatch)
    dispatch, plan, completion = _verification_for(store, dispatch)
    service.begin_continuation(dispatch, plan, completion, at=NOW + timedelta(minutes=1))
    blocked_task = dispatch.task.model_copy(
        update={
            "status": TaskStatus.BLOCKED,
            "attempts": 1,
            "updated_at": NOW + timedelta(minutes=2),
        }
    )
    service.finish_continuation(
        dispatch,
        BlockedResult(
            task=blocked_task,
            classification=RetryClassification.INVALID_OUTPUT,
            reason="Coder produced no candidate for an inconclusive QA result",
            attempt=1,
            artifact_ids=(),
            event_ids=("evt_continuation_failed",),
        ),
        at=blocked_task.updated_at,
    )
    current = store.current(dispatch.source_delivery_id)

    source = retained_candidate_checkpoint(store.list(current.delivery_id), dispatch)

    assert source.task_id == dispatch.source_task_id
    assert source.dispatch_commit_id == dispatch.source_dispatch_id
    assert source.candidate_revision == dispatch.source_revision

    qa = make_qa_artifact().model_copy(
        update={
            "task_id": plan.inputs.task_id,
            "source_revision": plan.inputs.candidate_revision,
            "parent_artifact_ids": (plan.inputs.implementation_id,),
        }
    )
    review = make_review_artifact().model_copy(
        update={
            "task_id": plan.inputs.task_id,
            "source_revision": plan.inputs.candidate_revision,
            "parent_artifact_ids": (qa.artifact_id,),
        }
    )
    verified = CandidateVerificationCompletion.create(
        plan_sha256=plan.plan_sha256,
        authorization_sha256="a" * 64,
        qa_invocation_sha256="b" * 64,
        reviewer_invocation_sha256="c" * 64,
        qa=qa,
        review=review,
        completed_at=NOW + timedelta(minutes=3),
    )

    accepted = service.accept_verification(plan, verified)

    assert accepted.checkpoint.stage is DeliveryStage.DONE
    assert accepted.checkpoint.candidate_revision == dispatch.source_revision


def test_inconclusive_verification_proposes_fresh_qa_without_coder(
    tmp_path: Path,
) -> None:
    dispatch = continuation_allocation(tmp_path)
    _, store = _service(tmp_path, dispatch)
    _, plan, completion = _verification_for(store, dispatch)
    qa = completion.qa
    completion = CandidateVerificationCompletion.create(
        plan_sha256=completion.plan_sha256,
        authorization_sha256=completion.authorization_sha256,
        qa_invocation_sha256=completion.qa_invocation_sha256,
        qa=qa.model_copy(
            update={
                "content": qa.content.model_copy(
                    update={
                        "status": QaReportStatus.FAIL,
                        "criteria_results": (
                            qa.content.criteria_results[0].model_copy(
                                update={"status": QaCriterionStatus.NOT_TESTED}
                            ),
                        ),
                        "tests_run": (
                            qa.content.tests_run[0].model_copy(
                                update={"status": QaTestStatus.ERROR}
                            ),
                        ),
                    }
                )
            }
        ),
        completed_at=completion.completed_at,
    )
    successor = CandidateVerificationPlan.create(
        **{
            **plan.model_dump(exclude={"plan_sha256"}),
            "execution_task_id": "task_verify_inconclusive_successor",
            "created_at": NOW + timedelta(minutes=3),
        }
    )
    verification = Mock()
    verification.latest_project.return_value = (Mock(), plan, tmp_path / "old-plan.json")
    verification.propose_project.return_value = (successor, tmp_path / "successor-plan.json")
    backend = Mock()
    entry = Mock()
    entry.status.return_value = type(
        "Result", (), {"checkpoint": store.current(plan.scope.delivery_id)}
    )()
    controller = DeliveryResumeController(
        config=Mock(),
        environment={},
        backend=backend,
        entry=entry,
        recovery=Mock(),
        verification=verification,
    )

    result = controller._continue_completion(plan, completion)

    assert result.outcome is DeliveryResumeOutcome.VERIFICATION_APPROVAL_REQUIRED
    assert result.verification_plan_sha256 == successor.plan_sha256
    verification.propose_project.assert_called_once_with(
        project_root=plan.scope.project_root,
        delivery_id=plan.scope.delivery_id,
    )
    backend.run_prepared_allocation.assert_not_called()


@pytest.mark.parametrize("retain_candidate", [True, False])
def test_verified_candidate_accepts_unchanged_checkpoint_append(
    tmp_path: Path,
    retain_candidate: bool,
) -> None:
    (tmp_path / "verification").mkdir()
    inputs, repository, verifier = setup_verification(
        tmp_path / "verification", ScriptedAdapter(), Admission()
    )
    try:
        result = verifier.verify_candidate(inputs)
        assert result.review is not None
        registry = tmp_path / "registry"
        state = registry / "project_test" / "state"
        state.mkdir(parents=True)
        store = FileProjectDeliveryCheckpointStore(state / "project-deliveries")
        source = store.put(
            ProjectDeliveryCheckpoint.create(
                delivery_id="delivery_test",
                sequence=1,
                project_id="project_test",
                project_root=str((tmp_path / "verification/project").resolve()),
                preparation_sha256="1" * 64,
                request_id="request_test",
                request_revision=1,
                product_checkpoint_sha256="2" * 64,
                product_spec_id="product_spec_test",
                product_spec_sha256="3" * 64,
                approval_id="product_approval_" + "4" * 64,
                approval_sha256="5" * 64,
                technical_design_id="technical_design_test",
                technical_design_sha256="6" * 64,
                execution_plan_id="execution_plan_test",
                execution_plan_sha256="7" * 64,
                planning_preview_id="planning_preview_" + "8" * 64,
                planning_preview_sha256="9" * 64,
                dispatch_commit_id="dispatch_commit_" + "a" * 64,
                dispatch_commit_sha256="b" * 64,
                task_id=inputs.task_id,
                task_revision=inputs.task_revision,
                task_status=TaskStatus.BLOCKED,
                candidate_revision=inputs.candidate_revision if retain_candidate else None,
                stage=DeliveryStage.BLOCKED,
                stage_attempts=DeliveryStageAttempts(delivering=1),
                next_action=DeliveryNextAction.REQUEST_HUMAN,
                failure_code=DeliveryFailureCode.INVALID_AGENT_OUTPUT,
                failure_summary="QA result needs independent verification",
                failed_stage=DeliveryStage.DELIVERING,
                checkpointed_at=NOW,
            )
        )
        assert source.dispatch_commit_sha256 is not None
        plan = CandidateVerificationPlan.create(
            scope=RecoveryScope(
                company_id="company_test",
                project_id=source.project_id,
                project_root=source.project_root,
                delivery_id=source.delivery_id,
            ),
            inputs=inputs,
            native_checkpoint_sha256=source.checkpoint_sha256,
            dispatch_sha256=source.dispatch_commit_sha256,
            approved_stage_chain_sha256="c" * 64,
            current_policy_sha256="d" * 64,
            definitions=tuple(_definitions().values()),
            created_at=NOW,
        )
        completion = CandidateVerificationCompletion.create(
            plan_sha256=plan.plan_sha256,
            authorization_sha256="e" * 64,
            qa_invocation_sha256="f" * 64,
            reviewer_invocation_sha256="1" * 64,
            qa=result.qa,
            review=result.review,
            completed_at=NOW + timedelta(minutes=2),
        )
        values = source.to_wire()
        values.pop("checkpoint_sha256")
        advanced = store.put(
            ProjectDeliveryCheckpoint.create(
                **{
                    **values,
                    "sequence": 2,
                    "previous_checkpoint_sha256": source.checkpoint_sha256,
                    "checkpointed_at": NOW + timedelta(minutes=1),
                }
            )
        )
        service = UnifiedProjectEntryService(
            backend=Mock(),
            catalog=ProjectDeliveryCheckpointCatalog(registry),
        )

        accepted = service.accept_verification(plan, completion).checkpoint

        assert accepted.stage is DeliveryStage.DONE
        assert accepted.previous_checkpoint_sha256 == advanced.checkpoint_sha256
        assert accepted.verification_plan_sha256 == plan.plan_sha256
    finally:
        repository.close()
