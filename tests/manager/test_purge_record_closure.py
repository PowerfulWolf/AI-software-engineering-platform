"""Formal writers define scope, storage keys and paired deletion files."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.knowledge.models import KnowledgeError, digest
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


def _knowledge_carry(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, StateDeletionScope]:
    from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
    from ai_software_engineer.knowledge.models import KnowledgeRunBinding
    from ai_software_engineer.manager.rejected_knowledge_preparation import (
        RejectedKnowledgeCarryRefusal,
    )
    from ai_software_engineer.work_queue.models import QueueClaim
    from tests.knowledge import test_assessment_rejection as assessment
    from tests.knowledge.test_invocation_native import _actual_claim

    def scoped_claim(bound: KnowledgeRunBinding) -> QueueClaim:
        # Keep the fixture's real invocation claim inside this exact repository.
        claim = _actual_claim(bound)
        return claim.model_copy(
            update={
                "work_item": claim.work_item.model_copy(update={"repository_scopes": (str(root),)})
            }
        )

    monkeypatch.setattr(assessment, "_actual_claim", scoped_claim)
    case = assessment._http_rejection(root, assessment_fallback=False)
    claim = case.observation.original_claim
    record = RejectedKnowledgeCarryRefusal(
        observation_sha256=case.observation.observation_sha256,
        claim=claim,
        claim_sha256=claim_identity_sha256(claim),
        refused_at=datetime.now(UTC),
        refusal_sha256="0" * 64,
    )
    record = record.model_copy(
        update={
            "refusal_sha256": digest(record.model_dump(mode="json", exclude={"refusal_sha256"}))
        }
    )
    store = KnowledgeRecordStore(root / "state/rejected-knowledge")
    store.put("carry-refusals", claim.lease.id, record)
    expected = StateDeletionScope(
        team_id=case.bound.team_id,
        project_id=case.bound.project_id,
        repository_id=case.bound.repository_ids[0],
        repository_root=str(root),
        requirement_ids=frozenset({case.bound.requirement_id}),
        task_ids=frozenset({claim.work_item.task_id}),
    )
    return store.root / store._name("carry-refusals", claim.lease.id), expected


def test_knowledge_carry_requires_typed_owned_deletion_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, expected = _knowledge_carry(tmp_path, monkeypatch)
    assert (
        verified_state_record(path, tmp_path, {}, expected)["kind"]
        == "rejected_knowledge_carry_refusal"
    )


@pytest.mark.parametrize(
    "field",
    ["team_id", "project_id", "repository_id", "repository_root", "requirement_ids", "task_ids"],
)
def test_knowledge_carry_deletion_refuses_foreign_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    path, expected = _knowledge_carry(tmp_path, monkeypatch)
    before = path.read_bytes()
    foreign = expected.model_copy(
        update={field: frozenset({"foreign"}) if field.endswith("_ids") else "foreign"}
    )
    with pytest.raises(ValueError, match="differs"):
        verified_state_record(path, tmp_path, {}, foreign)
    assert path.read_bytes() == before


def test_knowledge_carry_selector_selects_owned_file_and_retains_foreign_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_software_engineer.multi_directory.purge_state import rejected_knowledge_files

    path, expected = _knowledge_carry(tmp_path, monkeypatch)
    before = path.read_bytes()
    assert rejected_knowledge_files(tmp_path, expected) == (path,)
    assert (
        rejected_knowledge_files(tmp_path, expected.model_copy(update={"task_ids": frozenset()}))
        == ()
    )
    assert path.read_bytes() == before
    unknown = path.parent / "unknown.json"
    unknown.write_text("{}")
    with pytest.raises(ValueError, match="unsupported"):
        rejected_knowledge_files(tmp_path, expected)
    assert path.read_bytes() == before and unknown.exists()


def test_knowledge_carry_wrong_key_and_missing_observation_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_software_engineer.multi_directory.purge_state import rejected_knowledge_files

    path, expected = _knowledge_carry(tmp_path, monkeypatch)
    wrong = path.with_name(KnowledgeRecordStore._name("carry-refusals", "wrong-key"))
    path.rename(wrong)
    with pytest.raises(ValueError, match="storage key"):
        rejected_knowledge_files(tmp_path, expected)
    wrong.rename(path)
    for observation in (tmp_path / "knowledge/runs").glob("assessment-rejections-*.json"):
        observation.unlink()
    with pytest.raises((KnowledgeError, ValueError)):
        rejected_knowledge_files(tmp_path, expected)
    assert path.exists()


def test_original_semantic_observation_has_typed_knowledge_deletion_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_software_engineer.multi_directory.purge_knowledge import select_knowledge
    from ai_software_engineer.multi_directory.service import CreateRequirement
    from tests.manager.test_requirement_retirement import _service

    root = tmp_path / "knowledge-fixture"
    root.mkdir()
    _, expected = _knowledge_carry(root, monkeypatch)
    service, repository = _service(tmp_path / "platform-fixture", monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="closure", repository_roots=(str(repository),))
    ).checkpoint
    checkpoint = checkpoint.model_copy(
        update={"team_id": expected.team_id, "project_id": expected.project_id}
    )
    task_id = next(iter(expected.task_ids))
    records = root / "knowledge/runs"
    originals = tuple(records.glob("assessment-rejections-*.json"))
    assert len(originals) == 1
    selected = select_knowledge(
        records,
        checkpoint,
        identities={task_id, *expected.requirement_ids},
        task_repositories={task_id: expected.repository_id},
        repository_id=expected.repository_id,
    )
    assert originals[0] in selected
    assert (
        select_knowledge(
            records,
            checkpoint,
            identities=set(),
            task_repositories={task_id: expected.repository_id},
            repository_id=expected.repository_id,
        )
        == ()
    )
    wrong = originals[0].with_name(KnowledgeRecordStore._name("assessment-rejections", "wrong-key"))
    originals[0].rename(wrong)
    with pytest.raises((KnowledgeError, ValueError)):
        select_knowledge(
            records,
            checkpoint,
            identities={task_id, *expected.requirement_ids},
            task_repositories={task_id: expected.repository_id},
            repository_id=expected.repository_id,
        )
    assert wrong.exists()


def _current_draft_deletion(
    root: Path,
) -> tuple[Path, StateDeletionScope]:
    from tests.manager.test_rejected_knowledge_current_draft import current_draft_fixture

    fixture = current_draft_fixture(root)
    evidence = fixture.evidence()
    assert evidence.current_draft_sha256 is not None
    path = (
        fixture.state
        / "rejected-knowledge"
        / KnowledgeRecordStore._name("current-drafts", evidence.current_draft_sha256)
    )
    expected = StateDeletionScope(
        team_id=fixture.scope.team_id,
        project_id=fixture.scope.project_id,
        repository_id=fixture.scope.repository_id,
        repository_root=fixture.scope.repository_root,
        requirement_ids=frozenset({"delivery_parent_scope", "delivery_current_draft"}),
        task_ids=frozenset({fixture.task.id}),
    )
    return path, expected


def test_current_draft_selector_uses_exact_record_and_keeps_other_tasks(tmp_path: Path) -> None:
    from ai_software_engineer.multi_directory.purge_state import rejected_knowledge_files

    path, expected = _current_draft_deletion(tmp_path)
    sidecar = path.parent.parent.parent
    before = path.read_bytes()
    assert rejected_knowledge_files(sidecar, expected) == (path,)
    assert (
        verified_state_record(path, sidecar, {}, expected)["kind"]
        == "rejected_knowledge_current_draft"
    )
    assert (
        rejected_knowledge_files(sidecar, expected.model_copy(update={"task_ids": frozenset()}))
        == ()
    )
    assert path.read_bytes() == before
    unknown = path.parent / "unknown.json"
    unknown.write_text("{}")
    with pytest.raises(ValueError, match="unsupported"):
        rejected_knowledge_files(sidecar, expected)
    assert path.read_bytes() == before and unknown.exists()


@pytest.mark.parametrize(
    "mutation", ["key", "scope", "nested-task", "sibling-task-alias", "digest"]
)
def test_current_draft_selector_refuses_changed_scope_key_and_complete_graph(
    tmp_path: Path,
    mutation: str,
) -> None:
    import json

    from ai_software_engineer.knowledge.assessment_rejection import RejectedKnowledgeAssessment
    from ai_software_engineer.manager.rejected_knowledge_draft import RejectedKnowledgeCurrentDraft
    from ai_software_engineer.multi_directory.purge_state import rejected_knowledge_files

    path, expected = _current_draft_deletion(tmp_path)
    sidecar = path.parent.parent.parent
    store = KnowledgeRecordStore(path.parent)
    record = KnowledgeRecordStore._decode_payload(path.read_bytes(), RejectedKnowledgeCurrentDraft)
    if mutation == "key":
        wrong = path.with_name(store._name("current-drafts", "wrong-key"))
        path.rename(wrong)
    elif mutation == "scope":
        expected = expected.model_copy(update={"project_id": "project_foreign"})
    elif mutation == "digest":
        envelope = json.loads(path.read_text())
        envelope["sha256"] = "f" * 64
        path.write_text(json.dumps(envelope))
    else:
        if mutation == "nested-task":
            changed = record.model_copy(
                update={
                    "publication": record.publication.model_copy(update={"task_id": "task_foreign"})
                }
            )
        else:
            knowledge = KnowledgeRecordStore(sidecar / "knowledge/runs")
            original = knowledge.get(
                "assessment-rejections", record.observation_sha256, RejectedKnowledgeAssessment
            )
            bound = original.binding.model_copy(update={"requirement_id": "task_foreign"})
            manifest = original.manifest.model_copy(update={"binding": bound})
            manifest = manifest.model_copy(
                update={
                    "manifest_sha256": digest(
                        manifest.model_dump(mode="json", exclude={"manifest_sha256"})
                    )
                }
            )
            changed_observation = RejectedKnowledgeAssessment.create(
                **original.model_dump(exclude={"binding", "manifest", "observation_sha256"}),
                binding=bound,
                manifest=manifest,
            )
            knowledge.put(
                "assessment-rejections", changed_observation.observation_sha256, changed_observation
            )
            changed = record.model_copy(
                update={"observation_sha256": changed_observation.observation_sha256}
            )
            expected = expected.model_copy(
                update={"task_ids": expected.task_ids | {"task_foreign"}}
            )
        changed = changed.model_copy(update={"record_sha256": changed.recompute_sha256()})
        path.unlink()
        # Self-consistently resealed hostile envelope bypasses the real writer's
        # read-after-write validation, so the cleanup reader must still reject.
        changed_path = path.parent / store._name("current-drafts", changed.record_sha256)
        changed_path.write_text(
            json.dumps({"record": changed.to_wire(), "sha256": digest(changed.to_wire())})
        )
    before = {value: value.read_bytes() for value in path.parent.glob("*.json")}
    with pytest.raises((KnowledgeError, ValueError)):
        rejected_knowledge_files(sidecar, expected)
    assert all(value.read_bytes() == content for value, content in before.items())


@pytest.mark.parametrize("kernel_change", ["boot", "reused-pid"])
def test_native_knowledge_deletion_uses_history_after_kernel_identity_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kernel_change: str,
) -> None:
    import json

    from ai_software_engineer.agents.structured_observation import StructuredNativeStopReceipt
    from ai_software_engineer.knowledge.assessment_rejection import (
        RejectedKnowledgeAssessment,
        read_rejected_assessment,
    )
    from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
    from ai_software_engineer.knowledge.invocation import (
        KnowledgeExecutionRecord,
        invocation_lane_sha256,
    )
    from ai_software_engineer.manager.rejected_knowledge_draft import RejectedKnowledgeCurrentDraft
    from ai_software_engineer.manager.rejected_knowledge_preparation import (
        RejectedKnowledgeCarryRefusal,
    )
    from ai_software_engineer.multi_directory.purge_knowledge import select_knowledge
    from ai_software_engineer.multi_directory.purge_state import rejected_knowledge_files
    from ai_software_engineer.multi_directory.service import CreateRequirement
    from ai_software_engineer.owned_sessions import OwnedProcessIdentity
    from tests.manager.test_requirement_retirement import _service

    draft_path, expected = _current_draft_deletion(tmp_path)
    sidecar = draft_path.parent.parent.parent
    state = KnowledgeRecordStore(draft_path.parent)
    draft = state._decode_payload(draft_path.read_bytes(), RejectedKnowledgeCurrentDraft)
    records = KnowledgeRecordStore(sidecar / "knowledge/runs")
    observation = records.get(
        "assessment-rejections", draft.observation_sha256, RejectedKnowledgeAssessment
    )
    lane = KnowledgeRecordStore(
        records.root / "invocations" / invocation_lane_sha256(observation.binding)
    )
    native_record = next(
        record
        for record in lane.list("knowledge-execution-records", KnowledgeExecutionRecord)
        if isinstance(record.observation, StructuredNativeStopReceipt)
    )
    native = native_record.observation
    assert isinstance(native, StructuredNativeStopReceipt)
    proof = native.process_stop.session_proof
    assert proof is not None
    original_boot = proof.boot_identity
    original_leader = proof.leader
    claim = observation.original_claim
    carry = RejectedKnowledgeCarryRefusal(
        observation_sha256=observation.observation_sha256,
        claim=claim,
        claim_sha256=claim_identity_sha256(claim),
        refused_at=datetime.now(UTC),
        refusal_sha256="0" * 64,
    )
    carry = carry.model_copy(
        update={"refusal_sha256": digest(carry.model_dump(mode="json", exclude={"refusal_sha256"}))}
    )
    state.put("carry-refusals", claim.lease.id, carry)
    carry_path = state.root / state._name("carry-refusals", claim.lease.id)

    class ChangedKernelInspector:
        def boot_identity(self) -> str:
            return original_boot + ":later" if kernel_change == "boot" else original_boot

        def identity(self, pid: int) -> OwnedProcessIdentity | None:
            if kernel_change == "reused-pid" and pid == original_leader.process_id:
                return original_leader.model_copy(update={"birth_identity": "reused-pid-new-birth"})
            return None

        def members(self, sid: int) -> tuple[OwnedProcessIdentity, ...]:
            return ()

    # The original stop was produced by real owned processes. Only current OS
    # observation changes: history stays byte-for-byte intact after reboot/reuse.
    monkeypatch.setattr("ai_software_engineer.owned_sessions._inspector", ChangedKernelInspector)
    before = {path: path.read_bytes() for path in sidecar.rglob("*.json")}
    with pytest.raises(KnowledgeError, match="EXECUTION_UNKNOWN"):
        read_rejected_assessment(records.root, observation.observation_sha256)
    assert set(rejected_knowledge_files(sidecar, expected)) == {draft_path, carry_path}

    service, repository = _service(tmp_path / "platform-fixture", monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="native history closure", repository_roots=(str(repository),))
    ).checkpoint.model_copy(update={"team_id": expected.team_id, "project_id": expected.project_id})
    task_id = next(iter(expected.task_ids))

    def selected_knowledge() -> tuple[Path, ...]:
        return select_knowledge(
            records.root,
            checkpoint,
            identities={task_id, *expected.requirement_ids},
            task_repositories={task_id: expected.repository_id},
            repository_id=expected.repository_id,
        )

    observation_path = records.root / records._name(
        "assessment-rejections", observation.observation_sha256
    )
    assert observation_path in selected_knowledge()
    assert all(path.read_bytes() == content for path, content in before.items())
    # Omitting current OS checks must never omit the independently sealed native
    # stop proof. Even a resealed outer record with a corrupt inner digest refuses.
    native_path = lane.root / lane._name("knowledge-execution-records", native_record.record_sha256)
    envelope = json.loads(native_path.read_text())
    envelope["record"]["observation"]["process_stop"]["session_proof"]["proof_sha256"] = "f" * 64
    envelope["sha256"] = digest(envelope["record"])
    native_path.write_text(json.dumps(envelope))
    damaged = {path: path.read_bytes() for path in sidecar.rglob("*.json")}
    with pytest.raises((KnowledgeError, ValueError)):
        rejected_knowledge_files(sidecar, expected)
    with pytest.raises((KnowledgeError, ValueError)):
        selected_knowledge()
    assert all(path.read_bytes() == content for path, content in damaged.items())
