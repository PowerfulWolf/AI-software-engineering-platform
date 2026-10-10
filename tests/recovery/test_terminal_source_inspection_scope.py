"""Recovery reads reuse pure scans while every fresh observation still executes."""

import ast
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer import redaction
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole, ProjectPreparation, TaskStatus
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.manager.delivery_checkpoint import ProjectDeliveryCheckpoint
from ai_software_engineer.manager.production_backend import (
    ProductionProjectDeliveryBackend,
    _delivery_role_permissions,
)
from ai_software_engineer.recovery import entry, workspace_snapshot
from ai_software_engineer.recovery.current import NativeRecoveryFacts, NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryPlan, RecoveryRejected
from ai_software_engineer.recovery.native import NativeRecoverySource, NativeRecoverySourceReader
from ai_software_engineer.recovery.sealing import RecoveryTaskSealingService
from ai_software_engineer.recovery.store import FileRecoveryStore
from tests.domain.factories import make_task
from tests.git.test_capture import git
from tests.orchestration.test_native_continuation import Fixture
from tests.recovery.test_authorization import make_plan
from tests.recovery.test_scope import _retained_worktree
from tests.recovery.test_workspace_snapshot import _audit, _composition
from tests.recovery.test_workspace_snapshot import native as native

LARGE_SOURCE = "VALUE = 2\n" + "".join(
    f"def value_{index}():\n    token=settings.token\n    return token\n\n" for index in range(120)
)


@contextmanager
def parsed_sources(monkeypatch: pytest.MonkeyPatch) -> Iterator[Counter[str]]:
    original = ast.parse
    calls: Counter[str] = Counter()

    def counted(source: str, filename: str = "<unknown>", mode: str = "exec") -> ast.AST:
        calls[source] += 1
        return cast(ast.AST, original(source, filename, mode))

    monkeypatch.setattr(ast, "parse", counted)
    yield calls


@dataclass(frozen=True)
class ProposalFixture:
    recovery: entry.NativeRecoveryEntry
    original: NativeRecoverySource
    checkpoint: ProjectDeliveryCheckpoint
    body: Path
    reads: list[str]
    cache_sizes: list[int]

    def propose(self, *, discovery: bool) -> tuple[RecoveryPlan, Path]:
        if discovery:
            return self.recovery.propose_delivery(self.checkpoint)
        return self.recovery.propose(
            repository_root=self.original.source.scope.repository_root,
            delivery_id=self.original.source.scope.delivery_id,
            failed_run_id=self.original.source.failed_run_id,
            failed_context_id=self.original.source.failed_context_id,
        )


def proposal_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProposalFixture:
    manager, worktree, historical = _retained_worktree(tmp_path)
    branch = "ai/feature/source-recovery"
    git(worktree.path, "branch", "-m", branch)
    worktree = replace(worktree, branch=branch)
    manager = GitWorktreeManager(
        Path(historical.source.scope.repository_root),
        tmp_path / "roles",
        branch_names={historical.source.task_id: branch},
    )
    body = worktree.path / "src/app.py"
    body.write_text(LARGE_SOURCE)
    source = historical.source
    task = make_task().model_copy(
        update={
            "id": source.task_id,
            "repository": source.scope.repository_root,
            "base_ref": source.base_revision,
            "branch_name": worktree.branch,
            "status": TaskStatus.BLOCKED,
            "attempts": 1,
            "interruption_continuation_policy": None,
        }
    )
    assert task.constraints is not None
    permissions = _delivery_role_permissions(AgentRole.CODER, task.constraints.allowed_paths, ())
    original = cast(
        NativeRecoverySource,
        SimpleNamespace(
            **{**vars(historical), "permissions": permissions},
            task=task,
            product=SimpleNamespace(branch_name=branch),
            worktree_revision=worktree.head_revision,
        ),
    )
    sidecar = tmp_path / "sidecar"
    (sidecar / "state").mkdir(parents=True)
    prepared = cast(
        ProjectPreparation,
        SimpleNamespace(
            repository_id=source.scope.repository_id,
            repository_root=source.scope.repository_root,
            repository_workspace_root=str(sidecar),
            preparation_sha256="c" * 64,
        ),
    )
    backend = cast(
        ProductionProjectDeliveryBackend,
        SimpleNamespace(
            prepare=lambda _: SimpleNamespace(preparation=prepared),
            _facts=lambda _: SimpleNamespace(profile=None),
        ),
    )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        team_id=source.scope.team_id,
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    recovery = entry.NativeRecoveryEntry(config, {}, backend)
    monkeypatch.setattr(recovery, "_manager", lambda *args: manager)
    monkeypatch.setattr(entry, "_task_commands", lambda _: permissions.commands)
    reads: list[str] = []
    cache_sizes: list[int] = []

    def read(label: str) -> str:
        reads.append(label)
        text = body.read_text()
        if redaction.source_secret_occurrences(text, source_path="src/app.py"):
            raise ValueError("changed source is sensitive")
        cache = redaction._SOURCE_INSPECTION_CACHE.get()
        if cache is not None:
            cache_sizes.append(cache.bytes)
            assert len(cache.facts) <= redaction._MAX_INSPECTION_ENTRIES
        return text

    def inspect_source(*args: object) -> NativeRecoverySource:
        read("source")
        return original

    monkeypatch.setattr(NativeRecoverySourceReader, "_inspect", inspect_source)

    @redaction.source_inspection_scope()
    def discover(*args: object) -> NativeRecoverySource:
        read("discovery")
        return original

    monkeypatch.setattr(NativeRecoverySourceReader, "discover_failed_coder", discover)

    def inspect_facts(plan: RecoveryPlan) -> NativeRecoveryFacts:
        text = read("facts")
        manager.verify_capture(plan.capture.to_capture(), plan.permissions)
        return cast(NativeRecoveryFacts, SimpleNamespace(text=text))

    monkeypatch.setattr(recovery._facts, "_inspect", inspect_facts)
    checkpoint = ProjectDeliveryCheckpoint.model_construct(
        repository_id=source.scope.repository_id,
        repository_root=source.scope.repository_root,
        delivery_id=source.scope.delivery_id,
    )
    return ProposalFixture(recovery, original, checkpoint, body, reads, cache_sizes)


@pytest.mark.parametrize("discovery", [False, True])
def test_proposal_reuses_exact_full_text_but_repeats_fresh_capture_and_fact_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, discovery: bool
) -> None:
    f = proposal_fixture(tmp_path, monkeypatch)
    # Admit the full source+path and no larger patch key; overflow must still scan.
    limit = len(LARGE_SOURCE.encode()) + len("src/app.py")
    monkeypatch.setattr(redaction, "_MAX_INSPECTION_BYTES", limit)
    with parsed_sources(monkeypatch) as calls:
        plan, path = f.propose(discovery=discovery)
        assert path.is_file()
        assert plan.capture.files[0].path == "src/app.py"
        assert "def value_119()" in plan.capture.patch
        assert calls[LARGE_SOURCE] == 1
        assert f.reads.count("facts") == 4, "before/after admission each still double-read facts"
        assert f.reads.count("source") == 1
        assert f.cache_sizes and max(f.cache_sizes) <= limit
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
        f.propose(discovery=discovery)
        assert calls[LARGE_SOURCE] == 2, "the next public proposal must own a fresh scope"
        assert f.reads.count("facts") == 8
        assert not redaction.source_secret_occurrences(LARGE_SOURCE, source_path="src/app.py")
        assert calls[LARGE_SOURCE] == 3, "a caller after return cannot borrow proposal scans"
    assert f.body.read_text() == LARGE_SOURCE


def test_approval_reuses_pure_scans_across_authorization_and_offline_sealing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = proposal_fixture(tmp_path, monkeypatch)
    plan, path = f.propose(discovery=False)
    store = FileRecoveryStore(path.parent, scope=plan.source.scope)
    monkeypatch.setattr(f.recovery, "open_plan", lambda _: (store, plan))
    sealed: list[str] = []

    def seal(_: RecoveryTaskSealingService, plan_sha256: str) -> None:
        # Task derivation is outside this scanner contract; keep its fresh-facts
        # seam explicit while authorization and immutable receipt writes are real.
        sealed.append(plan_sha256)
        f.recovery._facts.validate(plan)

    monkeypatch.setattr(RecoveryTaskSealingService, "seal", seal)
    initial_reads = f.reads.count("facts")
    with parsed_sources(monkeypatch) as calls:
        f.recovery.approve(path, confirmed_plan=plan.plan_sha256, reference="exact plan")
        assert calls[LARGE_SOURCE] == 1
        assert f.reads.count("facts") - initial_reads == 10
        assert sealed == [plan.plan_sha256]
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
        receipt = store.get_authorization(plan.plan_sha256)
        before_replay = calls[LARGE_SOURCE]
        f.recovery.approve(path, confirmed_plan=plan.plan_sha256, reference="exact plan")
        assert calls[LARGE_SOURCE] == before_replay + 1, (
            "approval replay owns a fresh synchronous scope"
        )
        assert store.get_authorization(plan.plan_sha256) == receipt
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None


@pytest.mark.parametrize("change", [None, "safe_text", "fact"])
def test_current_inspection_scans_once_but_still_rejects_changed_second_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str | None
) -> None:
    plan = make_plan(tmp_path / "project")
    body = tmp_path / "body.py"
    body.write_text(LARGE_SOURCE)
    verifier = NativeRecoveryFactsVerifier(
        ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            model_routes=(
                ProviderRouteConfig(
                    provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        ),
        {},
    )
    observations = 0
    changed = LARGE_SOURCE + "EXTRA = 4\n"

    def inspect(_: RecoveryPlan) -> NativeRecoveryFacts:
        nonlocal observations
        observations += 1
        text = body.read_text()
        assert not redaction.source_secret_occurrences(text, source_path="src/app.py")
        if change == "safe_text" and observations == 1:
            body.write_text(changed)
        return cast(
            NativeRecoveryFacts,
            SimpleNamespace(text=text, fact=observations if change == "fact" else 0),
        )

    monkeypatch.setattr(verifier, "_inspect", inspect)
    with parsed_sources(monkeypatch) as calls:
        if change is None:
            verifier.inspect(plan)
        else:
            with pytest.raises(RecoveryRejected):
                verifier.inspect(plan)
        assert observations == 2
        assert calls[LARGE_SOURCE] == 1
        if change == "safe_text":
            assert calls[changed] == 1, "new bytes require their own complete inspection"
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None


def test_terminal_audit_reuses_parsing_without_caching_facts_capture_or_inventory(
    native: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = _audit(native)
    body = native.worktree.path / "src/app.py"
    body.write_text(LARGE_SOURCE)
    audit = replace(
        audit,
        capture=CapturedChanges.from_capture(
            native.git.capture_changes(native.worktree, native.request.permissions)
        ),
        observation=replace(
            audit.observation, inventory_after=capture_mutation_inventory(native.worktree.path)
        ),
    )
    expected = audit.validate()
    real_verify = GitWorktreeManager.verify_capture
    config, original, _lock = _composition(audit, monkeypatch)
    monkeypatch.setattr(
        workspace_snapshot, "GitWorktreeManager", lambda *args, **kwargs: native.git
    )
    real_facts = workspace_snapshot._read_facts
    real_observe = workspace_snapshot._observe
    checks: Counter[str] = Counter()

    def counted(label: str, operation: Callable[..., object]) -> Callable[..., object]:
        def execute(*args: object, **kwargs: object) -> object:
            checks[label] += 1
            assert not redaction.source_secret_occurrences(
                body.read_text(), source_path="src/app.py"
            )
            return operation(*args, **kwargs)

        return execute

    monkeypatch.setattr(
        NativeRecoverySourceReader,
        "inspect",
        counted("source", lambda *args, **kwargs: original),
    )
    monkeypatch.setattr(workspace_snapshot, "_read_facts", counted("facts", real_facts))
    monkeypatch.setattr(workspace_snapshot, "_observe", counted("inventory", real_observe))
    monkeypatch.setattr(GitWorktreeManager, "verify_capture", counted("capture", real_verify))
    with parsed_sources(monkeypatch) as calls:
        snapshot = workspace_snapshot.read_terminal_workspace_snapshot(
            config, {}, original, audit.capture
        )
        assert snapshot == expected
        assert checks == {"source": 2, "facts": 2, "inventory": 2, "capture": 2}
        assert calls[LARGE_SOURCE] == 1
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
