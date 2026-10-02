"""Normal Continue asks Manager for a durable remedy before repeating QA approval."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents.structured import StructuredModelResult
from ai_software_engineer.artifacts import FileArtifactStore, artifact_digest, seal_artifact
from ai_software_engineer.domain import AgentRole, QaCriterionStatus, QaReportStatus
from ai_software_engineer.domain.artifact import QaReportArtifact
from ai_software_engineer.execution import CommandResult
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.native_ui import (
    NativeUiNode,
    NativeUiOutput,
    NativeUiResult,
    NativeUiScenario,
    NativeUiSession,
    NativeUiSessionPrerequisite,
    native_ui_capability,
)
from ai_software_engineer.manager.verification_coordination import (
    ManagerVerificationAdvice,
    ManagerVerificationDraft,
    VerificationFailureReference,
)
from ai_software_engineer.manager.verification_environment import swift_sandbox_command
from ai_software_engineer.recovery import verification_entry as module
from ai_software_engineer.recovery.models import (
    RecoveryRejected,
    RecoveryScope,
    VerificationExecutionBlocked,
    digest,
)
from ai_software_engineer.recovery.resume import DeliveryResumeController, DeliveryResumeOutcome
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification_entry import CandidateVerificationEntry
from ai_software_engineer.recovery.verification_native import NativeCandidateSourceReader
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationInputs,
    CandidateVerificationPlan,
    VerificationExecutionRecord,
)
from tests.agents.test_candidate_review_source import repository as source_repository
from tests.domain.factories import (
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_task,
)
from tests.knowledge.test_audit_qa import _approved_resolution
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions
from tests.recovery.test_candidate_verification import Admission, setup_verification
from tests.recovery.test_delivery_continuation import _service, _verification_for
from tests.recovery.test_execution_records import continuation_allocation
from tests.recovery.test_native_ui import scenario
from tests.recovery.test_verification_environment import _admitted


@pytest.fixture(autouse=True)
def manager_claim_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.manager.test_manager_model_execution import executor

    monkeypatch.setattr(module, "_manager_executor", lambda *_: executor(tmp_path / "manager-runs"))


def _mock_source_view(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    # These tests isolate coordination/caching; the real Git source seam is tested below.
    monkeypatch.setattr(module, "candidate_read_scope", lambda *_: None)
    monkeypatch.setattr(module, "candidate_review_snapshot", lambda *_: text)


def test_manager_reads_real_candidate_scope_without_unrelated_repository_bulk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, scope = source_repository(tmp_path)
    task = make_task().model_copy(update={"base_ref": scope.base_revision, "repository": str(root)})
    plan_art = make_plan_artifact()
    plan_art = seal_artifact(
        plan_art.model_copy(
            update={
                "source_revision": scope.base_revision,
                "content": plan_art.content.model_copy(
                    update={
                        "steps": (
                            plan_art.content.steps[0].model_copy(
                                update={"files": ("dependency.txt", "new.py")}
                            ),
                        )
                    }
                ),
            }
        ),
        validated_at=_clock(),
    )
    implementation = make_implementation_artifact()
    implementation = seal_artifact(
        implementation.model_copy(
            update={
                "source_revision": scope.candidate_revision,
                "content": implementation.content.model_copy(
                    update={"commit_sha": scope.candidate_revision}
                ),
            }
        ),
        validated_at=_clock(),
    )
    qa = make_qa_artifact()
    qa = seal_artifact(
        qa.model_copy(
            update={
                "source_revision": scope.candidate_revision,
                "content": qa.content.model_copy(
                    update={
                        "status": QaReportStatus.FAIL,
                        "criteria_results": tuple(
                            c.model_copy(update={"status": QaCriterionStatus.NOT_TESTED})
                            for c in qa.content.criteria_results
                        ),
                    }
                ),
            }
        ),
        validated_at=_clock(),
    )
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    for artifact in (plan_art, implementation, qa):
        artifacts.put(artifact)
    inputs = CandidateVerificationInputs(
        task_id=task.id,
        task_revision=3,
        task_sha256=digest(task.to_wire()),
        plan_id=plan_art.artifact_id,
        plan_sha256=artifact_digest(plan_art),
        implementation_id=implementation.artifact_id,
        implementation_sha256=artifact_digest(implementation),
        candidate_revision=scope.candidate_revision,
    )
    plan = CandidateVerificationPlan.create(
        scope=RecoveryScope(
            team_id="team_test",
            repository_id="repository_test",
            repository_root=str(root),
            delivery_id="delivery_test",
        ),
        inputs=inputs,
        native_checkpoint_sha256="1" * 64,
        dispatch_sha256="2" * 64,
        approved_stage_chain_sha256="3" * 64,
        current_policy_sha256="4" * 64,
        definitions=tuple(_definitions().values()),
        created_at=_clock(),
    )
    source = SimpleNamespace(
        parent_delivery_id=None,
        inputs=inputs,
        scope=plan.scope,
        stages=SimpleNamespace(
            preparation=SimpleNamespace(repository_workspace_root=str(tmp_path))
        ),
        runtime=SimpleNamespace(
            task=task, events=(SimpleNamespace(artifact_ids=(qa.artifact_id,)),)
        ),
    )
    store = FileRecoveryStore.initialize(tmp_path / "verification", scope=plan.scope)
    store.put_verification_plan(plan)
    monkeypatch.setattr(NativeCandidateSourceReader, "inspect", lambda *_: source)
    monkeypatch.setattr(module, "verification_store_root", lambda _: tmp_path / "verification")
    monkeypatch.setattr(module, "_manager_resolutions", lambda *_: ())
    client = Mock()
    client.complete.return_value = StructuredModelResult(
        payload={
            "disposition": "WAITING_HUMAN",
            "summary": "Missing independent executor",
            "next_action": "Approve the exact controlled test capability",
        },
        duration_ms=1,
    )
    backend = Mock()
    backend._structured_clients.for_project.return_value = client
    assert CandidateVerificationEntry(Mock(), {}, backend).coordinate(plan) is not None
    snapshot = client.complete.call_args.kwargs["input_payload"]["candidate_source"]
    assert "first change must remain visible" in snapshot
    assert "required dependency" in snapshot
    assert "irrelevant baseline" not in snapshot
    assert scope.base_revision in snapshot and scope.candidate_revision in snapshot


@pytest.mark.parametrize("verification_completed", [False, True])
def test_manager_uses_durable_qa_order_not_report_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verification_completed: bool
) -> None:
    plan, store, _, _, completion = _admitted(tmp_path, environment_error=True)
    qa = completion.qa
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    stale = QaReportArtifact.model_validate(
        seal_artifact(
            qa.model_copy(
                update={
                    "artifact_id": "art_qa_old_future_timestamp",
                    "created_at": qa.created_at + timedelta(days=1),
                }
            ),
            validated_at=_clock(),
        ).to_wire()
    )
    artifacts.put(stale)
    events: tuple[SimpleNamespace, ...] = (SimpleNamespace(artifact_ids=(stale.artifact_id,)),)
    if not verification_completed:
        events += (SimpleNamespace(artifact_ids=(qa.artifact_id,)),)
        monkeypatch.setattr(FileRecoveryStore, "latest_verification_completion", lambda _: None)
    source = SimpleNamespace(
        inputs=plan.inputs,
        scope=plan.scope,
        stages=SimpleNamespace(
            preparation=SimpleNamespace(repository_workspace_root=str(tmp_path))
        ),
        runtime=SimpleNamespace(task=make_task(), events=events),
    )
    monkeypatch.setattr(NativeCandidateSourceReader, "inspect", lambda *_: source)
    monkeypatch.setattr(module, "verification_store_root", lambda _: tmp_path / "verification")
    _mock_source_view(monkeypatch, "bounded candidate source")
    monkeypatch.setattr(module, "_manager_resolutions", lambda *_: ())
    client = Mock()
    client.complete.return_value = StructuredModelResult(
        payload={
            "disposition": "WAITING_HUMAN",
            "summary": "Manager coordinates the current QA finding",
            "next_action": "Platform owner supplies the missing verification capability",
        },
        duration_ms=1,
    )
    backend = Mock()
    backend._structured_clients.for_project.return_value = client
    advice = CandidateVerificationEntry(Mock(), {}, backend).coordinate(plan)
    assert advice is not None and advice.qa_artifact_id == qa.artifact_id
    assert client.complete.call_args.kwargs["input_payload"]["qa"] == qa.to_wire()
    capability = client.complete.call_args.kwargs["input_payload"]["available_ui_capability"]
    assert capability["screenshots"]["max_per_scenario"] == 6
    assert "never desktop" in capability["screenshots"]["scope"]
    assert "scroll" in capability["actions"]
    assert "no role/attribute/value/index" in capability["scroll"]["selectors"]
    assert CandidateVerificationEntry(Mock(), {}, backend).coordinate(plan) == advice
    client.complete.assert_called_once()
    assert artifacts.get(stale.artifact_id) == stale
    if verification_completed:
        assert store.get_verification_completion(plan.plan_sha256) == completion


def test_manager_decision_is_bound_cached_and_reopened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, repository, _ = setup_verification(tmp_path, ScriptedAdapter(), Admission())
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    qa = make_qa_artifact().model_copy(
        update={
            "task_id": inputs.task_id,
            "source_revision": inputs.candidate_revision,
            "parent_artifact_ids": (inputs.implementation_id,),
        }
    )
    qa = QaReportArtifact.model_validate(
        seal_artifact(
            qa.model_copy(
                update={
                    "artifact_id": "art_qa_inconclusive",
                    "content": qa.content.model_copy(
                        update={
                            "status": QaReportStatus.FAIL,
                            "criteria_results": tuple(
                                c.model_copy(update={"status": QaCriterionStatus.NOT_TESTED})
                                for c in qa.content.criteria_results
                            ),
                        }
                    ),
                }
            ),
            validated_at=_clock(),
        ).to_wire()
    )
    artifacts.put(qa)
    plan = CandidateVerificationPlan.create(
        scope=RecoveryScope(
            team_id="team_test",
            repository_id="repository_test",
            repository_root=str(tmp_path / "project"),
            delivery_id="delivery_test",
        ),
        inputs=inputs,
        native_checkpoint_sha256="1" * 64,
        dispatch_sha256="2" * 64,
        approved_stage_chain_sha256="3" * 64,
        current_policy_sha256="4" * 64,
        definitions=tuple(_definitions().values()),
        created_at=_clock(),
    )
    source = SimpleNamespace(
        parent_delivery_id=None,
        inputs=inputs,
        scope=plan.scope,
        stages=SimpleNamespace(
            preparation=SimpleNamespace(repository_workspace_root=str(tmp_path))
        ),
        runtime=SimpleNamespace(
            task=repository.get(inputs.task_id),
            events=(SimpleNamespace(artifact_ids=(qa.artifact_id,)),),
        ),
    )
    repository.close()
    (tmp_path / "state").mkdir()
    store = FileRecoveryStore.initialize(
        tmp_path / "state" / f"candidate-verification-{plan.scope.delivery_id}", scope=plan.scope
    )
    store.put_verification_plan(plan)
    monkeypatch.setattr(NativeCandidateSourceReader, "inspect", lambda *_: source)
    _mock_source_view(monkeypatch, "exact bounded source")
    _, resolution = _approved_resolution(tmp_path / "knowledge", task_id=inputs.task_id)
    monkeypatch.setattr(module, "_manager_resolutions", lambda *_: (resolution,))
    client = Mock()
    client.complete.return_value = StructuredModelResult(
        payload={
            "disposition": "WAITING_HUMAN",
            "summary": "UI executor unavailable",
            "next_action": "Manager requests executor provisioning; resume after probe succeeds",
        },
        duration_ms=1,
        provider="fixture",
        model="fixture",
    )
    backend = Mock()
    backend._structured_clients.for_project.return_value = client
    advice = CandidateVerificationEntry(Mock(), {}, backend).coordinate(plan)
    assert advice is not None
    assert advice.qa_artifact_id == qa.artifact_id
    assert advice.qa_artifact_sha256 == qa.integrity.sha256
    assert advice.draft.disposition == "WAITING_HUMAN"
    assert advice.knowledge_resolutions == (resolution,)
    assert client.complete.call_args.kwargs["input_payload"]["approved_knowledge_resolutions"] == [
        resolution.to_wire()
    ]
    reopened = CandidateVerificationEntry(Mock(), {}, backend).coordinate(plan)
    assert reopened == advice
    client.complete.assert_called_once()
    assert store.get_verification_advice(advice.input_sha256) == advice
    with pytest.raises(RecoveryRejected, match="another delivery scope"):
        store.put_verification_advice(
            ManagerVerificationAdvice.create(
                **{**advice.model_dump(exclude={"advice_sha256"}), "scope_sha256": "f" * 64}
            )
        )


@pytest.mark.parametrize("ui", [False, True])
def test_continue_routes_manager_remedy_before_old_approval(tmp_path: Path, ui: bool) -> None:
    dispatch = continuation_allocation(tmp_path)
    _, journal = _service(tmp_path, dispatch)
    _, plan, _ = _verification_for(journal, dispatch)
    current = journal.current(plan.scope.delivery_id)
    store = Mock()
    from ai_software_engineer.recovery.store import RecoveryRecordMissing

    store.get_verification_invocation.side_effect = RecoveryRecordMissing("not admitted")
    draft = ManagerVerificationDraft(
        disposition="PROPOSE_UI" if ui else "WAITING_HUMAN",
        summary="Manager owns the blocker",
        next_action="Approve bounded GUI probe" if ui else "Unlock desktop then resume",
        native_ui_scenario=NativeUiScenario.model_validate(
            {
                "product": "Fixture",
                "mock_argument": "--mock-ui",
                "window_title": "Fixture",
                "steps": [{"name": "initial"}],
            }
        )
        if ui
        else None,
    )
    advice = ManagerVerificationAdvice.create(
        input_sha256="1" * 64,
        scope_sha256=digest(plan.scope.to_wire()),
        candidate_revision=plan.inputs.candidate_revision,
        qa_artifact_id="art_qa_fixture",
        qa_artifact_sha256="2" * 64,
        manager_run_id="manager_run_fixture",
        provider="fixture",
        model="fixture",
        draft=draft,
    )
    verifier = Mock()
    verifier.latest_project.return_value = (store, plan, tmp_path / "old.json")
    verifier.coordinate.return_value = advice
    verifier.propose_project.return_value = (plan, tmp_path / "new.json")
    entry = Mock()
    entry.status.return_value = SimpleNamespace(checkpoint=current)
    entry.retry_interrupted_stage.return_value = SimpleNamespace(checkpoint=current)
    controller = DeliveryResumeController(
        config=Mock(),
        environment={},
        backend=Mock(),
        entry=entry,
        recovery=Mock(),
        verification=verifier,
    )
    outcome = controller.resume(
        ResumeProjectDelivery(
            delivery_id=current.delivery_id,
            approved_plan_sha256=plan.plan_sha256,
            approval_reference="old build-only plan",
        )
    )
    verifier.approve.assert_not_called()
    verifier.execute.assert_not_called()
    if ui:
        assert outcome.outcome is DeliveryResumeOutcome.VERIFICATION_APPROVAL_REQUIRED
        assert verifier.propose_project.call_args.kwargs["manager_advice"] == advice
    else:
        assert outcome.outcome is DeliveryResumeOutcome.WAITING_HUMAN
        assert "Unlock desktop" in outcome.next_action
        verifier.propose_project.assert_not_called()


@pytest.mark.parametrize("already_admitted", [False, True])
@pytest.mark.parametrize("desktop_locked", [False, True])
def test_executor_block_returns_to_manager_before_identical_reapproval(
    tmp_path: Path, already_admitted: bool, desktop_locked: bool
) -> None:
    dispatch = continuation_allocation(tmp_path)
    _, journal = _service(tmp_path, dispatch)
    _, plan, _ = _verification_for(journal, dispatch)
    current = journal.current(plan.scope.delivery_id)
    store = Mock()
    store.get_verification_completion.side_effect = RecoveryRecordMissing("no verdict")
    if not already_admitted:
        store.get_verification_invocation.side_effect = RecoveryRecordMissing("not admitted")
    advice = ManagerVerificationAdvice.create(
        input_sha256="1" * 64,
        scope_sha256=digest(plan.scope.to_wire()),
        candidate_revision=plan.inputs.candidate_revision,
        qa_artifact_id="art_qa_fixture",
        qa_artifact_sha256="2" * 64,
        manager_run_id="manager_run_fixture",
        provider="fixture",
        model="fixture",
        execution_failure=VerificationFailureReference(
            plan_sha256=plan.plan_sha256, record_sha256="f" * 64, role=AgentRole.QA
        )
        if desktop_locked
        else None,
        environment_prerequisite=NativeUiSessionPrerequisite(
            observed_status="SESSION_LOCKED",
            current_session=NativeUiSession(status="SESSION_LOCKED"),
        )
        if desktop_locked
        else None,
        draft=ManagerVerificationDraft(
            disposition="WAITING_HUMAN",
            summary="Initial AX snapshot has zero windows",
            next_action="Platform owner must provide a bounded window-launch diagnostic capability",
        ),
    )
    verifier = Mock()
    verifier.latest_project.return_value = (store, plan, tmp_path / "plan.json")
    verifier.coordinate.side_effect = [advice] if already_admitted else [None, advice]
    verifier.execute.side_effect = VerificationExecutionBlocked("e" * 64, "NATIVE_UI_UNAVAILABLE")
    verifier.propose_project.return_value = (plan, tmp_path / "successor.json")
    entry = Mock()
    entry.status.return_value = SimpleNamespace(checkpoint=current)
    entry.retry_interrupted_stage.return_value = SimpleNamespace(checkpoint=current)
    result = DeliveryResumeController(
        config=Mock(),
        environment={},
        backend=Mock(),
        entry=entry,
        recovery=Mock(),
        verification=verifier,
    ).resume(ResumeProjectDelivery(delivery_id=current.delivery_id))
    assert result.outcome is DeliveryResumeOutcome.WAITING_HUMAN
    if desktop_locked:
        assert "请解锁运行 ASE 的 Mac" in result.next_action
        assert "旧计划不能重放" in result.next_action
        assert "Platform owner" not in result.next_action
    else:
        assert "zero windows" in result.next_action
        assert "Platform owner" in result.next_action
    verifier.propose_project.assert_not_called()
    assert verifier.coordinate.call_count == (1 if already_admitted else 2)


@pytest.mark.parametrize(
    "failure_code",
    ["NATIVE_UI_UNAVAILABLE", "NATIVE_UI_SESSION_LOCKED", None],
)
def test_first_executor_failure_reaches_manager_and_reopens_without_qa_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_code: str | None
) -> None:
    ui = native_ui_capability(scenario())
    plan, store, _, _, _ = _admitted(tmp_path, native_ui=ui)
    invocation = store.get_verification_invocation(plan.plan_sha256, AgentRole.QA)
    started = store.put_verification_execution(
        VerificationExecutionRecord.create(
            phase="STARTED",
            plan_sha256=plan.plan_sha256,
            invocation_sha256=invocation.invocation_sha256,
            authorization_sha256=invocation.authorization_sha256,
            candidate_revision=plan.inputs.candidate_revision,
            role=AgentRole.QA,
            capability=plan.executor_capability,
            native_ui=ui,
            source_root=str(tmp_path / "source"),
            scratch_root=str(tmp_path / "scratch"),
            recorded_at=_clock(),
        )
    )
    actions: tuple[Literal["build", "test"], ...] = ("build", "test")
    failed = store.put_verification_execution(
        VerificationExecutionRecord.create(
            **{
                **started.model_dump(exclude={"record_sha256"}),
                "phase": "BLOCKED" if failure_code else "COMPLETED",
                "failure_code": failure_code,
                "results": tuple(
                    CommandResult(
                        argv=swift_sandbox_command(
                            started.capability,
                            Path(started.source_root),
                            Path(started.scratch_root),
                            action,
                        ),
                        cwd=started.source_root,
                        returncode=0,
                        stdout="ok",
                        stderr="",
                        duration_ms=1,
                    )
                    for action in actions
                )
                if failure_code is None
                else (),
                "ui_results": (
                    NativeUiResult(
                        step=ui.scenario.steps[0],
                        output=NativeUiOutput(
                            pid=123,
                            action="snapshot",
                            nodes=(
                                NativeUiNode(
                                    path="0.1",
                                    attributes={
                                        "AXRole": "AXButton",
                                        "AXDescription": "全选",
                                    },
                                ),
                            ),
                            error="WINDOW_UNAVAILABLE" if failure_code else "TARGET_UNAVAILABLE",
                            diagnostic="AXWindows count=0",
                        ),
                    ),
                )
                if failure_code != "NATIVE_UI_SESSION_LOCKED"
                else None,
            },
        )
    )
    source = SimpleNamespace(
        inputs=plan.inputs.model_copy(
            update={
                "prior_run_ids": tuple(
                    sorted(
                        {
                            *plan.inputs.prior_run_ids,
                            invocation.request.run_id,
                        }
                    )
                )
            }
        ),
        scope=plan.scope,
        stages=SimpleNamespace(
            preparation=SimpleNamespace(repository_workspace_root=str(tmp_path))
        ),
        runtime=SimpleNamespace(task=make_task(), events=()),
    )
    monkeypatch.setattr(NativeCandidateSourceReader, "inspect", lambda *_: source)
    monkeypatch.setattr(module, "verification_store_root", lambda _: tmp_path / "verification")
    monkeypatch.setattr(FileRecoveryStore, "latest_verification_completion", lambda _: None)
    _mock_source_view(monkeypatch, "bounded candidate source")
    monkeypatch.setattr(module, "_manager_resolutions", lambda *_: ())
    session_probe = Mock(return_value=NativeUiSession(status="SESSION_LOCKED"))
    monkeypatch.setattr(module, "probe_native_ui_session", session_probe)
    client = Mock()
    client.complete.return_value = StructuredModelResult(
        payload={
            "disposition": "WAITING_HUMAN",
            "summary": "Window launch needs diagnostics",
            "next_action": "Platform owner supplies bounded launch diagnostics then resumes",
        },
        duration_ms=1,
    )
    backend = Mock()
    backend._structured_clients.for_project.return_value = client
    advice = CandidateVerificationEntry(Mock(), {}, backend).coordinate(plan)
    assert advice is not None and advice.qa_artifact_id is None
    assert advice.execution_failure is not None
    assert advice.execution_failure.record_sha256 == failed.record_sha256
    payload = client.complete.call_args.kwargs["input_payload"]
    assert payload["qa"] is None
    failure = payload["latest_execution_failure"]
    if failure_code != "NATIVE_UI_SESSION_LOCKED":
        assert failure["ui_diagnostic"] == "AXWindows count=0"
        assert failure["failed_ui_step"] == ui.scenario.steps[0].to_wire()
        assert failure["observed_ui_controls"] == [
            {
                "path": "0.1",
                "attributes": {"AXRole": "AXButton", "AXDescription": "全选"},
            }
        ]
        if failure_code is None:
            assert failure["recorded_phase"] == "COMPLETED"
            assert failure["failure_code"] == "NATIVE_UI_UNAVAILABLE"
            assert failed.effective_failure_code == "NATIVE_UI_UNAVAILABLE"
            assert payload["source_prerequisite_repair"]["available"] is False
            assert (
                store.get_verification_execution(plan.plan_sha256, AgentRole.QA, completed=True)
                == failed
            )
    else:
        # Preflight has no launched child/AX result. Its explicit OS-session meaning
        # must survive the receipt -> Manager boundary, not become a queue-lock guess.
        prerequisite = failure["environment_prerequisite"]
        assert prerequisite["kind"] == "macos_console_session"
        assert prerequisite["observed_status"] == failure_code.removeprefix("NATIVE_UI_")
        assert prerequisite["owner"] == "logged_in_user"
        assert prerequisite["is_execution_mutex"] is False
        assert "密码" in prerequisite["next_action"]
        assert failure["failed_ui_step"] is None
    assert CandidateVerificationEntry(Mock(), {}, backend).coordinate(plan) == advice
    client.complete.assert_called_once()
    if failure_code == "NATIVE_UI_SESSION_LOCKED":
        assert advice.environment_prerequisite is not None
        assert not advice.environment_prerequisite.ready
        assert store.get_verification_advice(advice.input_sha256) == advice
        with pytest.raises(RecoveryRejected, match="session prerequisite source mismatch"):
            store.put_verification_advice(
                ManagerVerificationAdvice.create(
                    **{
                        **advice.model_dump(exclude={"advice_sha256"}),
                        "environment_prerequisite": advice.environment_prerequisite.model_copy(
                            update={"observed_status": "SESSION_UNAVAILABLE"}
                        ),
                    }
                )
            )
        session_probe.return_value = NativeUiSession(status="READY")
        resumed = CandidateVerificationEntry(Mock(), {}, backend).coordinate(plan)
        assert resumed is not None and resumed.input_sha256 != advice.input_sha256
        assert resumed.environment_prerequisite is not None
        assert resumed.environment_prerequisite.ready
        assert client.complete.call_count == 2
        # Reopen with the same READY status must not invoke a third model call.
        assert CandidateVerificationEntry(Mock(), {}, backend).coordinate(plan) == resumed
        assert client.complete.call_count == 2
        assert store.get_verification_advice(advice.input_sha256) == advice
    else:
        session_probe.assert_not_called()
    assert store.latest_verification_execution(plan) == failed
    other_candidate = plan.model_copy(
        update={"inputs": plan.inputs.model_copy(update={"candidate_revision": "f" * 40})}
    )
    assert store.latest_verification_execution(other_candidate) is None
    other_task = plan.model_copy(
        update={"inputs": plan.inputs.model_copy(update={"task_id": "task_unrelated"})}
    )
    assert store.latest_verification_execution(other_task) is None
    source.inputs = source.inputs.model_copy(
        update={
            "prior_run_ids": (*source.inputs.prior_run_ids, "run_unadmitted"),
        }
    )
    with pytest.raises(RecoveryRejected, match="source changed"):
        CandidateVerificationEntry(Mock(), {}, backend).coordinate(plan)
    with pytest.raises(RecoveryRejected, match="executor source mismatch"):
        store.put_verification_advice(
            ManagerVerificationAdvice.create(
                **{
                    **advice.model_dump(exclude={"advice_sha256"}),
                    "execution_failure": advice.execution_failure.model_copy(
                        update={"record_sha256": "f" * 64}
                    ),
                },
            )
        )
