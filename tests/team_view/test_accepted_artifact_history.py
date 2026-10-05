"""Accepted QA waits retain complete findings without manufacturing StateEvents."""

import json
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain.artifact import Artifact, Finding, QaReportArtifact
from ai_software_engineer.domain.enums import (
    AgentRole,
    FindingSeverity,
    QaCriterionStatus,
    QaReportStatus,
    QaTestStatus,
    ReviewVerdict,
    RiskTier,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.model import JsonValue
from ai_software_engineer.projection.models import ProjectionFacts
from ai_software_engineer.projection.projector import ProjectionConflict, RunProjectionBuilder
from ai_software_engineer.team_view.models import ScopeView, TaskView
from ai_software_engineer.team_view.reader import (
    _merge_task_history,
    _read_accepted_artifact_history,
)
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, record_digest
from ai_software_engineer.work_queue.models import QueueArtifactReceipt, QueuedWorkItem
from tests.domain.factories import (
    NOW,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
    make_task,
)


class _Cursor:
    def __init__(
        self,
        receipts: tuple[AcceptedRoleArtifact, ...],
        *,
        table: bool = True,
        claims: dict[str, list[dict[str, object]]] | None = None,
    ) -> None:
        self.receipts, self.table = receipts, table
        self.queries: list[tuple[str, object]] = []
        self.claims = (
            claims
            if claims is not None
            else {receipt.lease_id: [_claim(receipt)] for receipt in receipts}
        )

    def execute(self, query: str, params: object = None) -> None:
        assert query.startswith("SELECT ")
        self.queries.append((query, params))

    def fetchone(self) -> dict[str, str] | None:
        return {"TABLE_NAME": "work_queue_accepted_artifacts"} if self.table else None

    def fetchall(self) -> list[dict[str, object]]:
        query, params = self.queries[-1]
        if "FROM work_queue_events " in query:
            assert isinstance(params, tuple)
            return [row for lease_id in params for row in self.claims.get(str(lease_id), [])]
        return [
            {
                "id": record.receipt.artifact_id,
                "task_id": record.task_id,
                "payload_json": json.dumps(record.to_wire()),
                "sha256": record_digest(record),
            }
            for record in self.receipts
        ]


def _claim(
    receipt: AcceptedRoleArtifact, *, sequence: int = 1, role: AgentRole = AgentRole.QA
) -> dict[str, object]:
    item = QueuedWorkItem(
        id=receipt.work_item_id,
        task_id=receipt.task_id,
        repository_id="repository_history_001",
        status=WorkItemStatus.LEASED,
        role=role,
        priority=100,
        risk=RiskTier.LOW,
        attempt=1,
        checkpoint_sequence=receipt.checkpoint_sequence,
        dispatch_sequence=receipt.dispatch_sequence,
        repository_scopes=("/tmp/history",),
        created_at=NOW,
        updated_at=NOW,
    )
    return {
        "sequence": sequence,
        "work_item_id": item.id,
        "lease_id": receipt.lease_id,
        "payload_json": json.dumps({"work_item": item.to_wire(), "detail": {}}),
    }


def _first_detail(value: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(value, list) and value
    first = value[0]
    assert isinstance(first, dict)
    return first


def _fixture(sidecar: Path) -> tuple[QaReportArtifact, AcceptedRoleArtifact]:
    store = FileArtifactStore(sidecar / "artifacts")
    store.put(seal_artifact(make_plan_artifact(), validated_at=NOW))
    store.put(seal_artifact(make_implementation_artifact(), validated_at=NOW))
    template = make_qa_artifact()
    qa = cast(
        QaReportArtifact,
        seal_artifact(
            template.model_copy(
                update={
                    "context_manifest_id": "ctx_" + "c" * 64,
                    "content": template.content.model_copy(
                        update={
                            "status": QaReportStatus.FAIL,
                            "criteria_results": tuple(
                                item.model_copy(update={"status": QaCriterionStatus.NOT_TESTED})
                                for item in template.content.criteria_results
                            ),
                            "tests_run": tuple(
                                item.model_copy(update={"status": QaTestStatus.ERROR})
                                for item in template.content.tests_run
                            ),
                            "environment": {
                                "reason": "固定增量测试入口尚未执行, 需要重新独立验收。"
                            },
                            "findings": (
                                Finding(
                                    finding_id="finding_qa_environment",
                                    severity=FindingSeverity.MINOR,
                                    code="ENVIRONMENT_UNAVAILABLE",
                                    message="固定增量测试入口尚未执行, 需要重新独立验收。",
                                    evidence_ids=("ev_qa_tests",),
                                    file="tests/test_delivery.py",
                                    recommendation="由工程团队核验固定测试入口后重新独立验收。",
                                ),
                            ),
                        }
                    ),
                }
            ),
            validated_at=NOW,
        ),
    )
    store.put(qa)
    receipt = AcceptedRoleArtifact(
        task_id=qa.task_id,
        work_item_id="work_qa_history",
        lease_id="lease_qa_history",
        dispatch_sequence=1,
        checkpoint_sequence=3,
        run_id=qa.producer.run_id,
        context_manifest_id=qa.context_manifest_id,
        source_revision=qa.source_revision,
        receipt=QueueArtifactReceipt(artifact_id=qa.artifact_id, sha256=qa.integrity.sha256),
    )
    return qa, receipt


def test_accepted_inconclusive_qa_is_full_history_without_state_event_or_write(
    tmp_path: Path,
) -> None:
    qa, receipt = _fixture(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    cursor = _Cursor((receipt,))
    history = _read_accepted_artifact_history(
        cast(DictCursor, cursor),
        task_id=qa.task_id,
        sidecar=tmp_path,
        state_artifact_ids=("art_plan_001", "art_impl_001"),
    )
    assert qa in history.artifacts
    task = make_task().model_copy(update={"status": TaskStatus.QA})
    projection = RunProjectionBuilder().build(
        ProjectionFacts(
            tasks=(task,), artifacts=history.artifacts, artifact_positions=history.positions
        )
    )
    entry = next(value for value in projection.tasks[0].timeline if value.id == qa.artifact_id)
    assert entry.details["status"] == "FAIL"
    assert entry.details["parent_artifact_ids"] == list(qa.parent_artifact_ids)
    assert _first_detail(entry.details["tests_run"])["status"] == "ERROR"
    assert _first_detail(entry.details["criteria_results"])["status"] == "NOT_TESTED"
    assert _first_detail(entry.details["findings"])["message"] == qa.content.findings[0].message
    assert entry.details["environment"] == qa.content.environment
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert len(cursor.queries) == 3


@pytest.mark.parametrize(
    "field", ["task_id", "run_id", "context_manifest_id", "source_revision", "sha256"]
)
def test_accepted_history_rejects_a_semantically_changed_receipt(
    tmp_path: Path, field: str
) -> None:
    qa, receipt = _fixture(tmp_path)
    changed = receipt.model_copy(
        update={"receipt": receipt.receipt.model_copy(update={"sha256": "a" * 64})}
        if field == "sha256"
        else {
            field: (
                "f" * 40
                if field == "source_revision"
                else "ctx_" + "d" * 64
                if field == "context_manifest_id"
                else field + "_foreign"
            )
        }
    )
    with pytest.raises(ValueError, match="exact receipt binding"):
        _read_accepted_artifact_history(
            cast(DictCursor, _Cursor((changed,))),
            task_id=qa.task_id,
            sidecar=tmp_path,
            state_artifact_ids=(),
        )


def test_legacy_reader_uses_only_state_artifacts_when_acceptance_table_is_absent(
    tmp_path: Path,
) -> None:
    qa, _receipt = _fixture(tmp_path)
    history = _read_accepted_artifact_history(
        cast(DictCursor, _Cursor((), table=False)),
        task_id=qa.task_id,
        sidecar=tmp_path,
        state_artifact_ids=("art_plan_001", "art_impl_001"),
    )
    assert {artifact.artifact_id for artifact in history.artifacts} == {
        "art_plan_001",
        "art_impl_001",
    }
    assert qa not in history.artifacts
    assert all(
        position.stream.startswith("state_artifact_references:") for position in history.positions
    )


@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "task", "generation", "role", "sequence"]
)
def test_accepted_history_requires_exact_original_claim_position(
    tmp_path: Path, fault: str
) -> None:
    qa, receipt = _fixture(tmp_path)
    claim = _claim(receipt)
    if fault == "sequence":
        claim["sequence"] = True
    elif fault in {"task", "generation", "role"}:
        payload = json.loads(str(claim["payload_json"]))
        payload["work_item"].update(
            {"task_id": "task_foreign_001"}
            if fault == "task"
            else {"dispatch_sequence": 2}
            if fault == "generation"
            else {"role": "coder"}
        )
        claim["payload_json"] = json.dumps(payload)
    claims = [] if fault == "missing" else [claim, claim] if fault == "duplicate" else [claim]
    with pytest.raises(ValueError):
        _read_accepted_artifact_history(
            cast(DictCursor, _Cursor((receipt,), claims={receipt.lease_id: claims})),
            task_id=qa.task_id,
            sidecar=tmp_path,
            state_artifact_ids=(),
        )


def test_multiple_qa_review_rounds_ignore_provider_times_and_random_ids(tmp_path: Path) -> None:
    """Equal sealed clocks use verified claim order, including no-StateEvent results."""
    finding = Finding(
        finding_id="finding_rework_history",
        severity=FindingSeverity.MAJOR,
        message="缺少空输入回归检查。",
        evidence_ids=("ev_review_diff",),
    )
    plan = make_plan_artifact()
    impl = make_implementation_artifact()
    qa_template = make_qa_artifact()
    review_template = make_review_artifact()
    qa_fail = qa_template.model_copy(
        update={
            "artifact_id": "art_qa_z_first",
            "content": qa_template.content.model_copy(update={"status": QaReportStatus.FAIL}),
        }
    )
    impl_fix = impl.model_copy(
        update={
            "artifact_id": "art_impl_y_fix",
            "parent_artifact_ids": (plan.artifact_id, qa_fail.artifact_id),
            "supersedes": impl.artifact_id,
        }
    )
    qa_pass = qa_template.model_copy(
        update={
            "artifact_id": "art_qa_x_pass",
            "parent_artifact_ids": (impl_fix.artifact_id,),
            "supersedes": qa_fail.artifact_id,
        }
    )
    review_reject = review_template.model_copy(
        update={
            "artifact_id": "art_review_z_reject",
            "parent_artifact_ids": (qa_pass.artifact_id,),
            "content": review_template.content.model_copy(
                update={"verdict": ReviewVerdict.REJECT, "findings": (finding,)}
            ),
        }
    )
    impl_review_fix = impl.model_copy(
        update={
            "artifact_id": "art_impl_b_review_fix",
            "parent_artifact_ids": (plan.artifact_id, review_reject.artifact_id),
            "supersedes": impl_fix.artifact_id,
        }
    )
    qa_final = qa_template.model_copy(
        update={
            "artifact_id": "art_qa_a_final",
            "parent_artifact_ids": (impl_review_fix.artifact_id,),
            "supersedes": qa_pass.artifact_id,
        }
    )
    review_final = review_template.model_copy(
        update={
            "artifact_id": "art_review_a_approve",
            "parent_artifact_ids": (qa_final.artifact_id,),
            "supersedes": review_reject.artifact_id,
        }
    )
    rounds: tuple[Artifact, ...] = (
        impl,
        qa_fail,
        impl_fix,
        qa_pass,
        review_reject,
        impl_review_fix,
        qa_final,
        review_final,
    )
    store = FileArtifactStore(tmp_path / "artifacts")
    store.put(seal_artifact(plan, validated_at=NOW))
    sealed: list[Artifact] = []
    receipts: list[AcceptedRoleArtifact] = []
    claims: dict[str, list[dict[str, object]]] = {}
    for index, artifact in enumerate(rounds, 1):
        # Provider clocks repeat and run backwards while all store seals share a timestamp.
        artifact = seal_artifact(
            artifact.model_copy(
                update={
                    "created_at": NOW + timedelta(days=100 if index % 2 else -100),
                    "context_manifest_id": "ctx_" + f"{index:064x}",
                    "producer": artifact.producer.model_copy(
                        update={"run_id": f"run_history_{index:03d}"}
                    ),
                }
            ),
            validated_at=NOW,
        )
        store.put(artifact)
        sealed.append(artifact)
        receipt = AcceptedRoleArtifact(
            task_id=artifact.task_id,
            work_item_id=f"work_history_{index:03d}",
            lease_id=f"lease_history_{index:03d}",
            dispatch_sequence=index,
            checkpoint_sequence=index,
            run_id=artifact.producer.run_id,
            context_manifest_id=artifact.context_manifest_id,
            source_revision=artifact.source_revision,
            receipt=QueueArtifactReceipt(
                artifact_id=artifact.artifact_id, sha256=artifact.integrity.sha256
            ),
        )
        receipts.append(receipt)
        claims[receipt.lease_id] = [
            _claim(receipt, sequence=index * 10, role=artifact.producer.role)
        ]
    cursor = _Cursor(tuple(reversed(receipts)), claims=claims)
    history = _read_accepted_artifact_history(
        cast(DictCursor, cursor),
        task_id=plan.task_id,
        sidecar=tmp_path,
        state_artifact_ids=(plan.artifact_id,),
    )
    snapshot = RunProjectionBuilder().build(
        ProjectionFacts(
            tasks=(make_task(),), artifacts=history.artifacts, artifact_positions=history.positions
        )
    )
    task = snapshot.tasks[0]
    assert task.qa_status == "PASS" and task.review_verdict == "APPROVE"
    expected = [plan.artifact_id, *(item.artifact_id for item in sealed)]
    assert [entry.id for entry in task.timeline] == expected
    assert all(entry.occurred_at == NOW for entry in task.timeline)
    for entry, artifact in zip(task.timeline[1:], sealed, strict=True):
        assert entry.details["provider_created_at"] == artifact.created_at.isoformat()
    view = TaskView(
        id="delivery_history",
        task_id=task.task_id,
        title="完整历史",
        status="NEW",
        project_id="project_history_001",
        request_id="request_history_001",
        scope=ScopeView(root="/tmp/history", selected_paths=(".",)),
        checkpoint_stage="DELIVERING",
        terminal=False,
        last_activity=NOW,
        next_action="由团队继续交付。",
        timeline=task.timeline,
    )
    assert [entry.id for entry in _merge_task_history(view, ()).execution_history] == expected
    assert len(task.timeline) > 8
    assert len(cursor.queries) == 3


@pytest.mark.parametrize("field", ["task_id", "artifact_sha256"])
def test_projection_rejects_changed_durable_artifact_position(tmp_path: Path, field: str) -> None:
    qa, receipt = _fixture(tmp_path)
    history = _read_accepted_artifact_history(
        cast(DictCursor, _Cursor((receipt,))),
        task_id=qa.task_id,
        sidecar=tmp_path,
        state_artifact_ids=(),
    )
    position = history.positions[0].model_copy(
        update={field: "task_other_history" if field == "task_id" else "f" * 64}
    )
    with pytest.raises(ProjectionConflict, match="exact sealed binding"):
        RunProjectionBuilder().build(
            ProjectionFacts(artifacts=history.artifacts, artifact_positions=(position,))
        )


def test_unsealed_provider_time_cannot_become_projection_publication_time() -> None:
    artifact = make_qa_artifact().model_copy(
        update={
            "integrity": make_qa_artifact().integrity.model_copy(
                update={"validated": False, "validated_at": None}
            )
        }
    )
    with pytest.raises(ProjectionConflict, match="sealed validation facts"):
        RunProjectionBuilder().build(ProjectionFacts(artifacts=(artifact,)))
