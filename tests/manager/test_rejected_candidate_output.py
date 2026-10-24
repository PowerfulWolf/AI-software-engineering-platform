"""Pure historical rescue contracts; synthetic wire facts grant no real authority."""

from dataclasses import dataclass, replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    ChangedFile,
    ChangeType,
    NetworkAccess,
    Task,
    TaskStatus,
)
from ai_software_engineer.domain.artifact import ImplementationReportArtifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.git.mutation import MutationFile, WorkspaceMutationInventory
from ai_software_engineer.git.mutation_capture import (
    FileMutationCapture,
    MutationTextBody,
    WorktreeMutationCapture,
)
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.rejected_candidate_output import (
    RejectedCandidateOutputProof,
    validate_rejected_candidate_inventory,
)
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationScope,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.owned_sessions import OwnedProcessIdentity, OwnedSessionStopProof
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from tests.domain.factories import make_implementation_artifact, make_task
from tests.orchestration.test_native_continuation import NOW, claim

BASE = "a" * 40
CANDIDATE = "b" * 40
PATH = "src/app.py"
PATCH = (
    b"diff --git a/src/app.py b/src/app.py\n"
    b"--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n"
)


def _file(path: str, text: str) -> MutationFile:
    body = text.encode()
    return MutationFile(path, "file", sha256(body).hexdigest(), 0o644, len(body))


def _outcome(start: DeliveryInvocationStart, result: AgentResult) -> DeliveryInvocationOutcome:
    value = DeliveryInvocationOutcome(start=start, result=result, outcome_sha256="0" * 64)
    return value.model_copy(
        update={"outcome_sha256": digest(value.model_dump(mode="json", exclude={"outcome_sha256"}))}
    )


@dataclass(frozen=True)
class RejectedCandidateFixture:
    proof: RejectedCandidateOutputProof

    @property
    def task(self) -> Task:
        return self.proof.task

    @property
    def step(self) -> QueuedRoleStep:
        return self.proof.step

    @property
    def scope(self) -> EngineeringScope:
        return self.proof.scope

    def create(self, **changes: object) -> RejectedCandidateOutputProof:
        return RejectedCandidateOutputProof.create(
            **{**self.proof.model_dump(mode="python", exclude={"proof_sha256"}), **changes}
        )


@pytest.fixture
def rejected_candidate_proof_fixture() -> RejectedCandidateFixture:
    """Reusable pure fixture; production collectors must supply real observed facts."""
    template = make_task()
    task = template.model_copy(
        update={"base_ref": BASE, "attempts": 1, "status": TaskStatus.IMPLEMENTING}
    )
    permissions = AgentPermissions(
        read_paths=("**",),
        write_paths=("src/**",),
        commands=("pytest",),
        network=NetworkAccess.NONE,
    )
    request = AgentRequest(
        task_id=task.id,
        run_id="run_rejected_candidate_001",
        role=AgentRole.CODER,
        attempt=1,
        source_revision=BASE,
        context_manifest_id="ctx_" + "1" * 64,
        input_artifact_ids=("art_plan_001",),
        permissions=permissions,
        output_schema="schemas/coder-output.schema.json",
        timeout_seconds=600,
    )
    original = claim(task, 1)
    original = original.model_copy(
        update={"work_item": original.work_item.model_copy(update={"checkpoint_sequence": 2})}
    )
    step = QueuedRoleStep(
        work_item=original.work_item,
        boundary=RoleRunBoundary(task.id, AgentRole.CODER, 1, 2, BASE),
        allocation_sha256="c" * 64,
    )
    start = DeliveryInvocationStart(
        work_item_id=original.work_item.id,
        checkpoint_sequence=2,
        request=request,
        lease_id=original.lease.id,
        started_at=NOW,
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    scope = EngineeringScope(
        team_id="team_fixture",
        project_id="project_fixture",
        repository_id=original.work_item.repository_id,
        repository_root=task.repository,
    )
    inventory_before = WorkspaceMutationInventory((_file(PATH, "VALUE = 1\n"),))
    capture_start = ExecutionCaptureStart.create(
        scope=ContinuationScope(
            team_id=scope.team_id,
            project_id=scope.project_id,
            repository_id=scope.repository_id,
            requirement_id="delivery_fixture",
            dispatch_sha256=step.allocation_sha256,
        ),
        request=request,
        claim=original,
        task_intent_sha256=task_intent_sha256(task),
        task_revision=2,
        policy_sha256="d" * 64,
        worktree_path="/fixture/read-only-proof-worktree",
        inventory_before=inventory_before,
        started_at=NOW,
    )
    leader = OwnedProcessIdentity(
        process_id=101, group_id=101, session_id=101, birth_identity="synthetic-unit-fixture"
    )
    session = OwnedSessionStopProof.create(
        boot_identity="synthetic-unit-fixture",
        leader=leader,
        observed_processes=(leader,),
        observation_count=2,
        observations_sha256="e" * 64,
        observed_at=NOW + timedelta(seconds=1),
    )
    stop = ExecutionCaptureStop.create(
        task_id=task.id,
        run_id=request.run_id,
        capture_start_sha256=capture_start.start_sha256,
        process_stop=NativeProcessStop.create(
            process_id=101,
            group_id=101,
            kind="completed",
            returncode=0,
            stopped_at=NOW + timedelta(seconds=1),
            session_proof=session,
        ),
        output_present=True,
    )
    report_template = make_implementation_artifact()
    report = report_template.model_copy(
        update={
            "schema_version": "v1.0",
            "task_id": task.id,
            "source_revision": CANDIDATE,
            "context_manifest_id": request.context_manifest_id,
            "producer": report_template.producer.model_copy(
                update={"run_id": request.run_id, "agent_id": original.assignment.agent_id}
            ),
            "content": report_template.content.model_copy(
                update={
                    "commit_sha": CANDIDATE,
                    "changed_files": (
                        ChangedFile(
                            path=PATH, change=ChangeType.MODIFIED, lines_added=1, lines_deleted=1
                        ),
                    ),
                }
            ),
        }
    )
    result = AgentResult(
        run_id=request.run_id,
        task_id=task.id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        status=AgentRunStatus.SUCCEEDED,
        artifact=report,
    )
    capture = CapturedMutations.from_capture(
        WorktreeMutationCapture(
            worktree=WorktreeRef(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                path=Path(capture_start.worktree_path),
                head_revision=CANDIDATE,
                branch=f"ai/{task.id}/attempt-1",
                detached=False,
            ),
            patch=PATCH,
            index_diff_sha256=sha256(PATCH).hexdigest(),
            mutations=(
                FileMutationCapture(
                    path=PATH,
                    before=MutationTextBody("VALUE = 1\n", 0o644, source_path=PATH),
                    after=MutationTextBody("VALUE = 2\n", 0o644, source_path=PATH),
                ),
            ),
            base_revision=BASE,
        )
    )
    return RejectedCandidateFixture(
        RejectedCandidateOutputProof.create(
            scope=scope,
            task=task,
            task_revision=2,
            task_intent_sha256=task_intent_sha256(task),
            step=step,
            outcome=_outcome(start, result),
            capture_start=capture_start,
            capture_stop=stop,
            candidate_revision=CANDIDATE,
            candidate_parent_revision=BASE,
            complete_capture=capture,
            inventory=WorkspaceMutationInventory((_file(PATH, "VALUE = 2\n"),)),
            publication_absent=True,
        )
    )


def test_proof_preserves_original_success_and_has_pure_schema_roundtrip(
    rejected_candidate_proof_fixture: RejectedCandidateFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    proof = rejected_candidate_proof_fixture.proof
    wire = proof.to_wire()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("pure proof must not inspect filesystem")

    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "is_dir", forbidden)
    proof.validate_for(proof.task, proof.step, proof.scope, proof.request.permissions)
    reopened = RejectedCandidateOutputProof.model_validate(wire)
    reopened.validate_integrity()
    Draft202012Validator(RejectedCandidateOutputProof.model_json_schema()).validate(wire)
    assert reopened.outcome == proof.outcome
    assert reopened.outcome.result.status is AgentRunStatus.SUCCEEDED
    assert (
        cast(ImplementationReportArtifact, reopened.outcome.result.artifact).schema_version
        == "v1.0"
    )
    assert reopened.capture_start == proof.capture_start
    assert reopened.capture_stop == proof.capture_stop
    assert reopened.complete_capture.base_revision == BASE
    assert reopened.complete_capture.source_revision == CANDIDATE


@pytest.mark.parametrize("change", ["current_version", "failed", "blocked", "wrong_candidate"])
def test_only_exact_unsupported_successful_implementation_qualifies(
    rejected_candidate_proof_fixture: RejectedCandidateFixture, change: str
) -> None:
    fixture = rejected_candidate_proof_fixture
    proof, result = fixture.proof, fixture.proof.outcome.result
    report = cast(ImplementationReportArtifact, result.artifact)
    if change == "current_version":
        result = result.model_copy(
            update={"artifact": report.model_copy(update={"schema_version": "v0.1"})}
        )
    elif change == "failed":
        result = result.model_copy(
            update={
                "status": AgentRunStatus.FAILED,
                "artifact": None,
                "error": AgentFailure(
                    code=AgentErrorCode.INVALID_OUTPUT, message="invalid", transient=False
                ),
            }
        )
    elif change == "blocked":
        result = result.model_copy(
            update={
                "artifact": report.model_copy(
                    update={
                        "content": report.content.model_copy(update={"blocked_reason": "not done"})
                    }
                )
            }
        )
    else:
        with pytest.raises(ValueError):
            fixture.create(candidate_revision="f" * 40)
        return
    with pytest.raises(ValueError):
        fixture.create(outcome=_outcome(proof.outcome.start, result))


@pytest.mark.parametrize("change", ["no_session", "no_output", "wrong_start", "failure", "abort"])
def test_unknown_or_incomplete_stop_is_not_rescuable(
    rejected_candidate_proof_fixture: RejectedCandidateFixture, change: str
) -> None:
    fixture, stop = (
        rejected_candidate_proof_fixture,
        rejected_candidate_proof_fixture.proof.capture_stop,
    )
    values = stop.model_dump(mode="python", exclude={"observation_sha256"})
    if change == "no_session":
        values["process_stop"] = stop.process_stop.model_copy(update={"session_proof": None})
    elif change == "no_output":
        values["output_present"] = False
    elif change == "wrong_start":
        values["capture_start_sha256"] = "f" * 64
    elif change == "failure":
        values["process_stop"] = NativeProcessStop.create(
            **{
                **stop.process_stop.model_dump(mode="python", exclude={"stop_sha256"}),
                "kind": "failed",
                "returncode": 1,
            }
        )
    else:
        values["original_error_code"] = AgentErrorCode.WORK_INTERRUPTED
    with pytest.raises(ValueError):
        fixture.create(capture_stop=ExecutionCaptureStop.create(**values))


@pytest.mark.parametrize(
    "path", ["ignored.tmp", "src/ignored.py", ".trellis/spec/x.md", "src/.git/config"]
)
def test_complete_ignored_inventory_cannot_hide_non_candidate_writes(
    rejected_candidate_proof_fixture: RejectedCandidateFixture, path: str
) -> None:
    fixture = rejected_candidate_proof_fixture
    inventory = WorkspaceMutationInventory(
        tuple(
            sorted(
                (*fixture.proof.inventory.files, _file(path, "extra\n")), key=lambda item: item.path
            )
        )
    )
    with pytest.raises(ValueError):
        fixture.create(inventory=inventory)


def test_only_regular_explicit_cache_is_omittable(
    rejected_candidate_proof_fixture: RejectedCandidateFixture,
) -> None:
    fixture = rejected_candidate_proof_fixture
    cache = _file("src/__pycache__/app.pyc", "synthetic cache")
    inventory = WorkspaceMutationInventory(
        tuple(sorted((*fixture.proof.inventory.files, cache), key=lambda item: item.path))
    )
    fixture.create(inventory=inventory).validate_integrity()
    for bad in (replace(cache, kind="symlink"), replace(cache, mode=0o600)):
        with pytest.raises(ValueError):
            fixture.create(
                inventory=WorkspaceMutationInventory(
                    tuple(sorted((*fixture.proof.inventory.files, bad), key=lambda item: item.path))
                )
            )


@pytest.mark.parametrize("change", ["parent", "intent", "publication", "inventory", "digest"])
def test_exact_binding_and_fingerprint_tampering_is_rejected(
    rejected_candidate_proof_fixture: RejectedCandidateFixture, change: str
) -> None:
    fixture, proof = rejected_candidate_proof_fixture, rejected_candidate_proof_fixture.proof
    alternatives: dict[str, dict[str, object]] = {
        "parent": {"candidate_parent_revision": "f" * 40},
        "intent": {"task_intent_sha256": "f" * 64},
        "publication": {"publication_absent": False},
        "inventory": {"inventory": WorkspaceMutationInventory((_file(PATH, "different\n"),))},
    }
    changes = alternatives.get(change, {})
    with pytest.raises(ValueError):
        if change == "digest":
            proof.model_copy(update={"proof_sha256": "f" * 64}).validate_integrity()
        else:
            fixture.create(**changes)


def test_exact_current_permissions_and_native_rule_denies_remain_enforced(
    rejected_candidate_proof_fixture: RejectedCandidateFixture,
) -> None:
    fixture, proof = rejected_candidate_proof_fixture, rejected_candidate_proof_fixture.proof
    with pytest.raises(ValueError):
        proof.validate_for(
            fixture.task, fixture.step, fixture.scope, proof.request.permissions, (PATH,)
        )
    with pytest.raises(ValueError):
        proof.validate_for(
            fixture.task,
            fixture.step,
            fixture.scope,
            proof.request.permissions.model_copy(update={"write_paths": ("**",)}),
        )
    with pytest.raises(ValueError):
        fixture.create(inventory=WorkspaceMutationInventory(proof.inventory.files * 2))
    with pytest.raises(ValidationError):
        fixture.create(untrusted_extra_authority=True)


@pytest.mark.parametrize("change", ["agent", "parents", "step_parent", "status"])
def test_independent_identity_counterexamples_remain_rejected(
    rejected_candidate_proof_fixture: RejectedCandidateFixture, change: str
) -> None:
    fixture, proof = rejected_candidate_proof_fixture, rejected_candidate_proof_fixture.proof
    report = cast(ImplementationReportArtifact, proof.outcome.result.artifact)
    with pytest.raises(ValueError):
        if change == "agent":
            report = report.model_copy(
                update={
                    "producer": report.producer.model_copy(update={"agent_id": "agent_foreign"})
                }
            )
        elif change == "parents":
            report = report.model_copy(update={"parent_artifact_ids": ("art_foreign",)})
        elif change == "step_parent":
            fixture.create(
                step=proof.step.model_copy(
                    update={
                        "work_item": proof.step.work_item.model_copy(
                            update={"parent_work_item_id": "work_foreign"}
                        )
                    }
                )
            )
            return
        else:
            fixture.create(task=proof.task.model_copy(update={"status": TaskStatus.DONE}))
            return
        fixture.create(
            outcome=_outcome(
                proof.outcome.start, proof.outcome.result.model_copy(update={"artifact": report})
            )
        )


def test_frozen_rejection_version_is_independent_of_future_platform_support(
    rejected_candidate_proof_fixture: RejectedCandidateFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.domain import artifact

    proof = rejected_candidate_proof_fixture.proof
    monkeypatch.setattr(artifact, "SUPPORTED_ARTIFACT_SCHEMA_VERSION", "v1.0")
    RejectedCandidateOutputProof.model_validate(proof.to_wire()).validate_integrity()
    assert proof.rejected_supported_version == "v0.1"


def test_missing_supersedes_contract_key_returns_validation_error(
    rejected_candidate_proof_fixture: RejectedCandidateFixture,
) -> None:
    from ai_software_engineer.domain.model import WirePayload

    wire = rejected_candidate_proof_fixture.proof.to_wire()
    outcome = cast(WirePayload, wire["outcome"])
    start = cast(WirePayload, outcome["start"])
    request = cast(WirePayload, start["request"])
    request["expected_supersedes_by_kind"] = {"coder-progress": None}
    with pytest.raises(ValueError):
        RejectedCandidateOutputProof.model_validate(wire)


@pytest.mark.parametrize(
    "path", [".pytest_cache/v/cache/nodeids", "src/__pycache__/app.pyc", ".ruff_cache/cache"]
)
def test_public_report_inventory_allows_regular_execution_cache_only(path: str) -> None:
    old = WorkspaceMutationInventory((_file(PATH, "VALUE = 2\n"),))
    new = WorkspaceMutationInventory(
        tuple(sorted((*old.files, _file(path, "cache")), key=lambda item: item.path))
    )
    validate_rejected_candidate_inventory(old, new)
    validate_rejected_candidate_inventory(new, old)


@pytest.mark.parametrize("change", ["source", "ignored", "symlink", "mode", "git_directory"])
def test_public_report_inventory_refuses_source_and_special_cache_changes(change: str) -> None:
    old = WorkspaceMutationInventory(())
    item = _file(".pytest_cache/cache", "cache")
    if change == "source":
        item = _file(PATH, "VALUE = 3\n")
    elif change == "ignored":
        item = _file("ignored.tmp", "ignored")
    elif change == "symlink":
        item = replace(item, kind="symlink")
    elif change == "mode":
        item = replace(item, mode=0o600)
    else:
        item = replace(item, kind="git_directory")
    new = WorkspaceMutationInventory((item,))
    with pytest.raises(ValueError):
        validate_rejected_candidate_inventory(old, new)
    with pytest.raises(ValueError):
        validate_rejected_candidate_inventory(new, old)
