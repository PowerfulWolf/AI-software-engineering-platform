"""Public deletion removes data rather than hiding a retained Requirement."""

from pathlib import Path

import pytest

from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.multi_directory.retirement import RequirementRetiredError
from ai_software_engineer.multi_directory.service import CreateRequirement, DeleteRequirement
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_requirement_retirement import _service


def test_draft_delete_physically_removes_journal_and_attachments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, root = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="physical", repository_roots=(str(root),))
    ).checkpoint
    directory = service.journal.directory(checkpoint.delivery_id)
    attachments = directory / "attachments"
    attachments.mkdir()
    (attachments / "private.txt").write_text("private requirement data")
    command = DeleteRequirement(
        delivery_id=checkpoint.delivery_id, expected_checkpoint_sha256=checkpoint.checkpoint_sha256
    )
    service.delete_requirement(command)
    assert not directory.exists()
    assert service.journal.current(checkpoint.delivery_id) is None
    with pytest.raises(RequirementRetiredError):
        service.resume(ResumeProjectDelivery(delivery_id=checkpoint.delivery_id))
    recreated = service.create(
        CreateRequirement(name="physical", repository_roots=(str(root),))
    ).checkpoint
    assert recreated.delivery_id != checkpoint.delivery_id


def test_owned_knowledge_queries_removed_and_foreign_record_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.domain.enums import TeamRole
    from ai_software_engineer.knowledge.agents import KnowledgeIntent
    from ai_software_engineer.knowledge.models import KnowledgeRunBinding
    from ai_software_engineer.knowledge.store import KnowledgeRecordStore

    service, root = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="knowledge", repository_roots=(str(root),))
    ).checkpoint
    repo = service.project.repository_registry().discover()[0]
    records = KnowledgeRecordStore(repo.root / "knowledge/runs")
    binding = KnowledgeRunBinding(
        run_id="run_delete_knowledge",
        role=TeamRole.PRODUCT,
        team_id=checkpoint.team_id,
        project_id=checkpoint.project_id,
        requirement_id=checkpoint.delivery_id,
        repository_ids=(repo.repository_id,),
        source_revision="a" * 40,
        context_manifest_id="ctx_" + "a" * 64,
        snapshot_sha256="b" * 64,
    )
    foreign = binding.model_copy(
        update={"run_id": "run_foreign_knowledge", "requirement_id": "foreign_requirement"}
    )
    for item in (binding, foreign):
        records.put("bindings", item.run_id, item)
        records.put("knowledge-intents", item.run_id, KnowledgeIntent(queries=()))
    service.delete_requirement(
        DeleteRequirement(
            delivery_id=checkpoint.delivery_id,
            expected_checkpoint_sha256=checkpoint.checkpoint_sha256,
        )
    )
    assert records.find("knowledge-intents", binding.run_id, KnowledgeIntent) is None
    assert records.find("bindings", binding.run_id, KnowledgeRunBinding) is None
    assert records.find("knowledge-intents", foreign.run_id, KnowledgeIntent) is not None
    assert records.get("bindings", foreign.run_id, KnowledgeRunBinding) == foreign


def test_prepare_before_retirement_crash_is_replayable_without_reviving_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, root = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="crash", repository_roots=(str(root),))
    ).checkpoint
    command = DeleteRequirement(
        delivery_id=checkpoint.delivery_id, expected_checkpoint_sha256=checkpoint.checkpoint_sha256
    )
    original = service._retire_deleted

    def crash(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected before retirement")

    monkeypatch.setattr(service, "_retire_deleted", crash)
    with pytest.raises(RuntimeError, match="injected"):
        service.delete_requirement(command)
    assert service.journal.directory(checkpoint.delivery_id).exists()
    monkeypatch.setattr(service, "_retire_deleted", original)
    service.delete_requirement(command)
    with pytest.raises(RequirementRetiredError):
        service.journal.append(checkpoint, expected=None)
    assert not service.journal.directory(checkpoint.delivery_id).exists()


def test_partial_file_deletion_can_replay_exact_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_software_engineer.multi_directory.purge as purge

    service, root = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="partial", repository_roots=(str(root),))
    ).checkpoint
    command = DeleteRequirement(
        delivery_id=checkpoint.delivery_id, expected_checkpoint_sha256=checkpoint.checkpoint_sha256
    )
    unlink = purge._unlink_sealed
    calls = 0

    def fail_after_first(base: Path, item: purge.PurgeFile) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected partial delete")
        unlink(base, item)

    monkeypatch.setattr(purge, "_unlink_sealed", fail_after_first)
    with pytest.raises(OSError, match="injected"):
        service.delete_requirement(command)
    monkeypatch.setattr(purge, "_unlink_sealed", unlink)
    service.delete_requirement(command)
    assert not service.journal.directory(checkpoint.delivery_id).exists()
    assert (
        purge.read_purge_completion(service.project.requirements_root, checkpoint.delivery_id)
        is not None
    )


def test_unsealed_file_drift_refuses_delete_even_with_same_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.multi_directory.purge import (
        RequirementPurger,
        RequirementPurgeRejected,
    )

    service, root = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="tamper", repository_roots=(str(root),))
    ).checkpoint
    private = service.journal.directory(checkpoint.delivery_id) / "private.txt"
    private.write_text("first")
    purger = RequirementPurger(service.project)
    plan = purger.prepare(checkpoint, {}, native_ids={})
    private.write_text("other")
    with pytest.raises(RequirementPurgeRejected, match="已变化"):
        purger.execute(plan)
    assert private.read_text() == "other"


def test_corrupt_artifact_owner_rejected_before_any_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from ai_software_engineer.artifacts.store import (
        ArtifactCorruption,
        FileArtifactStore,
        seal_artifact,
    )
    from ai_software_engineer.multi_directory.purge import RequirementPurger
    from tests.domain.factories import NOW, make_qa_artifact
    from tests.manager.test_requirement_deletion import _delivery

    service, checkpoint, sidecar, _, _ = _delivery(tmp_path, monkeypatch)
    task_id = checkpoint.children[0].checkpoint.task_id
    assert task_id is not None
    artifact = seal_artifact(make_qa_artifact(), validated_at=NOW)
    store = FileArtifactStore(sidecar / "artifacts")
    # Put a sealed real record with valid parent references through its writer.
    path = sidecar / "artifacts" / (artifact.artifact_id + ".json")
    path.write_text(json.dumps(artifact.to_wire()))
    assert store.get(artifact.artifact_id) == artifact
    payload = artifact.to_wire()
    payload["task_id"] = task_id
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    with pytest.raises(ArtifactCorruption):
        RequirementPurger(service.project).prepare(
            checkpoint,
            {
                task_id: (
                    sidecar,
                    str(service.project.repository_registry().discover()[0].repository_root),
                )
            },
            native_ids={},
            persist=False,
        )
    assert path.read_bytes() == before
    assert service.journal.directory(checkpoint.delivery_id).exists()
    assert not (service.project.requirements_root / "purge-pending").exists()


@pytest.mark.mysql
def test_real_wait_authority_writer_closure_is_physically_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mysql_dsn: str
) -> None:
    from datetime import UTC, datetime

    from ai_software_engineer.domain import Task
    from ai_software_engineer.domain.engineering_authority import (
        EngineeringCapability,
        EngineeringPolicy,
        EngineeringScope,
        LocalOperatorPrincipal,
    )
    from ai_software_engineer.knowledge.models import digest
    from ai_software_engineer.manager.delivery_wait import delivery_wait_recovery_scope
    from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
    from ai_software_engineer.recovery.store import FileRecoveryStore
    from tests.manager.test_requirement_deletion import _delete
    from tests.manager.test_requirement_resource_release import _persist_physical_delete_facts
    from tests.manager.test_waiting_requirement_close import _close, _waiting

    service, checkpoint, repository, queue, _ = _waiting(tmp_path, monkeypatch)
    repo = service.project.repository_registry().discover()[0]
    task = next(iter(repository.tasks.values()))
    scope = EngineeringScope(
        team_id=checkpoint.team_id,
        project_id=checkpoint.project_id,
        repository_id=repo.repository_id,
        repository_root=task.repository,
    )
    policy = EngineeringPolicy.bounded_local(
        scope=scope, principal=LocalOperatorPrincipal.trusted_local()
    )
    task = Task.model_validate({**task.to_wire(), "engineering_policy": policy.to_wire()})
    repository.tasks[task.id] = task
    from tests.manager.test_waiting_requirement_close import _waiting_item

    item = _waiting_item(task, repo.repository_id)
    queue.items[item.id] = item
    closed = _close(service, checkpoint)
    task = repository.get(task.id)
    local = repo.root / "state" / ("delivery-wait-authority-" + digest(task.id))
    records = FileRecoveryStore.initialize(local, scope=delivery_wait_recovery_scope(task, scope))
    ledger_root = service.team.directory("work-items")
    admission = EngineeringAuthority(ledger_root).admit(
        task=task,
        store=records,
        plan_sha256="a" * 64,
        facts_sha256="b" * 64,
        capabilities=(EngineeringCapability.DELIVERY_WAIT_RESOLUTION,),
        at=datetime.now(UTC),
    )
    assert records.list_engineering_admissions() == (admission,)
    ledger = ledger_root / digest({"repository_id": repo.repository_id, "task_id": task.id})
    assert (ledger / "scope.json").exists()
    _persist_physical_delete_facts(service, repository, mysql_dsn, tmp_path)
    _delete(service, closed)
    assert not local.exists()
    assert not ledger.exists()
    _delete(service, closed)


def test_purge_schemas_match_models_and_validate_real_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    import jsonschema

    from ai_software_engineer.multi_directory.purge import (
        RequirementPurgeCompletion,
        RequirementPurgePlan,
        RequirementPurger,
    )

    service, root = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="schema", repository_roots=(str(root),))
    ).checkpoint
    plan = RequirementPurger(service.project).prepare(checkpoint, {}, native_ids={}, persist=False)
    for model, value, filename in (
        (RequirementPurgePlan, plan, "requirement-purge-plan.schema.json"),
        (
            RequirementPurgeCompletion,
            RequirementPurger._completion(plan),
            "requirement-purge-completion.schema.json",
        ),
    ):
        schema = json.loads((Path("schemas") / filename).read_text())
        expected = model.model_json_schema()
        assert {
            key: item for key, item in schema.items() if key not in {"$schema", "$id"}
        } == expected
        jsonschema.Draft202012Validator(schema).validate(value.to_wire())
        value.validate_integrity()


def test_persisted_plan_size_is_checked_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_software_engineer.multi_directory.purge as purge

    service, root = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="capacity", repository_roots=(str(root),))
    ).checkpoint
    purger = purge.RequirementPurger(service.project)
    plan = purger.prepare(checkpoint, {}, native_ids={}, persist=False)
    compact_size = len(plan.model_dump_json().encode())
    assert compact_size < len(plan.model_dump_json(indent=2).encode())
    monkeypatch.setattr(purge, "_MAX_PLAN", compact_size)
    with pytest.raises(purge.RequirementPurgeRejected, match=r"容量|过大"):
        purger.prepare(checkpoint, {}, native_ids={})
    with pytest.raises(purge.RequirementPurgeRejected, match=r"容量|过大"):
        purge._publish(purger.plan_path(checkpoint.delivery_id), plan)
    assert not purger.plan_path(checkpoint.delivery_id).exists()
    assert service.journal.current(checkpoint.delivery_id) == checkpoint


def test_completion_publication_before_pending_removal_replays_public_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.multi_directory.purge import RequirementPurger, read_purge_completion

    service, root = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="marker-window", repository_roots=(str(root),))
    ).checkpoint
    command = DeleteRequirement(
        delivery_id=checkpoint.delivery_id, expected_checkpoint_sha256=checkpoint.checkpoint_sha256
    )
    pending_path = RequirementPurger(service.project).plan_path(checkpoint.delivery_id)
    unlink = Path.unlink

    def interrupt(path: Path, missing_ok: bool = False) -> None:
        if path == pending_path:
            raise OSError("fixture pending removal interruption")
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", interrupt)
    with pytest.raises(OSError, match="interruption"):
        service.delete_requirement(command)
    assert pending_path.exists()
    assert (
        read_purge_completion(service.project.requirements_root, checkpoint.delivery_id) is not None
    )
    monkeypatch.setattr(Path, "unlink", unlink)
    service.delete_requirement(command)
    assert not pending_path.exists()
    assert not service.journal.directory(checkpoint.delivery_id).exists()
