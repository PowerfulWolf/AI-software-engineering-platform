"""Executor failures authorize no source writes until a separate exact repair grant."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator, ValidationError

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.prerequisite_repair import (
    PrerequisiteRepairPlan,
    PrerequisiteRepairRequest,
)
from ai_software_engineer.manager.verification_coordination import (
    ManagerVerificationAdvice,
    ManagerVerificationDraft,
    VerificationFailureReference,
)
from ai_software_engineer.orchestration import FileRunContextBuilder
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryAuthorization,
    RecoveryRejected,
    RecoveryScope,
    VerificationExecutionBlocked,
    VerifiedRecoveryDecision,
    digest,
)
from ai_software_engineer.recovery.remediation import require_repair_authority
from ai_software_engineer.recovery.resume import DeliveryResumeController, DeliveryResumeOutcome
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification import CandidateVerificationRunner
from ai_software_engineer.recovery.verification_admission import (
    CandidateVerificationAdmission,
    ExplicitVerificationHuman,
)
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationPlan,
    VerificationExecutionRecord,
)
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions
from tests.recovery.test_candidate_verification import Admission, setup_verification
from tests.recovery.test_verification_admission import Facts
from tests.recovery.test_verification_environment import capability


def executor_failure(
    tmp_path: Path,
    role: AgentRole = AgentRole.QA,
) -> tuple[CandidateVerificationPlan, FileRecoveryStore, VerificationExecutionRecord]:
    class BeforeModel(ScriptedAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            if request.role is role:
                raise VerificationExecutionBlocked("e" * 64, "NATIVE_UI_UNAVAILABLE")
            return super().run(request)

    adapter = BeforeModel()
    inputs, repository, _ = setup_verification(tmp_path, adapter, Admission())
    plan = CandidateVerificationPlan.create(
        scope=RecoveryScope(
            team_id="team_test",
            repository_id="repository_test",
            delivery_id="delivery_test",
            repository_root=str(tmp_path / "project"),
        ),
        inputs=inputs,
        native_checkpoint_sha256="1" * 64,
        dispatch_sha256="2" * 64,
        approved_stage_chain_sha256="3" * 64,
        current_policy_sha256="4" * 64,
        definitions=tuple(_definitions().values()),
        created_at=_clock(),
        executor_capability=capability(),
    )
    store = FileRecoveryStore.initialize(tmp_path / "verification", scope=plan.scope)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    admission = CandidateVerificationAdmission(
        store=store, plan_sha256=plan.plan_sha256, facts=Facts(), artifacts=artifacts, clock=_clock
    )
    admission.propose(plan)
    admission.approve(
        RecoveryApprovalCommand(
            operation_id="op_executor",
            plan_sha256=plan.plan_sha256,
            approval_reference="fixture-user",
            submitted_at=_clock(),
        ),
        human=ExplicitVerificationHuman(plan.plan_sha256),
    )
    runner = CandidateVerificationRunner(
        repository=repository,
        artifact_store=artifacts,
        context_builder=FileRunContextBuilder(tmp_path / "project"),
        agent_adapter=adapter,
        agent_definitions=_definitions(),
        admission=admission,
        clock=_clock,
    )
    try:
        with pytest.raises(VerificationExecutionBlocked):
            runner.verify_candidate(inputs)
    finally:
        repository.close()
    invocation = store.get_verification_invocation(plan.plan_sha256, role)
    start = store.put_verification_execution(
        VerificationExecutionRecord.create(
            phase="STARTED",
            plan_sha256=plan.plan_sha256,
            invocation_sha256=invocation.invocation_sha256,
            authorization_sha256=invocation.authorization_sha256,
            candidate_revision=plan.inputs.candidate_revision,
            role=role,
            capability=capability(),
            source_root=str(tmp_path / "source"),
            scratch_root=str(tmp_path / "scratch"),
            recorded_at=_clock(),
        )
    )
    failed = store.put_verification_execution(
        VerificationExecutionRecord.create(
            **{
                **start.model_dump(exclude={"record_sha256"}),
                "phase": "BLOCKED",
                "failure_code": "NATIVE_UI_UNAVAILABLE",
            },
        )
    )
    return plan, store, failed


@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
def test_executor_observation_is_not_a_qa_completion_and_repair_is_separately_bound(
    tmp_path: Path,
    role: AgentRole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, failed = executor_failure(tmp_path, role)
    observation = store.record_executor_prerequisite(failed)
    assert observation.verified is False
    assert "qa" not in observation.to_wire() and "review" not in observation.to_wire()
    with pytest.raises(RecoveryRecordMissing):
        store.get_verification_completion(plan.plan_sha256)
    repair = PrerequisiteRepairPlan(
        repository_root=plan.scope.repository_root,
        delivery_id=plan.scope.delivery_id,
        source_task_id=plan.inputs.task_id,
        source_plan_sha256=plan.plan_sha256,
        executor_prerequisite_sha256=observation.observation_sha256,
        native_checkpoint_sha256=plan.native_checkpoint_sha256,
        candidate_revision=plan.inputs.candidate_revision,
        target_base_revision="f" * 40,
        target_preparation_sha256="5" * 64,
        request=PrerequisiteRepairRequest(
            objective="Repair the isolated test entry, preserving original criteria.",
            write_paths=("src/mock.py", "tests/**"),
        ),
        created_at=observation.observed_at,
        plan_sha256="0" * 64,
    )
    repair = repair.model_copy(update={"plan_sha256": repair.recompute_sha256()})
    store.put_repair_plan(repair)
    reopened = FileRecoveryStore(tmp_path / "verification", scope=plan.scope)
    assert reopened.get_repair_plan(repair.plan_sha256) == repair
    assert reopened.record_executor_prerequisite(failed) == observation
    assert (
        reopened.get_remediation_evidence(plan.plan_sha256, observation.observation_sha256)
        == observation
    )
    with pytest.raises(RecoveryRecordMissing):
        reopened.get_repair_authorization(repair.plan_sha256)
    with pytest.raises(RecoveryRecordMissing):
        require_repair_authority(reopened, repair, plan, observation, plan.native_checkpoint_sha256)
    for update in ({"candidate_revision": "f" * 40}, {"source_task_id": "task_other"}):
        changed = repair.model_copy(update=update)
        changed = changed.model_copy(update={"plan_sha256": changed.recompute_sha256()})
        with pytest.raises(RecoveryRejected):
            reopened.put_repair_plan(changed)
    with pytest.raises(ValueError, match="mutually exclusive"):
        PrerequisiteRepairPlan.model_validate({**repair.to_wire(), "completion_sha256": "a" * 64})
    validator = Draft202012Validator(
        json.loads(
            (Path(__file__).parents[2] / "schemas/candidate-verification.schema.json").read_text()
        )
    )
    validator.validate(observation.to_wire())
    validator.validate(repair.to_wire())
    with pytest.raises(ValidationError):
        validator.validate({**repair.to_wire(), "completion_sha256": "a" * 64})
    command = RecoveryApprovalCommand(
        operation_id="op_repair",
        plan_sha256=repair.plan_sha256,
        approval_reference="fixture-user",
        submitted_at=_clock(),
    )
    store.put_repair_authorization(
        RecoveryAuthorization.create(
            command,
            VerifiedRecoveryDecision(
                plan_sha256=repair.plan_sha256,
                approval_reference=command.approval_reference,
                approved=True,
                operator_id="fixture",
                rationale="Exact fixture repair",
                decided_at=_clock(),
            ),
        )
    )
    require_repair_authority(store, repair, plan, observation, plan.native_checkpoint_sha256)
    with pytest.raises(RecoveryRejected, match="authority"):
        require_repair_authority(store, repair, plan, observation, "f" * 64)
    from ai_software_engineer.recovery import verification_native as native

    monkeypatch.setattr(native, "FileRecoveryStore", lambda *args, **kwargs: store)
    checkpoint = Mock(
        checkpoint_sha256=plan.native_checkpoint_sha256, dispatch_commit_id="dispatch_fixture"
    )
    runtime = Mock()
    runtime.dispatch.dispatch_sha256 = plan.dispatch_sha256
    continuation = Mock(
        prerequisite_repair_sha256=repair.plan_sha256,
        continuation_plan_sha256=plan.plan_sha256,
        continuation_sha256=observation.observation_sha256,
        source_delivery_id=plan.scope.delivery_id,
        source_task_id=plan.inputs.task_id,
        source_revision=plan.inputs.candidate_revision,
        source_dispatch_id=checkpoint.dispatch_commit_id,
    )
    admitted = {store.get_verification_invocation(plan.plan_sha256, AgentRole.QA).request.run_id}
    if role is AgentRole.REVIEWER:
        admitted.add(store.get_verification_invocation(plan.plan_sha256, role).request.run_id)
    inputs = plan.inputs.model_copy(
        update={"prior_run_ids": tuple(sorted(set(plan.inputs.prior_run_ids) | admitted))}
    )
    native._validate_inconclusive_continuation(
        tmp_path, plan.scope, (checkpoint,), checkpoint, runtime, inputs, continuation
    )
    with pytest.raises(RecoveryRejected, match="executor prerequisite"):
        native._validate_inconclusive_continuation(
            tmp_path,
            plan.scope,
            (checkpoint,),
            checkpoint,
            runtime,
            inputs.model_copy(update={"prior_run_ids": (*inputs.prior_run_ids, "run_unadmitted")}),
            continuation,
        )


def test_manager_executor_repair_only_publishes_exact_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.recovery.test_delivery_continuation import _service
    from tests.recovery.test_execution_records import continuation_allocation

    plan, store, failed = executor_failure(tmp_path)
    advice = ManagerVerificationAdvice.create(
        input_sha256="6" * 64,
        scope_sha256=digest(plan.scope.to_wire()),
        candidate_revision=plan.inputs.candidate_revision,
        execution_failure=VerificationFailureReference(
            plan_sha256=plan.plan_sha256, record_sha256=failed.record_sha256, role=failed.role
        ),
        manager_run_id="manager_fixture",
        provider="fixture",
        model="fixture",
        draft=ManagerVerificationDraft(
            disposition="PROPOSE_REPAIR",
            summary="No primary mock window",
            next_action="Approve isolated test-entry repair",
            prerequisite_repair=PrerequisiteRepairRequest(
                objective="Create the primary isolated mock window on direct launch.",
                write_paths=("Sources/App.swift", "Tests/**"),
            ),
        ),
    )
    store.put_verification_advice(advice)
    backend = Mock()
    backend.prepare.return_value.preparation.preparation_sha256 = "e" * 64
    backend.delivery_base_revision.return_value = "d" * 40
    verification = Mock(backend=backend)
    verification.coordinate.return_value = advice
    verification.latest_project.return_value = (store, plan, tmp_path / "plan.json")
    entry = Mock()
    controller = DeliveryResumeController(
        config=Mock(),
        environment={},
        backend=backend,
        entry=entry,
        recovery=Mock(),
        verification=verification,
    )
    source = Mock()
    source.inputs.task_id = plan.inputs.task_id
    monkeypatch.setattr(controller, "_native_source", lambda _: source)
    fixture = tmp_path / "checkpoint-fixture"
    fixture.mkdir()
    allocation = continuation_allocation(fixture)
    _, checkpoints = _service(fixture, allocation)
    current = checkpoints.list(allocation.source_delivery_id)[0].model_copy(
        update={
            "repository_root": plan.scope.repository_root,
            "delivery_id": plan.scope.delivery_id,
            "checkpoint_sha256": plan.native_checkpoint_sha256,
        }
    )
    result = controller._coordinate_prerequisites(current, plan)
    assert result is not None and result.outcome is DeliveryResumeOutcome.REPAIR_APPROVAL_REQUIRED
    repair = result.prerequisite_repair_plan
    assert repair is not None and repair.manager_advice_input_sha256 == advice.input_sha256
    assert repair.executor_prerequisite_sha256 is not None and repair.completion_sha256 is None
    assert controller._coordinate_prerequisites(current, plan) == result
    verification.approve.assert_not_called()
    verification.execute.assert_not_called()
    backend.run_prepared_allocation.assert_not_called()
    entry.begin_continuation.assert_not_called()
    changed = repair.model_copy(
        update={"request": repair.request.model_copy(update={"write_paths": ("Sources/**",)})}
    )
    changed = changed.model_copy(update={"plan_sha256": changed.recompute_sha256()})
    with pytest.raises(RecoveryRejected, match="exact Manager proposal"):
        store.put_repair_plan(changed)
    from ai_software_engineer.web_console.manager import _summarize

    console = _summarize(result, project_id="project_test")
    assert console.approval is not None
    assert any("非 QA 结论" in fact for fact in console.approval.facts)


def test_executor_observation_rejects_tampering_and_completed_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, store, failed = executor_failure(tmp_path)
    observation = store.record_executor_prerequisite(failed)
    monkeypatch.setattr(store, "get_verification_completion", lambda _: Mock())
    with pytest.raises(RecoveryRejected, match="completed verification"):
        store.record_executor_prerequisite(failed)
    with pytest.raises(RecoveryRejected, match="completed verification"):
        store.get_executor_prerequisite(observation.observation_sha256)
    monkeypatch.undo()
    (
        tmp_path / "verification" / f"executor-prerequisite-{observation.observation_sha256}.json"
    ).write_text("{}")
    with pytest.raises(RecoveryRejected):
        store.get_executor_prerequisite(observation.observation_sha256)
