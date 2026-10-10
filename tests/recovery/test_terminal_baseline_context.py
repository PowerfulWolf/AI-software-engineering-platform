"""The real original request and complete required Context select a terminal epoch."""

import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.context.execution_baseline import ExecutionBaselineContext
from ai_software_engineer.context.models import ContextBudget, ContextBundle, ContextSection
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.execution_baseline import (
    BaselineInputMode,
    ExecutionBaselineBinding,
    RetainedExecutionPatch,
)
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.recovery.baseline_source import (
    RecoveryBaselineEpoch,
    read_recovery_baseline_epochs,
    require_terminal_baseline_context,
    validate_pre_candidate_sources,
)
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryScope
from ai_software_engineer.recovery.native import NativeRecoverySource
from ai_software_engineer.recovery.scope import (
    expanded_recovery_permissions,
    inspect_recovery_scope_supplement,
)
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from tests.agents.test_openai_compatible import _request
from tests.domain.factories import NOW, make_state_event
from tests.manager.test_execution_baseline import authorize, setup
from tests.manager.test_terminal_candidate_reconstruction import _binding
from tests.recovery.test_authorization import make_plan
from tests.recovery.test_terminal_baseline import _task


def _fixture(
    tmp_path: Path,
) -> tuple[Path, Task, ContextBundle, RecoveryBaselineEpoch, AgentRequest]:
    task = _task()
    wire = _binding(task).to_wire()
    wire.pop("binding_sha256")
    wire.pop("retained_patch")
    patch = "retained complete patch\n"
    binding = ExecutionBaselineBinding.create(
        **wire,
        retained_patch=RetainedExecutionPatch(
            uri="baseline://complete",
            sha256=hashlib.sha256(patch.encode()).hexdigest(),
            bytes=len(patch.encode()),
        ),
    )
    request = _request(AgentRole.CODER, attempt=2, source_revision="d" * 40).model_copy(
        update={
            "task_id": task.id,
            "execution_baseline_sha256": binding.binding_sha256,
            "execution_base_ref": binding.execution_base_ref,
        }
    )
    value = ExecutionBaselineContext(
        binding=binding, instructions="exact approved source", complete_patch=patch
    )
    content = value.model_dump_json()
    section = ContextSection(
        name="execution.baseline",
        uri="baseline://" + binding.binding_sha256,
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        tokens=1,
        content=content,
        priority=1,
    )
    context = ContextBundle(
        context_id=request.context_manifest_id,
        task_id=task.id,
        role=AgentRole.CODER,
        attempt=2,
        source_revision="d" * 40,
        sections=(section,),
        budget=ContextBudget(max_input_tokens=100, reserved_output_tokens=0, used_input_tokens=1),
        built_at=NOW,
    )
    (tmp_path / "state/invocations").mkdir(parents=True)
    return tmp_path, task, context, RecoveryBaselineEpoch(binding, 2), request


def _put_start(
    root: Path,
    request: AgentRequest,
    *,
    work_id: str = "work_original",
    checkpoint: int = 1,
    seconds: int = 1,
) -> None:
    start = DeliveryInvocationStart(
        work_item_id=work_id,
        checkpoint_sequence=checkpoint,
        request=request,
        lease_id="lease_original",
        started_at=NOW + timedelta(seconds=seconds),
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    KnowledgeRecordStore(root / "state/invocations").put("invocation-starts", work_id, start)


def test_exact_original_invocation_and_complete_context_are_read_only(tmp_path: Path) -> None:
    root, task, context, epoch, request = _fixture(tmp_path)
    _put_start(root, request)
    files = {p: p.read_bytes() for p in (root / "state/invocations").rglob("*.json")}
    assert files
    actual = require_terminal_baseline_context(
        root,
        task,
        context,
        (epoch,),
        run_id=request.run_id,
        request_sha256=digest(request.to_wire()),
        attempt=request.attempt,
        source_revision=request.source_revision,
    )
    assert actual == epoch.binding
    assert files == {p: p.read_bytes() for p in (root / "state/invocations").rglob("*.json")}


@pytest.mark.parametrize(
    "fault",
    [
        "digest",
        "base",
        "role",
        "checkpoint",
        "time",
        "truncated",
        "content",
        "missing",
        "duplicate",
    ],
)
def test_unbound_terminal_request_or_context_is_rejected(tmp_path: Path, fault: str) -> None:
    root, task, context, epoch, request = _fixture(tmp_path)
    checkpoint, seconds = 1, 1
    if fault == "digest":
        request = request.model_copy(update={"execution_baseline_sha256": "e" * 64})
    elif fault == "base":
        request = request.model_copy(update={"execution_base_ref": "f" * 40})
    elif fault == "role":
        request = request.model_copy(
            update={"role": AgentRole.QA, "output_schema": "schemas/qa-report.schema.json"}
        )
    elif fault == "checkpoint":
        checkpoint = 0
    elif fault == "time":
        seconds = -1
    elif fault in {"truncated", "content"}:
        section = context.sections[0].model_copy(
            update={"truncated": True} if fault == "truncated" else {"sha256": "0" * 64}
        )
        context = context.model_copy(update={"sections": (section,)})
    if fault != "missing":
        _put_start(root, request, checkpoint=checkpoint, seconds=seconds)
    if fault == "duplicate":
        _put_start(root, request, work_id="work_another")
    with pytest.raises(ValueError):
        require_terminal_baseline_context(
            root,
            task,
            context,
            (epoch,),
            run_id=request.run_id,
            request_sha256=digest(request.to_wire()),
            attempt=request.attempt,
            source_revision=request.source_revision,
        )


def test_context_cannot_invent_a_missing_baseline_history(tmp_path: Path) -> None:
    root, task, context, _, request = _fixture(tmp_path)
    with pytest.raises(ValueError, match="history"):
        require_terminal_baseline_context(
            root,
            task,
            context,
            (),
            run_id=request.run_id,
            request_sha256=digest(request.to_wire()),
            attempt=request.attempt,
            source_revision=request.source_revision,
        )


def test_preserved_draft_terminal_context_keeps_real_source_and_capture_base_distinct(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.domain.enums import TaskStatus
    from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore

    f = setup(tmp_path)
    facts = f.collector.facts.model_copy(
        update={
            "scope": f.collector.facts.scope.model_copy(
                update={"repository_id": "repository_baseline"}
            )
        }
    )
    facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    f.collector.facts = facts
    original_task = facts.task.to_wire()
    sidecar = tmp_path / "sidecar"
    f.service.store = FileExecutionBaselineStore(
        sidecar / "state/execution-baselines" / facts.task.id
    )
    plan = f.service.propose(f.target)
    binding = f.service.execute(plan.plan_sha256, authority=authorize(plan))
    assert binding.input_mode is BaselineInputMode.PRESERVE_DRAFT
    assert binding.execution_source_revision != binding.execution_base_ref
    assert binding.approved_base_ref == facts.task.base_ref
    task = facts.task.model_copy(update={"status": TaskStatus.BLOCKED, "attempts": 2})
    scope = RecoveryScope(
        team_id=binding.scope.team_id,
        repository_id=binding.scope.repository_id,
        repository_root=binding.scope.repository_root,
        delivery_id="delivery_baseline",
    )
    epochs = read_recovery_baseline_epochs(
        sidecar, task, scope, project_id=binding.scope.project_id
    )
    request = _request(
        AgentRole.CODER, attempt=2, source_revision=binding.execution_source_revision
    ).model_copy(
        update={
            "task_id": task.id,
            "execution_baseline_sha256": binding.binding_sha256,
            "execution_base_ref": binding.execution_base_ref,
        }
    )
    content = ExecutionBaselineContext.from_required_context(
        binding, f.service.store.required_context(binding)
    ).model_dump_json()
    context = ContextBundle(
        context_id=request.context_manifest_id,
        task_id=task.id,
        role=AgentRole.CODER,
        attempt=request.attempt,
        source_revision=request.source_revision,
        sections=(
            ContextSection(
                name="execution.baseline",
                uri="baseline://" + binding.binding_sha256,
                sha256=hashlib.sha256(content.encode()).hexdigest(),
                tokens=1,
                content=content,
                priority=1,
            ),
        ),
        budget=ContextBudget(max_input_tokens=100, reserved_output_tokens=0, used_input_tokens=1),
        built_at=binding.completed_at + timedelta(seconds=1),
    )
    start = DeliveryInvocationStart(
        work_item_id="work_preserved_terminal",
        checkpoint_sequence=binding.prior_task_revision,
        request=request,
        lease_id="lease_preserved_terminal",
        started_at=binding.completed_at + timedelta(seconds=2),
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    KnowledgeRecordStore(sidecar / "state/invocations").put(
        "invocation-starts", start.work_item_id, start
    )
    events = tuple(
        make_state_event(event_id=f"evt_preserved_{revision}").model_copy(
            update={
                "task_id": task.id,
                "attempt": 1 if revision <= binding.prior_task_revision else request.attempt,
                "source_revision": task.base_ref
                if revision <= binding.prior_task_revision
                else request.source_revision,
                "occurred_at": binding.completed_at
                + timedelta(seconds=revision - binding.prior_task_revision),
            }
        )
        for revision in range(1, binding.prior_task_revision + 2)
    )
    validate_pre_candidate_sources(task, events, epochs)
    with pytest.raises(ValueError, match="source"):
        validate_pre_candidate_sources(
            task,
            (
                *events[:-1],
                events[-1].model_copy(update={"source_revision": binding.execution_base_ref}),
            ),
            epochs,
        )
    assert (
        require_terminal_baseline_context(
            sidecar,
            task,
            context,
            epochs,
            run_id=request.run_id,
            request_sha256=digest(request.to_wire()),
            attempt=request.attempt,
            source_revision=request.source_revision,
        )
        == binding
    )
    source = make_plan(f.repository).source.model_copy(
        update={
            "scope": scope,
            "task_id": task.id,
            "task_revision": len(events),
            "task_sha256": digest(task.to_wire()),
            "failed_run_id": request.run_id,
            "failed_context_id": request.context_manifest_id,
            "base_revision": task.base_ref,
            "execution_baseline_sha256": binding.binding_sha256,
            "execution_base_revision": binding.execution_base_ref,
        }
    )
    worktree = replace(f.worktree, head_revision=binding.execution_source_revision)
    permissions = facts.permissions.model_copy(update={"write_paths": ()})
    original = cast(
        NativeRecoverySource,
        SimpleNamespace(source=source, permissions=permissions, denied_paths=facts.denied_paths),
    )
    supplement = inspect_recovery_scope_supplement(f.manager, worktree, original)
    assert supplement is not None
    assert supplement.paths == ("src/app.py",)
    assert supplement.base_revision == source.effective_base_revision == binding.execution_base_ref
    capture = CapturedChanges.from_capture(
        f.manager.capture_changes(
            worktree,
            expanded_recovery_permissions(permissions, supplement),
            denied_paths=facts.denied_paths,
            base_revision=source.effective_base_revision,
        )
    )
    assert capture.source_revision == request.source_revision == binding.execution_source_revision
    assert capture.to_capture().effective_base_revision == request.execution_base_ref
    assert "VALUE = 2" in capture.patch and "EXTRA = 3" in capture.patch
    assert "README.md" not in capture.patch
    assert facts.task.to_wire() == original_task
