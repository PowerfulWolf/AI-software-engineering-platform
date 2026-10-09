"""Same-Task native approvals, preserved pauses and inherited immutable rule inputs."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.artifacts import seal_artifact
from ai_software_engineer.domain.artifact import CoderProgressArtifact
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    resolve_coder_execution_input,
)
from ai_software_engineer.domain.execution_native_rules import native_rules_sha256
from ai_software_engineer.manager.baseline_models import BaselineOperatorAuthorization
from ai_software_engineer.manager.baseline_native_rules import build_native_rule_change
from ai_software_engineer.manager.baseline_production import native_rules_at_revision
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.recovery.models import digest
from tests.domain.factories import make_coder_progress_artifact
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
    old_progress = seal_artifact(
        make_coder_progress_artifact().model_copy(
            update={"source_revision": f.worktree.head_revision}
        ),
        validated_at=datetime.now(UTC),
    )
    assert isinstance(old_progress, CoderProgressArtifact)
    values = original.model_copy(
        update={
            "source_native_rules_sha256": native_rules_sha256(old),
            "target_native_rules_sha256": native_rules_sha256(target),
            "native_rule_change": change,
            "progress_artifact_id": old_progress.artifact_id,
            "source_artifact_ids": (*original.source_artifact_ids, old_progress.artifact_id),
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
            "progress_artifact_id": None,
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
    assert binding.superseded_progress_artifact_id == old_progress.artifact_id
    assert next_binding.superseded_progress_artifact_id is None
    continued = resolver.current(original.task, implementation=None, progress=old_progress)
    assert continued.source_revision == next_binding.execution_source_revision
    assert continued.active_progress is None
    assert continued.progress_supersedes == old_progress.artifact_id
    assert old_progress.artifact_id in continued.superseded_artifact_ids
    valid_new = seal_artifact(
        old_progress.model_copy(
            update={
                "artifact_id": "art_progress_new",
                "supersedes": old_progress.artifact_id,
                "source_revision": next_binding.execution_source_revision,
            }
        ),
        validated_at=datetime.now(UTC),
    )
    assert isinstance(valid_new, CoderProgressArtifact)
    assert (
        resolver.current(original.task, implementation=None, progress=valid_new).active_progress
        == valid_new
    )
    unknown_old_source = seal_artifact(
        old_progress.model_copy(update={"artifact_id": "art_progress_unapproved"}),
        validated_at=datetime.now(UTC),
    )
    assert isinstance(unknown_old_source, CoderProgressArtifact)
    with pytest.raises(ValueError, match=r"开发进度.*执行版本不一致"):
        resolver.current(original.task, implementation=None, progress=unknown_old_source)
    foreign = valid_new.model_copy(update={"task_id": "task_foreign"})
    with pytest.raises(ValueError, match="another Task"):
        resolver.current(original.task, implementation=None, progress=foreign)
    with pytest.raises(ValueError, match="predecessor"):
        resolve_coder_execution_input(
            original.task,
            implementation=None,
            progress=old_progress,
            baseline=next_binding,
            baseline_history=(next_binding,),
        )
    with pytest.raises(ValueError, match="最新绑定"):
        resolve_coder_execution_input(
            original.task,
            implementation=None,
            progress=old_progress,
            baseline=binding,
            baseline_history=(binding, next_binding),
        )
