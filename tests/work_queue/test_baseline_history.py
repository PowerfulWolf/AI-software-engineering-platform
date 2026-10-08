"""Historical baseline lineage retains each role's immutable candidate source."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.manager.baseline_models import ExecutionBaselinePlan
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue import baseline
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    record_digest,
)
from ai_software_engineer.work_queue.ports import QueueCorruption, QueueNotFound
from tests.git.test_worktree import _git
from tests.manager.test_execution_baseline import Setup, authorize, setup
from tests.work_queue.test_mysql_queue import queued_item


@dataclass
class History:
    queue: MySqlRoleQueue
    fixture: Setup
    plan: ExecutionBaselinePlan
    record: BaselineQueueConsumption
    steps: dict[str, QueuedRoleStep]

    def append(self, role: AgentRole, parent: QueuedRoleStep, source: str) -> QueuedRoleStep:
        index = len(self.steps)
        item = parent.work_item.model_copy(
            update={
                "id": f"work_history_{role.value}_{index}",
                "role": role,
                "checkpoint_sequence": index,
                "parent_work_item_id": parent.work_item.id,
            }
        )
        step = QueuedRoleStep(
            work_item=item,
            boundary=RoleRunBoundary(item.task_id, role, item.attempt, index, source),
            allocation_sha256=parent.allocation_sha256,
        )
        self.steps[item.id] = step
        return step


def history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, reserved: bool = True) -> History:
    fixture = setup(tmp_path)
    plan = fixture.service.propose(fixture.target)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    item = queued_item().model_copy(
        update={
            "id": plan.facts.work_item_id,
            "task_id": plan.facts.task.id,
            "repository_id": binding.scope.repository_id,
            "repository_scopes": (binding.scope.repository_root,),
            "checkpoint_sequence": plan.facts.checkpoint_sequence,
        }
    )
    original = QueuedRoleStep(
        work_item=item,
        boundary=RoleRunBoundary(
            item.task_id,
            item.role,
            item.attempt,
            item.checkpoint_sequence,
            binding.prior_source_revision,
        ),
        allocation_sha256="a" * 64,
    )
    record = BaselineQueueConsumption(
        task_id=item.task_id,
        work_item_id=item.id,
        next_work_item_id="work_" + binding.binding_sha256 if reserved else item.id,
        prior_step_sha256=record_digest(original),
        plan=plan,
        binding=binding,
    )
    steps = {item.id: original}
    if reserved:
        item = item.model_copy(
            update={"id": record.next_work_item_id, "parent_work_item_id": item.id, "attempt": 2}
        )
        steps[item.id] = QueuedRoleStep(
            work_item=item,
            boundary=RoleRunBoundary(
                item.task_id,
                item.role,
                item.attempt,
                item.checkpoint_sequence,
                binding.execution_source_revision,
            ),
            allocation_sha256=original.allocation_sha256,
        )
    queue = MySqlRoleQueue.__new__(MySqlRoleQueue)

    def original_step(identity: str) -> QueuedRoleStep:
        if identity not in steps:
            raise QueueNotFound(identity)
        return steps[identity]

    monkeypatch.setattr(queue, "original_step", original_step)
    monkeypatch.setattr(baseline, "consumptions", lambda queue, task_id: (record,))
    return History(queue, fixture, plan, record, steps)


@pytest.mark.parametrize("reserved", [True, False])
def test_qa_review_and_feedback_coder_inherit_exact_epoch_without_rewriting_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reserved: bool
) -> None:
    fixture = history(tmp_path, monkeypatch, reserved=reserved)
    prior = fixture.steps[fixture.record.next_work_item_id]
    sources = ("c" * 40, "c" * 40, "c" * 40, "d" * 40, "d" * 40)
    for role, source in zip(
        (AgentRole.QA, AgentRole.REVIEWER, AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER),
        sources,
        strict=True,
    ):
        step = fixture.append(role, prior, source)
        assert (
            fixture.queue.step_for_invocation(
                step.work_item.id, fixture.record.binding.binding_sha256
            )
            == step
        )
        assert step.boundary.source_revision == source
        prior = step


@pytest.mark.parametrize(
    "drift", ["task", "repository", "scopes", "allocation", "missing", "cycle", "unrelated"]
)
def test_inherited_baseline_rejects_broken_or_unrelated_immutable_parent_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    fixture = history(tmp_path, monkeypatch)
    root = fixture.steps[fixture.record.next_work_item_id]
    qa = fixture.append(AgentRole.QA, root, "c" * 40)
    review = fixture.append(AgentRole.REVIEWER, qa, "c" * 40)
    changed = qa
    if drift == "allocation":
        changed = qa.model_copy(update={"allocation_sha256": "f" * 64})
    elif drift == "task":
        changed = qa.model_copy(
            update={
                "work_item": qa.work_item.model_copy(update={"task_id": "task_foreign_001"}),
                "boundary": replace(qa.boundary, task_id="task_foreign_001"),
            }
        )
    else:
        values: dict[str, object] = {
            "repository": {"repository_id": "repository_foreign_001"},
            "scopes": {"repository_scopes": ("/unrelated",)},
            "missing": {"parent_work_item_id": "work_missing_parent_001"},
            "cycle": {"parent_work_item_id": review.work_item.id},
            "unrelated": {"parent_work_item_id": None},
        }.get(drift, {})
        changed = qa.model_copy(update={"work_item": qa.work_item.model_copy(update=values)})
    fixture.steps[qa.work_item.id] = changed
    with pytest.raises(QueueCorruption):
        fixture.queue.step_for_invocation(
            review.work_item.id, fixture.record.binding.binding_sha256
        )


def test_unknown_baseline_digest_cannot_use_a_valid_task_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = history(tmp_path, monkeypatch)
    qa = fixture.append(AgentRole.QA, fixture.steps[fixture.record.next_work_item_id], "c" * 40)
    with pytest.raises(QueueCorruption, match="epoch"):
        fixture.queue.step_for_invocation(qa.work_item.id, "f" * 64)


def test_reserved_baseline_anchor_rejects_changed_source_or_predecessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = history(tmp_path, monkeypatch)
    root = fixture.steps[fixture.record.next_work_item_id]
    qa = fixture.append(AgentRole.QA, root, "c" * 40)
    changed = root.model_copy(update={"boundary": replace(root.boundary, source_revision="e" * 40)})
    fixture.steps[root.work_item.id] = changed
    with pytest.raises(QueueCorruption, match="exact input"):
        fixture.queue.step_for_invocation(qa.work_item.id, fixture.record.binding.binding_sha256)
    fixture.steps[root.work_item.id] = root
    predecessor = fixture.steps[fixture.record.work_item_id]
    fixture.steps[predecessor.work_item.id] = predecessor.model_copy(
        update={"boundary": replace(predecessor.boundary, source_revision="e" * 40)}
    )
    with pytest.raises(QueueCorruption, match="predecessor"):
        fixture.queue.step_for_invocation(qa.work_item.id, fixture.record.binding.binding_sha256)


def test_exact_baseline_anchor_rejects_a_different_checkout_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = history(tmp_path, monkeypatch)
    qa = fixture.append(AgentRole.QA, fixture.steps[fixture.record.next_work_item_id], "c" * 40)
    for identity, step in tuple(fixture.steps.items()):
        fixture.steps[identity] = step.model_copy(
            update={
                "work_item": step.work_item.model_copy(
                    update={"repository_scopes": ("/elsewhere",)}
                )
            }
        )
    with pytest.raises(QueueCorruption, match="scope"):
        fixture.queue.step_for_invocation(qa.work_item.id, fixture.record.binding.binding_sha256)


@pytest.mark.parametrize("reserved", [True, False])
def test_newer_epoch_does_not_reinterpret_old_invocations_or_let_descendants_use_old_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reserved: bool
) -> None:
    fixture = history(tmp_path, monkeypatch, reserved=reserved)
    first = fixture.record
    root = fixture.steps[first.next_work_item_id]
    if reserved:
        old_qa = fixture.append(AgentRole.QA, root, first.binding.execution_source_revision)
        root = fixture.append(AgentRole.CODER, old_qa, first.binding.execution_source_revision)
    before = root.model_copy(
        update={
            "boundary": replace(
                root.boundary, source_revision=first.binding.execution_source_revision
            )
        }
    )
    f = fixture.fixture
    (f.repository / "README.md").write_text("second target prerequisite\n")
    _git(f.repository, "add", "README.md")
    _git(f.repository, "commit", "-m", "second target baseline")
    facts = f.collector.facts.model_copy(
        update={
            "work_item_id": root.work_item.id,
            "checkpoint_sequence": root.work_item.checkpoint_sequence,
            "task": f.collector.facts.task.model_copy(update={"attempts": root.work_item.attempt}),
        }
    )
    f.collector.facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    f.collector.worktree = replace(
        f.collector.worktree, head_revision=_git(f.worktree.path, "rev-parse", "HEAD")
    )
    plan = f.service.propose(_git(f.repository, "rev-parse", "HEAD"))
    binding = f.service.execute(plan.plan_sha256, authority=authorize(plan))
    second = BaselineQueueConsumption(
        task_id=root.work_item.task_id,
        work_item_id=root.work_item.id,
        next_work_item_id="work_" + binding.binding_sha256 if reserved else root.work_item.id,
        prior_step_sha256=record_digest(before),
        plan=plan,
        binding=binding,
    )
    if reserved:
        next_item = root.work_item.model_copy(
            update={
                "id": second.next_work_item_id,
                "attempt": root.work_item.attempt + 1,
                "parent_work_item_id": root.work_item.id,
            }
        )
        root = QueuedRoleStep(
            work_item=next_item,
            boundary=RoleRunBoundary(
                next_item.task_id,
                next_item.role,
                next_item.attempt,
                next_item.checkpoint_sequence,
                binding.execution_source_revision,
            ),
            allocation_sha256=root.allocation_sha256,
        )
        fixture.steps[root.work_item.id] = root
    monkeypatch.setattr(baseline, "consumptions", lambda queue, task_id: (first, second))
    qa = fixture.append(AgentRole.QA, root, "d" * 40)
    assert fixture.queue.step_for_invocation(qa.work_item.id, binding.binding_sha256) == qa
    with pytest.raises(QueueCorruption, match="epoch"):
        fixture.queue.step_for_invocation(qa.work_item.id, first.binding.binding_sha256)
    if reserved:
        assert (
            fixture.queue.step_for_invocation(old_qa.work_item.id, first.binding.binding_sha256)
            == old_qa
        )
    else:
        old = fixture.queue.step_for_invocation(root.work_item.id, first.binding.binding_sha256)
        assert old == before
        latest = fixture.queue.step_for_invocation(root.work_item.id, binding.binding_sha256)
        assert latest.boundary.source_revision == binding.execution_source_revision
        assert fixture.queue.step_for_invocation(root.work_item.id, None) == root
