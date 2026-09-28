"""A fresh approval may combine exact predecessor pixels with new observations."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents.openai_compatible import PromptMessage, PromptPayload
from ai_software_engineer.agents.structured import StructuredModelResult
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.execution import CommandResult, SubprocessCommandExecutor
from ai_software_engineer.manager.native_ui import (
    NativeUiCapture,
    NativeUiNode,
    NativeUiOutput,
    NativeUiResult,
    NativeUiStep,
    native_ui_capability,
)
from ai_software_engineer.recovery import verification_entry as entry_module
from ai_software_engineer.recovery.models import RecoveryApprovalCommand, RecoveryRejected
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification_admission import (
    CandidateVerificationAdmission,
    ExplicitVerificationHuman,
)
from ai_software_engineer.recovery.verification_entry import (
    CandidateVerificationEntry,
    NativeVerificationFacts,
    _available_prior_visual_evidence,
)
from ai_software_engineer.recovery.verification_execution import BoundSwiftVerificationEvidence
from ai_software_engineer.recovery.verification_native import NativeCandidateSourceReader
from ai_software_engineer.recovery.verification_records import CandidateVerificationPlan
from tests.domain.factories import make_task
from tests.domain.test_visual_evidence import png_evidence
from tests.orchestration.test_runner import _clock
from tests.recovery.test_native_ui import scenario
from tests.recovery.test_verification_environment import _admitted, capability


def test_exact_predecessor_images_are_approved_forwarded_and_reopened_without_recapture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ui = native_ui_capability(
        scenario().model_copy(
            update={
                "steps": tuple(NativeUiStep(name=f"old_{i}", capture_window=True) for i in range(6))
            }
        )
    )
    plan, store, facts, requests, completion = _admitted(
        tmp_path, environment_error=True, native_ui=ui
    )
    root = tmp_path / "worktrees"
    commands = Mock(
        side_effect=lambda executor, argv, **_: CommandResult(
            argv=argv,
            cwd=str(executor._workspace_root),
            returncode=0,
            stdout="fixture test passed",
            stderr="",
            duration_ms=1,
        )
    )
    monkeypatch.setattr(
        SubprocessCommandExecutor, "run", lambda self, argv, **kw: commands(self, argv, **kw)
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution.discover_swift_sandbox_capability",
        lambda _: capability(),
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution._require_clean_candidate",
        lambda *_: None,
    )
    image = png_evidence()
    captures = Mock(
        side_effect=lambda current, *_: tuple(
            NativeUiResult(
                step=step,
                output=NativeUiOutput(
                    pid=123,
                    action="snapshot",
                    nodes=(NativeUiNode(path="0", attributes={"AXRole": "AXWindow"}),),
                    capture=NativeUiCapture(window_id=42, image=image),
                ),
            )
            for step in current.scenario.steps
        )
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution.run_native_ui", captures
    )
    source = root / plan.execution_task_id / "qa-attempt-01"
    source.mkdir(parents=True)
    old = BoundSwiftVerificationEvidence(store=store, plan=plan, facts=facts, worktree_root=root)
    old_evidence = old.evidence_for(requests[0], source)
    receipt = store.get_verification_execution(plan.plan_sha256, AgentRole.QA, completed=True)
    incident = store.record_verification_incident(completion)
    original_wire = plan.to_wire()
    assert "prior_visual_evidence" not in original_wire
    values: dict[str, object] = {k: v for k, v in original_wire.items() if k != "plan_sha256"}
    values.update(
        execution_task_id="task_verify_successor",
        prerequisite_incident_sha256=incident.incident_sha256,
        native_ui=native_ui_capability(
            scenario().model_copy(
                update={
                    "steps": tuple(
                        NativeUiStep(name=f"new_{i}", capture_window=True) for i in range(6)
                    )
                }
            )
        ),
    )
    legacy = CandidateVerificationPlan.create(**values)
    successor = CandidateVerificationPlan.create(
        **values,
        prior_visual_evidence={
            "plan_sha256": plan.plan_sha256,
            "record_sha256": receipt.record_sha256,
        },
    )
    assert successor.plan_sha256 != legacy.plan_sha256
    assert _available_prior_visual_evidence(store, plan.inputs, completion) == receipt
    assert _available_prior_visual_evidence(store, plan.inputs, None) is None
    assert (
        _available_prior_visual_evidence(
            store, plan.inputs.model_copy(update={"candidate_revision": "f" * 40}), completion
        )
        is None
    )
    admission = CandidateVerificationAdmission(
        store=store,
        plan_sha256=successor.plan_sha256,
        facts=facts,
        artifacts=FileArtifactStore(tmp_path / "artifacts"),
        clock=_clock,
    )
    admission.propose(successor)
    admission.approve(
        RecoveryApprovalCommand(
            operation_id="op_visual_successor",
            plan_sha256=successor.plan_sha256,
            approval_reference="fixture-approved-prior-pixels",
            submitted_at=_clock(),
        ),
        human=ExplicitVerificationHuman(successor.plan_sha256),
    )
    request = requests[0].model_copy(update={"run_id": "run_qa_visual_successor"})
    admission.admit(successor.inputs, request)
    current_root = root / successor.execution_task_id / "qa-attempt-01"
    current_root.mkdir(parents=True)
    service = BoundSwiftVerificationEvidence(
        store=store, plan=successor, facts=facts, worktree_root=root
    )
    evidence = service.evidence_for(request, current_root)
    assert len(evidence.images) == 12
    assert all("Historical QA" in item.label for item in evidence.images[:6])
    assert all(f"old_{i}" in item.label for i, item in enumerate(evidence.images[:6]))
    assert all(f"new_{i}" in item.label for i, item in enumerate(evidence.images[6:]))
    assert tuple(item.image for item in evidence.images[:6]) == tuple(
        item.image for item in old_evidence.images
    )
    assert receipt.record_sha256 in evidence.text
    assert image.data_base64 not in evidence.text
    prompt = PromptPayload(
        messages=(PromptMessage(role="user", content=evidence.text),), images=evidence.images
    )
    assert len(prompt.to_messages()) == 13
    reopened = BoundSwiftVerificationEvidence(
        store=FileRecoveryStore(tmp_path / "verification", scope=plan.scope),
        plan=successor,
        facts=facts,
        worktree_root=root,
    )
    assert reopened.evidence_for(request, current_root) == evidence
    assert commands.call_count == 4 and captures.call_count == 2
    assert store.get_verification_plan(plan.plan_sha256).to_wire() == original_wire
    # Production proposal and Manager context must select the same actual predecessor.
    source_facts = SimpleNamespace(
        inputs=plan.inputs,
        scope=plan.scope,
        checkpoint=SimpleNamespace(checkpoint_sha256=plan.native_checkpoint_sha256),
        parent_delivery_id=None,
        parent_checkpoint_sha256=None,
        stages=SimpleNamespace(
            preparation=SimpleNamespace(repository_workspace_root=str(tmp_path))
        ),
        runtime=SimpleNamespace(
            task=make_task(),
            events=(),
            dispatch=SimpleNamespace(dispatch_sha256=plan.dispatch_sha256),
        ),
    )
    monkeypatch.setattr(NativeCandidateSourceReader, "inspect", lambda *_: source_facts)
    monkeypatch.setattr(NativeVerificationFacts, "validate", lambda *_: None)
    monkeypatch.setattr(
        entry_module, "verification_store_root", lambda _: tmp_path / "verification"
    )
    monkeypatch.setattr(entry_module, "candidate_read_snapshot", lambda *_: "fixture source")
    monkeypatch.setattr(entry_module, "_manager_resolutions", lambda *_: ())
    monkeypatch.setattr(entry_module, "_verification_allocation", lambda *_, **__: Mock())
    monkeypatch.setattr(
        entry_module, "_definitions", lambda *_: {d.role: d for d in plan.definitions}
    )
    monkeypatch.setattr(entry_module, "_stage_sha", lambda *_: plan.approved_stage_chain_sha256)
    monkeypatch.setattr(entry_module, "_policy_sha", lambda *_: plan.current_policy_sha256)
    monkeypatch.setattr(entry_module, "_executor_capability", lambda *_: capability())
    backend = Mock()
    entry = CandidateVerificationEntry(Mock(), {}, backend)
    monkeypatch.setattr(entry, "_authority", lambda *_: Mock())
    proposed, _ = entry.propose(plan.scope, native_ui_scenario=ui.scenario)
    assert proposed.prior_visual_evidence == successor.prior_visual_evidence
    backend._structured_clients.for_project.return_value.complete.return_value = (
        StructuredModelResult(
            payload={
                "disposition": "WAITING_HUMAN",
                "summary": "fixture prerequisite",
                "next_action": "fixture owner supplies data",
            },
            duration_ms=1,
        )
    )
    inspect_plan = CandidateVerificationPlan.create(**{**values, "native_ui": None})
    store.put_verification_plan(inspect_plan)
    assert entry.coordinate(inspect_plan) is not None
    manager_input = backend._structured_clients.for_project.return_value.complete.call_args.kwargs[
        "input_payload"
    ]
    prior_input = manager_input["available_prior_visual_evidence"]
    assert prior_input["record_sha256"] == receipt.record_sha256
    assert [item["step"] for item in prior_input["captures"]] == [f"old_{i}" for i in range(6)]
    assert manager_input["available_ui_capability"]["screenshots"]["max_per_scenario"] == 6
    for field, value in (
        ("task_id", "task_foreign"),
        ("implementation_sha256", "f" * 64),
        ("candidate_revision", "f" * 40),
    ):
        invalid = CandidateVerificationPlan.create(
            **{**values, "inputs": successor.inputs.model_copy(update={field: value})},
            prior_visual_evidence=successor.prior_visual_evidence,
        )
        with pytest.raises(RecoveryRejected):
            store.put_verification_plan(invalid)
    for changed in ({"record_sha256": "f" * 64}, {"plan_sha256": successor.plan_sha256}):
        invalid = CandidateVerificationPlan.create(
            **values,
            prior_visual_evidence={
                "plan_sha256": plan.plan_sha256,
                "record_sha256": receipt.record_sha256,
                **changed,
            },
        )
        with pytest.raises(RecoveryRejected):
            store.put_verification_plan(invalid)
    # A later disk mutation must be revalidated, not hidden by the read graph cache.
    path = (
        tmp_path / "verification" / f"verification-execution-qa-completed-{plan.plan_sha256}.json"
    )
    wire = json.loads(path.read_text())
    wire["record"]["record_sha256"] = "f" * 64
    path.write_text(json.dumps(wire))
    with pytest.raises(RecoveryRejected):
        reopened.evidence_for(request, current_root)
    assert commands.call_count == 4 and captures.call_count == 2
