"""Audited cache relocation can finish after a fault without repeating the rename."""

import hashlib
import importlib.util
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.git.mutation import MutationFile, capture_mutation_inventory
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from tests.manager.test_delivery_wait import WaitQueue, seal_start
from tests.orchestration.test_native_continuation import NOW, Guard
from tests.orchestration.test_native_continuation_v2 import V2Fixture


@pytest.fixture
def maintenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    path = (
        Path(__file__).parents[2]
        / ".trellis/tasks/10-11-run7-cache-maintenance/cache_quarantine.py"
    )
    spec = importlib.util.spec_from_file_location("_ase_cache_maintenance_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    descriptor = os.open(tmp_path / "lock", os.O_CREAT | os.O_RDWR, 0o600)
    native = V2Fixture(tmp_path, Guard(descriptor))
    try:
        queue = WaitQueue(native)
        native.claim = queue.original
        seal_start(native, queue, tmp_path)
        service = native.service()
        assert service.started(native.request, native.worktree.path) is not None
        stop = native.stopped()
        service.record_native_stop(
            native.request,
            native.worktree.path,
            process_stop=NativeProcessStop.create(
                **stop.model_dump(exclude={"kind", "returncode", "stopped_at", "stop_sha256"}),
                kind="completed",
                returncode=0,
                stopped_at=NOW + timedelta(seconds=1),
            ),
            output_present=True,
            cause=None,
            original_error_code=None,
        )
        start = native.store.capture_start(native.request.run_id)
        capture_stop = native.store.capture_stop(native.request.run_id)
        invocation = KnowledgeRecordStore(tmp_path / "invocations").get(
            "invocation-starts", queue.item.id, DeliveryInvocationStart
        )
        request = native.request
        result = AgentResult(
            task_id=request.task_id,
            run_id=request.run_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.FAILED,
            error=AgentFailure(
                code=AgentErrorCode.WORK_INTERRUPTED, message="fixture", transient=False
            ),
        )
        outcome = DeliveryInvocationOutcome(
            start=invocation, result=result, outcome_sha256="0" * 64
        )
        outcome = outcome.model_copy(
            update={
                "outcome_sha256": digest(
                    outcome.model_dump(mode="json", exclude={"outcome_sha256"})
                )
            }
        )
        # Match the real repository's ignored-cache facts without granting it
        # Coder source permissions or changing the checked-out source revision.
        exclude = Path(
            native.git._run_git(
                ("rev-parse", "--path-format=absolute", "--git-path", "info/exclude"),
                cwd=native.worktree.path,
            )
        )
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(".mypy_cache/\n")
        cache = native.worktree.path / ".mypy_cache"
        (cache / "3.12").mkdir(parents=True)
        for relative in (".gitignore", "CACHEDIR.TAG", "missing_stubs"):
            (cache / relative).write_bytes(b"cache metadata")
        body = b"x" * 16_000_001
        (cache / "3.12/cache.db").write_bytes(body)
        large = MutationFile(
            ".mypy_cache/3.12/cache.db", "file", hashlib.sha256(body).hexdigest(), 0o644, len(body)
        )
        monkeypatch.setattr(module, "LARGE", large)
        files, sidecar = tmp_path / "maintenance", tmp_path / "sidecar"
        files.mkdir()
        sidecar.mkdir()
        monkeypatch.setattr(module, "FILES", files)
        monkeypatch.setattr(module, "SIDECAR", sidecar)
        monkeypatch.setattr(module, "TASK_ID", native.task.id)
        capture = CapturedMutations.from_capture(
            native.git.capture_mutations(native.worktree, request.permissions)
        )
        observed = module.Observed(
            native.repository.get(native.task.id),
            queue.item,
            queue.bound,
            queue.original,
            start,
            capture_stop,
            outcome,
            capture,
            "a" * 64,
            capture_mutation_inventory(native.worktree.path, known_oversized_file=large),
            "case_fixture_001",
        )

        def observe(queue: object, cursor: object, *, after: bool = False) -> object:
            del queue, cursor
            inventory = capture_mutation_inventory(
                native.worktree.path, known_oversized_file=None if after else large
            )
            return replace(observed, inventory=inventory)

        @contextmanager
        def locked() -> Iterator[tuple[object, object, object]]:
            yield object(), object(), object()

        monkeypatch.setattr(module, "observe", observe)
        monkeypatch.setattr(module, "locked", locked)
        monkeypatch.setattr(module, "validate_stop", lambda facts, guard: None)
        plan = module.plan_from(observed, NOW)
        module.IO.seal(files / "plan.json", module.canonical_bytes(plan.to_wire()) + b"\n")
        monkeypatch.setattr(module, "_test_plan", plan, raising=False)
        yield module
    finally:
        native.repository.close()
        os.close(descriptor)


def test_completion_failure_can_resume_and_exact_completed_replay_keeps_bytes(
    maintenance: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, plan = maintenance, maintenance._test_plan
    original_seal = module.IO.seal
    failed = False

    def fault(path: Path, payload: bytes) -> None:
        nonlocal failed
        if path.name == "completion.json" and not failed:
            failed = True
            raise OSError("fixture completion publication failure")
        original_seal(path, payload)

    # Only the immutable publication seam is faulted; actual filesystem rename,
    # full hashing, source before/after inventories and all typed records execute.
    monkeypatch.setattr(module.IO, "seal", fault)
    with pytest.raises(OSError):
        module.apply(plan.plan_sha256, "fixture delegated authority")
    root = Path(plan.start.worktree_path)
    audit = module.SIDECAR / "state/external-maintenance" / plan.plan_sha256
    assert not (root / ".mypy_cache").exists()
    assert (audit / "mypy-cache/3.12/cache.db").is_file()
    authority = (audit / "authorization.json").read_bytes()
    module.apply(plan.plan_sha256, "fixture delegated authority")
    completed = (audit / "completion.json").read_bytes()
    module.apply(plan.plan_sha256, "fixture delegated authority")
    assert (audit / "authorization.json").read_bytes() == authority
    assert (audit / "completion.json").read_bytes() == completed
    assert not (root / ".mypy_cache").exists()


def test_archive_or_authority_drift_refuses_without_replacing_original_files(
    maintenance: ModuleType,
) -> None:
    module, plan = maintenance, maintenance._test_plan
    module.apply(plan.plan_sha256, "fixture delegated authority")
    audit = module.SIDECAR / "state/external-maintenance" / plan.plan_sha256
    completed = (audit / "completion.json").read_bytes()
    with pytest.raises(RuntimeError):
        module.apply(plan.plan_sha256, "different authority")
    cache = audit / "mypy-cache/3.12/cache.db"
    with cache.open("r+b") as stream:
        stream.write(b"y")
    with pytest.raises(RuntimeError):
        module.apply(plan.plan_sha256, "fixture delegated authority")
    assert (audit / "completion.json").read_bytes() == completed
    assert cache.read_bytes().startswith(b"y")
