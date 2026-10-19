"""Recursive compatibility through approved legacy Plans that predate inheritance."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.context import ContextBundle, FileContextBuilder
from ai_software_engineer.domain import AgentRole, Task, TaskStatus
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.recovery.context import recovery_context_sources
from ai_software_engineer.recovery.inherited_input import (
    InheritedInputRecords,
    reconstruct_inherited_reapply_inputs,
)
from ai_software_engineer.recovery.models import (
    CapturedChanges,
    InheritedReapplyInput,
    RecoveryAuthorization,
    RecoveryPlan,
    RecoveryRejected,
    RecoverySource,
    digest,
)
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from tests.domain.factories import make_task
from tests.recovery.test_authorization import Human, approval, make_plan


class TrustedRecords:
    """Trusted store/queue ports; native SQL and immutable-store checks are tested separately."""

    def __init__(self, project: Path) -> None:
        self.prototype = make_plan(project)
        self.plans: dict[str, RecoveryPlan] = {}
        self.authorizations: dict[str, RecoveryAuthorization] = {}
        self.tasks: dict[str, Task] = {}
        self.contexts: dict[str, ContextBundle] = {}
        self.starts: dict[str, DeliveryInvocationStart] = {}
        self.dispatches: dict[str, SimpleNamespace] = {}
        self.sealed: dict[str, Task] = {}
        self.recoveries = cast(FileRecoveryStore, self)

    def get_plan(self, sha: str) -> RecoveryPlan:
        return self.plans[sha]

    def get_authorization(self, sha: str) -> RecoveryAuthorization:
        if sha not in self.authorizations:
            raise RecoveryRejected("missing historical authorization")
        return self.authorizations[sha]

    def get_task_record(self, sha: str) -> SimpleNamespace:
        return SimpleNamespace(task=self.sealed[sha], record_sha256="c" * 64)

    def get_seed(self, sha: str) -> SimpleNamespace:
        return SimpleNamespace(
            dispatch_sha256=self.dispatches[sha].dispatch_sha256, record_sha256="d" * 64
        )

    def get_invocation(self, sha: str) -> SimpleNamespace:
        start = self.starts[self.plans[sha].new_task_id]
        return SimpleNamespace(
            run_id=start.request.run_id,
            context_manifest_id=start.request.context_manifest_id,
            seed_record_sha256="d" * 64,
        )

    def task(self, identity: str) -> tuple[Task, int]:
        return self.tasks[identity], 3

    def dispatch(self, sha: str) -> RecoveryDispatchRecord:
        return cast(RecoveryDispatchRecord, self.dispatches[sha])

    def context(self, identity: str) -> ContextBundle:
        return self.contexts[identity]

    def invocation(
        self, run_id: str, *, dispatch: RecoveryDispatchRecord, task: Task, first: bool = False
    ) -> DeliveryInvocationStart:
        start = self.starts[task.id]
        assert start.request.run_id == run_id and dispatch.task_id == task.id
        return start

    def source(self, task: Task) -> RecoverySource:
        plan_sha = task.metadata.get("recovery_plan_sha256")
        previous = self.starts.get(task.id)
        return self.prototype.source.model_copy(
            update={
                "task_id": task.id,
                "task_sha256": digest(task.to_wire()),
                "base_revision": task.base_ref,
                "dispatch_sha256": self.dispatches[str(plan_sha)].dispatch_sha256
                if plan_sha
                else "3" * 64,
                "failed_run_id": previous.request.run_id if previous else "run_original",
                "failed_context_id": previous.request.context_manifest_id
                if previous
                else self.prototype.source.failed_context_id,
            }
        )

    def generation(
        self, previous: Task, *, mode: str | None, body: str
    ) -> tuple[RecoveryPlan, Task]:
        plan = RecoveryPlan.create(
            **{
                **self.prototype.to_wire(),
                "source": self.source(previous),
                "input_mode": mode,
                "capture": CapturedChanges.from_capture(
                    replace(
                        self.prototype.capture.to_capture(),
                        worktree=replace(
                            self.prototype.capture.to_capture().worktree,
                            task_id=previous.id,
                            head_revision=previous.base_ref,
                            branch=f"ai/{previous.id}/attempt-1",
                        ),
                        patch=body.encode(),
                    )
                ),
            }
        )
        # Legacy wire is deliberately field-absent, with its original digest.
        assert "inherited_reapply_inputs" not in plan.to_wire()
        task = make_task().model_copy(
            update={
                "id": plan.new_task_id,
                "repository": plan.source.scope.repository_root,
                "base_ref": plan.target_base_revision,
                "metadata": {"recovery_plan_sha256": plan.plan_sha256},
            }
        )
        self.sealed[plan.plan_sha256] = task
        self.tasks[previous.id] = previous
        terminal = task.model_copy(update={"status": TaskStatus.BLOCKED, "attempts": 1})
        self.tasks[task.id] = terminal
        context = FileContextBuilder(
            Path(task.repository), plan.permissions, sources=recovery_context_sources(plan)
        ).build(task, AgentRole.CODER, attempt=1)
        self.contexts[context.context_id] = context
        request = AgentRequest(
            run_id=f"run_generation_{len(self.plans)}",
            task_id=task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=task.base_ref,
            context_manifest_id=context.context_id,
            input_artifact_ids=(),
            permissions=plan.effective_target_permissions,
            output_schema="schemas/coder-output.schema.json",
            timeout_seconds=60,
        )
        start = DeliveryInvocationStart(
            work_item_id=f"work_generation_{len(self.plans)}",
            checkpoint_sequence=2,
            request=request,
            lease_id=f"lease_generation_{len(self.plans)}",
            started_at=plan.created_at,
            start_sha256="0" * 64,
        )
        self.starts[task.id] = start.model_copy(
            update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
        )
        self.plans[plan.plan_sha256] = plan
        command = approval(plan)
        self.authorizations[plan.plan_sha256] = RecoveryAuthorization.create(
            command, Human().verify(command)
        )
        self.dispatches[plan.plan_sha256] = SimpleNamespace(
            task=task,
            task_id=task.id,
            dispatch_sha256=digest({"dispatch_of": plan.plan_sha256}),
            recovery_task_record_sha256="c" * 64,
            validate_integrity=lambda: None,
        )
        return plan, terminal


@pytest.mark.parametrize("failure", [None, "missing_authorization", "rejected_authorization"])
def test_legacy_none_recursively_preserves_old_complete_reapply_input(
    tmp_path: Path, failure: str | None
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    records = TrustedRecords(project)
    original = make_task().model_copy(
        update={
            "id": "task_original",
            "repository": str(project),
            "base_ref": "a" * 40,
            "status": TaskStatus.BLOCKED,
            "attempts": 1,
        }
    )
    old_body = "diff --git a/remaining.py b/remaining.py\n+STILL_UNADAPTED = True\n"
    first_plan, first = records.generation(original, mode="coder_reapply", body=old_body)
    second_plan, second = records.generation(first, mode=None, body="only the newer partial work\n")
    assert second_plan.inherited_reapply_inputs is None
    if failure == "missing_authorization":
        del records.authorizations[first_plan.plan_sha256]
    if failure == "rejected_authorization":
        auth = records.authorizations[first_plan.plan_sha256]
        records.authorizations[first_plan.plan_sha256] = auth.model_copy(
            update={"decision": auth.decision.model_copy(update={"approved": False})}
        )

    def reconstruct() -> tuple[InheritedReapplyInput, ...] | None:
        return reconstruct_inherited_reapply_inputs(
            cast(InheritedInputRecords, records), records.source(second), second
        )

    if failure:
        with pytest.raises(RecoveryRejected):
            reconstruct()
    else:
        result = reconstruct()
        assert result is not None and len(result) == 1
        assert result[0].origin_plan_sha256 == first_plan.plan_sha256
        assert result[0].origin_task_id == first.id
        assert (
            result[0].origin_context_manifest_id
            == records.starts[first.id].request.context_manifest_id
        )
        assert result[0].patch == old_body
        assert result[0].patch_bytes == len(old_body.encode())
