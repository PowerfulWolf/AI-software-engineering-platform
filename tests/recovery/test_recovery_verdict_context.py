"""Sealed verifier remediation survives interrupted Coder recovery generations."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import (
    ContextBudget,
    ContextBudgetExceeded,
    ContextSource,
    FileContextBuilder,
    FileContextStore,
)
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.artifact import Finding
from ai_software_engineer.domain.enums import FindingSeverity, ReviewVerdict
from ai_software_engineer.orchestration import FileRunContextBuilder
from ai_software_engineer.recovery.context import (
    preserved_native_verdict_context,
    preserved_verification_context,
)
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryPlan, RecoveryRejected
from ai_software_engineer.recovery.store import FileRecoveryStore
from tests.domain.factories import make_review_artifact, make_task
from tests.orchestration.test_runner import _definitions
from tests.recovery.test_authorization import make_plan
from tests.recovery.test_verification_environment import _admitted


def _failed_coder_context(
    tmp_path: Path, *, verified: bool = False, source_update: dict[str, object] | None = None
) -> tuple[RecoveryPlan, FileContextStore, FileRecoveryStore, ContextSource]:
    verification, store, _, _, completion = _admitted(tmp_path, business_failure=not verified)
    task = make_task().model_copy(update={"id": "task_original"})
    source = ContextSource(
        source_id="remediation.verification",
        uri=f"candidate-verification://{verification.scope.delivery_id}/{completion.evidence_sha256}",
        content=json.dumps(completion.to_wire(), ensure_ascii=False, sort_keys=True),
        priority=2,
        required=True,
    )
    if source_update:
        source = ContextSource.model_validate({**source.to_wire(), **source_update})
    original = make_plan(Path(verification.scope.repository_root))
    context = FileContextBuilder(
        verification.scope.repository_root, original.permissions, sources=(source,)
    ).build(task, AgentRole.CODER, attempt=1)
    contexts = FileContextStore(tmp_path / "recovery-contexts")
    contexts.put(context)
    plan = RecoveryPlan.create(
        **{
            **original.to_wire(),
            "source": original.source.model_copy(
                update={"scope": verification.scope, "failed_context_id": context.context_id}
            ),
        }
    )
    return plan, contexts, store, source


def test_failed_coder_recovery_preserves_exact_verifier_failure_across_generations(
    tmp_path: Path,
) -> None:
    plan, contexts, store, source = _failed_coder_context(tmp_path)
    prior_path = tmp_path / "recovery-contexts" / f"{plan.source.failed_context_id}.json"
    prior_bytes = prior_path.read_bytes()
    reopened = FileRecoveryStore(tmp_path / "verification", scope=plan.source.scope)
    preserved = preserved_verification_context(plan, contexts, reopened)
    assert preserved == (source,)
    task = make_task().model_copy(update={"id": plan.new_task_id})
    root = plan.source.scope.repository_root
    successor = FileContextBuilder(root, plan.permissions, sources=preserved).build(
        task, AgentRole.CODER, attempt=1
    )
    contexts.put(successor)
    section = next(s for s in successor.sections if s.name == "source:remediation.verification")
    assert section.content == source.content
    assert not section.truncated
    captured = plan.capture.to_capture()
    captured = replace(
        captured,
        worktree=replace(captured.worktree, task_id=task.id, branch=f"ai/{task.id}/attempt-1"),
    )
    again = RecoveryPlan.create(
        **{
            **plan.to_wire(),
            "capture": CapturedChanges.from_capture(captured),
            "source": plan.source.model_copy(
                update={"task_id": task.id, "failed_context_id": successor.context_id}
            ),
        }
    )
    assert preserved_verification_context(again, contexts, reopened) == preserved
    assert prior_path.read_bytes() == prior_bytes
    assert store.get_verification_completion(json.loads(source.content or "{}")["plan_sha256"])
    with pytest.raises(RecoveryRejected, match="missing"):
        preserved_verification_context(plan, contexts, None)
    with pytest.raises(ContextBudgetExceeded):
        FileContextBuilder(
            root,
            plan.permissions,
            sources=preserved,
            budget=ContextBudget(max_input_tokens=100, reserved_output_tokens=1),
        ).build(task, AgentRole.CODER, attempt=1)


@pytest.mark.parametrize(
    "bad", ["wrong_uri", "wrong_body", "foreign_scope", "verified", "stored_tamper"]
)
def test_recovery_verifier_source_rejects_substitution_and_tampering(
    tmp_path: Path, bad: str
) -> None:
    update = (
        {"uri": "candidate-verification://delivery_foreign/" + "e" * 64}
        if bad == "wrong_uri"
        else None
    )
    if bad == "wrong_body":
        update = {"content": "{}"}
    plan, contexts, store, _ = _failed_coder_context(
        tmp_path, verified=bad == "verified", source_update=update
    )
    if bad == "foreign_scope":
        plan = RecoveryPlan.create(
            **{
                **plan.to_wire(),
                "source": plan.source.model_copy(
                    update={
                        "scope": plan.source.scope.model_copy(
                            update={"delivery_id": "delivery_other"}
                        )
                    }
                ),
            }
        )
    if bad == "stored_tamper":
        path = next((tmp_path / "verification").glob("verification-completion-*.json"))
        path.write_text("{}")
    with pytest.raises((RecoveryRejected, ValueError)):
        preserved_verification_context(plan, contexts, store)


@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
def test_native_failed_verdict_feedback_survives_serial_recovery(
    tmp_path: Path, role: AgentRole
) -> None:
    verification, _, _, _, completion = _admitted(tmp_path, business_failure=True)
    root = Path(verification.scope.repository_root)
    task = make_task().model_copy(update={"id": completion.qa.task_id})
    report = completion.qa
    if role is AgentRole.REVIEWER:
        template = make_review_artifact()
        review = template.model_copy(
            update={
                "task_id": task.id,
                "source_revision": completion.qa.source_revision,
                "parent_artifact_ids": (completion.qa.artifact_id,),
                "content": template.content.model_copy(
                    update={
                        "verdict": ReviewVerdict.REJECT,
                        "findings": (
                            Finding(
                                finding_id="finding_review_recovery",
                                severity=FindingSeverity.MAJOR,
                                message="Preserve rejected review feedback across new Tasks.",
                                evidence_ids=template.content.evidence,
                            ),
                        ),
                    }
                ),
            }
        )
        report = seal_artifact(review, validated_at=review.created_at)
        FileArtifactStore(tmp_path / "artifacts").put(report)
    native = FileRunContextBuilder._artifact_sources(
        task, _definitions()[AgentRole.CODER], (report,)
    )
    original = make_plan(root)
    contexts = FileContextStore(tmp_path / "feedback-contexts")
    manifest = FileContextBuilder(root, original.permissions, sources=native).build(
        task, AgentRole.CODER, attempt=1
    )
    contexts.put(manifest)
    prior_path = tmp_path / "feedback-contexts" / f"{manifest.context_id}.json"
    prior_bytes = prior_path.read_bytes()
    captured = original.capture.to_capture()
    captured = replace(
        captured,
        worktree=replace(captured.worktree, task_id=task.id, branch=f"ai/{task.id}/attempt-1"),
    )
    plan = RecoveryPlan.create(
        **{
            **original.to_wire(),
            "capture": CapturedChanges.from_capture(captured),
            "source": original.source.model_copy(
                update={
                    "scope": verification.scope,
                    "task_id": task.id,
                    "failed_context_id": manifest.context_id,
                }
            ),
        }
    )
    artifacts = FileArtifactStore(tmp_path / "artifacts", read_only=True)
    (feedback,) = preserved_native_verdict_context(plan, contexts, artifacts)
    assert feedback.required and feedback.roles == (AgentRole.CODER,)
    assert feedback.uri == native[0].uri
    assert feedback.content == native[0].content
    assert preserved_verification_context(plan, contexts, None) == ()
    successor_task = task.model_copy(update={"id": plan.new_task_id})
    successor = FileContextBuilder(root, plan.permissions, sources=(feedback,)).build(
        successor_task, AgentRole.CODER, attempt=1
    )
    contexts.put(successor)
    successor_capture = replace(
        captured,
        worktree=replace(
            captured.worktree,
            task_id=successor_task.id,
            branch=f"ai/{successor_task.id}/attempt-1",
        ),
    )
    again = RecoveryPlan.create(
        **{
            **plan.to_wire(),
            "capture": CapturedChanges.from_capture(successor_capture),
            "source": plan.source.model_copy(
                update={
                    "task_id": successor_task.id,
                    "failed_context_id": successor.context_id,
                }
            ),
        }
    )
    assert preserved_native_verdict_context(again, contexts, artifacts) == (feedback,)
    assert prior_path.read_bytes() == prior_bytes
    empty = FileContextBuilder(root, plan.permissions).build(task, AgentRole.CODER, attempt=3)
    contexts.put(empty)
    ordinary = RecoveryPlan.create(
        **{
            **plan.to_wire(),
            "source": plan.source.model_copy(update={"failed_context_id": empty.context_id}),
        }
    )
    assert preserved_native_verdict_context(ordinary, contexts, artifacts) == ()
