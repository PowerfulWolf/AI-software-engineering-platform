"""Public resume routing exposes one exact no-start recovery for the original delivery."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
from ai_software_engineer.manager.delivery_checkpoint import DeliveryFailureCode, DeliveryStage
from ai_software_engineer.recovery.context_capacity import (
    LEGACY_CAPACITY_SUMMARY,
    LegacyContextCapacitySourceReader,
)
from ai_software_engineer.recovery.entry import NativeRecoveryEntry
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.native import NativeRecoverySourceReader
from tests.e2e.test_delivery_checkpoint import _checkpoint, _full_fields
from tests.recovery.test_context_capacity_input import capacity_plan


def test_capacity_public_entry_does_not_discover_an_older_failed_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = capacity_plan(tmp_path / "project")
    receipt = ContextCapacityReceipt(
        origin="legacy_terminal_context",
        task_id=plan.source.task_id,
        task_sha256=plan.source.task_sha256,
        task_intent_sha256="b" * 64,
        task_revision=3,
        work_item_id="work_capacity",
        lease_id="lease_capacity",
        assignment_id="assignment_capacity",
        claim_sha256="a" * 64,
        dispatch_sequence=1,
        checkpoint_sequence=2,
        role=AgentRole.CODER,
        attempt=2,
        source_revision=plan.source.effective_base_revision,
        context_manifest_id=plan.source.failed_context_id,
        context_sha256="c" * 64,
        max_input_tokens=252000,
        context_input_tokens=255325,
        execution_baseline_sha256=plan.source.execution_baseline_sha256,
        observed_at=datetime.now(UTC),
        receipt_sha256="0" * 64,
    )
    from ai_software_engineer.knowledge.models import digest

    receipt = receipt.model_copy(
        update={
            "receipt_sha256": digest(receipt.model_dump(mode="json", exclude={"receipt_sha256"}))
        }
    )
    receipt.validate_integrity()
    source = SimpleNamespace(
        source=plan.source.model_copy(
            update={"context_capacity_receipt_sha256": receipt.receipt_sha256}
        ),
        capacity_receipt=receipt,
    )
    discover = Mock(return_value=source)
    ordinary = Mock(side_effect=AssertionError("capacity reused an old failed Run"))
    monkeypatch.setattr(LegacyContextCapacitySourceReader, "discover", discover)
    monkeypatch.setattr(NativeRecoverySourceReader, "discover_failed_coder", ordinary)
    entry = object.__new__(NativeRecoveryEntry)
    entry.config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        team_id=plan.source.scope.team_id,
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    entry.environment = {}
    proposed = Mock(return_value=(plan, tmp_path / "plan.json"))
    monkeypatch.setattr(entry, "propose", proposed)
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir(mode=0o700)
    monkeypatch.setattr(
        "ai_software_engineer.recovery.entry._repository_sidecar", lambda *_: sidecar
    )
    cp = _checkpoint(
        tmp_path / "project",
        **{
            **_full_fields(),
            "stage": DeliveryStage.BLOCKED,
            "task_status": TaskStatus.BLOCKED,
            "task_id": plan.source.task_id,
            "task_revision": 3,
            "candidate_revision": None,
            "failure_code": DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED,
            "failed_stage": DeliveryStage.DELIVERING,
            "failure_summary": LEGACY_CAPACITY_SUMMARY,
        },
    )
    assert entry.scope_supplement(cp) is None
    assert not (sidecar / "state/delivery-preflight").exists()
    assert entry.propose_delivery(cp) == proposed.return_value
    assert proposed.call_args.kwargs["failed_run_id"] is None
    assert proposed.call_args.kwargs["capacity_receipt_sha256"] == receipt.receipt_sha256
    assert proposed.call_args.kwargs["delivery_id"] == cp.delivery_id
    ordinary.assert_not_called()
    from ai_software_engineer.knowledge.store import KnowledgeRecordStore

    assert (
        KnowledgeRecordStore(sidecar / "state/delivery-preflight", read_only=True).get(
            "context-capacity-receipts", receipt.receipt_sha256, ContextCapacityReceipt
        )
        == receipt
    )


def test_capacity_reader_missing_environment_never_initializes_store(tmp_path: Path) -> None:
    plan = capacity_plan(tmp_path / "project")
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        team_id=plan.source.scope.team_id,
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    reader = LegacyContextCapacitySourceReader(config, {})
    with pytest.raises(RecoveryRejected):
        reader.discover(plan.source.scope)
    assert not Path(config.platform_root).exists()


def test_capacity_exact_approval_builds_new_task_for_original_approved_requirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace
    from hashlib import sha256

    from ai_software_engineer.domain.execution_baseline import RetainedExecutionPatch
    from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
    from ai_software_engineer.recovery.models import (
        CapturedChanges,
        ContextCapacityRecoveryInput,
        RecoveryPlan,
    )
    from ai_software_engineer.recovery.service import RecoveryAuthorizationService
    from ai_software_engineer.recovery.store import FileRecoveryStore
    from ai_software_engineer.recovery.task import AuthorizedRecoveryTaskBuilder
    from tests.recovery.test_authorization import Captures, Human, approval
    from tests.recovery.test_preparation_inspection_scope import preparation_fixture

    f = preparation_fixture(tmp_path, monkeypatch)
    original = f.builder._facts._inspect(f.plan).original
    old_task = original.task.to_wire()
    old_records = {path: path.read_bytes() for path in f.store._root.glob("*.json")}
    patch = f.plan.capture.patch
    source = f.plan.source.model_copy(
        update={
            "failed_run_id": None,
            "context_capacity_receipt_sha256": "d" * 64,
            "execution_baseline_sha256": "e" * 64,
            "execution_base_revision": f.plan.source.base_revision,
        }
    )
    capacity = ContextCapacityRecoveryInput(
        execution_baseline_sha256="e" * 64,
        retained_patch=RetainedExecutionPatch(
            uri="baseline://complete",
            sha256=sha256(patch.encode()).hexdigest(),
            bytes=len(patch.encode()),
        ),
        patch=patch,
    )
    capture = CapturedChanges.from_capture(
        replace(f.plan.capture.to_capture(), patch=b"", file_sha256s=())
    )
    plan = RecoveryPlan.create(
        **{
            **f.plan.to_wire(),
            "input_mode": "coder_reapply",
            "source": source,
            "capture": capture,
            "context_capacity_input": capacity,
        }
    )
    facts = replace(
        f.builder._facts._inspect(f.plan),
        original=replace(original, source=source, capacity_input=capacity),
    )
    verifier = NativeRecoveryFactsVerifier(f.builder._facts._config, {})
    monkeypatch.setattr(verifier, "_read_source", Mock(return_value=facts.original))
    monkeypatch.setattr(verifier, "_target_preflight", Mock(return_value=object()))
    monkeypatch.setattr(verifier, "_target_facts", Mock(return_value=facts))
    monkeypatch.setattr(
        "ai_software_engineer.recovery.current.read_terminal_workspace_snapshot",
        Mock(side_effect=AssertionError("capacity invented old invocation/stop facts")),
    )
    store = FileRecoveryStore.initialize(tmp_path / "capacity-recovery", scope=plan.source.scope)
    service = RecoveryAuthorizationService(
        store, facts=verifier, captures=Captures(), human=Human()
    )
    service.propose(plan)
    builder = AuthorizedRecoveryTaskBuilder(service, verifier)
    with pytest.raises(RecoveryRejected):
        builder.build(plan.plan_sha256)
    service.authorize(approval(plan))
    draft = builder.build(plan.plan_sha256)
    assert draft.task.status is TaskStatus.NEW and draft.task.attempts == 0
    assert draft.task.id != original.task.id and draft.task.id == plan.new_task_id
    assert draft.task.base_ref == plan.target_base_revision
    assert draft.rebound_request.id == original.request.id
    assert draft.task.acceptance_criteria == original.task.acceptance_criteria
    assert draft.task.metadata["recovery_of_delivery_id"] == source.scope.delivery_id
    assert original.task.to_wire() == old_task
    assert {path: path.read_bytes() for path in f.store._root.glob("*.json")} == old_records
