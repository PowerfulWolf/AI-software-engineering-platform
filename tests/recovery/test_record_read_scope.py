"""Recovery's real immutable consumers reuse decode, never current authority/facts."""

from __future__ import annotations

import asyncio
import hashlib
import os
import weakref
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import store as context_store
from ai_software_engineer.context.models import ContextBundle
from ai_software_engineer.context.ports import ContextCorruption, ContextStoreError
from ai_software_engineer.context.store import FileContextStore
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline import ProjectSpecBaseline
from ai_software_engineer.manager.baseline_models import (
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import ProjectDeliveryCheckpoint
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.manager.production_backend import ProductionProjectDeliveryBackend
from ai_software_engineer.read_record_scope import (
    current_recovery_record_reads,
    decode_verified_record,
    finish_recovery_record_reads,
    recovery_record_read_scope,
)
from ai_software_engineer.recovery import resume as resume_module
from ai_software_engineer.recovery.current import NativeRecoveryFacts
from ai_software_engineer.recovery.entry import (
    ExplicitRecoveryHuman,
    NativeRecoveryEntry,
    NativeRecoveryExecution,
)
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected
from ai_software_engineer.recovery.resume import DeliveryResumeController, DeliveryResumeResult
from ai_software_engineer.recovery.sealing import RecoveryTaskSealingService
from ai_software_engineer.recovery.service import RecoveryAuthorizationService
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.task import AuthorizedRecoveryTaskBuilder
from ai_software_engineer.repository_profile import RepositoryProfile
from tests.context.test_store import _bundle
from tests.manager.test_execution_baseline import Setup, authorize, setup
from tests.recovery.test_authorization import Captures
from tests.recovery.test_task_policy_builder import authorized_plan, policy_fixture


def _bound(
    tmp_path: Path,
) -> tuple[Setup, ExecutionBaselinePlan, ExecutionBaselineBinding, FileExecutionBaselineStore]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture = setup(tmp_path)
    plan = fixture.service.propose(fixture.target)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    readonly = FileExecutionBaselineStore(fixture.service.store.root, read_only=True)
    return fixture, plan, binding, readonly


def test_actual_chain_selector_and_context_consumers_read_every_byte_decode_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, plan, binding, readonly = _bound(tmp_path)
    reads: Counter[str] = Counter()
    decodes: Counter[str] = Counter()
    original_read = KnowledgeRecordStore._read_payload
    original_decode = KnowledgeRecordStore._decode_payload

    def read(self: KnowledgeRecordStore, name: str) -> bytes | None:
        reads[name.split("-")[0]] += 1
        return original_read(self, name)

    def decode[T: DomainModel](payload: bytes, model: type[T]) -> T:
        decodes[model.__name__] += 1
        return original_decode(payload, model)

    monkeypatch.setattr(KnowledgeRecordStore, "_read_payload", read)
    monkeypatch.setattr(KnowledgeRecordStore, "_decode_payload", staticmethod(decode))
    with recovery_record_read_scope() as cache:
        history = readonly.bindings_for_task(fixture.collector.facts.task.id)
        selected = StoredCoderExecutionInputResolver(readonly).current(
            fixture.collector.facts.task, implementation=None, progress=None
        )
        StoredCoderExecutionInputResolver(readonly).require_current(
            binding, fixture.collector.facts.task
        )
        assert history == (binding,) and selected.baseline == binding
        assert readonly.required_context(binding)
        assert readonly.plan(plan.plan_sha256) == plan
        assert decodes["ExecutionBaselinePlan"] == 1
        assert decodes["BaselineOperationStart"] == 1
        assert decodes["BaselineOperatorAuthorization"] >= 3, (
            "authority is read/decoded again per consumer"
        )
        assert sum(reads.values()) >= 12, "full originals are reopened even with cached decode"
        assert cache.retained_entries == 2
    assert current_recovery_record_reads() is None
    with recovery_record_read_scope():
        assert readonly.plan(plan.plan_sha256) == plan
    assert decodes["ExecutionBaselinePlan"] == 2, "next public operation is a fresh scope"


def test_same_length_mtime_tamper_authority_absence_and_writer_are_never_cached(
    tmp_path: Path,
) -> None:
    fixture, plan, binding, readonly = _bound(tmp_path)
    path = readonly.root / readonly.records._name("baseline-plans", plan.plan_sha256)
    original = path.read_bytes()
    before = path.stat()
    with recovery_record_read_scope():
        assert readonly.plan(plan.plan_sha256) == plan
        new = original.replace(b"VALUE = 2", b"VALUE = 9")
        assert new != original and len(new) == len(original)
        path.write_bytes(new)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with pytest.raises((ValueError, KnowledgeError)):
            readonly.plan(plan.plan_sha256)
        path.write_bytes(original)
        readonly.plan(plan.plan_sha256)
        authority = readonly.root / readonly.records._name("baseline-authorities", plan.plan_sha256)
        authority.unlink()
        with pytest.raises((ValueError, KnowledgeError)):
            readonly.bindings_for_task(binding.task_id)
    with recovery_record_read_scope() as cache:
        fixture.service.store.plan(plan.plan_sha256)
        assert cache.retained_entries == 0, "writer ports cannot use immutable reading reuse"


def test_nested_copy_isolation_bounded_aggregate_and_pre_model_clear(tmp_path: Path) -> None:
    _, plan, _, readonly = _bound(tmp_path)
    with recovery_record_read_scope() as cache:
        first = readonly.plan(plan.plan_sha256)
        first.facts.task.metadata["caller_poison"] = "bad"
        assert "caller_poison" not in readonly.plan(plan.plan_sha256).facts.task.metadata
        with recovery_record_read_scope() as nested:
            assert nested is cache
            readonly.start(plan.plan_sha256)
        assert cache.retained_entries == 2
        assert cache.retained_bytes <= 32 * 1024 * 1024
        finish_recovery_record_reads()
        assert cache.retained_entries == cache.retained_bytes == 0
        assert current_recovery_record_reads() is None
        # A later short gate can own a new cache; old owner remains empty.
        with recovery_record_read_scope() as next_gate:
            assert next_gate is not cache
            readonly.plan(plan.plan_sha256)
            assert next_gate.retained_entries == 1
    assert current_recovery_record_reads() is None


def test_zero_capacity_keeps_complete_results_and_every_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, plan, binding, readonly = _bound(tmp_path)
    with recovery_record_read_scope() as cache:
        monkeypatch.setattr(cache, "maximum_bytes", 0)
        assert readonly.bindings_for_task(binding.task_id) == (binding,)
        assert readonly.plan(plan.plan_sha256) == plan
        assert cache.retained_entries == 0 and cache.retained_bytes == 0


def test_fixed_raw_integrity_contract_rejects_corrupt_envelope_key_or_authority(
    tmp_path: Path,
) -> None:
    _, plan, _, readonly = _bound(tmp_path)
    path = readonly.root / readonly.records._name("baseline-plans", plan.plan_sha256)
    payload = path.read_bytes()
    corrupt_payload = payload.replace(b'"sha256":"', b'"sha256":"f', 1)
    assert corrupt_payload != payload
    with recovery_record_read_scope() as cache:
        with pytest.raises((KnowledgeError, ValueError)):
            decode_verified_record(
                path=path,
                kind="baseline-plan",
                model=ExecutionBaselinePlan,
                record_key=plan.plan_sha256,
                payload=corrupt_payload,
            )
        assert cache.retained_entries == 0, "registration must validate complete raw envelope"
        path.write_bytes(corrupt_payload)
        with pytest.raises(KnowledgeError):
            readonly.plan(plan.plan_sha256)
        assert cache.retained_entries == 0
        path.write_bytes(payload)
        assert readonly.plan(plan.plan_sha256) == plan
        with pytest.raises(ValueError):
            decode_verified_record(
                path=path,
                kind="baseline-plan",
                model=ExecutionBaselinePlan,
                record_key="f" * 64,
                payload=payload,
            )
        with pytest.raises(ValueError):
            decode_verified_record(
                path=path,
                kind="baseline-plan",
                model=BaselineOperatorAuthorization,
                record_key=plan.plan_sha256,
                payload=payload,
            )
        assert cache.retained_entries == 1


def test_context_complete_identity_decode_and_non_utf8_tamper_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path)
    root = tmp_path / "contexts"
    FileContextStore(root).put(bundle)
    readonly = FileContextStore(root, read_only=True)
    path = root / f"{bundle.context_id}.json"
    original = path.read_bytes()
    before = path.stat()
    identities = 0
    validate = context_store._validate_context_identity

    def counted(value: ContextBundle, error: type[ContextStoreError]) -> None:
        nonlocal identities
        identities += 1
        validate(value, error)

    monkeypatch.setattr(context_store, "_validate_context_identity", counted)
    with recovery_record_read_scope() as cache:
        assert readonly.get(bundle.context_id) == bundle
        assert readonly.get(bundle.context_id) == bundle
        assert identities == 1 and cache.retained_entries == 1
        saved = weakref.ref(next(iter(cache._records.values())).value)
        changed = original.replace(
            bundle.source_revision.encode(), b"x" * len(bundle.source_revision)
        )
        assert len(changed) == len(original) and changed != original
        path.write_bytes(changed)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with pytest.raises(ContextCorruption):
            readonly.get(bundle.context_id)
        assert cache.retained_entries == 0 and saved() is None
        for encoding in ("utf-16", "utf-32"):
            path.write_bytes(original.decode("utf-8").encode(encoding))
            with pytest.raises(ContextCorruption):
                readonly.get(bundle.context_id)
        path.write_bytes(original)
        assert readonly.get(bundle.context_id) == bundle
        alternate = tmp_path / "manifest.json"
        alternate.write_bytes(original)
        path.unlink()
        path.symlink_to(alternate)
        with pytest.raises(ContextCorruption):
            readonly.get(bundle.context_id)
        path.unlink()
    assert cache.retained_entries == cache.retained_bytes == 0
    path.write_bytes(original.decode("utf-8").encode("utf-16"))
    with pytest.raises(ContextCorruption):
        readonly.get(bundle.context_id)
    with pytest.raises(ContextCorruption):
        FileContextStore(root).get(bundle.context_id)


def test_large_valid_context_preserves_store_contract_and_overflow_full_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path)
    content = "retained context " + "x" * 8_000_001
    first = bundle.sections[0].model_copy(
        update={"content": content, "sha256": hashlib.sha256(content.encode()).hexdigest()}
    )
    large = bundle.model_copy(update={"sections": (first, *bundle.sections[1:])})
    large = large.model_copy(update={"context_id": "ctx_" + context_store._manifest_digest(large)})
    root = tmp_path / "large-contexts"
    FileContextStore(root).put(large)
    readonly = FileContextStore(root, read_only=True)
    with recovery_record_read_scope() as cache:
        monkeypatch.setattr(cache, "maximum_bytes", 1)
        first_read = readonly.get(large.context_id)
        second_read = readonly.get(large.context_id)
        assert first_read == second_read == large
        assert first_read.sections[0].content.endswith("x" * 64)
        assert cache.retained_entries == cache.retained_bytes == 0


def test_aggregate_limit_thread_inheritance_and_scope_failure_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path)
    readers = []
    for index in range(4):
        root = tmp_path / f"contexts-{index}"
        FileContextStore(root).put(bundle)
        readers.append(FileContextStore(root, read_only=True))
    with recovery_record_read_scope() as cache:
        assert cache.maximum_entries == 512 and cache.maximum_bytes == 32 * 1024 * 1024
        monkeypatch.setattr(cache, "maximum_entries", 2)
        for reader in readers:
            assert reader.get(bundle.context_id) == bundle
        assert cache.retained_entries == 2, "all roots share one entry limit"
        first_bytes = cache.retained_bytes
        inherited = copy_context()

        def other_thread() -> None:
            assert current_recovery_record_reads() is None
            with recovery_record_read_scope() as separate:
                assert separate is not cache
                readers[2].get(bundle.context_id)
                assert separate.retained_entries == 1
            assert separate.retained_entries == 0

        with ThreadPoolExecutor(max_workers=1) as threads:
            threads.submit(inherited.run, other_thread).result()
        assert cache.retained_entries == 2 and cache.retained_bytes == first_bytes
    with recovery_record_read_scope() as aggregate:
        readers[0].get(bundle.context_id)
        one_record = aggregate.retained_bytes
        monkeypatch.setattr(aggregate, "maximum_bytes", one_record)
        readers[1].get(bundle.context_id)
        assert aggregate.retained_entries == 1 and aggregate.retained_bytes == one_record
    saved = None
    with pytest.raises(RuntimeError), recovery_record_read_scope() as failed:
        readers[0].get(bundle.context_id)
        saved = weakref.ref(next(iter(failed._records.values())).value)
        raise RuntimeError("admission failure")
    assert saved is not None and saved() is None
    assert failed.retained_entries == failed.retained_bytes == 0
    assert current_recovery_record_reads() is None


def test_public_approval_real_builder_fresh_fences_and_clear_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline_fixture, baseline_plan, binding, readonly = _bound(tmp_path / "baseline")
    (tmp_path / "recovery-task").mkdir()
    fixture = policy_fixture(tmp_path / "recovery-task")
    plan = authorized_plan(fixture)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        team_id=fixture.target.team_id,
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    entry = NativeRecoveryEntry(config, {}, cast(ProductionProjectDeliveryBackend, Mock()))
    facts = NativeRecoveryFacts(
        fixture.original,
        fixture.target,
        cast(RepositoryProfile, object()),
        cast(ProjectSpecBaseline, object()),
    )
    observations = 0
    drift = False
    owned_scopes = []

    def inspect(_: RecoveryPlan) -> NativeRecoveryFacts:
        nonlocal observations
        observations += 1
        assert readonly.bindings_for_task(binding.task_id) == (binding,)
        StoredCoderExecutionInputResolver(readonly).require_current(
            binding, baseline_fixture.collector.facts.task
        )
        assert readonly.required_context(binding)
        scope = current_recovery_record_reads()
        assert scope is not None
        if scope not in owned_scopes:
            owned_scopes.append(scope)
        if drift:
            return NativeRecoveryFacts(
                facts.original, facts.target, cast(RepositoryProfile, object()), facts.baseline
            )
        return facts

    monkeypatch.setattr(entry._facts, "_inspect", inspect)
    store = FileRecoveryStore.initialize(tmp_path / "recovery", scope=plan.source.scope)
    store.put_plan(plan)
    service = RecoveryAuthorizationService(
        store,
        facts=entry._facts,
        captures=Captures(),
        human=ExplicitRecoveryHuman(plan.plan_sha256),
    )
    builder = AuthorizedRecoveryTaskBuilder(service, entry._facts)
    sealing = RecoveryTaskSealingService(store, builder)
    path = tmp_path / "recovery" / f"plan-{plan.plan_sha256}.json"
    monkeypatch.setattr(entry, "open_plan", lambda _: (store, plan))
    monkeypatch.setattr(entry, "_services", lambda *args: (service, builder, sealing))
    decodes: Counter[str] = Counter()
    original_decode = KnowledgeRecordStore._decode_payload

    def decode[T: DomainModel](payload: bytes, model: type[T]) -> T:
        decodes[model.__name__] += 1
        return original_decode(payload, model)

    monkeypatch.setattr(KnowledgeRecordStore, "_decode_payload", staticmethod(decode))
    original_task = fixture.original.task.model_dump_json()
    entry.approve(path, confirmed_plan=plan.plan_sha256, reference="exact approval")
    assert observations == 18, "all authorization and Task-builder before/after facts remain"
    assert decodes["ExecutionBaselinePlan"] == decodes["BaselineOperationStart"] == 1
    assert decodes["BaselineOperatorAuthorization"] >= 18
    assert fixture.original.task.model_dump_json() == original_task
    receipt = store.get_authorization(plan.plan_sha256)
    sealed = store.get_task_record(plan.plan_sha256)
    assert sealed.task.id == plan.new_task_id and sealed.task.status.value == "NEW"
    assert all(scope.closed and scope.retained_entries == 0 for scope in owned_scopes)

    controller = object.__new__(DeliveryResumeController)
    controller._config, controller._environment, controller._recovery = config, {}, entry
    monkeypatch.setattr(entry, "latest_delivery", lambda _: (store, plan, path))
    monkeypatch.setattr(entry, "pending_knowledge_wait", lambda _: None)
    monkeypatch.setattr(resume_module, "read_recovery_task", lambda *args: None)
    reached_model = []

    def execute(_: Path) -> NativeRecoveryExecution:
        assert current_recovery_record_reads() is None
        assert all(scope.closed and scope.retained_entries == 0 for scope in owned_scopes)
        reached_model.append(True)
        return cast(NativeRecoveryExecution, object())

    monkeypatch.setattr(entry, "resume_execution", execute)
    expected = DeliveryResumeResult.model_construct()
    monkeypatch.setattr(controller, "_finish_coder_recovery", lambda _: expected)
    checkpoint = ProjectDeliveryCheckpoint.model_construct()
    command = ResumeProjectDelivery(
        delivery_id=plan.source.scope.delivery_id,
        approved_plan_sha256=plan.plan_sha256,
        approval_reference="exact approval",
    )
    assert controller._continue_coder_recovery(checkpoint, command) is expected
    assert reached_model == [True]
    assert decodes["ExecutionBaselinePlan"] == decodes["BaselineOperationStart"] == 2
    assert store.get_authorization(plan.plan_sha256) == receipt
    assert store.get_task_record(plan.plan_sha256) == sealed
    assert current_recovery_record_reads() is None
    drift = True
    with recovery_record_read_scope():
        assert readonly.plan(baseline_plan.plan_sha256) == baseline_plan
        with pytest.raises(RecoveryRejected):
            sealing.require_current(plan.plan_sha256)
    assert store.get_authorization(plan.plan_sha256) == receipt
    assert store.get_task_record(plan.plan_sha256) == sealed


def test_same_thread_async_child_cannot_inherit_or_close_parent_cache(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    root = tmp_path / "contexts"
    FileContextStore(root).put(bundle)
    readonly = FileContextStore(root, read_only=True)

    async def parent() -> None:
        with recovery_record_read_scope() as owned:
            readonly.get(bundle.context_id)

            async def child() -> None:
                assert current_recovery_record_reads() is None
                finish_recovery_record_reads()
                with recovery_record_read_scope() as separate:
                    assert separate is not owned
                    readonly.get(bundle.context_id)
                    assert separate.retained_entries == 1
                assert separate.closed and separate.retained_entries == 0
                assert current_recovery_record_reads() is None

            await asyncio.create_task(child())
            assert current_recovery_record_reads() is owned
            assert not owned.closed and owned.retained_entries == 1
        assert owned.retained_entries == 0
        assert current_recovery_record_reads() is None

    asyncio.run(parent())
    assert current_recovery_record_reads() is None
