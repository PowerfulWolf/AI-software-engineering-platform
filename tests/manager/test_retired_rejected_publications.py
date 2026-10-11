"""A consumed rejected publication cannot obstruct a later rejected Coder round."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.artifacts import seal_artifact
from ai_software_engineer.domain.artifact import ChangedFile
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    RejectedCoderOutputEvidence,
    ResolveDeliveryWait,
)
from ai_software_engineer.domain.enums import ChangeType
from ai_software_engineer.manager.rejected_output_checkpoint import read_rejected_checkpoint
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.models import QueueArtifactReceipt
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_delivery_wait import (
    WaitQueue,
    _outcome,
    _reject_wait,
    _successful_progress,
    service,
)
from tests.manager.test_rejected_coder_output import RejectedFixture, rejected_fixture
from tests.manager.test_wait_fact_collection import collector
from tests.orchestration.test_native_continuation import NOW
from tests.orchestration.test_native_continuation_v2 import V2Fixture


class RetirementQueue(WaitQueue):
    """Offline queue port; only genuinely consumed fixture decisions are exposed."""

    def __init__(self, native: V2Fixture, decisions: tuple[DeliveryResolution, ...]) -> None:
        super().__init__(native)
        self.decisions = decisions

    def retired_rejected_outputs(self, task_id: str) -> tuple[RejectedCoderOutputEvidence, ...]:
        evidence = []
        for decision in self.decisions:
            decision.validate_integrity()
            assert decision.task_id == task_id
            assert decision.resolution_kind is DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT
            assert decision.rejected_output is not None
            evidence.append(decision.rejected_output)
        return tuple(evidence)


@dataclass
class SecondRound:
    first: RejectedFixture
    queue: RetirementQueue
    facts: DeliveryWaitFactCollector
    outcome: DeliveryInvocationOutcome
    decision: DeliveryResolution
    first_publication: AcceptedRoleArtifact

    def collect(self, root: Path) -> None:
        native = self.first.native
        guard = WorkerExecutionGuard()
        with guard.task_scope(root / "idle-locks", native.task.id):
            self.facts.collect(native.repository.get(native.task.id), self.queue.bound, guard)


@contextmanager
def second_round(root: Path) -> Iterator[SecondRound]:
    with rejected_fixture(root) as first:
        first.collect(root)
        proof = first.entry.inspect(first.queue.command())
        assert proof.rejected_output is not None
        decision = first.entry.resolve(
            ResolveDeliveryWait.model_validate(
                {
                    **first.queue.command().to_wire(),
                    "proof_sha256": proof.proof_sha256,
                    "resolution_kind": DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT,
                    "submitted_at": NOW + timedelta(seconds=2),
                }
            )
        )
        assert first.queue.consumed == [decision]
        native = first.native
        native.repository.record_attempt(native.task.id, 2)
        native.activate(2)
        native.claim = native.claim.model_copy(
            update={
                "work_item": native.claim.work_item.model_copy(
                    update={
                        "id": "work_" + decision.resolution_sha256,
                        "parent_work_item_id": first.queue.item.id,
                    }
                )
            }
        )
        queue = RetirementQueue(native, tuple(first.queue.consumed))
        native.claim = queue.original
        _reject_wait(queue, "PLATFORM_BUG")
        native.guard.live = True
        continuation = native.service()
        assert continuation.started(native.request, native.worktree.path) is not None
        (native.worktree.path / "src/app.py").write_text("VALUE = 3\n")
        result = _successful_progress(native, queue)
        assert result.artifact is not None
        result = result.model_copy(
            update={
                "artifact": result.artifact.model_copy(
                    update={
                        "artifact_id": "art_second_rejected_progress",
                        "content": result.artifact.content.model_copy(
                            update={
                                "checkpoint_sequence": native.request.attempt + 8,
                                "changed_files": (
                                    ChangedFile(
                                        path="src/app.py",
                                        change=ChangeType.MODIFIED,
                                        lines_added=1,
                                        lines_deleted=1,
                                    ),
                                ),
                            }
                        ),
                    }
                )
            }
        )
        outcome = _outcome(native, queue, root, result)
        continuation.record_native_stop(
            native.request,
            native.worktree.path,
            process_stop=NativeProcessStop.create(
                process_id=999_998,
                group_id=999_998,
                returncode=0,
                kind="completed",
                stopped_at=NOW + timedelta(seconds=1),
            ),
            output_present=True,
            cause=None,
            original_error_code=None,
        )
        captures = FileContinuationStore(
            root / "continuations" / native.task.id, task_id=native.task.id
        )
        captures.put_capture_start(native.store.capture_start(native.request.run_id))
        captures.put_capture_stop(native.store.capture_stop(native.request.run_id))
        artifacts = first.entry.artifacts
        assert artifacts is not None and result.artifact is not None
        reference = artifacts.put(seal_artifact(result.artifact, validated_at=NOW))
        first_publication = first.queue.accepted_artifacts[0]
        queue.accepted_artifacts = (
            first_publication,
            AcceptedRoleArtifact(
                task_id=native.task.id,
                work_item_id=queue.item.id,
                lease_id=queue.original.lease.id,
                dispatch_sequence=queue.original.work_item.dispatch_sequence,
                checkpoint_sequence=queue.bound.boundary.checkpoint_sequence,
                run_id=native.request.run_id,
                context_manifest_id=native.request.context_manifest_id,
                source_revision=native.request.source_revision,
                receipt=QueueArtifactReceipt(
                    artifact_id=reference.artifact_id, sha256=reference.sha256
                ),
            ),
        )
        native.guard.live = False
        yield SecondRound(
            first, queue, collector(native, queue, root), outcome, decision, first_publication
        )


def test_second_rejected_round_ignores_only_the_exact_consumed_first_publication(
    tmp_path: Path,
) -> None:
    with second_round(tmp_path) as fixture:
        native = fixture.first.native
        before = native.repository.get(native.task.id)
        events = native.repository.list_events(native.task.id)
        publications = fixture.queue.accepted_artifacts
        original_records = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
        assert publications[0].checkpoint_sequence == publications[1].checkpoint_sequence
        assert publications[0].run_id != publications[1].run_id
        fixture.collect(tmp_path)
        record = read_rejected_checkpoint(tmp_path, fixture.queue.item.id)
        assert record is not None and record.outcome == fixture.outcome
        entry = service(native, fixture.queue, tmp_path)
        entry.artifacts = fixture.first.entry.artifacts
        proof = entry.inspect(fixture.queue.command())
        assert proof.rejected_output == record.evidence and not proof.missing
        assert proof.permitted_resolutions == (DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT,)
        fixture.collect(tmp_path)
        assert read_rejected_checkpoint(tmp_path, fixture.queue.item.id) == record
        assert native.repository.get(native.task.id) == before
        assert native.repository.list_events(native.task.id) == events
        assert fixture.queue.accepted_artifacts == publications and not fixture.queue.consumed
        assert fixture.first.queue.consumed == [fixture.decision]
        assert all(path.read_bytes() == body for path, body in original_records.items())
        assert (native.worktree.path / "src/app.py").read_text() == "VALUE = 3\n"


@pytest.mark.parametrize(
    "drift",
    [
        "unconsumed",
        "task",
        "work",
        "lease",
        "dispatch",
        "run",
        "context",
        "source",
        "artifact_id",
        "artifact_sha",
        "current_work",
        "current_run",
        "later_checkpoint",
    ],
)
def test_unretired_or_changed_publications_still_block_the_second_capture(
    tmp_path: Path, drift: str
) -> None:
    with second_round(tmp_path) as fixture:
        publication = fixture.first_publication
        if drift == "unconsumed":
            fixture.queue.decisions = ()
        elif drift in {"artifact_id", "artifact_sha"}:
            publication = publication.model_copy(
                update={
                    "receipt": publication.receipt.model_copy(
                        update={"artifact_id": "art_other_progress"}
                        if drift == "artifact_id"
                        else {"sha256": "f" * 64}
                    )
                }
            )
        else:
            updates: dict[str, dict[str, str | int]] = {
                "task": {"task_id": "task_other"},
                "work": {"work_item_id": "work_other"},
                "lease": {"lease_id": "lease_other"},
                "dispatch": {"dispatch_sequence": publication.dispatch_sequence + 1},
                "run": {"run_id": "run_other"},
                "context": {"context_manifest_id": "ctx_" + "f" * 64},
                "source": {"source_revision": "f" * 40},
                "current_work": {"work_item_id": fixture.queue.item.id},
                "current_run": {"run_id": fixture.outcome.start.request.run_id},
                "later_checkpoint": {"checkpoint_sequence": publication.checkpoint_sequence + 1},
            }
            publication = publication.model_copy(update=updates[drift])
        fixture.queue.accepted_artifacts = (publication, fixture.queue.accepted_artifacts[1])
        before = fixture.first.native.repository.get(fixture.first.native.task.id)
        with pytest.raises(ContinuationRejected):
            fixture.collect(tmp_path)
        assert read_rejected_checkpoint(tmp_path, fixture.queue.item.id) is None
        assert fixture.first.native.repository.get(before.id) == before
        assert not fixture.queue.consumed


@pytest.mark.parametrize("later_checkpoint", [False, True])
def test_actual_independent_successor_is_never_hidden_by_an_older_retirement(
    tmp_path: Path, later_checkpoint: bool
) -> None:
    with second_round(tmp_path) as fixture:
        current = fixture.queue.accepted_artifacts[1]
        successor = current.model_copy(
            update={
                "work_item_id": "work_independent_successor",
                "lease_id": "lease_independent_successor",
                "run_id": "run_independent_successor",
                "context_manifest_id": "ctx_" + "e" * 64,
                "checkpoint_sequence": current.checkpoint_sequence + int(later_checkpoint),
                "receipt": QueueArtifactReceipt(
                    artifact_id="art_independent_successor", sha256="e" * 64
                ),
            }
        )
        fixture.queue.accepted_artifacts = (*fixture.queue.accepted_artifacts, successor)
        with pytest.raises(ContinuationRejected):
            fixture.collect(tmp_path)
        assert read_rejected_checkpoint(tmp_path, fixture.queue.item.id) is None
