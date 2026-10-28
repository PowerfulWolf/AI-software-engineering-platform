"""A contained start-only UNKNOWN is a separate, exact recovery source."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.models import RecoveryPlan, RecoverySource
from tests.recovery.test_authorization import make_plan


def contained_plan(tmp_path: Path) -> RecoveryPlan:
    old = make_plan(tmp_path / "project")
    return RecoveryPlan.create(
        **{
            **old.to_wire(),
            "input_mode": "coder_reapply",
            "source": {
                **old.source.to_wire(),
                "contained_unknown_settlement_sha256": "d" * 64,
            },
        }
    )


def test_contained_unknown_source_keeps_the_real_run_and_ordinary_historical_wire(
    tmp_path: Path,
) -> None:
    old = make_plan(tmp_path / "old")
    assert "contained_unknown_settlement_sha256" not in old.source.to_wire()
    assert RecoveryPlan.model_validate(old.to_wire()) == old
    plan = contained_plan(tmp_path)
    assert plan.source.failed_run_id == old.source.failed_run_id
    assert plan.plan_sha256 != old.plan_sha256
    assert RecoveryPlan.model_validate(plan.to_wire()) == plan
    for changes in (
        {"failed_run_id": None},
        {"context_capacity_receipt_sha256": "e" * 64},
        {"stopped_unknown_settlement_sha256": "e" * 64},
        {"contained_unknown_settlement_sha256": "bad-digest"},
    ):
        with pytest.raises(ValidationError):
            RecoverySource.model_validate({**plan.source.to_wire(), **changes})


@pytest.mark.parametrize("change", ("mode", "snapshot", "scope"))
def test_contained_unknown_plan_rejects_incompatible_recovery_modes(
    tmp_path: Path, change: str
) -> None:
    plan = contained_plan(tmp_path)
    changes: dict[str, object] = {"input_mode": None}
    if change == "snapshot":
        # Start-only execution has neither outcome nor stop, so an ordinary
        # terminal snapshot cannot be inferred from its containment.
        changes = {"context_capacity_input": {}}
    elif change == "scope":
        changes = {"scope_approval_reference": "unbound-scope-expansion"}
    with pytest.raises(ValidationError):
        RecoveryPlan.create(**{**plan.to_wire(), **changes})


def test_current_source_routes_contained_unknown_to_its_exact_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.recovery.contained_unknown import ContainedUnknownRecoverySourceReader

    plan = contained_plan(tmp_path)
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    verifier = NativeRecoveryFactsVerifier(config, {})
    original = Mock(source=plan.source, denied_paths=plan.denied_paths)
    exact = Mock(return_value=original)
    monkeypatch.setattr(ContainedUnknownRecoverySourceReader, "inspect", exact)
    monkeypatch.setattr(
        verifier._source,
        "inspect",
        Mock(side_effect=AssertionError("contained unknown used failed-route reader")),
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.inherited_input.read_inherited_reapply_inputs",
        Mock(return_value=None),
    )
    assert verifier._read_source(plan) is original
    exact.assert_called_once_with(plan.source.scope, "d" * 64)
    assert not Path(config.platform_root).exists()


def test_contained_unknown_reader_missing_environment_never_initializes_stores(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.recovery.contained_unknown import ContainedUnknownRecoverySourceReader
    from ai_software_engineer.recovery.models import RecoveryRejected

    plan = contained_plan(tmp_path)
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    reader = ContainedUnknownRecoverySourceReader(config, {})
    with pytest.raises(RecoveryRejected):
        reader.discover(plan.source.scope)
    with pytest.raises(RecoveryRejected):
        reader.inspect(plan.source.scope, "Bearer " + "x" * 30)
    assert not Path(config.platform_root).exists()


def test_settled_unknown_after_qa_feedback_routes_to_coder_before_old_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.domain import TaskStatus
    from ai_software_engineer.manager.delivery import ProjectDeliveryResult, ResumeProjectDelivery
    from ai_software_engineer.manager.delivery_checkpoint import (
        DeliveryFailureCode,
        DeliveryStage,
    )
    from ai_software_engineer.recovery.contained_unknown import CONTAINED_UNKNOWN_BUDGET_SUMMARY
    from ai_software_engineer.recovery.resume import (
        DeliveryResumeController,
        DeliveryResumeOutcome,
        DeliveryResumeResult,
    )
    from tests.e2e.test_delivery_checkpoint import _checkpoint, _full_fields

    checkpoint = _checkpoint(
        tmp_path,
        **{
            **_full_fields(),
            "stage": DeliveryStage.BLOCKED,
            "task_status": TaskStatus.BLOCKED,
            "failed_stage": DeliveryStage.DELIVERING,
            "failure_code": DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED,
            "failure_summary": CONTAINED_UNKNOWN_BUDGET_SUMMARY,
        },
    )
    entry = Mock()
    entry.status.return_value = ProjectDeliveryResult(checkpoint=checkpoint)
    verification = Mock()
    verification.latest_project.return_value = None
    verification.propose_project.side_effect = AssertionError(
        "historical QA candidate cannot replace the settled Coder recovery"
    )
    controller = DeliveryResumeController(
        config=ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            model_routes=(
                ProviderRouteConfig(
                    provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        ),
        environment={},
        backend=Mock(),
        entry=entry,
        recovery=Mock(),
        verification=verification,
    )
    expected = DeliveryResumeResult(
        outcome=DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED,
        checkpoint=checkpoint,
        next_action="Approve the exact retained Coder recovery plan.",
        recovery_plan_sha256="d" * 64,
    )
    coder = Mock(return_value=expected)
    monkeypatch.setattr(controller, "_continue_coder_recovery", coder)

    command = ResumeProjectDelivery(delivery_id=checkpoint.delivery_id)
    assert controller.resume(command) == expected
    coder.assert_called_once_with(checkpoint, command)
    verification.propose_project.assert_not_called()


def test_contained_unknown_candidate_lineage_requires_feedback_and_exact_projection(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.domain import AgentRole, TaskStatus
    from ai_software_engineer.domain.enums import QaReportStatus
    from ai_software_engineer.domain.event import StateEvent
    from ai_software_engineer.recovery.contained_unknown import (
        require_contained_unknown_candidate_lineage,
    )
    from tests.domain.factories import make_implementation_artifact, make_qa_artifact
    from tests.manager.test_dispatch import RecordingDispatchStore, _facts, _service

    request, workforce = _facts(tmp_path)
    dispatch = _service(RecordingDispatchStore(), workforce, request).commit_dispatch(request)
    task = dispatch.task.model_copy(update={"status": TaskStatus.BLOCKED, "attempts": 1})
    candidate_revision = "b" * 40
    candidate = StateEvent(
        event_id="evt_unknown_prior_candidate",
        task_id=task.id,
        from_status=TaskStatus.IMPLEMENTING,
        to_status=TaskStatus.QA,
        actor=AgentRole.ORCHESTRATOR,
        reason="candidate_ready",
        artifact_ids=("art_impl_001",),
        source_revision=candidate_revision,
        occurred_at=task.updated_at,
    )
    feedback = StateEvent(
        event_id="evt_unknown_prior_feedback",
        task_id=task.id,
        from_status=TaskStatus.QA,
        to_status=TaskStatus.IMPLEMENTING,
        actor=AgentRole.ORCHESTRATOR,
        reason="qa_failed_route_to_coder",
        artifact_ids=("art_qa_001",),
        source_revision=candidate_revision,
        occurred_at=task.updated_at,
    )
    terminal = StateEvent(
        event_id="evt_unknown_last_coder",
        task_id=task.id,
        from_status=TaskStatus.IMPLEMENTING,
        to_status=TaskStatus.BLOCKED,
        actor=AgentRole.ORCHESTRATOR,
        reason="fixture stopped UNKNOWN",
        artifact_ids=(),
        source_revision=candidate_revision,
        occurred_at=task.updated_at,
    )
    events = (candidate, feedback, terminal)
    implementation = make_implementation_artifact().model_copy(
        update={
            "task_id": task.id,
            "source_revision": candidate_revision,
            "content": make_implementation_artifact().content.model_copy(
                update={"commit_sha": candidate_revision}
            ),
        }
    )
    qa = make_qa_artifact().model_copy(
        update={
            "task_id": task.id,
            "source_revision": candidate_revision,
            "content": make_qa_artifact().content.model_copy(
                update={"status": QaReportStatus.FAIL}
            ),
        }
    )
    artifact_map = {implementation.artifact_id: implementation, qa.artifact_id: qa}
    artifacts = Mock()
    artifacts.get.side_effect = artifact_map.__getitem__
    require_contained_unknown_candidate_lineage(candidate_revision, task, events, artifacts)
    require_contained_unknown_candidate_lineage(None, task, events, artifacts)

    for projected, history in (
        ("c" * 40, events),
        (candidate_revision, (candidate, terminal)),
        (
            candidate_revision,
            (candidate, feedback.model_copy(update={"artifact_ids": ()}), terminal),
        ),
        (
            candidate_revision,
            (candidate, feedback.model_copy(update={"reason": "other"}), terminal),
        ),
    ):
        with pytest.raises(ValueError, match="candidate"):
            require_contained_unknown_candidate_lineage(projected, task, history, artifacts)
    for changed in (
        qa.model_copy(update={"task_id": "task_foreign"}),
        qa.model_copy(update={"source_revision": "c" * 40}),
        qa.model_copy(
            update={"content": qa.content.model_copy(update={"status": QaReportStatus.PASS})}
        ),
        qa.model_copy(update={"parent_artifact_ids": ("art_foreign",)}),
    ):
        artifacts.get.side_effect = {
            implementation.artifact_id: implementation,
            qa.artifact_id: changed,
        }.__getitem__
        with pytest.raises(ValueError, match="candidate"):
            require_contained_unknown_candidate_lineage(candidate_revision, task, events, artifacts)
    require_contained_unknown_candidate_lineage(None, task, (terminal,), artifacts)

    # A retry can supersede an earlier sealed QA report from another candidate.
    prior_revision = "c" * 40
    prior_implementation = implementation.model_copy(
        update={
            "artifact_id": "art_impl_previous",
            "source_revision": prior_revision,
            "content": implementation.content.model_copy(update={"commit_sha": prior_revision}),
            "producer": implementation.producer.model_copy(update={"run_id": "run_impl_previous"}),
        }
    )
    prior_qa = qa.model_copy(
        update={
            "artifact_id": "art_qa_previous",
            "source_revision": prior_revision,
            "parent_artifact_ids": (prior_implementation.artifact_id,),
            "producer": qa.producer.model_copy(update={"run_id": "run_qa_previous"}),
        }
    )
    current_qa = qa.model_copy(update={"supersedes": prior_qa.artifact_id})
    artifact_map = {
        implementation.artifact_id: implementation,
        current_qa.artifact_id: current_qa,
        prior_qa.artifact_id: prior_qa,
        prior_implementation.artifact_id: prior_implementation,
    }
    artifacts.get.side_effect = artifact_map.__getitem__
    require_contained_unknown_candidate_lineage(None, task, events, artifacts)
    artifact_map["art_impl_foreign"] = prior_implementation.model_copy(
        update={"artifact_id": "art_impl_foreign", "task_id": "task_foreign"}
    )
    for predecessor in (
        prior_qa.model_copy(update={"task_id": "task_foreign"}),
        prior_qa.model_copy(update={"producer": qa.producer}),
        prior_qa.model_copy(update={"parent_artifact_ids": ("art_impl_foreign",)}),
    ):
        artifact_map[prior_qa.artifact_id] = predecessor
        with pytest.raises(ValueError, match=r"candidate|feedback"):
            require_contained_unknown_candidate_lineage(None, task, events, artifacts)


def test_contained_unknown_review_feedback_requires_sealed_reject(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.domain import AgentRole, TaskStatus
    from ai_software_engineer.domain.enums import ReviewVerdict
    from ai_software_engineer.domain.event import StateEvent
    from ai_software_engineer.recovery.contained_unknown import (
        require_contained_unknown_candidate_lineage,
    )
    from tests.domain.factories import (
        make_implementation_artifact,
        make_qa_artifact,
        make_review_artifact,
    )
    from tests.manager.test_dispatch import RecordingDispatchStore, _facts, _service

    request, workforce = _facts(tmp_path)
    dispatch = _service(RecordingDispatchStore(), workforce, request).commit_dispatch(request)
    task = dispatch.task.model_copy(update={"status": TaskStatus.BLOCKED, "attempts": 1})
    revision = "b" * 40
    implementation = make_implementation_artifact().model_copy(
        update={
            "task_id": task.id,
            "source_revision": revision,
            "content": make_implementation_artifact().content.model_copy(
                update={"commit_sha": revision}
            ),
        }
    )
    qa = make_qa_artifact().model_copy(update={"task_id": task.id, "source_revision": revision})
    review = make_review_artifact().model_copy(
        update={
            "task_id": task.id,
            "source_revision": revision,
            "content": make_review_artifact().content.model_copy(
                update={"verdict": ReviewVerdict.REJECT}
            ),
        }
    )
    artifacts = Mock()
    artifact_map = {a.artifact_id: a for a in (implementation, qa, review)}
    artifacts.get.side_effect = artifact_map.__getitem__
    candidate = StateEvent(
        event_id="evt_prior_candidate_review",
        task_id=task.id,
        from_status=TaskStatus.IMPLEMENTING,
        to_status=TaskStatus.QA,
        actor=AgentRole.ORCHESTRATOR,
        reason="candidate_ready",
        artifact_ids=(implementation.artifact_id,),
        source_revision=revision,
        occurred_at=task.updated_at,
    )
    qa_pass = candidate.model_copy(
        update={
            "event_id": "evt_prior_qa_pass",
            "from_status": TaskStatus.QA,
            "to_status": TaskStatus.REVIEW,
            "reason": "qa_passed",
            "artifact_ids": (qa.artifact_id,),
        }
    )
    feedback = candidate.model_copy(
        update={
            "event_id": "evt_prior_review_reject",
            "from_status": TaskStatus.REVIEW,
            "to_status": TaskStatus.IMPLEMENTING,
            "reason": "review_rejected_route_to_coder",
            "artifact_ids": (review.artifact_id,),
        }
    )
    terminal = candidate.model_copy(
        update={
            "event_id": "evt_last_unknown_after_review",
            "from_status": TaskStatus.IMPLEMENTING,
            "to_status": TaskStatus.BLOCKED,
            "reason": "fixture stopped UNKNOWN",
            "artifact_ids": (),
        }
    )
    events = (candidate, qa_pass, feedback, terminal)
    require_contained_unknown_candidate_lineage(None, task, events, artifacts)
    prior_review = review.model_copy(
        update={
            "artifact_id": "art_review_previous",
            "supersedes": None,
            "producer": review.producer.model_copy(update={"run_id": "run_review_previous"}),
        }
    )
    artifact_map[prior_review.artifact_id] = prior_review
    artifact_map[review.artifact_id] = review.model_copy(
        update={"supersedes": prior_review.artifact_id}
    )
    require_contained_unknown_candidate_lineage(None, task, events, artifacts)
    artifact_map[review.artifact_id] = review.model_copy(
        update={"content": review.content.model_copy(update={"verdict": ReviewVerdict.APPROVE})}
    )
    with pytest.raises(ValueError, match="candidate"):
        require_contained_unknown_candidate_lineage(None, task, events, artifacts)


def test_contained_unknown_complete_recovery_capture_cannot_drop_or_change_draft(
    tmp_path: Path,
) -> None:
    from dataclasses import replace
    from types import SimpleNamespace
    from typing import cast

    from ai_software_engineer.git.capture import WorktreeChangeCapture
    from ai_software_engineer.git.mutation_capture import (
        FileMutationCapture,
        MutationTextBody,
        WorktreeMutationCapture,
    )
    from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
    from ai_software_engineer.recovery.contained_unknown import require_contained_unknown_capture
    from ai_software_engineer.recovery.models import CapturedChanges, RecoveryRejected
    from ai_software_engineer.recovery.native import NativeRecoverySource

    plan = contained_plan(tmp_path)
    worktree = plan.capture.to_capture().worktree
    body = MutationTextBody("complete stopped work\n", 0o644)
    patch = b"diff --git a/src/app.py b/src/app.py\n+complete stopped work\n"
    mutation = CapturedMutations.from_capture(
        WorktreeMutationCapture(
            worktree=worktree,
            patch=patch,
            index_diff_sha256="a" * 64,
            mutations=(FileMutationCapture("src/app.py", None, body),),
        )
    )
    original = cast(
        NativeRecoverySource,
        SimpleNamespace(contained_unknown_capture=mutation, source=plan.source),
    )
    captured = CapturedChanges.from_capture(
        WorktreeChangeCapture(
            worktree=worktree,
            patch=patch,
            index_diff_sha256="a" * 64,
            file_sha256s=(("src/app.py", body.sha256),),
            base_revision=plan.source.effective_base_revision,
        )
    )
    current = CapturedChanges.from_capture(replace(captured.to_capture(), base_revision=None))
    require_contained_unknown_capture(original, captured, current)
    for changed in (
        replace(current.to_capture(), patch=b""),
        replace(current.to_capture(), file_sha256s=()),
        replace(current.to_capture(), index_diff_sha256="b" * 64),
        replace(
            current.to_capture(),
            worktree=replace(worktree, head_revision="c" * 40),
        ),
    ):
        with pytest.raises(RecoveryRejected):
            require_contained_unknown_capture(
                original, captured, CapturedChanges.from_capture(changed)
            )
    for changed in (
        replace(captured.to_capture(), file_sha256s=()),
        replace(captured.to_capture(), base_revision="c" * 40),
    ):
        with pytest.raises(RecoveryRejected):
            require_contained_unknown_capture(
                original, CapturedChanges.from_capture(changed), current
            )


@pytest.mark.parametrize("final_state", ("clean", "dirty", "restore_base"))
def test_contained_unknown_keeps_committed_history_separate_from_final_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_state: str
) -> None:
    """Real Git: last UNKNOWN Run may be clean after earlier Coder commits."""
    import subprocess
    from dataclasses import replace
    from types import SimpleNamespace
    from typing import cast

    from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
    from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
    from ai_software_engineer.git.worktree import WorktreeCaptureRejected
    from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
    from ai_software_engineer.recovery.contained_unknown import require_contained_unknown_capture
    from ai_software_engineer.recovery.models import CapturedChanges, RecoveryRejected
    from ai_software_engineer.recovery.native import NativeRecoverySource

    def git(root: Path, *args: str) -> str:
        return subprocess.run(
            ("git", *args), cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()

    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "--initial-branch=main")
    git(repository, "config", "user.name", "Fixture")
    git(repository, "config", "user.email", "fixture@example.invalid")
    source = repository / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 'base'\n")
    git(repository, "add", "src/app.py")
    git(repository, "commit", "-m", "base")
    base_revision = git(repository, "rev-parse", "HEAD")
    manager = GitWorktreeManager(repository, tmp_path / "roles")
    worktree = manager.create(
        WorktreeSpec(
            task_id="task_contained_unknown_capture",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=base_revision,
        )
    )
    permissions = AgentPermissions(
        read_paths=("src/**",),
        write_paths=("src/**",),
        commands=(),
        network=NetworkAccess.NONE,
    )
    (worktree.path / "src/app.py").write_text("value = 'committed'\n")
    git(worktree.path, "add", "src/app.py")
    git(worktree.path, "commit", "-m", "earlier Coder progress")
    worktree = replace(worktree, head_revision=git(worktree.path, "rev-parse", "HEAD"))
    if final_state == "dirty":
        (worktree.path / "src/app.py").write_text("value = 'last stopped draft'\n")
    elif final_state == "restore_base":
        (worktree.path / "src/app.py").write_text("value = 'base'\n")

    retained = CapturedMutations.from_capture(manager.capture_mutations(worktree, permissions))
    if final_state == "restore_base":
        # The net Task-base diff omits this file while the index still carries
        # an earlier committed version. The capture gate refuses to omit it.
        with pytest.raises(WorktreeCaptureRejected, match="index-only changes"):
            manager.capture_legacy_changes(worktree, permissions, base_revision=base_revision)
        return
    full = CapturedChanges.from_capture(
        manager.capture_legacy_changes(worktree, permissions, base_revision=base_revision)
    )
    current = CapturedChanges.from_capture(manager.capture_legacy_changes(worktree, permissions))
    original = cast(
        NativeRecoverySource,
        SimpleNamespace(
            source=SimpleNamespace(
                effective_base_revision=base_revision,
                stopped_unknown_settlement_sha256=None,
                contained_unknown_settlement_sha256="d" * 64,
            ),
            contained_unknown_capture=retained,
            denied_paths=(),
        ),
    )
    require_contained_unknown_capture(original, full, current)
    assert full.patch != current.patch
    assert full.files
    if final_state == "dirty":
        assert current.files
    else:
        assert current.files == ()
    manager.verify_legacy_capture(full.to_capture(), permissions)
    manager.verify_legacy_capture(current.to_capture(), permissions)

    # Exercise the current-facts composition, not merely its capture helper:
    # it must observe final-Run dirt separately while verifying the complete
    # Task-base patch before an approval or execution may continue.
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    verifier = NativeRecoveryFactsVerifier(config, {})
    target = SimpleNamespace(manager=manager)
    facts = object()
    monkeypatch.setattr(verifier, "_read_source", lambda _plan: original)
    monkeypatch.setattr(verifier, "_target_preflight", lambda _plan, _original: target)
    monkeypatch.setattr(verifier, "_target_facts", lambda _plan, _target: facts)
    plan = cast(
        RecoveryPlan,
        SimpleNamespace(source=original.source, capture=full, permissions=permissions),
    )
    assert verifier._inspect(plan) is facts

    # A later writer cannot turn a settled UNKNOWN proof into another draft.
    (worktree.path / "src/app.py").write_text("value = 'later writer'\n")
    changed = CapturedChanges.from_capture(manager.capture_legacy_changes(worktree, permissions))
    with pytest.raises(RecoveryRejected, match="完整未知结果开发草稿"):
        require_contained_unknown_capture(original, full, changed)
    with pytest.raises(RecoveryRejected, match="完整未知结果开发草稿"):
        verifier._inspect(plan)
