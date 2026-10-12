"""Same-worktree continuation reads retained files after complete fresh verification."""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ExecutionInterruptionReceipt,
)
from tests.orchestration.test_native_continuation import Guard
from tests.orchestration.test_native_continuation_v2 import V2Fixture


@pytest.fixture
def native(tmp_path: Path) -> Iterator[V2Fixture]:
    fd = os.open(tmp_path / "continuation.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    value = V2Fixture(tmp_path, Guard(fd))
    try:
        yield value
    finally:
        value.repository.close()
        os.close(fd)


def test_large_verified_draft_is_read_from_same_worktree_not_repeated_inline(
    native: V2Fixture,
) -> None:
    service = native.service()
    text = "# Complete retained progress 中文\n" + "VALUE = 2\n" * 16_000
    receipt = native.interrupt(service, text=text)
    assert native.reserve(service) == 2
    native.restart()
    native.activate(2)
    before = {str(p): p.read_bytes() for p in native.store_root.rglob("*.json")}
    continued = native.service()
    prompt = continued.preview(native.request, native.worktree.path)
    assert prompt is not None and len(prompt) < 8_000
    assert text not in prompt
    assert native.store.admissions_for_task(native.task.id) == ()

    assert {str(p): p.read_bytes() for p in native.store_root.rglob("*.json")} == before
    manifest = json.loads(prompt.split("PRESERVED_WORKTREE_INPUT=", 1)[1])
    assert manifest["kind"] == "preserved_worktree_continuation_input"
    assert manifest["schema_version"] == "v1"
    assert manifest["receipt_sha256"] == receipt.receipt_sha256
    assert manifest["scope"] == receipt.scope.to_wire()
    assert manifest["patch_sha256"] == hashlib.sha256(receipt.capture.patch.encode()).hexdigest()
    assert manifest["patch_bytes"] == len(receipt.capture.patch.encode())
    assert manifest["source_revision"] == native.request.source_revision
    change = manifest["mutations"][0]
    assert change["path"] == "src/app.py" and change["deleted"] is False
    assert change["after"]["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert change["after"]["size"] == len(text.encode())
    assert isinstance(receipt.capture, CapturedMutations)
    original = receipt.capture.mutations[0].before
    assert original is not None
    assert change["before"]["sha256"] == original.sha256
    assert continued.prepare(native.request, native.worktree.path) == prompt
    assert len(native.store.admissions_for_task(native.task.id)) == 1
    assert native.store.get_receipt(receipt.request.run_id) == receipt
    assert (native.worktree.path / "src/app.py").read_text() == text


@pytest.mark.parametrize("change", ["delete", "rename", "mode"])
def test_manifest_preserves_deletion_addition_and_mode_facts(
    native: V2Fixture, change: str
) -> None:
    from ai_software_engineer.agents.continuation import InterruptionObservation
    from ai_software_engineer.agents.models import AgentErrorCode

    service = native.service()
    root = native.worktree.path
    before = service.started(native.request, root)
    assert before is not None
    app = root / "src/app.py"
    if change == "delete":
        app.unlink()
    elif change == "rename":
        app.rename(root / "src/renamed.py")
    else:
        app.chmod(0o755)
    assert (
        service.interrupted(
            native.request,
            root,
            before=before,
            cause="local_execution_limit",
            original_error_code=AgentErrorCode.TIMEOUT,
            process_stop=native.stopped(local=True),
            output_present=False,
        )
        is InterruptionObservation.CAPTURED
    )
    receipt = native.store.get_receipt(native.request.run_id)
    assert native.reserve(service) == 2
    native.activate(2)
    prompt = native.service().preview(native.request, root)
    assert prompt is not None
    manifest = json.loads(prompt.split("PRESERVED_WORKTREE_INPUT=", 1)[1])
    assert isinstance(receipt.capture, CapturedMutations)
    expected = [
        {
            "path": item.path,
            "before": None
            if item.before is None
            else {
                "sha256": item.before.sha256,
                "size": item.before.size,
                "mode": item.before.mode,
            },
            "after": None
            if item.after is None
            else {
                "sha256": item.after.sha256,
                "size": item.after.size,
                "mode": item.after.mode,
            },
            "deleted": item.after is None,
        }
        for item in receipt.capture.mutations
    ]
    assert manifest["mutations"] == expected
    if change in ("delete", "rename"):
        assert expected[0]["deleted"] is True and expected[0]["path"] == "src/app.py"
    if change == "rename":
        assert expected[1]["path"] == "src/renamed.py" and expected[1]["before"] is None
    if change == "mode":
        assert manifest["mutations"][0]["before"]["mode"] == 0o644
        assert manifest["mutations"][0]["after"]["mode"] == 0o755


@pytest.mark.parametrize("fault", ["content", "mode", "symlink", "binary", "owner"])
def test_projection_never_waives_current_complete_workspace_or_owner_checks(
    native: V2Fixture, fault: str
) -> None:
    service = native.service()
    native.interrupt(service)
    assert native.reserve(service) == 2
    native.activate(2)
    current = native.worktree.path / "src/app.py"
    if fault == "content":
        current.write_text("VALUE = 99\n")
    elif fault == "mode":
        current.chmod(0o755)
    elif fault == "symlink":
        current.unlink()
        current.symlink_to(native.worktree.path / "README.md")
    elif fault == "binary":
        current.write_bytes(b"\x00untrusted")
    else:
        native.guard.live = False
    with pytest.raises(ContinuationRejected):
        native.service().preview(native.request, native.worktree.path)
    assert native.store.admissions_for_task(native.task.id) == ()


def test_final_native_input_keeps_complete_reapply_patch_and_schema_before_capacity_check(
    native: V2Fixture,
) -> None:
    from ai_software_engineer.agents import CodexCliAgentAdapter, StoredContextResolver
    from ai_software_engineer.agents.model_input import BoundModelInputBudget
    from ai_software_engineer.agents.openai_compatible import ContextPromptBuilder
    from ai_software_engineer.context import (
        ContextBudget,
        ContextBudgetExceeded,
        ContextSource,
        InMemoryContextStore,
    )
    from ai_software_engineer.context.builder import estimate_input_tokens
    from ai_software_engineer.domain import AgentRole
    from ai_software_engineer.orchestration.context import FileRunContextBuilder
    from tests.agents.test_model_input_preflight import _PreviewControl, _Runner
    from tests.orchestration.test_runner import _definitions

    service = native.service()
    receipt = native.interrupt(service, text="VALUE = 2\n" * 16_000)
    assert native.reserve(service) == 2
    native.activate(2)
    complete_old_patch = "ORIGINAL_REQUIRED_REAPPLY_PATCH\n" + "x" * 900_000
    contexts = InMemoryContextStore()
    context = FileRunContextBuilder(
        native.worktree.path,
        sources=(
            ContextSource(
                source_id="recovery.patch",
                uri="recovery://fixture/full-patch",
                content=complete_old_patch,
                required=True,
            ),
        ),
        context_store=contexts,
        budget=ContextBudget(max_input_tokens=256_000, reserved_output_tokens=4_000),
    ).build(
        native.repository.get(native.task.id),
        _definitions()[AgentRole.CODER],
        attempt=2,
        input_artifacts=native.artifacts.list_for_task(native.task.id),
    )
    native.request = native.request.model_copy(update={"context_manifest_id": context.context_id})
    resolver = StoredContextResolver(contexts, native.artifacts)
    runner = _Runner()
    legacy = CodexCliAgentAdapter(
        workspace_root=native.worktree.path,
        model="test",
        agent_id="agent_fixture",
        agent_version="v1",
        runner=runner,
        prompt_builder=ContextPromptBuilder(resolver),
        input_budget=BoundModelInputBudget(resolver),
        interruption_control=_PreviewControl("完整补丁:\n" + receipt.capture.patch),
    )
    with pytest.raises(ContextBudgetExceeded):
        legacy.prepare_input(native.request)
    adapter = CodexCliAgentAdapter(
        workspace_root=native.worktree.path,
        model="test",
        agent_id="agent_fixture",
        agent_version="v1",
        runner=runner,
        prompt_builder=ContextPromptBuilder(resolver),
        input_budget=BoundModelInputBudget(resolver),
        interruption_control=native.service(),
    )
    before = context.to_wire()
    adapter.prepare_input(native.request)
    prepared = adapter._prepared_inputs[native.request.run_id]
    messages = json.loads(
        prepared.compiled_prompt.split("PROMPT_MESSAGES=", 1)[1].split("平台已完整核验", 1)[0]
    )
    user = next(m["content"] for m in messages if m["role"] == "user")
    assert (
        next(s["content"] for s in user["sections"] if s["uri"] == "recovery://fixture/full-patch")
        == complete_old_patch
    )
    assert estimate_input_tokens(prepared.budget_content) <= 256_000
    assert prepared.schema_content and prepared.schema_path.read_text() == prepared.schema_content
    assert context.to_wire() == before and contexts.get(context.context_id).to_wire() == before
    assert native.store.admissions_for_task(native.task.id) == () and runner.calls == 0
    adapter.discard_prepared_input(native.request)
    assert not adapter._prepared_inputs and not prepared.schema_path.exists()


def test_live_original_group_cannot_produce_a_preserved_worktree_reading(
    native: V2Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = native.service()
    receipt = native.interrupt(service)
    assert native.reserve(service) == 2
    native.activate(2)
    child = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(30)"), start_new_session=True
    )
    try:
        assert isinstance(receipt.process_stop, NativeProcessStop)
        stop = receipt.process_stop.model_copy(
            update={"process_id": child.pid, "group_id": child.pid}
        )
        stop = stop.model_copy(update={"stop_sha256": stop.recompute_sha256()})
        alleged = receipt.model_copy(
            update={"process_stop": stop, "process_stop_sha256": stop.stop_sha256}
        )
        alleged = alleged.model_copy(update={"receipt_sha256": alleged.recompute_sha256()})
        alleged.validate_integrity()

        def receipts(task_id: str) -> tuple[ExecutionInterruptionReceipt, ...]:
            assert task_id == native.task.id
            return (alleged,)

        monkeypatch.setattr(native.store, "receipts_for_task", receipts)
        with pytest.raises(ContinuationRejected, match="remains alive"):
            native.service().preview(native.request, native.worktree.path)
        assert native.store.admissions_for_task(native.task.id) == ()
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)
