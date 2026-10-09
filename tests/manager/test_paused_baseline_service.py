"""Same-Task native approvals, preserved pauses and inherited immutable rule inputs."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode
from ai_software_engineer.domain.execution_native_rules import native_rules_sha256
from ai_software_engineer.manager.baseline_models import BaselineOperatorAuthorization
from ai_software_engineer.manager.baseline_native_rules import build_native_rule_change
from ai_software_engineer.manager.baseline_production import native_rules_at_revision
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.recovery.models import digest
from tests.git.test_worktree import _git
from tests.manager.test_execution_baseline import setup


def test_exact_native_approval_pauses_and_later_source_update_inherits_rules(
    tmp_path: Path,
) -> None:
    f = setup(tmp_path)
    original = f.collector.facts
    old = native_rules_at_revision(
        f.manager, repository_id=original.scope.repository_id, revision=original.task.base_ref
    )
    target = native_rules_at_revision(
        f.manager, repository_id=original.scope.repository_id, revision=f.target
    )
    change = build_native_rule_change(
        git=f.manager,
        records=f.service.store.records,
        scope=original.scope,
        task_id=original.task.id,
        source_revision=original.task.base_ref,
        target_base_ref=f.target,
        source_rules=old,
        target_rules=target,
    )
    assert change is not None
    values = original.model_copy(
        update={
            "source_native_rules_sha256": native_rules_sha256(old),
            "target_native_rules_sha256": native_rules_sha256(target),
            "native_rule_change": change,
        }
    )
    f.collector.facts = values.model_copy(
        update={"facts_sha256": digest(values.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    plan = f.service.propose(f.target)
    for wrong in (None, "f" * 64):
        with pytest.raises(ValueError, match="项目规范"):
            BaselineOperatorAuthorization.for_plan(
                plan,
                principal=LocalOperatorPrincipal.trusted_local(),
                reference="wrong rules",
                submitted_at=datetime.now(UTC),
                continuation_mode=BaselineContinuationMode.PAUSE,
                approved_native_rule_change_sha256=wrong,
            )
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="reviewed full rules",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        approved_native_rule_change_sha256=change.change_sha256,
    )
    binding = f.service.execute(plan.plan_sha256, authority=authority)
    assert binding.continuation_mode is BaselineContinuationMode.PAUSE
    assert binding.native_rule_epoch_sha256 == change.target.epoch_sha256
    epoch = f.service.store.native_rule_epoch(change.target.epoch_sha256)
    assert epoch.inspect_change("README.md").after_body is not None
    resolver = StoredCoderExecutionInputResolver(f.service.store)
    source = resolver.current(original.task, implementation=None, progress=None)
    assert resolver.native_rule_epoch(source) == epoch
    assert original.task.base_ref == binding.approved_base_ref

    (f.repository / "tooling.txt").write_text("next source, identical rules\n")
    _git(f.repository, "add", "tooling.txt")
    _git(f.repository, "commit", "-m", "next source")
    newer = _git(f.repository, "rev-parse", "HEAD")
    f.collector.worktree = replace(f.worktree, head_revision=binding.execution_source_revision)
    values = f.collector.facts.model_copy(
        update={
            "native_rule_change": None,
            "source_native_rules_sha256": native_rules_sha256(target),
            "implementation_artifact_id": None,
        }
    )
    f.collector.facts = values.model_copy(
        update={"facts_sha256": digest(values.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    next_plan = f.service.propose(newer)
    refused = BaselineOperatorAuthorization.for_plan(
        next_plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="must remain paused",
        submitted_at=datetime.now(UTC),
    )
    head = _git(f.worktree.path, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="保持暂停"):
        f.service.execute(next_plan.plan_sha256, authority=refused)
    assert _git(f.worktree.path, "rev-parse", "HEAD") == head
    assert f.service.store.start(next_plan.plan_sha256) is None
    assert (
        f.service.store.records.find(
            "baseline-authorities", next_plan.plan_sha256, BaselineOperatorAuthorization
        )
        is None
    )
    paused = BaselineOperatorAuthorization.for_plan(
        next_plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="keep paused",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    next_binding = f.service.execute(next_plan.plan_sha256, authority=paused)
    assert next_binding.native_rule_epoch_sha256 == binding.native_rule_epoch_sha256
    assert next_binding.approved_base_ref == original.task.base_ref
    assert next_binding.branch_name == binding.branch_name
    source = resolver.current(original.task, implementation=None, progress=None)
    assert resolver.native_rule_epoch(source) == epoch
    assert len(f.service.store.bindings_for_task(original.task.id)) == 2
