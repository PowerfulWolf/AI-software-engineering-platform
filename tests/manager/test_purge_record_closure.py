"""Formal writers define scope, storage keys and paired deletion files."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.multi_directory.purge import RequirementPurger, _owners
from ai_software_engineer.multi_directory.purge_state import (
    StateDeletionScope,
    verified_state_record,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn


def test_foreign_scope_receipt_and_wrong_storage_key_are_rejected(tmp_path: Path) -> None:
    from ai_software_engineer.manager.delivery_preflight import (
        DeliveryPreflightReceipt,
        DeliveryPreflightScope,
    )

    store = KnowledgeRecordStore(tmp_path / "state/preflight")
    expected = StateDeletionScope(
        team_id="team_owned",
        project_id="project_owned",
        repository_id="repository_owned",
        repository_root=str(tmp_path),
        requirement_ids=frozenset({"delivery_owned"}),
        task_ids=frozenset({"task_owned"}),
    )
    receipt = DeliveryPreflightReceipt(
        scope=DeliveryPreflightScope(
            team_id="team_foreign",
            project_id="project_foreign",
            repository_id="repository_foreign",
            requirement_id="delivery_foreign",
        ),
        task_id="task_owned",
        source_revision="a" * 40,
        plan_sha256="b" * 64,
        frozen_policy_sha256="c" * 64,
        requirements_sha256="d" * 64,
        observations=(),
        status="READY",
        checked_at=datetime.now(UTC),
        receipt_sha256="0" * 64,
    )
    receipt = receipt.model_copy(
        update={
            "receipt_sha256": digest(receipt.model_dump(mode="json", exclude={"receipt_sha256"}))
        }
    )
    store.put("preflight-receipts", receipt.receipt_sha256, receipt)
    path = store.root / store._name("preflight-receipts", receipt.receipt_sha256)
    with pytest.raises(ValueError, match="team_id differs"):
        verified_state_record(path, tmp_path, {}, expected)
    owned = receipt.model_copy(
        update={
            "scope": DeliveryPreflightScope(
                team_id=expected.team_id,
                project_id=expected.project_id,
                repository_id=expected.repository_id,
                requirement_id="delivery_owned",
            )
        }
    )
    owned = owned.model_copy(
        update={"receipt_sha256": digest(owned.model_dump(mode="json", exclude={"receipt_sha256"}))}
    )
    store.put("preflight-receipts", "wrong-key", owned)
    wrong = store.root / store._name("preflight-receipts", "wrong-key")
    with pytest.raises(ValueError, match="namespace/key differs"):
        verified_state_record(wrong, tmp_path, {}, expected)
    store.put("preflight-receipts", owned.receipt_sha256, owned)
    assert (
        verified_state_record(
            store.root / store._name("preflight-receipts", owned.receipt_sha256),
            tmp_path,
            {},
            expected,
        )
        == owned.to_wire()
    )


def test_real_rejected_checkpoint_writer_has_exact_owned_closure(tmp_path: Path) -> None:
    from ai_software_engineer.manager.rejected_output_checkpoint import read_rejected_checkpoint
    from tests.manager.test_rejected_coder_output import rejected_fixture

    state = tmp_path / "state"
    state.mkdir()
    with rejected_fixture(state) as fixture:
        fixture.collect(state)
        record = read_rejected_checkpoint(state, fixture.queue.item.id)
        assert record is not None
        scope = record.capture_start.scope
        expected = StateDeletionScope(
            team_id=scope.team_id,
            project_id=scope.project_id,
            repository_id=scope.repository_id,
            repository_root=fixture.native.task.repository,
            requirement_ids=frozenset({scope.requirement_id}),
            task_ids=frozenset({fixture.native.task.id}),
        )
        path = (
            state
            / "rejected-coder-output"
            / KnowledgeRecordStore._name("rejected-checkpoints", fixture.queue.item.id)
        )
        assert _owners({"record": record.to_wire()}) == {fixture.native.task.id}
        assert verified_state_record(path, tmp_path, {}, expected) == record.to_wire()
        foreign = expected.model_copy(update={"repository_id": "repository_foreign"})
        with pytest.raises(ValueError, match="repository_id differs"):
            verified_state_record(path, tmp_path, {}, foreign)


@pytest.mark.mysql
def test_real_handoff_writer_json_and_markdown_are_both_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mysql_dsn: str
) -> None:
    from ai_software_engineer.domain import TaskStatus
    from ai_software_engineer.evaluation import FileHandoffStore, HandoffBuilder
    from ai_software_engineer.multi_directory.service import CreateRequirement
    from tests.evaluation.test_handoff import _persist_trace
    from tests.manager.test_requirement_retirement import _service

    trace = tmp_path / "trace"
    trace.mkdir()
    repository, artifacts = _persist_trace(trace, terminal=TaskStatus.BLOCKED)
    owned_task = repository.get("task_domain_001")
    try:
        bundle = HandoffBuilder(repository=repository, artifact_store=artifacts).build(
            "task_domain_001"
        )
    finally:
        repository.close()
    service, root = _service(tmp_path / "platform", monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="handoff closure", repository_roots=(str(root),))
    ).checkpoint
    repo = service.project.repository_registry().discover()[0]
    from ai_software_engineer.evaluation.handoff import handoff_identity

    bundle = bundle.model_copy(update={"repository": str(repo.repository_root)})
    bundle = bundle.model_copy(update={"handoff_id": handoff_identity(bundle)})
    reference = FileHandoffStore(repo.root / "handoffs").put(bundle)
    from ai_software_engineer.domain import Task
    from tests.manager.test_requirement_cancellation import _Repository
    from tests.manager.test_requirement_resource_release import _persist_physical_delete_facts

    task = Task.model_validate({**owned_task.to_wire(), "repository": str(repo.repository_root)})
    from ai_software_engineer.multi_directory.deletion import ProductionRequirementDeletionGuard
    from tests.manager.test_requirement_deletion import _Queue

    service.deletion_guard = ProductionRequirementDeletionGuard(
        service.project, _Queue(), mysql_dsn
    )
    _persist_physical_delete_facts(service, _Repository(task), mysql_dsn, tmp_path)
    purger = RequirementPurger(service.project, mysql_dsn)
    plan = purger.prepare(
        checkpoint, {bundle.task_id: (repo.root, str(repo.repository_root))}, native_ids={}
    )
    assert {
        reference.json_path.relative_to(service.project.root).as_posix(),
        reference.markdown_path.relative_to(service.project.root).as_posix(),
    } <= {item.path for item in plan.files}
    purger.execute(plan)
    assert not reference.json_path.exists() and not reference.markdown_path.exists()


def test_foreign_policy_scope_is_rejected_after_real_admission_writer(tmp_path: Path) -> None:
    from ai_software_engineer.domain.engineering_authority import EngineeringCapability
    from tests.domain.factories import NOW
    from tests.manager.test_engineering_authority import engineering_fixture

    task, store, authority = engineering_fixture(tmp_path)
    admission = authority.admit(
        task=task,
        store=store,
        plan_sha256="a" * 64,
        facts_sha256="b" * 64,
        capabilities=(EngineeringCapability.VERIFICATION_REFRESH,),
        at=NOW,
    )
    path = tmp_path / "recovery" / ("engineering-admission-" + admission.plan_sha256 + ".json")
    expected = StateDeletionScope(
        team_id="team_other",
        project_id="project_test",
        repository_id="repository_test",
        repository_root=task.repository,
        requirement_ids=frozenset({"delivery_test"}),
        task_ids=frozenset({task.id}),
    )
    with pytest.raises(ValueError, match="team_id differs"):
        verified_state_record(path, tmp_path, {}, expected)
    assert store.get_engineering_admission(admission.plan_sha256) == admission


def test_foreign_evidence_repository_identity_is_rejected(tmp_path: Path) -> None:
    from ai_software_engineer.evidence import FileEvidenceStore
    from ai_software_engineer.multi_directory.purge_records import verified_record
    from tests.evidence.test_store import _record

    record = _record()
    FileEvidenceStore(tmp_path / "evidence", tmp_path / "runs").put(record)
    path = tmp_path / "evidence" / (record.evidence_id + ".json")
    expected = StateDeletionScope(
        team_id="team_owned",
        project_id="project_owned",
        repository_id="repository_other",
        repository_root=str(tmp_path),
        requirement_ids=frozenset({"delivery_owned"}),
        task_ids=frozenset({record.identity.task_id}),
    )
    with pytest.raises(ValueError, match="repository_id differs"):
        verified_record(path, tmp_path, record.to_wire(), expected)
    assert path.exists()


@pytest.mark.parametrize("field", ["team_id", "project_id", "repository_id", "requirement_ids"])
def test_continuation_directory_requires_full_scope_from_real_writer(
    tmp_path: Path, field: str
) -> None:
    from ai_software_engineer.multi_directory.purge_state import task_state_directories
    from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
    from tests.orchestration.test_continuation_records import make_receipt

    receipt = make_receipt(tmp_path)
    sidecar = tmp_path / "sidecar"
    parent = sidecar / "state/continuations"
    parent.mkdir(parents=True)
    root = parent / receipt.request.task_id
    store = FileContinuationStore.initialize(root, task_id=receipt.request.task_id)
    store.put_receipt(receipt)
    expected = StateDeletionScope(
        team_id=receipt.scope.team_id,
        project_id=receipt.scope.project_id,
        repository_id=receipt.scope.repository_id,
        repository_root=str(tmp_path),
        requirement_ids=frozenset({receipt.scope.requirement_id}),
        task_ids=frozenset({receipt.request.task_id}),
    )
    assert task_state_directories(sidecar, expected) == (root,)
    foreign = expected.model_copy(
        update={field: frozenset({"foreign"}) if field == "requirement_ids" else "foreign"}
    )
    with pytest.raises(ValueError, match="differs"):
        task_state_directories(sidecar, foreign)
    (root / "unknown.json").write_text("{}")
    with pytest.raises(ValueError, match="unsupported"):
        task_state_directories(sidecar, expected)
    assert store.receipt_for_task(receipt.request.task_id) == receipt


def test_baseline_directory_requires_scope_and_complete_namespace_inventory(tmp_path: Path) -> None:
    from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
    from ai_software_engineer.multi_directory.purge_state import task_state_directories
    from tests.manager.test_execution_baseline import authorize, setup

    fixture = setup(tmp_path)
    task = fixture.collector.facts.task
    sidecar = tmp_path / "sidecar"
    root = sidecar / "state/execution-baselines" / task.id
    fixture.service.store = FileExecutionBaselineStore(root)
    plan = fixture.service.propose(fixture.target)
    fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    scope = fixture.collector.facts.scope
    expected = StateDeletionScope(
        team_id=scope.team_id,
        project_id=scope.project_id,
        repository_id=scope.repository_id,
        repository_root=scope.repository_root,
        requirement_ids=frozenset(),
        task_ids=frozenset({task.id}),
    )
    assert task_state_directories(sidecar, expected) == (root,)
    with pytest.raises(ValueError, match="team_id differs"):
        task_state_directories(sidecar, expected.model_copy(update={"team_id": "foreign"}))
    (root / "unknown.json").write_text("{}")
    with pytest.raises(ValueError, match="unsupported"):
        task_state_directories(sidecar, expected)


def test_nested_quiescence_legacy_scope_is_checked_from_real_producer(tmp_path: Path) -> None:
    from ai_software_engineer.knowledge.models import digest
    from ai_software_engineer.manager.baseline_production import BaselineQuiescenceProof
    from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
    from ai_software_engineer.multi_directory.purge_state import task_state_directories
    from tests.manager.test_legacy_containment import legacy_fixture

    collector, task, item, legacy = legacy_fixture(tmp_path)
    invocations = collector._invocations(task, (item,), (), (), legacy=legacy)
    sidecar = tmp_path / "sidecar"
    root = sidecar / "state/execution-baselines" / task.id
    store = FileExecutionBaselineStore(root)
    proof = BaselineQuiescenceProof(
        task_id=task.id,
        task_revision=2,
        task_snapshot_sha256=digest(task.to_wire()),
        task_events_sha256="a" * 64,
        allocation_sha256=collector.allocation.dispatch_sha256,
        queue_snapshot_sha256=digest([item.to_wire()]),
        assignments_sha256=digest([]),
        invocations=invocations,
    )
    store.records.put("baseline-quiescence", digest(proof.to_wire()), proof)
    expected = StateDeletionScope(
        team_id=legacy.scope.team_id,
        project_id=legacy.scope.project_id,
        repository_id=legacy.scope.repository_id,
        repository_root=task.repository,
        requirement_ids=frozenset({legacy.requirement_id}),
        task_ids=frozenset({task.id}),
    )
    assert task_state_directories(sidecar, expected) == (root,)
    with pytest.raises(ValueError, match="team_id differs"):
        task_state_directories(sidecar, expected.model_copy(update={"team_id": "foreign"}))
