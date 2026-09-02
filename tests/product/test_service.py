"""Product discovery application workflow contract tests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.domain import (
    AcceptanceCriterion,
    ProductApprovalDecision,
    ProductRequirement,
    ProductSpec,
    ProductSpecApproval,
    ProductSpecStatus,
    ProjectPreparation,
    RequirementPriority,
)
from ai_software_engineer.product.agents import (
    FakeProductAgentAdapter,
    FakeProductBehavior,
    FakeProductScenario,
    ProductAgentErrorCode,
    ProductClarification,
)
from ai_software_engineer.product.models import (
    ProductDiscoveryCheckpoint,
    ProductDiscoveryStatus,
)
from ai_software_engineer.product.service import (
    HumanProductDecisionCommand,
    ProductDiscoveryOutcome,
    ProductDiscoveryService,
    ProductDiscoveryStaleCheckpoint,
    ProductDiscoveryStateError,
    ProductOperationConflict,
    RecordHumanMessageCommand,
    RunProductAgentCommand,
    StartProductDiscoveryCommand,
    VerifiedHumanProductDecision,
)
from ai_software_engineer.product.store import (
    FileProductRecordStore,
    ProductRecordNotFound,
)
from ai_software_engineer.project_manager import ProjectPreparationDrift
from ai_software_engineer.project_manager.stages import (
    ProjectStage,
    ProjectStageAdvancer,
)
from tests.product.factories import prepared_product_facts, product_knowledge

NOW = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
REQUEST_ID = "request_product_001"


class _ProjectManagerStageSkill:
    """Test double for the current-fact-revalidating Project Manager Skill."""

    def advance_stage(self, request):  # type: ignore[no-untyped-def]
        return ProjectStageAdvancer().advance_stage(request, authorized_at=NOW)


class _DriftedProjectManagerStageSkill:
    def advance_stage(self, request):  # type: ignore[no-untyped-def]
        del request
        raise ProjectPreparationDrift("project facts changed after Product discovery")


class _UnavailableProjectManagerStageSkill:
    def advance_stage(self, request):  # type: ignore[no-untyped-def]
        del request
        raise AssertionError("completed approval replay must not reauthorize")


class _CorruptProjectManagerStageSkill:
    def advance_stage(self, request):  # type: ignore[no-untyped-def]
        valid = ProjectStageAdvancer().advance_stage(request, authorized_at=NOW)
        return valid.model_copy(update={"project_id": "project_wrong_001"})


class _HumanDecisionVerifier:
    """Only references captured by this trusted test channel can approve."""

    def verify(self, command: HumanProductDecisionCommand) -> VerifiedHumanProductDecision:
        decisions = {
            "human://approval/approved": (
                ProductApprovalDecision.APPROVED,
                "Scope and acceptance criteria are correct.",
            ),
            "human://approval/changes": (
                ProductApprovalDecision.REQUEST_CHANGES,
                "Add the rollback acceptance behavior.",
            ),
        }
        try:
            decision, rationale = decisions[command.approval_reference]
        except KeyError as error:
            raise ValueError("unknown human approval reference") from error
        return VerifiedHumanProductDecision(
            approval_reference=command.approval_reference,
            request_id=command.request_id,
            product_spec_id=command.product_spec_id,
            product_spec_sha256=command.product_spec_sha256,
            decision=decision,
            operator_id="user_owner_001",
            rationale=rationale,
            decided_at=NOW,
        )


class _UnavailableHumanDecisionVerifier:
    def verify(self, command: HumanProductDecisionCommand) -> VerifiedHumanProductDecision:
        del command
        raise AssertionError("completed approval replay must not reverify")


class _FailOnceCheckpointStore(FileProductRecordStore):
    """Inject a crash after the operation receipt but before checkpoint commit."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.failed = False

    def put_checkpoint(self, checkpoint: ProductDiscoveryCheckpoint) -> ProductDiscoveryCheckpoint:
        if checkpoint.revision == 2 and not self.failed:
            self.failed = True
            raise RuntimeError("simulated process crash before checkpoint commit")
        return super().put_checkpoint(checkpoint)


class _FailOnceProductSpecStore(FileProductRecordStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.failed = False

    def put_product_spec(self, product_spec: ProductSpec) -> ProductSpec:
        if not self.failed:
            self.failed = True
            raise RuntimeError("simulated crash before ProductSpec publish")
        return super().put_product_spec(product_spec)


class _FailOnceApprovalStore(FileProductRecordStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.failed = False

    def put_approval(self, approval: ProductSpecApproval) -> ProductSpecApproval:
        if not self.failed:
            self.failed = True
            raise RuntimeError("simulated crash before approval publish")
        return super().put_approval(approval)


def _preparation(tmp_path: Path) -> ProjectPreparation:
    prepared, _, _ = prepared_product_facts(tmp_path)
    return prepared


def _spec(
    preparation: ProjectPreparation,
    *,
    version: int = 1,
    supersedes: str | None = None,
) -> ProductSpec:
    criterion = AcceptanceCriterion(
        id="ac_product_01",
        description="The delivered behavior matches the confirmed product requirement.",
        required=True,
        verification="Run the acceptance test.",
        test_ids=("test_product_acceptance",),
    )
    return ProductSpec.create(
        spec_id=f"product_spec_product_00{version}",
        request_id=REQUEST_ID,
        project_id=preparation.project_id,
        version=version,
        status=ProductSpecStatus.READY_FOR_REVIEW,
        summary="A reviewable product contract.",
        goals=("Preserve the exact user intent.",),
        requirements=(
            ProductRequirement(
                id="req_product_01",
                statement="Implement the confirmed behavior.",
                priority=RequirementPriority.MUST,
                rationale="The user explicitly requested it.",
                acceptance_criterion_ids=(criterion.id,),
            ),
        ),
        acceptance_criteria=(criterion,),
        supersedes=supersedes,
        created_at=NOW,
    )


def _service(
    tmp_path: Path,
    preparation: ProjectPreparation,
    scenarios: dict[str, FakeProductScenario],
    *,
    stage_advancer: (
        _ProjectManagerStageSkill
        | _DriftedProjectManagerStageSkill
        | _CorruptProjectManagerStageSkill
        | None
    ) = None,
    store: FileProductRecordStore | None = None,
) -> tuple[ProductDiscoveryService, FileProductRecordStore]:
    store = store or FileProductRecordStore(tmp_path / "records")
    profile, baseline = product_knowledge(preparation)
    return (
        ProductDiscoveryService(
            preparation=preparation,
            project_profile=profile,
            project_baseline=baseline,
            store=store,
            adapter=FakeProductAgentAdapter(scenarios=scenarios),
            stage_advancer=stage_advancer or _ProjectManagerStageSkill(),
            human_decision_verifier=_HumanDecisionVerifier(),
            clock=lambda: NOW,
        ),
        store,
    )


def _start(service: ProductDiscoveryService):  # type: ignore[no-untyped-def]
    return service.start(
        StartProductDiscoveryCommand(
            operation_id="start_product_001",
            request_id=REQUEST_ID,
            title="Add a product workflow",
            initial_requirement="Build a traceable Product Agent confirmation loop.",
            submitted_at=NOW,
        )
    )


def _ready(service: ProductDiscoveryService, checkpoint_sha256: str):  # type: ignore[no-untyped-def]
    return service.run_product(
        RunProductAgentCommand(
            run_id="run_product_ready_001",
            request_id=REQUEST_ID,
            expected_checkpoint_sha256=checkpoint_sha256,
            submitted_at=NOW,
        )
    )


def test_start_and_clarification_are_durable_and_replay_safe(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path)
    clarification = ProductClarification(
        summary="One product decision is missing.",
        questions=("Should the API reject stale approvals?",),
    )
    service, store = _service(
        tmp_path,
        preparation,
        {
            "run_product_clarify_001": FakeProductScenario(
                behavior=FakeProductBehavior.CLARIFY,
                clarification=clarification,
            )
        },
    )

    started = _start(service)
    clarified = service.run_product(
        RunProductAgentCommand(
            run_id="run_product_clarify_001",
            request_id=REQUEST_ID,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            submitted_at=NOW,
        )
    )
    replay = service.run_product(
        RunProductAgentCommand(
            run_id="run_product_clarify_001",
            request_id=REQUEST_ID,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            submitted_at=NOW,
        )
    )

    assert clarified.outcome is ProductDiscoveryOutcome.CLARIFICATION_REQUIRED
    assert clarified.clarification == clarification
    assert replay.replayed is True
    assert replay.checkpoint == clarified.checkpoint
    assert len(store.list_dialogue(REQUEST_ID)) == 2
    assert store.current_checkpoint(REQUEST_ID).revision == 2


def test_human_message_appends_from_exact_checkpoint(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path)
    service, store = _service(tmp_path, preparation, {})
    started = _start(service)

    result = service.record_human_message(
        RecordHumanMessageCommand(
            operation_id="message_product_001",
            request_id=REQUEST_ID,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            content="Yes, stale approvals must be rejected.",
            submitted_at=NOW,
        )
    )

    assert result.outcome is ProductDiscoveryOutcome.HUMAN_MESSAGE_RECORDED
    assert result.dialogue is not None
    assert result.dialogue.actor.value == "HUMAN"
    assert len(store.list_dialogue(REQUEST_ID)) == 2


def test_ready_spec_exact_human_approval_unlocks_designer(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path)
    spec = _spec(preparation)
    service, store = _service(
        tmp_path,
        preparation,
        {
            "run_product_ready_001": FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=spec,
            )
        },
    )
    started = _start(service)
    ready = _ready(service, started.checkpoint.checkpoint_sha256)

    approved = service.decide_as_human(
        HumanProductDecisionCommand(
            operation_id="approve_product_001",
            request_id=REQUEST_ID,
            expected_checkpoint_sha256=ready.checkpoint.checkpoint_sha256,
            product_spec_id=spec.id,
            product_spec_sha256=spec.product_spec_sha256,
            approval_reference="human://approval/approved",
            submitted_at=NOW,
        )
    )
    replay = service.decide_as_human(
        HumanProductDecisionCommand(
            operation_id="approve_product_001",
            request_id=REQUEST_ID,
            expected_checkpoint_sha256=ready.checkpoint.checkpoint_sha256,
            product_spec_id=spec.id,
            product_spec_sha256=spec.product_spec_sha256,
            approval_reference="human://approval/approved",
            submitted_at=NOW,
        )
    )

    assert ready.outcome is ProductDiscoveryOutcome.READY_FOR_APPROVAL
    assert approved.outcome is ProductDiscoveryOutcome.APPROVED
    assert approved.authorization is not None
    assert approved.authorization.target is ProjectStage.SOLUTION_DESIGN
    assert replay.replayed is True
    assert store.current_checkpoint(REQUEST_ID).status is ProductDiscoveryStatus.APPROVED


def test_request_changes_requires_next_version_and_supersedes(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path)
    first = _spec(preparation)
    second = _spec(preparation, version=2, supersedes=first.id)
    service, store = _service(
        tmp_path,
        preparation,
        {
            "run_product_ready_001": FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=first,
            ),
            "run_product_ready_002": FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=second,
            ),
        },
    )
    ready = _ready(service, _start(service).checkpoint.checkpoint_sha256)
    changes = service.decide_as_human(
        HumanProductDecisionCommand(
            operation_id="changes_product_001",
            request_id=REQUEST_ID,
            expected_checkpoint_sha256=ready.checkpoint.checkpoint_sha256,
            product_spec_id=first.id,
            product_spec_sha256=first.product_spec_sha256,
            approval_reference="human://approval/changes",
            submitted_at=NOW,
        )
    )
    revised = service.run_product(
        RunProductAgentCommand(
            run_id="run_product_ready_002",
            request_id=REQUEST_ID,
            expected_checkpoint_sha256=changes.checkpoint.checkpoint_sha256,
            submitted_at=NOW,
        )
    )

    assert changes.outcome is ProductDiscoveryOutcome.CHANGES_REQUESTED
    assert changes.authorization is None
    assert revised.product_spec == second
    assert revised.checkpoint.current_product_spec_version == 2
    assert store.list_product_specs(REQUEST_ID) == (first, second)


@pytest.mark.parametrize(
    ("behavior", "expected_outcome", "error_code"),
    [
        (
            FakeProductBehavior.INVALID_OUTPUT,
            ProductDiscoveryOutcome.AGENT_FAILED,
            ProductAgentErrorCode.INVALID_OUTPUT,
        ),
        (
            FakeProductBehavior.PROVIDER_ERROR,
            ProductDiscoveryOutcome.AGENT_FAILED,
            ProductAgentErrorCode.PROVIDER_ERROR,
        ),
        (
            FakeProductBehavior.TIMEOUT,
            ProductDiscoveryOutcome.AGENT_TIMED_OUT,
            ProductAgentErrorCode.TIMEOUT,
        ),
    ],
)
def test_agent_failures_do_not_write_spec_or_advance_checkpoint(
    tmp_path: Path,
    behavior: FakeProductBehavior,
    expected_outcome: ProductDiscoveryOutcome,
    error_code: ProductAgentErrorCode,
) -> None:
    preparation = _preparation(tmp_path)
    service, store = _service(
        tmp_path,
        preparation,
        {"run_product_failure_001": FakeProductScenario(behavior=behavior)},
    )
    started = _start(service)

    result = service.run_product(
        RunProductAgentCommand(
            run_id="run_product_failure_001",
            request_id=REQUEST_ID,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            submitted_at=NOW,
        )
    )

    assert result.outcome is expected_outcome
    assert result.agent_error_code is error_code
    assert store.current_checkpoint(REQUEST_ID) == started.checkpoint
    assert store.list_product_specs(REQUEST_ID) == ()
    assert store.current_request_revision(REQUEST_ID) == started.request_revision


def test_stale_approval_and_changed_operation_replay_fail_closed(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path)
    spec = _spec(preparation)
    service, _ = _service(
        tmp_path,
        preparation,
        {
            "run_product_ready_001": FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=spec,
            )
        },
    )
    started = _start(service)
    ready = _ready(service, started.checkpoint.checkpoint_sha256)

    with pytest.raises(ProductDiscoveryStaleCheckpoint):
        service.decide_as_human(
            HumanProductDecisionCommand(
                operation_id="approve_product_stale_001",
                request_id=REQUEST_ID,
                expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
                product_spec_id=spec.id,
                product_spec_sha256=spec.product_spec_sha256,
                approval_reference="human://approval/approved",
                submitted_at=NOW,
            )
        )
    with pytest.raises(ProductOperationConflict):
        service.start(
            StartProductDiscoveryCommand(
                operation_id="start_product_001",
                request_id=REQUEST_ID,
                title="Changed replay",
                initial_requirement="A different requirement.",
                submitted_at=NOW,
            )
        )
    with pytest.raises(ProductDiscoveryStateError):
        service.record_human_message(
            RecordHumanMessageCommand(
                operation_id="message_too_late_001",
                request_id=REQUEST_ID,
                expected_checkpoint_sha256=ready.checkpoint.checkpoint_sha256,
                content="This cannot silently reopen approval.",
                submitted_at=NOW,
            )
        )


def test_unverified_human_reference_cannot_create_approval(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path)
    spec = _spec(preparation)
    service, store = _service(
        tmp_path,
        preparation,
        {
            "run_product_ready_001": FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=spec,
            )
        },
    )
    ready = _ready(service, _start(service).checkpoint.checkpoint_sha256)

    with pytest.raises(ProductDiscoveryStateError, match="could not be verified"):
        service.decide_as_human(
            HumanProductDecisionCommand(
                operation_id="approve_product_forged_001",
                request_id=REQUEST_ID,
                expected_checkpoint_sha256=ready.checkpoint.checkpoint_sha256,
                product_spec_id=spec.id,
                product_spec_sha256=spec.product_spec_sha256,
                approval_reference="agent://self-approval",
                submitted_at=NOW,
            )
        )

    assert store.current_checkpoint(REQUEST_ID) == ready.checkpoint
    with pytest.raises(ProductRecordNotFound):
        store.get_approval(REQUEST_ID, spec.id)


def test_project_drift_blocks_approval_before_any_approval_fact_is_written(
    tmp_path: Path,
) -> None:
    preparation = _preparation(tmp_path)
    spec = _spec(preparation)
    service, store = _service(
        tmp_path,
        preparation,
        {
            "run_product_ready_001": FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=spec,
            )
        },
        stage_advancer=_DriftedProjectManagerStageSkill(),
    )
    ready = _ready(service, _start(service).checkpoint.checkpoint_sha256)

    with pytest.raises(ProjectPreparationDrift):
        service.decide_as_human(
            HumanProductDecisionCommand(
                operation_id="approve_product_drifted_001",
                request_id=REQUEST_ID,
                expected_checkpoint_sha256=ready.checkpoint.checkpoint_sha256,
                product_spec_id=spec.id,
                product_spec_sha256=spec.product_spec_sha256,
                approval_reference="human://approval/approved",
                submitted_at=NOW,
            )
        )

    assert store.current_checkpoint(REQUEST_ID) == ready.checkpoint
    with pytest.raises(ProductRecordNotFound):
        store.get_approval(REQUEST_ID, spec.id)


def test_completed_approval_replays_without_external_verifier_or_reauthorization(
    tmp_path: Path,
) -> None:
    preparation = _preparation(tmp_path)
    spec = _spec(preparation)
    service, store = _service(
        tmp_path,
        preparation,
        {
            "run_product_ready_001": FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=spec,
            )
        },
    )
    ready = _ready(service, _start(service).checkpoint.checkpoint_sha256)
    command = HumanProductDecisionCommand(
        operation_id="approve_product_restart_001",
        request_id=REQUEST_ID,
        expected_checkpoint_sha256=ready.checkpoint.checkpoint_sha256,
        product_spec_id=spec.id,
        product_spec_sha256=spec.product_spec_sha256,
        approval_reference="human://approval/approved",
        submitted_at=NOW,
    )
    approved = service.decide_as_human(command)
    restarted = ProductDiscoveryService(
        preparation=preparation,
        project_profile=product_knowledge(preparation)[0],
        project_baseline=product_knowledge(preparation)[1],
        store=store,
        adapter=FakeProductAgentAdapter(),
        stage_advancer=_UnavailableProjectManagerStageSkill(),
        human_decision_verifier=_UnavailableHumanDecisionVerifier(),
        clock=lambda: NOW,
    )

    replay = restarted.decide_as_human(command)

    assert replay.replayed is True
    assert replay.authorization == approved.authorization
    assert replay.approval == approved.approval


def test_operation_receipt_recovers_checkpoint_after_interrupted_commit(
    tmp_path: Path,
) -> None:
    preparation = _preparation(tmp_path)
    spec = _spec(preparation)
    store = _FailOnceCheckpointStore(tmp_path / "records")
    service, _ = _service(
        tmp_path,
        preparation,
        {
            "run_product_ready_001": FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=spec,
            )
        },
        store=store,
    )
    started = _start(service)
    command = RunProductAgentCommand(
        run_id="run_product_ready_001",
        request_id=REQUEST_ID,
        expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
        submitted_at=NOW,
    )

    with pytest.raises(RuntimeError, match="simulated process crash"):
        service.run_product(command)

    recovered = service.run_product(command)

    assert recovered.replayed is True
    assert recovered.outcome is ProductDiscoveryOutcome.READY_FOR_APPROVAL
    assert recovered.product_spec == spec
    assert store.current_checkpoint(REQUEST_ID) == recovered.checkpoint


def test_receipt_recovers_effects_without_reinvoking_product_agent(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path)
    spec = _spec(preparation)
    store = _FailOnceProductSpecStore(tmp_path / "records")
    service, _ = _service(
        tmp_path,
        preparation,
        {
            "run_product_ready_001": FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=spec,
            )
        },
        store=store,
    )
    started = _start(service)
    command = RunProductAgentCommand(
        run_id="run_product_ready_001",
        request_id=REQUEST_ID,
        expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
        submitted_at=NOW,
    )

    with pytest.raises(RuntimeError, match="ProductSpec publish"):
        service.run_product(command)

    restarted = ProductDiscoveryService(
        preparation=preparation,
        project_profile=product_knowledge(preparation)[0],
        project_baseline=product_knowledge(preparation)[1],
        store=store,
        adapter=FakeProductAgentAdapter(),
        stage_advancer=_UnavailableProjectManagerStageSkill(),
        human_decision_verifier=_UnavailableHumanDecisionVerifier(),
    )
    recovered = restarted.run_product(command)

    assert recovered.replayed is True
    assert recovered.product_spec == spec
    assert store.current_checkpoint(REQUEST_ID) == recovered.checkpoint


def test_receipt_recovers_approval_without_reverification_or_reauthorization(
    tmp_path: Path,
) -> None:
    preparation = _preparation(tmp_path)
    spec = _spec(preparation)
    store = _FailOnceApprovalStore(tmp_path / "records")
    service, _ = _service(
        tmp_path,
        preparation,
        {
            "run_product_ready_001": FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=spec,
            )
        },
        store=store,
    )
    ready = _ready(service, _start(service).checkpoint.checkpoint_sha256)
    command = HumanProductDecisionCommand(
        operation_id="approve_product_crash_001",
        request_id=REQUEST_ID,
        expected_checkpoint_sha256=ready.checkpoint.checkpoint_sha256,
        product_spec_id=spec.id,
        product_spec_sha256=spec.product_spec_sha256,
        approval_reference="human://approval/approved",
        submitted_at=NOW,
    )

    with pytest.raises(RuntimeError, match="approval publish"):
        service.decide_as_human(command)

    restarted = ProductDiscoveryService(
        preparation=preparation,
        project_profile=product_knowledge(preparation)[0],
        project_baseline=product_knowledge(preparation)[1],
        store=store,
        adapter=FakeProductAgentAdapter(),
        stage_advancer=_UnavailableProjectManagerStageSkill(),
        human_decision_verifier=_UnavailableHumanDecisionVerifier(),
    )
    recovered = restarted.decide_as_human(command)

    assert recovered.replayed is True
    assert recovered.outcome is ProductDiscoveryOutcome.APPROVED
    assert recovered.authorization is not None
    assert store.current_checkpoint(REQUEST_ID) == recovered.checkpoint


def test_invalid_stage_authorization_cannot_approve_product_spec(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path)
    spec = _spec(preparation)
    service, store = _service(
        tmp_path,
        preparation,
        {
            "run_product_ready_001": FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=spec,
            )
        },
        stage_advancer=_CorruptProjectManagerStageSkill(),
    )
    ready = _ready(service, _start(service).checkpoint.checkpoint_sha256)

    with pytest.raises(ProductDiscoveryStateError, match="invalid solution-design"):
        service.decide_as_human(
            HumanProductDecisionCommand(
                operation_id="approve_product_bad_auth_001",
                request_id=REQUEST_ID,
                expected_checkpoint_sha256=ready.checkpoint.checkpoint_sha256,
                product_spec_id=spec.id,
                product_spec_sha256=spec.product_spec_sha256,
                approval_reference="human://approval/approved",
                submitted_at=NOW,
            )
        )

    assert store.current_checkpoint(REQUEST_ID) == ready.checkpoint
    with pytest.raises(ProductRecordNotFound):
        store.get_approval(REQUEST_ID, spec.id)
