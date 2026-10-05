"""Exact same-Task baseline recovery, separate from product approval and platform upgrade."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from ai_software_engineer.domain.artifact import CoderProgressArtifact, ImplementationReportArtifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import (
    EngineeringAdmission,
    EngineeringCapability,
)
from ai_software_engineer.domain.enums import TaskStatus
from ai_software_engineer.domain.execution_baseline import (
    BaselineInputMode,
    CoderExecutionInput,
    ExecutionBaselineBinding,
    RetainedExecutionPatch,
    resolve_coder_execution_input,
)
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.baseline import (
    BaselineGitConflict,
    BaselineGitPreview,
    GitExecutionBaselineAdapter,
)
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionFacts,
    BaselineOperationStart,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.recovery.models import digest


class BaselineFactCollector(Protocol):
    """Trusted production composition holds an exclusive Task lock/queue fence.

    collect must verify no active lease/model process, exact stopped/definitive
    invocation proof, immutable selected artifacts/native rules, current Task
    revision and remaining budget. Target rules cannot expand Task permissions.
    """

    def collect(self, target_base_ref: str) -> BaselineExecutionFacts: ...

    def source_worktree(self, facts: BaselineExecutionFacts) -> WorktreeRef: ...

    def completed_task(self, binding: ExecutionBaselineBinding) -> Task: ...

    def execution_scope(self) -> AbstractContextManager[None]: ...


class ExecutionBaselineService:
    def __init__(
        self,
        *,
        store: FileExecutionBaselineStore,
        git: GitExecutionBaselineAdapter,
        facts: BaselineFactCollector,
        publish_completion: Callable[[ExecutionBaselinePlan, ExecutionBaselineBinding], None]
        | None = None,
    ) -> None:
        self.store, self.git, self.facts = store, git, facts
        self.publish_completion = publish_completion

    def propose(
        self,
        target_base_ref: str,
        *,
        input_mode: BaselineInputMode = BaselineInputMode.PRESERVE_DRAFT,
    ) -> ExecutionBaselinePlan:
        with self.store.execution_lock(), self.facts.execution_scope():
            facts = self.facts.collect(target_base_ref)
            self._require_facts(facts)
            previous = self.store.bindings_for_task(facts.task.id)
            binding = previous[-1] if previous else None
            worktree = self.facts.source_worktree(facts)
            expected_base = (
                binding.execution_base_ref if binding is not None else facts.task.base_ref
            )
            dirty = self.git.manager.capture_mutations(
                worktree, facts.permissions, denied_paths=facts.denied_paths
            )
            complete = self.git.manager.capture_mutations(
                worktree,
                facts.permissions,
                denied_paths=facts.denied_paths,
                base_revision=expected_base,
            )
            before = capture_mutation_inventory(worktree.path)
            conflicted = False
            try:
                preview = self.git.preview(
                    dirty=dirty,
                    complete=complete,
                    target_base=target_base_ref,
                    permissions=facts.permissions,
                    denied_paths=facts.denied_paths,
                    input_mode=input_mode,
                )
            except BaselineGitConflict:
                # Keep the exact refused preserve plan for audit. A separately
                # proposed coder_reapply plan has a different digest/authority.
                conflicted = True
                preview = BaselineGitPreview(
                    target_base_ref,
                    self.git.manager._run_git(
                        ("rev-parse", f"{target_base_ref}^{{tree}}"), cwd=worktree.path
                    ),
                    "",
                )
            if (
                self.facts.collect(target_base_ref) != facts
                or capture_mutation_inventory(worktree.path) != before
            ):
                raise ValueError("baseline source changed during exact proposal")
            plan = ExecutionBaselinePlan.create(
                facts=facts,
                previous_binding=binding,
                input_mode=input_mode,
                target_base_ref=target_base_ref,
                prepared_source_revision=preview.source_revision,
                prepared_dirty_tree=preview.dirty_tree,
                prepared_dirty_patch=preview.dirty_patch,
                dirty_capture=CapturedMutations.from_capture(dirty),
                complete_capture=CapturedMutations.from_capture(complete),
                before_inventory=before,
                conflicted=conflicted,
            )
            return self.store.put_plan(plan)

    @staticmethod
    def _require_facts(facts: BaselineExecutionFacts) -> None:
        facts.validate_integrity()
        if facts.task.status is not TaskStatus.IMPLEMENTING or facts.task.branch_name is None:
            raise ValueError(
                "baseline migration requires the same nonterminal named Coder checkpoint"
            )
        work_limit = (
            facts.task.retry_policy.max_work_attempts
            if facts.task.retry_policy is not None
            else facts.task.max_attempts
        )
        if facts.task.work_attempt > work_limit:
            raise ValueError("baseline update does not grant new Coder budget")

    @staticmethod
    def _require_authority(
        plan: ExecutionBaselinePlan, authority: EngineeringAdmission | BaselineOperatorAuthorization
    ) -> tuple[Literal["organization_engineering_policy", "engineering_operator_decision"], str]:
        authority.validate_integrity()
        task = plan.facts.task
        if (
            authority.task_id != task.id
            or authority.task_intent_sha256 != task_intent_sha256(task)
            or authority.plan_sha256 != plan.plan_sha256
            or authority.facts_sha256 != plan.facts.facts_sha256
        ):
            raise ValueError("baseline authority is not for this exact new plan and source facts")
        if isinstance(authority, EngineeringAdmission):
            EngineeringAuthority.validate(task=task, record=authority)
            if authority.capabilities != (EngineeringCapability.EXECUTION_BASELINE_REBIND,):
                raise ValueError("baseline action has no exact versioned engineering capability")
            return authority.authorization_source, authority.admission_sha256
        return authority.authorization_source, authority.authorization_sha256

    def execute(
        self, plan_sha256: str, *, authority: EngineeringAdmission | BaselineOperatorAuthorization
    ) -> ExecutionBaselineBinding:
        with self.store.execution_lock(), self.facts.execution_scope():
            plan = self.store.plan(plan_sha256)
            source, authority_sha = self._require_authority(plan, authority)
            if plan.conflicted:
                raise BaselineGitConflict(
                    "conflicted preserve plan requires a new exact coder_reapply authorization"
                )
            self.store.put_authority(authority)
            existing = self.store.bindings_for_task(plan.facts.task.id)
            prior_completion = next(
                (item for item in existing if item.plan_sha256 == plan.plan_sha256), None
            )
            if prior_completion is not None:
                # Publication proved the exact Git operation completed. A later
                # queue consumption or role run legitimately changes counters,
                # source and artifacts; do not recollect the old mutation facts.
                prior_completion.require_task(self.facts.completed_task(prior_completion))
                if (source, authority_sha) != (
                    prior_completion.authority_source,
                    prior_completion.authority_sha256,
                ):
                    raise ValueError("completed baseline cannot acquire another authorization")
                if self.publish_completion is not None:
                    self.publish_completion(plan, prior_completion)
                return prior_completion
            current = self.facts.collect(plan.target_base_ref)
            self._require_facts(current)
            expected_previous = existing[-1] if existing else None
            if expected_previous != plan.previous_binding or current != plan.facts:
                raise ValueError(
                    "baseline plan/source/queue facts drifted; request a new exact plan"
                )
            started = self.store.start(plan_sha256)
            if started is None:
                self.git.manager.verify_mutations(
                    plan.dirty_capture.to_capture(),
                    current.permissions,
                    denied_paths=current.denied_paths,
                )
                self.git.manager.verify_mutations(
                    plan.complete_capture.to_capture(),
                    current.permissions,
                    denied_paths=current.denied_paths,
                )
                if (
                    capture_mutation_inventory(Path(plan.dirty_capture.worktree_path))
                    != plan.before_inventory
                ):
                    raise ValueError("baseline source inventory drifted before execution")
                start = BaselineOperationStart(
                    plan=plan,
                    authority_source=source,
                    authority_sha256=authority_sha,
                    started_at=datetime.now(UTC),
                    start_sha256="0" * 64,
                )
                start = start.model_copy(
                    update={
                        "start_sha256": digest(
                            start.model_dump(mode="json", exclude={"start_sha256"})
                        )
                    }
                )
                self.store.put_start(start)
            elif started.plan != plan or (started.authority_source, started.authority_sha256) != (
                source,
                authority_sha,
            ):
                raise ValueError("baseline operation start changed; preserve all existing state")
            reference, after_inventory = self.git.apply(
                dirty=plan.dirty_capture.to_capture(),
                complete=plan.complete_capture.to_capture(),
                preview=BaselineGitPreview(
                    plan.prepared_source_revision,
                    plan.prepared_dirty_tree,
                    plan.prepared_dirty_patch,
                ),
                plan_sha256=plan_sha256,
                permissions=current.permissions,
                denied_paths=current.denied_paths,
                original_inventory=plan.before_inventory,
            )
            if self.facts.collect(plan.target_base_ref) != current:
                raise ValueError(
                    "baseline Task/queue/native rules changed during mutation; "
                    "preserve the admitted operation"
                )
            patch_body = plan.complete_capture.patch.encode("utf-8")
            previous = plan.previous_binding
            binding = ExecutionBaselineBinding.create(
                scope=current.scope,
                task_id=current.task.id,
                task_intent_sha256=task_intent_sha256(current.task),
                sequence=len(existing) + 1,
                previous_binding_sha256=previous.binding_sha256 if previous is not None else None,
                approved_base_ref=current.task.base_ref,
                branch_name=current.task.branch_name,
                worktree_path=str(reference.path),
                prior_execution_base_ref=previous.execution_base_ref
                if previous is not None
                else current.task.base_ref,
                prior_source_revision=plan.dirty_capture.source_revision,
                execution_base_ref=plan.target_base_ref,
                execution_source_revision=reference.head_revision,
                input_mode=plan.input_mode,
                superseded_implementation_artifact_id=current.implementation_artifact_id,
                superseded_progress_artifact_id=current.progress_artifact_id,
                source_artifact_ids=current.source_artifact_ids,
                resolved_interruption_receipt_sha256s=current.resolved_interruption_receipt_sha256s,
                retained_patch=RetainedExecutionPatch(
                    uri=self.store.patch_uri(plan_sha256),
                    sha256=hashlib.sha256(patch_body).hexdigest(),
                    bytes=len(patch_body),
                ),
                authority_source=source,
                authority_sha256=authority_sha,
                plan_sha256=plan_sha256,
                facts_sha256=current.facts_sha256,
                prior_task_revision=current.task_revision,
                before_inventory_sha256=plan.before_inventory.sha256,
                after_inventory_sha256=after_inventory,
                completed_at=datetime.now(UTC),
            )
            completed = self.store.put_binding(binding)
            if self.publish_completion is not None:
                self.publish_completion(plan, completed)
            return completed


class StoredCoderExecutionInputResolver:
    """All runtime consumers share this append-only selector and verified patch body."""

    def __init__(self, store: FileExecutionBaselineStore | None) -> None:
        self.store = store

    def current(
        self,
        task: Task,
        *,
        implementation: ImplementationReportArtifact | None,
        progress: CoderProgressArtifact | None,
    ) -> CoderExecutionInput:
        history = self.store.bindings_for_task(task.id) if self.store is not None else ()
        return resolve_coder_execution_input(
            task,
            implementation=implementation,
            progress=progress,
            baseline=history[-1] if history else None,
        )

    def required_context(self, source: CoderExecutionInput) -> str | None:
        if source.baseline is None:
            return None
        if self.store is None:
            raise ValueError("bound baseline has no immutable patch body store")
        return self.store.required_context(source.baseline)
