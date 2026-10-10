"""Synchronous recovery preparation shares scans, never fresh facts or authority."""

import hashlib
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer import redaction
from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import FileContextBuilder, FileContextStore
from ai_software_engineer.domain import AgentPermissions, AgentRole, TaskStatus
from ai_software_engineer.domain.project_delivery import derive_delivery_task
from ai_software_engineer.git import GitWorktreeManager, WorktreeChangeCapture, WorktreeRef
from ai_software_engineer.manager.baseline import ProjectSpecBaseline
from ai_software_engineer.manager.dispatch import DispatchWorkforceSnapshot, RecoveryDispatchRecord
from ai_software_engineer.manager.mysql_dispatch_authority import MySqlDispatchAuthority
from ai_software_engineer.recovery.allocation import RecoveryAllocator
from ai_software_engineer.recovery.current import NativeRecoveryFacts, NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.models import (
    CapturedChanges,
    RecoveryAuthorization,
    RecoveryPlan,
    RecoveryRejected,
)
from ai_software_engineer.recovery.native import NativeRecoverySource
from ai_software_engineer.recovery.records import RecoveryInvocationRecord, RecoverySeedRecord
from ai_software_engineer.recovery.sealing import RecoveryTaskSealingService
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.recovery.service import RecoveryAuthorizationService
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.task import AuthorizedRecoveryTaskBuilder
from ai_software_engineer.repository_profile import RepositoryProfile
from tests.manager.test_contracts import stage_chain
from tests.manager.test_dispatch import _agents, _policy
from tests.recovery.test_authorization import Human, approval, make_plan

SOURCE = "VALUE = 2\n" + "".join(
    f"def value_{index}():\n    token=settings.token\n    return token\n\n" for index in range(120)
)
CLEAN_BODY = "x" * 179_583
PATCH = (
    "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
    f"@@ -0,0 +1,{len(SOURCE.splitlines())} @@\n"
    + "".join("+" + line + "\n" for line in SOURCE.splitlines())
)


@dataclass
class Scans:
    source: int = 0
    generic: int = 0
    patch: int = 0


class CountedPattern:
    def __init__(self, pattern: re.Pattern[str], scans: Scans) -> None:
        self.pattern, self.scans = pattern, scans

    def subn(self, replacement: str, content: str) -> tuple[str, int]:
        if content == CLEAN_BODY:
            self.scans.generic += 1
        return self.pattern.subn(replacement, content)

    def search(self, content: str) -> re.Match[str] | None:
        return self.pattern.search(content)

    def findall(self, content: str) -> list[str]:
        return self.pattern.findall(content)


def count_scans(monkeypatch: pytest.MonkeyPatch) -> Scans:
    scans = Scans()
    original = redaction._inspect_source
    original_patch = redaction._inspect_patch

    def source(
        content: str, *, source_path: str | None
    ) -> tuple[redaction.RedactionOccurrence, ...]:
        if content == SOURCE and source_path == "src/app.py":
            scans.source += 1
        return original(content, source_path=source_path)

    def patch(content: str) -> tuple[redaction.RedactionOccurrence, ...]:
        if content == PATCH:
            scans.patch += 1
        return original_patch(content)

    monkeypatch.setattr(redaction, "_inspect_source", source)
    monkeypatch.setattr(redaction, "_inspect_patch", patch)
    monkeypatch.setattr(
        redaction,
        "_SECRET_PATTERNS",
        tuple(
            (kind, cast(re.Pattern[str], CountedPattern(pattern, scans)))
            for kind, pattern in redaction._SECRET_PATTERNS
        ),
    )
    return scans


@dataclass
class PreparationFixture:
    plan: RecoveryPlan
    store: FileRecoveryStore
    builder: AuthorizedRecoveryTaskBuilder
    sealing: RecoveryTaskSealingService
    body: Path
    reads: Counter[str]
    getters: Counter[str]
    observe: Callable[[str], None]


def preparation_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PreparationFixture:
    prepared, request, product, approved, design, execution = stage_chain(tmp_path)
    prototype = make_plan(Path(prepared.repository_root), repository_id=prepared.repository_id)
    task = derive_delivery_task(
        prepared,
        request,
        product,
        approved,
        design,
        execution,
        task_id=prototype.source.task_id,
        repository=prepared.repository_root,
        base_ref=prototype.source.base_revision,
        max_attempts=3,
        created_at=request.created_at,
    ).model_copy(update={"status": TaskStatus.BLOCKED, "attempts": 1})
    source = prototype.source.model_copy(
        update={
            "scope": prototype.source.scope.model_copy(update={"team_id": prepared.team_id}),
            "preparation_sha256": prepared.preparation_sha256,
            "product_spec_sha256": product.product_spec_sha256,
            "approval_sha256": approved.approval_sha256,
            "technical_design_sha256": design.technical_design_sha256,
            "execution_plan_sha256": execution.execution_plan_sha256,
        }
    )
    plan = RecoveryPlan.create(
        **{
            **prototype.to_wire(),
            "source": source,
            "capture": CapturedChanges.from_capture(
                replace(
                    prototype.capture.to_capture(),
                    patch=PATCH.encode(),
                    file_sha256s=(("src/app.py", hashlib.sha256(SOURCE.encode()).hexdigest()),),
                )
            ),
            "target_preparation_sha256": prepared.preparation_sha256,
        }
    )
    original = NativeRecoverySource(
        source,
        plan.permissions,
        plan.denied_paths,
        prepared,
        product,
        approved,
        design,
        execution,
        request,
        task,
        source.base_revision,
    )
    facts = NativeRecoveryFacts(
        original,
        prepared,
        cast(RepositoryProfile, object()),
        cast(ProjectSpecBaseline, object()),
    )
    body = tmp_path / "full-source.py"
    body.write_text(SOURCE)
    reads: Counter[str] = Counter()

    def observe(label: str) -> None:
        reads[label] += 1
        text = body.read_text()
        if redaction.source_secret_occurrences(text, source_path="src/app.py"):
            raise RecoveryRejected("changed source contains sensitive input")
        if text != SOURCE:
            raise RecoveryRejected("source body changed")
        assert not redaction.redact_text(CLEAN_BODY).occurrences

    verifier = NativeRecoveryFactsVerifier(
        ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            team_id=prepared.team_id,
            model_routes=(
                ProviderRouteConfig(
                    provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        ),
        {},
    )

    def inspect(_: RecoveryPlan) -> NativeRecoveryFacts:
        observe("facts")
        return facts

    monkeypatch.setattr(verifier, "_inspect", inspect)

    class CaptureVerifier:
        def verify_capture(
            self,
            capture: WorktreeChangeCapture,
            permissions: AgentPermissions,
            *,
            denied_paths: tuple[str, ...] = (),
        ) -> None:
            assert capture == plan.capture.to_capture() and permissions == plan.permissions
            assert denied_paths == plan.denied_paths
            observe("capture")

    store = FileRecoveryStore.initialize(tmp_path / "recovery", scope=plan.source.scope)
    service = RecoveryAuthorizationService(
        store, facts=verifier, captures=CaptureVerifier(), human=Human()
    )
    service.propose(plan)
    service.authorize(approval(plan))
    builder = AuthorizedRecoveryTaskBuilder(service, verifier)
    reads.clear()
    getters: Counter[str] = Counter()
    original_plan, original_authorization = store.get_plan, store.get_authorization

    def get_plan(sha256: str) -> RecoveryPlan:
        getters["plan"] += 1
        return original_plan(sha256)

    def get_authorization(sha256: str) -> RecoveryAuthorization:
        getters["authorization"] += 1
        return original_authorization(sha256)

    monkeypatch.setattr(store, "get_plan", get_plan)
    monkeypatch.setattr(store, "get_authorization", get_authorization)
    return PreparationFixture(
        plan,
        store,
        builder,
        RecoveryTaskSealingService(store, builder),
        body,
        reads,
        getters,
        observe,
    )


def test_builder_reuses_complete_source_and_generic_but_repeats_all_fresh_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    scans = count_scans(monkeypatch)
    first = f.builder.build(f.plan.plan_sha256)
    assert f.reads == {"facts": 10, "capture": 2}
    assert f.getters == {"plan": 6, "authorization": 2}
    assert scans == Scans(source=1, generic=6, patch=1)
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    assert f.builder.build(f.plan.plan_sha256) == first
    assert f.reads == {"facts": 20, "capture": 4}
    assert f.getters == {"plan": 12, "authorization": 4}
    assert scans == Scans(source=2, generic=12, patch=2)
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None


@pytest.mark.parametrize("method", ["seal", "require_current"])
def test_sealing_encloses_store_and_builder_without_caching_getters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    f.sealing.seal(f.plan.plan_sha256)
    reads = f.reads
    reads.clear()
    f.getters.clear()
    original = f.store.get_authorization

    def authorization(sha256: str) -> RecoveryAuthorization:
        f.observe("authorization")
        return original(sha256)

    monkeypatch.setattr(f.store, "get_authorization", authorization)
    scans = count_scans(monkeypatch)
    call = getattr(f.sealing, method)
    first = call(f.plan.plan_sha256)
    fresh = reads.copy()
    fresh_getters = f.getters.copy()
    assert fresh["facts"] == 10 and fresh["capture"] == 2
    assert fresh["authorization"] > 2
    assert scans == Scans(source=1, generic=6, patch=1)
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    assert call(f.plan.plan_sha256) == first
    assert reads == Counter({key: count * 2 for key, count in fresh.items()})
    assert f.getters == Counter({key: count * 2 for key, count in fresh_getters.items()})
    assert scans == Scans(source=2, generic=12, patch=2)


class OfflineAuthority:
    def __init__(self, f: PreparationFixture) -> None:
        self.fixture = f
        self.snapshot: DispatchWorkforceSnapshot | None = None
        self.record: RecoveryDispatchRecord | None = None
        self.drift = False

    def seed_snapshot(self, snapshot: DispatchWorkforceSnapshot) -> None:
        self.fixture.observe("snapshot")
        self.snapshot = snapshot

    def commit_recovery(
        self,
        *,
        repository_id: str,
        task_id: str,
        plan_sha256: str,
        validate_current: Callable[[RecoveryDispatchRecord | None], None],
        build: Callable[[DispatchWorkforceSnapshot], RecoveryDispatchRecord],
    ) -> RecoveryDispatchRecord:
        assert self.snapshot is not None
        assert (repository_id, task_id) == (self.snapshot.repository_id, self.snapshot.task_id)
        assert plan_sha256 == self.fixture.plan.plan_sha256
        self.fixture.observe("fence_before")
        validate_current(self.record)
        if self.record is not None:
            return self.record
        record = build(self.snapshot)
        record.validate_integrity()
        if self.drift:
            self.fixture.body.write_text(SOURCE + "CHANGED = 1\n")
        self.fixture.reads["fence_after"] += 1
        validate_current(record)
        self.record = record
        return record


def allocate(
    f: PreparationFixture, authority: OfflineAuthority | None = None
) -> tuple[RecoveryDispatchRecord, OfflineAuthority]:
    f.sealing.seal(f.plan.plan_sha256)
    f.reads.clear()
    f.getters.clear()
    authority = authority or OfflineAuthority(f)
    record = RecoveryAllocator(
        sealing=f.sealing,
        builder=f.builder,
        authority=cast(MySqlDispatchAuthority, authority),
        agents=_agents(),
        policies=(_policy(),),
    ).allocate(f.plan.plan_sha256)
    return record, authority


def test_allocator_shares_scans_across_both_fenced_fresh_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    f.sealing.seal(f.plan.plan_sha256)
    f.reads.clear()
    f.getters.clear()
    scans = count_scans(monkeypatch)
    authority = OfflineAuthority(f)
    allocator = RecoveryAllocator(
        sealing=f.sealing,
        builder=f.builder,
        authority=cast(MySqlDispatchAuthority, authority),
        agents=_agents(),
        policies=(_policy(),),
    )
    record = allocator.allocate(f.plan.plan_sha256)
    assert f.reads == {
        "facts": 40,
        "capture": 8,
        "snapshot": 1,
        "fence_before": 1,
        "fence_after": 1,
    }
    assert f.getters == {"plan": 33, "authorization": 14}
    assert scans == Scans(source=1, generic=6, patch=1)
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    f.reads.clear()
    f.getters.clear()
    assert allocator.allocate(f.plan.plan_sha256) == record
    assert f.reads == {"facts": 30, "capture": 6, "snapshot": 1, "fence_before": 1}
    assert f.getters == {"plan": 24, "authorization": 10}
    assert scans == Scans(source=2, generic=12, patch=2)


def test_allocator_second_fence_rejects_changed_complete_body_and_releases_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    authority = OfflineAuthority(f)
    authority.drift = True
    with pytest.raises(RecoveryRejected):
        allocate(f, authority)
    assert authority.record is None and f.reads["fence_after"] == 1
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    with pytest.raises(RecoveryRejected):
        f.builder.build(f.plan.plan_sha256)
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None


@pytest.mark.parametrize("change", ["safe", "secret"])
def test_next_call_rereads_changed_body_and_rejects_after_success_or_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    f.builder.build(f.plan.plan_sha256)
    suffix = "OTHER = 1\n" if change == "safe" else 'password="private-real-value"\n'
    f.body.write_text(SOURCE + suffix)
    for _ in range(2):
        with pytest.raises(RecoveryRejected):
            f.builder.build(f.plan.plan_sha256)
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    f.body.write_text(SOURCE)
    scans = count_scans(monkeypatch)
    f.builder.build(f.plan.plan_sha256)
    assert scans == Scans(source=1, generic=6, patch=1)


def test_changed_stored_plan_is_rejected_even_after_its_patch_was_scanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    path = tmp_path / "recovery" / f"plan-{f.plan.plan_sha256}.json"
    original = f.store.get_authorization
    modified = False

    def authorization(sha256: str) -> RecoveryAuthorization:
        nonlocal modified
        receipt = original(sha256)
        if not modified:
            body = path.read_text()
            changed = body.replace(f.plan.target_base_revision, "d" * 40)
            assert changed != body and len(changed) == len(body)
            path.write_text(changed)
            modified = True
        return receipt

    monkeypatch.setattr(f.store, "get_authorization", authorization)
    with pytest.raises(RecoveryRejected):
        f.builder.build(f.plan.plan_sha256)
    assert modified and f.getters["plan"] > 3
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    with pytest.raises(RecoveryRejected):
        f.builder.build(f.plan.plan_sha256)
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None


def test_zero_cache_budget_does_not_skip_scans_or_fresh_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_ENTRIES", 0)
    scans = count_scans(monkeypatch)
    f.builder.build(f.plan.plan_sha256)
    assert f.reads == {"facts": 10, "capture": 2}
    assert f.getters == {"plan": 6, "authorization": 2}
    assert scans.source > 1 and scans.patch > 1 and scans.generic > 6
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None


class SeedManager:
    def __init__(self, f: PreparationFixture) -> None:
        self.fixture = f

    def seed_changes(
        self,
        capture: WorktreeChangeCapture,
        target: WorktreeRef,
        source_permissions: AgentPermissions,
        target_permissions: AgentPermissions,
        *,
        source_denied_paths: tuple[str, ...] = (),
        target_denied_paths: tuple[str, ...] = (),
    ) -> WorktreeChangeCapture:
        assert capture == self.fixture.plan.capture.to_capture()
        assert source_permissions == target_permissions == self.fixture.plan.permissions
        assert source_denied_paths == target_denied_paths == self.fixture.plan.denied_paths
        self.fixture.observe("seed_application")
        return WorktreeChangeCapture(target, b"", "0" * 64, ())

    def verify_capture(
        self,
        capture: WorktreeChangeCapture,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> None:
        assert permissions == self.fixture.plan.permissions
        assert denied_paths == self.fixture.plan.denied_paths
        assert capture.worktree.task_id == self.fixture.plan.new_task_id
        self.fixture.observe("seed_verify")


def seed_fixture(
    f: PreparationFixture,
) -> tuple[RecoverySeedService, WorktreeRef, AgentRequest]:
    dispatch, _ = allocate(f)
    target = WorktreeRef(
        dispatch.task_id,
        AgentRole.CODER,
        1,
        f.body.parent / "target",
        dispatch.task.base_ref,
        f.plan.target_branch_name or f"ai/{dispatch.task_id}/attempt-1",
        False,
    )
    target.path.mkdir()
    contexts = FileContextStore(f.body.parent / "contexts")
    context = contexts.put(
        FileContextBuilder(target.path, f.plan.permissions).build(
            dispatch.task, AgentRole.CODER, attempt=1
        )
    )
    request = AgentRequest(
        run_id="run_scope_provider",
        task_id=dispatch.task_id,
        role=AgentRole.CODER,
        attempt=1,
        source_revision=dispatch.task.base_ref,
        context_manifest_id=context.context_id,
        input_artifact_ids=(),
        permissions=f.plan.permissions,
        output_schema="schemas/coder-output.schema.json",
        timeout_seconds=60,
    )
    service = RecoverySeedService(
        store=f.store,
        sealing=f.sealing,
        manager=cast(GitWorktreeManager, SeedManager(f)),
        dispatch=dispatch,
        permissions=f.plan.permissions,
        contexts=contexts,
    )
    f.reads.clear()
    return service, target, request


def test_seed_reuses_scans_and_replay_keeps_fresh_sealing_and_capture_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    seed, target, _ = seed_fixture(f)
    scans = count_scans(monkeypatch)
    receipt = seed.seed(target)
    assert isinstance(receipt, RecoverySeedRecord)
    assert f.reads == {"facts": 10, "capture": 2, "seed_application": 1, "seed_verify": 1}
    assert scans == Scans(source=1, generic=6, patch=1)
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    assert seed.seed(target) == receipt
    assert f.reads == {"facts": 20, "capture": 4, "seed_application": 1, "seed_verify": 2}
    assert scans == Scans(source=2, generic=12, patch=2)


def test_authorize_releases_scope_before_provider_and_replay_is_still_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    seed, target, request = seed_fixture(f)
    seed.seed(target)
    f.reads.clear()
    scans = count_scans(monkeypatch)
    seed.authorize(request, target.path)
    assert f.reads == {"facts": 10, "capture": 2, "seed_verify": 1}
    assert scans == Scans(source=1, generic=6, patch=1)
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None

    def provider() -> None:
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
        redaction.redact_text(CLEAN_BODY)
        redaction.redact_text(CLEAN_BODY)

    provider()
    assert scans.generic == 18, "the provider cannot inherit admission's scan facts"
    assert isinstance(f.store.get_invocation(f.plan.plan_sha256), RecoveryInvocationRecord)
    with pytest.raises(RecoveryRejected, match="already admitted"):
        seed.authorize(request, target.path)
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None


def test_failed_provider_admission_does_not_publish_invocation_or_retain_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    seed, target, request = seed_fixture(f)
    seed.seed(target)
    f.body.write_text(SOURCE + 'password="private-real-value"\n')
    with pytest.raises(RecoveryRejected):
        seed.authorize(request, target.path)
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    with pytest.raises(RecoveryRecordMissing):
        f.store.get_invocation(f.plan.plan_sha256)
