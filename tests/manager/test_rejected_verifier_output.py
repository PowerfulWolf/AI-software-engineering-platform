"""Inspect offers RETRY_REJECTED_VERIFIER_OUTPUT only for stopped QA/Reviewer INVALID_OUTPUT."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents.execution import ExecutionStop, SynchronousToolLoopStop
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.artifacts import FileArtifactStore, artifact_digest, seal_artifact
from ai_software_engineer.domain.artifact import (
    Artifact,
    ImplementationReportArtifact,
    QaReportArtifact,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryProofMissing,
    DeliveryResolutionKind,
    DeliveryWaitInvestigation,
)
from ai_software_engineer.domain.enums import AgentRole, QaReportStatus, TaskStatus
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact
from ai_software_engineer.work_queue.models import QueueArtifactReceipt, QueueClaim
from tests.domain.factories import (
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
)
from tests.manager.test_delivery_wait import (
    WaitQueue,
    _outcome,
    _reject_wait,
    native,
    service,
)
from tests.orchestration.test_native_continuation import NOW, Fixture

__all__ = ["native"]

RERUN = DeliveryResolutionKind.RETRY_REJECTED_VERIFIER_OUTPUT


def _record(
    native: Fixture, artifact: Artifact, work_item_id: str, run_id: str
) -> AcceptedRoleArtifact:
    return AcceptedRoleArtifact(
        task_id=native.task.id,
        work_item_id=work_item_id,
        lease_id="lease_" + work_item_id.removeprefix("work_"),
        dispatch_sequence=1,
        checkpoint_sequence=1,
        run_id=run_id,
        context_manifest_id="ctx_" + "9" * 64,
        source_revision=native.task.base_ref,
        receipt=QueueArtifactReceipt(
            artifact_id=artifact.artifact_id, sha256=artifact_digest(artifact)
        ),
    )


def _qa_fail(native: Fixture, queue: WaitQueue) -> QaReportArtifact:
    """A valid, schema-conforming QA FAIL produced by the original run."""
    template = make_qa_artifact()
    return cast(
        QaReportArtifact,
        seal_artifact(
            template.model_copy(
                update={
                    "task_id": native.task.id,
                    "source_revision": native.request.source_revision,
                    "context_manifest_id": native.request.context_manifest_id,
                    "producer": template.producer.model_copy(
                        update={
                            "agent_id": queue.original.assignment.agent_id,
                            "run_id": native.request.run_id,
                        }
                    ),
                    "content": template.content.model_copy(update={"status": QaReportStatus.FAIL}),
                }
            ),
            validated_at=NOW,
        ),
    )


def _verifier_wait(
    native: Fixture,
    root: Path,
    role: AgentRole,
    *,
    code: AgentErrorCode = AgentErrorCode.INVALID_OUTPUT,
    transient: bool = False,
    verdict: bool = False,
    accept_original: bool = False,
) -> tuple[WaitQueue, FileArtifactStore]:
    """Real Git/SQLite fixture for a sealed QA/Reviewer FAILED outcome."""
    base = native.task.base_ref
    current = native.repository.get(native.task.id)
    native.repository.append_event(
        build_event(
            current,
            TaskStatus.QA,
            event_id="evt_verifier_qa",
            reason="candidate ready",
            artifact_ids=("art_impl_001",),
            source_revision=base,
            occurred_at=current.updated_at + timedelta(seconds=1),
        )
    )
    artifacts = FileArtifactStore(root / "artifacts")
    plan = seal_artifact(
        make_plan_artifact().model_copy(
            update={"task_id": native.task.id, "source_revision": base}
        ),
        validated_at=NOW,
    )
    artifacts.put(plan)
    template = make_implementation_artifact()
    implementation = cast(
        ImplementationReportArtifact,
        seal_artifact(
            template.model_copy(
                update={
                    "task_id": native.task.id,
                    "source_revision": base,
                    "content": template.content.model_copy(update={"commit_sha": base}),
                }
            ),
            validated_at=NOW,
        ),
    )
    artifacts.put(implementation)
    records = [_record(native, implementation, "work_prior_coder", "run_prior_coder")]
    if role is AgentRole.REVIEWER:
        template_qa = make_qa_artifact()
        qa = cast(
            QaReportArtifact,
            seal_artifact(
                template_qa.model_copy(
                    update={
                        "task_id": native.task.id,
                        "source_revision": base,
                        "content": template_qa.content.model_copy(
                            update={"status": QaReportStatus.PASS}
                        ),
                    }
                ),
                validated_at=NOW,
            ),
        )
        artifacts.put(qa)
        current = native.repository.get(native.task.id)
        native.repository.append_event(
            build_event(
                current,
                TaskStatus.REVIEW,
                event_id="evt_verifier_review",
                reason="qa_passed",
                artifact_ids=(qa.artifact_id,),
                source_revision=base,
                occurred_at=current.updated_at + timedelta(seconds=1),
            )
        )
        records.append(_record(native, qa, "work_prior_qa", "run_prior_qa"))
    attempt = native.repository.get(native.task.id).attempts
    name = "qa" if role is AgentRole.QA else "reviewer"
    native.request = native.request.model_copy(
        update={
            "role": role,
            "attempt": attempt,
            "run_id": f"run_{name}_rejected",
            "output_schema": (
                "schemas/qa-report.schema.json"
                if role is AgentRole.QA
                else "schemas/review-report.schema.json"
            ),
            "input_artifact_ids": tuple(record.receipt.artifact_id for record in records),
        }
    )
    native.claim = QueueClaim.model_validate(
        {
            **native.claim.to_wire(),
            "work_item": {**native.claim.work_item.to_wire(), "role": role, "attempt": attempt},
            "assignment": {
                **native.claim.assignment.to_wire(),
                "role": role,
                "agent_id": f"agent_native_{name}",
                "attempt": attempt,
            },
            "lease": {**native.claim.lease.to_wire(), "agent_id": f"agent_native_{name}"},
        }
    )
    queue = WaitQueue(native)
    _reject_wait(queue)
    if verdict:
        # A valid negative verdict is a SUCCEEDED result with an artifact, not INVALID_OUTPUT.
        result = AgentResult(
            run_id=native.request.run_id,
            task_id=native.task.id,
            role=role,
            attempt=attempt,
            source_revision=base,
            context_manifest_id=native.request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=_qa_fail(native, queue),
        )
    else:
        result = AgentResult(
            run_id=native.request.run_id,
            task_id=native.task.id,
            role=role,
            attempt=attempt,
            source_revision=base,
            context_manifest_id=native.request.context_manifest_id,
            status=AgentRunStatus.FAILED,
            error=AgentFailure(
                code=code, message="原审查输出未通过平台契约。", transient=transient
            ),
        )
    if accept_original:
        records.append(
            records[0].model_copy(
                update={"work_item_id": queue.item.id, "run_id": native.request.run_id}
            )
        )
    queue.accepted_artifacts = tuple(records)
    _outcome(native, queue, root, result)
    return queue, artifacts


def _stop(native: Fixture) -> SynchronousToolLoopStop:
    return SynchronousToolLoopStop.create(
        task_id=native.task.id,
        run_id=native.request.run_id,
        request_sha256=digest(native.request.to_wire()),
        completed_operation_ids=(),
        kind="failed",
        stopped_at=NOW,
    )


def _reader(stop: ExecutionStop | None) -> Callable[..., ExecutionStop | None]:
    return lambda task, step, start, guard: stop


def _inspect(
    native: Fixture,
    queue: WaitQueue,
    artifacts: FileArtifactStore,
    root: Path,
    stop: ExecutionStop | None,
) -> DeliveryWaitInvestigation:
    entry = service(native, queue, root)
    entry.artifacts = artifacts
    entry.verifier_stop_reader = _reader(stop)
    return entry.inspect(queue.command())


def _assert_offered(native: Fixture, role: AgentRole, tmp_path: Path) -> None:
    queue, artifacts = _verifier_wait(native, tmp_path, role)
    stop = _stop(native)
    proof = _inspect(native, queue, artifacts, tmp_path, stop)
    assert proof.permitted_resolutions == (RERUN,)
    assert not proof.missing
    evidence = proof.rejected_verifier_output
    assert evidence is not None
    assert evidence.role is role
    assert evidence.task_id == native.task.id
    assert evidence.work_item_id == queue.item.id
    assert evidence.candidate_revision == native.task.base_ref
    assert evidence.implementation_artifact_id == "art_impl_001"
    assert evidence.previous_run_id == native.request.run_id
    assert evidence.previous_context_manifest_id == native.request.context_manifest_id
    assert evidence.execution_stop_sha256 == stop.stop_sha256
    assert evidence.error_code == "INVALID_OUTPUT"
    assert evidence.budget_source == "frozen_work_attempt"
    assert proof.process_stop_sha256 == stop.stop_sha256
    if role is AgentRole.QA:
        assert evidence.accepted_qa_artifact_id is None
    else:
        assert evidence.accepted_qa_artifact_id == "art_qa_001"
    assert not queue.consumed


def test_inspect_qa_invalid_output_offers_verifier_rerun(native: Fixture, tmp_path: Path) -> None:
    _assert_offered(native, AgentRole.QA, tmp_path)


def test_inspect_reviewer_invalid_output_offers_verifier_rerun(
    native: Fixture, tmp_path: Path
) -> None:
    _assert_offered(native, AgentRole.REVIEWER, tmp_path)


@pytest.mark.parametrize(
    "case",
    ["coder", "verdict", "policy", "transient", "accepted", "no_stop", "exhausted"],
)
def test_inspect_non_verifier_or_non_invalid_output_not_offered(
    native: Fixture, tmp_path: Path, case: str
) -> None:
    if case == "coder":
        queue = WaitQueue(native)
        _reject_wait(queue)
        _outcome(
            native,
            queue,
            tmp_path,
            native.result().model_copy(
                update={
                    "error": AgentFailure(
                        code=AgentErrorCode.INVALID_OUTPUT, message="无效输出。", transient=False
                    )
                }
            ),
        )
        artifacts = FileArtifactStore(tmp_path / "artifacts")
    else:
        if case == "exhausted":
            # The original verifier run consumed the last ordinary work attempt.
            task = native.repository.get(native.task.id)
            native.repository.record_attempt(native.task.id, task.max_attempts)
        queue, artifacts = _verifier_wait(
            native,
            tmp_path,
            AgentRole.QA,
            code=(
                AgentErrorCode.POLICY_VIOLATION
                if case == "policy"
                else AgentErrorCode.INVALID_OUTPUT
            ),
            transient=case == "transient",
            verdict=case == "verdict",
            accept_original=case == "accepted",
        )
    stop = None if case == "no_stop" else _stop(native)
    proof = _inspect(native, queue, artifacts, tmp_path, stop)
    assert RERUN not in proof.permitted_resolutions
    assert proof.rejected_verifier_output is None or case == "exhausted"
    if case == "no_stop":
        # No typed stop: never inferred, the wait keeps its conservative routing.
        assert {
            DeliveryProofMissing.PROCESS_LIVE_OR_UNKNOWN,
            DeliveryProofMissing.STOP_UNRECORDED,
        } & set(proof.missing)
    if case == "exhausted":
        assert DeliveryProofMissing.BUDGET_EXHAUSTED in proof.missing
    assert not queue.consumed
