"""Real terminal windows compose with the complete exact authorization gates."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

import ai_software_engineer.recovery.task as task_module
from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.domain.project_delivery import derive_delivery_task
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryRejected,
    RecoveryScope,
    VerifiedRecoveryDecision,
)
from ai_software_engineer.recovery.native import NativeRecoverySource, NativeRecoverySourceReader
from ai_software_engineer.recovery.service import RecoveryAuthorizationService
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.task import AuthorizedRecoveryTaskBuilder
from tests.recovery.facts_window_fixture import (
    ModernFailedNativeFixture,
    modern_failed_native_fixture,
)
from tests.recovery.test_authorized_facts import after_call


@pytest.fixture(autouse=True)
def isolated_mysql_facts() -> Iterator[None]:
    """The shared helper performs all resets only after exclusive test DB admission."""
    yield


class _FixtureHuman:
    def verify(self, command: RecoveryApprovalCommand) -> VerifiedRecoveryDecision:
        return VerifiedRecoveryDecision(
            plan_sha256=command.plan_sha256,
            approval_reference=command.approval_reference,
            approved=True,
            operator_id="fixture-human",
            rationale="Approve this exact offline recovery fixture.",
            decided_at=command.submitted_at,
        )


def _authorized_builder(
    root: Path, fixture: ModernFailedNativeFixture
) -> tuple[FileRecoveryStore, AuthorizedRecoveryTaskBuilder]:
    store = FileRecoveryStore.initialize(root, scope=fixture.plan.source.scope)
    captures = GitWorktreeManager(
        fixture.project,
        Path(fixture.config.platform_root) / "worktrees" / fixture.plan.source.scope.repository_id,
        branch_names={fixture.original.task.id: fixture.original.task.branch_name},
    )
    service = RecoveryAuthorizationService(
        store, facts=fixture.reader, captures=captures, human=_FixtureHuman()
    )
    service.propose(fixture.plan)
    receipt = service.authorize(
        RecoveryApprovalCommand(
            operation_id="approve_window_builder_fixture",
            plan_sha256=fixture.plan.plan_sha256,
            approval_reference="offline:exact-window-builder-approval",
            submitted_at=datetime.now(UTC),
        )
    )
    assert receipt.decision.approved
    return store, AuthorizedRecoveryTaskBuilder(service, fixture.reader)


@pytest.mark.mysql
def test_real_authorized_builder_keeps_four_fresh_two_source_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with modern_failed_native_fixture(tmp_path, monkeypatch) as fixture:
        store, builder = _authorized_builder(tmp_path / "builder-recovery", fixture)
        receipt = store.get_authorization(fixture.plan.plan_sha256)
        reads = 0
        inspect = NativeRecoverySourceReader.inspect

        def counted(
            reader: NativeRecoverySourceReader,
            scope: RecoveryScope,
            *,
            failed_run_id: str,
            failed_context_id: str,
        ) -> NativeRecoverySource:
            nonlocal reads
            reads += 1
            return inspect(
                reader,
                scope,
                failed_run_id=failed_run_id,
                failed_context_id=failed_context_id,
            )

        monkeypatch.setattr(NativeRecoverySourceReader, "inspect", counted)
        draft = builder.build(fixture.plan.plan_sha256)
        assert reads == 8  # Four complete Native inspections, two fresh sources each.
        assert draft.facts.original == fixture.original
        assert draft.task.id == fixture.plan.new_task_id
        assert draft.task.base_ref == fixture.plan.target_base_revision
        assert draft.task.status is TaskStatus.NEW and draft.task.attempts == 0
        assert store.get_authorization(fixture.plan.plan_sha256) == receipt
        with pytest.raises(RecoveryRecordMissing):
            store.get_task_record(fixture.plan.plan_sha256)


@pytest.mark.mysql
def test_real_builder_final_window_rejects_stop_removed_during_derivation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with modern_failed_native_fixture(tmp_path, monkeypatch) as fixture:
        root = tmp_path / "builder-recovery"
        store, builder = _authorized_builder(root, fixture)
        durable_before = {path.name: path.read_bytes() for path in root.glob("*.json")}
        derived = False

        def remove_stop() -> None:
            nonlocal derived
            stop = (
                Path(fixture.original.preparation.repository_workspace_root)
                / "state/continuations"
                / fixture.original.task.id
                / f"capture-stop-{fixture.plan.source.failed_run_id}.json"
            )
            stop.unlink()
            derived = True

        monkeypatch.setattr(
            task_module, "derive_delivery_task", after_call(derive_delivery_task, remove_stop)
        )
        with pytest.raises(RecoveryRejected):
            builder.build(fixture.plan.plan_sha256)
        assert derived
        assert {path.name: path.read_bytes() for path in root.glob("*.json")} == durable_before
        with pytest.raises(RecoveryRecordMissing):
            store.get_task_record(fixture.plan.plan_sha256)
