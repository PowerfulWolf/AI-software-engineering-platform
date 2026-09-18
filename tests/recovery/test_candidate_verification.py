"""Candidate verification preserves terminal history and never invokes Coder."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.artifacts import FileArtifactStore, artifact_digest
from ai_software_engineer.domain import AgentDefinition, AgentRole, Artifact, TaskStatus
from ai_software_engineer.domain.artifact import (
    Finding,
    ImplementationReportArtifact,
    QaReportArtifact,
)
from ai_software_engineer.domain.enums import FindingSeverity, ReviewVerdict
from ai_software_engineer.orchestration import (
    AgentRunFailed,
    DeliveryContractViolation,
    FileRunContextBuilder,
)
from ai_software_engineer.recovery.models import RecoveryRejected, digest
from ai_software_engineer.recovery.verification import (
    CandidateVerificationRunner,
)
from ai_software_engineer.recovery.verification_records import (
    AcceptedQaReport,
    CandidateVerificationInputs,
)
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import make_review_artifact
from tests.orchestration.test_output_parent_contract import AllInputsAsParentsAdapter
from tests.orchestration.test_retry import ScriptedAdapter, _runner
from tests.orchestration.test_runner import _clock, _definitions


class Admission:
    """Offline authority consumes each role once; production needs a durable receipt."""

    def __init__(self, *, approved: bool = True) -> None:
        self.approved = approved
        self.roles: list[AgentRole] = []

    def admit(self, inputs: CandidateVerificationInputs, request: AgentRequest) -> None:
        assert request.task_id == inputs.task_id
        assert request.source_revision == inputs.candidate_revision
        if not self.approved or request.role in self.roles:
            raise RecoveryRejected("missing approval or invocation already consumed")
        self.roles.append(request.role)

    def validate_configuration(
        self,
        inputs: CandidateVerificationInputs,
        definitions: Mapping[AgentRole, AgentDefinition],
    ) -> None:
        if not self.approved:
            raise RecoveryRejected("missing approval")


def setup_verification(
    tmp_path: Path, adapter: ScriptedAdapter, admission: Admission
) -> tuple[CandidateVerificationInputs, SqliteTaskRepository, CandidateVerificationRunner]:
    task, repository, original = _runner(tmp_path, AllInputsAsParentsAdapter())
    original.run_task(task.id)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    inputs = CandidateVerificationInputs(
        task_id=task.id,
        task_revision=repository.current_revision(task.id),
        task_sha256=digest(repository.get(task.id).to_wire()),
        plan_id="art_plan_001",
        plan_sha256=artifact_digest(artifacts.get("art_plan_001")),
        implementation_id="art_impl_001",
        implementation_sha256=artifact_digest(artifacts.get("art_impl_001")),
        candidate_revision="b" * 40,
        prior_run_ids=("run_qa_01",),
    )
    verifier = CandidateVerificationRunner(
        repository=repository,
        artifact_store=artifacts,
        context_builder=FileRunContextBuilder(tmp_path / "project"),
        agent_adapter=adapter,
        agent_definitions=_definitions(),
        admission=admission,
        clock=_clock,
    )
    return inputs, repository, verifier


def test_verifies_original_candidate_without_changing_terminal_history(tmp_path: Path) -> None:
    adapter, admission = ScriptedAdapter(), Admission()
    inputs, repository, verifier = setup_verification(tmp_path, adapter, admission)
    before = repository.get(inputs.task_id), repository.list_events(inputs.task_id)
    try:
        result = verifier.verify_candidate(inputs)
        assert result.verified
        assert result.candidate_revision == inputs.candidate_revision
        assert result.plan.artifact_id == inputs.plan_id
        assert result.implementation.artifact_id == inputs.implementation_id
        assert result.qa.parent_artifact_ids == (inputs.implementation_id,)
        assert result.review is not None
        assert result.review.parent_artifact_ids == (result.qa.artifact_id,)
        assert [r.role for r in adapter.requests] == [AgentRole.QA, AgentRole.REVIEWER]
        assert admission.roles == [AgentRole.QA, AgentRole.REVIEWER]
        assert (repository.get(inputs.task_id), repository.list_events(inputs.task_id)) == before
        with pytest.raises(RecoveryRejected):
            verifier.verify_candidate(inputs)
        assert len(adapter.requests) == 2
    finally:
        repository.close()


class ReviewerProviderFailureAdapter(ScriptedAdapter):
    def run(self, request: AgentRequest) -> AgentResult:
        if request.role is not AgentRole.REVIEWER:
            return super().run(request)
        self.requests.append(request)
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.FAILED,
            error=AgentFailure(
                code=AgentErrorCode.PROVIDER_ERROR,
                message="offline Reviewer provider failure",
                transient=True,
            ),
        )


def setup_reviewer_only_verification(
    tmp_path: Path,
) -> tuple[
    CandidateVerificationInputs,
    SqliteTaskRepository,
    FileArtifactStore,
    QaReportArtifact,
]:
    task, repository, delivery = _runner(tmp_path, ReviewerProviderFailureAdapter())
    blocked = delivery.run_task(task.id)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    history = artifacts.list_for_task(task.id)
    plan = artifacts.get("art_plan_001")
    implementation = artifacts.get("art_impl_001")
    assert isinstance(implementation, ImplementationReportArtifact)
    qa = next(artifact for artifact in history if isinstance(artifact, QaReportArtifact))
    inputs = CandidateVerificationInputs(
        task_id=task.id,
        task_revision=repository.current_revision(task.id),
        task_sha256=digest(repository.get(task.id).to_wire()),
        plan_id=plan.artifact_id,
        plan_sha256=artifact_digest(plan),
        implementation_id=implementation.artifact_id,
        implementation_sha256=artifact_digest(implementation),
        candidate_revision=implementation.content.commit_sha,
        accepted_qa=AcceptedQaReport(
            artifact_id=qa.artifact_id,
            artifact_sha256=artifact_digest(qa),
        ),
        prior_run_ids=tuple(sorted(artifact.producer.run_id for artifact in history)),
    )
    assert blocked.task.status is TaskStatus.BLOCKED
    return inputs, repository, artifacts, qa


@pytest.mark.parametrize("new_qa_assignment", [False, True])
def test_reuses_terminal_qa_pass_and_invokes_only_reviewer(
    tmp_path: Path, new_qa_assignment: bool
) -> None:
    inputs, repository, artifacts, qa = setup_reviewer_only_verification(tmp_path)
    adapter = ScriptedAdapter()
    definitions = _definitions()
    if new_qa_assignment:
        definitions[AgentRole.QA] = definitions[AgentRole.QA].model_copy(
            update={"id": "agent_qa_replacement"}
        )
    verifier = CandidateVerificationRunner(
        repository=repository,
        artifact_store=artifacts,
        context_builder=FileRunContextBuilder(tmp_path / "project"),
        agent_adapter=adapter,
        agent_definitions=definitions,
        admission=Admission(),
        clock=_clock,
    )
    try:
        result = verifier.verify_candidate(inputs)

        assert result.verified
        assert result.qa == qa
        assert result.review is not None
        assert result.review.parent_artifact_ids == (qa.artifact_id,)
        assert [request.role for request in adapter.requests] == [AgentRole.REVIEWER]
    finally:
        repository.close()


@pytest.mark.parametrize("case", ["missing", "digest_drift"])
def test_terminal_qa_pass_drift_refuses_before_provider(tmp_path: Path, case: str) -> None:
    inputs, repository, artifacts, _ = setup_reviewer_only_verification(tmp_path)
    changed = (
        inputs.model_copy(update={"accepted_qa": None})
        if case == "missing"
        else inputs.model_copy(
            update={
                "accepted_qa": inputs.accepted_qa.model_copy(update={"artifact_sha256": "f" * 64})
                if inputs.accepted_qa is not None
                else None
            }
        )
    )
    adapter = ScriptedAdapter()
    verifier = CandidateVerificationRunner(
        repository=repository,
        artifact_store=artifacts,
        context_builder=FileRunContextBuilder(tmp_path / "project"),
        agent_adapter=adapter,
        agent_definitions=_definitions(),
        admission=Admission(),
        clock=_clock,
    )
    try:
        with pytest.raises(RecoveryRejected, match="accepted QA"):
            verifier.verify_candidate(changed)
        assert not adapter.requests
    finally:
        repository.close()


@pytest.mark.parametrize(
    "field", ["task_sha256", "plan_sha256", "implementation_sha256", "candidate_revision"]
)
def test_stale_pinned_input_refuses_before_provider(tmp_path: Path, field: str) -> None:
    adapter = ScriptedAdapter()
    inputs, repository, verifier = setup_verification(tmp_path, adapter, Admission())
    try:
        value = "f" * (40 if field == "candidate_revision" else 64)
        with pytest.raises(RecoveryRejected):
            verifier.verify_candidate(inputs.model_copy(update={field: value}))
        assert not adapter.requests
    finally:
        repository.close()


def test_missing_approval_prevents_provider(tmp_path: Path) -> None:
    adapter = ScriptedAdapter()
    inputs, repository, verifier = setup_verification(tmp_path, adapter, Admission(approved=False))
    try:
        with pytest.raises(RecoveryRejected):
            verifier.verify_candidate(inputs)
        assert not adapter.requests
    finally:
        repository.close()


def test_qa_failure_stops_without_coder_or_reviewer(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(qa_failures=(1, 2, 3))
    inputs, repository, verifier = setup_verification(tmp_path, adapter, Admission())
    try:
        result = verifier.verify_candidate(inputs)
        assert not result.verified
        assert result.review is None
        assert [r.role for r in adapter.requests] == [AgentRole.QA]
    finally:
        repository.close()


def test_verifies_retained_candidate_after_routed_coder_failure(tmp_path: Path) -> None:
    task, repository, delivery = _runner(
        tmp_path,
        ScriptedAdapter(qa_failures=(1,), coder_timeouts=(2, 3)),
    )
    blocked = delivery.run_task(task.id)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    plan = artifacts.get("art_plan_001")
    implementation = artifacts.get("art_impl_001")
    inputs = CandidateVerificationInputs(
        task_id=task.id,
        task_revision=repository.current_revision(task.id),
        task_sha256=digest(repository.get(task.id).to_wire()),
        plan_id=plan.artifact_id,
        plan_sha256=artifact_digest(plan),
        implementation_id=implementation.artifact_id,
        implementation_sha256=artifact_digest(implementation),
        candidate_revision="b" * 40,
        prior_run_ids=tuple(
            sorted(artifact.producer.run_id for artifact in artifacts.list_for_task(task.id))
        ),
    )
    adapter = ScriptedAdapter()
    verifier = CandidateVerificationRunner(
        repository=repository,
        artifact_store=artifacts,
        context_builder=FileRunContextBuilder(tmp_path / "project"),
        agent_adapter=adapter,
        agent_definitions=_definitions(),
        admission=Admission(),
        clock=_clock,
    )
    before = repository.get(task.id), repository.list_events(task.id)
    try:
        assert blocked.task.status is TaskStatus.BLOCKED
        result = verifier.verify_candidate(inputs)
        assert result.verified
        assert [request.role for request in adapter.requests] == [
            AgentRole.QA,
            AgentRole.REVIEWER,
        ]
        assert (repository.get(task.id), repository.list_events(task.id)) == before
    finally:
        repository.close()


class FailureAdapter(ScriptedAdapter):
    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.FAILED,
            error=AgentFailure(
                code=AgentErrorCode.PROVIDER_ERROR, message="offline failure", transient=True
            ),
        )


@pytest.mark.parametrize("adapter", [FailureAdapter, AllInputsAsParentsAdapter])
def test_failed_or_invalid_qa_never_retries(tmp_path: Path, adapter: type[ScriptedAdapter]) -> None:
    instance = adapter()
    inputs, repository, verifier = setup_verification(tmp_path, instance, Admission())
    before = repository.get(inputs.task_id), repository.list_events(inputs.task_id)
    try:
        with pytest.raises(AgentRunFailed):
            verifier.verify_candidate(inputs)
        assert [r.role for r in instance.requests] == [AgentRole.QA]
        assert (repository.get(inputs.task_id), repository.list_events(inputs.task_id)) == before
        assert not any(
            a.kind.value == "qa-report"
            for a in FileArtifactStore(tmp_path / "artifacts").list_for_task(inputs.task_id)
        )
    finally:
        repository.close()


class RejectedReviewAdapter(ScriptedAdapter):
    def _artifact(self, request: AgentRequest) -> Artifact:
        artifact = super()._artifact(request)
        if request.role is AgentRole.REVIEWER:
            template = make_review_artifact()
            content = template.content.model_copy(
                update={
                    "verdict": ReviewVerdict.REJECT,
                    "findings": (
                        Finding(
                            finding_id="finding_review_001",
                            severity=FindingSeverity.MAJOR,
                            message="Offline review rejected the candidate",
                            evidence_ids=("ev_review_diff",),
                        ),
                    ),
                }
            )
            return artifact.model_copy(update={"content": content, "evidence": template.evidence})
        return artifact


def test_review_rejection_returns_findings_without_coder(tmp_path: Path) -> None:
    adapter = RejectedReviewAdapter()
    inputs, repository, verifier = setup_verification(tmp_path, adapter, Admission())
    try:
        result = verifier.verify_candidate(inputs)
        assert not result.verified
        assert result.review is not None
        assert result.review.content.verdict is ReviewVerdict.REJECT
        assert [r.role for r in adapter.requests] == [AgentRole.QA, AgentRole.REVIEWER]
    finally:
        repository.close()


def test_historical_coder_cannot_become_verifier(tmp_path: Path) -> None:
    adapter = ScriptedAdapter()
    inputs, repository, verifier = setup_verification(tmp_path, adapter, Admission())
    definitions = _definitions()
    definitions[AgentRole.QA] = definitions[AgentRole.QA].model_copy(
        update={"id": definitions[AgentRole.CODER].id}
    )
    # A fresh composition attempts to change the role of a historical producer.
    verifier = CandidateVerificationRunner(
        repository=repository,
        artifact_store=FileArtifactStore(tmp_path / "artifacts"),
        context_builder=FileRunContextBuilder(tmp_path / "project"),
        agent_adapter=adapter,
        agent_definitions=definitions,
        admission=Admission(),
        clock=_clock,
    )
    try:
        with pytest.raises(RecoveryRejected, match="historical work"):
            verifier.verify_candidate(inputs)
        assert not adapter.requests
    finally:
        repository.close()


class SameRunIdentity:
    def new_run_id(self, task_id: str, role: AgentRole, attempt: int) -> str:
        return "run_qa_01"

    def new_event_id(
        self, task_id: str, from_status: TaskStatus, to_status: TaskStatus, attempt: int
    ) -> str:
        raise AssertionError("verification must not create Task events")


def test_failed_historical_run_id_cannot_be_reused(tmp_path: Path) -> None:
    adapter = ScriptedAdapter()
    inputs, repository, _ = setup_verification(tmp_path, adapter, Admission())
    verifier = CandidateVerificationRunner(
        repository=repository,
        artifact_store=FileArtifactStore(tmp_path / "artifacts"),
        context_builder=FileRunContextBuilder(tmp_path / "project"),
        agent_adapter=adapter,
        agent_definitions=_definitions(),
        admission=Admission(),
        identities=SameRunIdentity(),
        clock=_clock,
    )
    try:
        with pytest.raises(DeliveryContractViolation, match="duplicate Agent run"):
            verifier.verify_candidate(inputs)
        assert not adapter.requests
    finally:
        repository.close()
