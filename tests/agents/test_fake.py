"""Public-seam contract tests for the deterministic FakeAgentAdapter."""

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from ai_software_engineer.agents import (
    AgentConfigurationError,
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentRequestConflict,
    AgentResult,
    AgentRunStatus,
    FakeAgentAdapter,
    FakeBehavior,
    FakeScenario,
)
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    Artifact,
    Finding,
    FindingSeverity,
    NetworkAccess,
    QaReportArtifact,
    QaReportStatus,
    ReviewReportArtifact,
    ReviewReportContent,
    ReviewVerdict,
)
from tests.domain.factories import (
    CANDIDATE_SHA,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
)

CONTEXT_ID = "ctx_" + "c" * 64
TASK_ID = "task_domain_001"


def _permissions() -> AgentPermissions:
    return AgentPermissions(
        read_paths=("src/**", "tests/**"),
        write_paths=("src/**", "tests/**"),
        commands=("pytest",),
        network=NetworkAccess.NONE,
    )


def _request(
    role: AgentRole,
    *,
    run_id: str = "run_fake_001",
    attempt: int = 1,
    source_revision: str = CANDIDATE_SHA,
    context_manifest_id: str = CONTEXT_ID,
) -> AgentRequest:
    output_schema = {
        AgentRole.ORCHESTRATOR: "schemas/plan.schema.json",
        AgentRole.CODER: "schemas/implementation-report.schema.json",
        AgentRole.QA: "schemas/qa-report.schema.json",
        AgentRole.REVIEWER: "schemas/review-report.schema.json",
    }[role]
    return AgentRequest(
        run_id=run_id,
        task_id=TASK_ID,
        role=role,
        attempt=attempt,
        source_revision=source_revision,
        context_manifest_id=context_manifest_id,
        input_artifact_ids=(),
        permissions=_permissions(),
        output_schema=output_schema,
        timeout_seconds=60,
    )


def _align(artifact: Artifact, request: AgentRequest) -> Artifact:
    typed = artifact.model_copy(
        update={
            "task_id": request.task_id,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
            "producer": artifact.producer.model_copy(update={"run_id": request.run_id}),
        }
    )
    return typed


def test_fake_success_returns_typed_artifact_and_exact_replay_is_idempotent() -> None:
    request = _request(AgentRole.CODER)
    artifact = _align(make_implementation_artifact(), request)
    adapter = FakeAgentAdapter(
        default=FakeScenario(behavior=FakeBehavior.SUCCESS, artifact=artifact)
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact == artifact
    assert result.error is None
    assert adapter.run(request) == result


@pytest.mark.parametrize(
    ("role", "behavior", "artifact_factory"),
    (
        (AgentRole.ORCHESTRATOR, FakeBehavior.SUCCESS, make_plan_artifact),
        (AgentRole.CODER, FakeBehavior.SUCCESS, make_implementation_artifact),
        (AgentRole.QA, FakeBehavior.SUCCESS, make_qa_artifact),
        (AgentRole.REVIEWER, FakeBehavior.SUCCESS, make_review_artifact),
    ),
)
def test_each_role_success_requires_its_declared_artifact_contract(
    role: AgentRole,
    behavior: FakeBehavior,
    artifact_factory: Callable[[], Artifact],
) -> None:
    request = _request(role)
    artifact = _align(artifact_factory(), request)

    result = FakeAgentAdapter(default=FakeScenario(behavior=behavior, artifact=artifact)).run(
        request
    )

    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact is not None
    assert result.artifact.producer.role is role


def test_qa_fail_is_only_emitted_by_qa() -> None:
    request = _request(AgentRole.QA)
    artifact = _align(make_qa_artifact(), request)
    artifact = artifact.model_copy(
        update={"content": artifact.content.model_copy(update={"status": QaReportStatus.FAIL})}
    )

    result = FakeAgentAdapter(
        default=FakeScenario(behavior=FakeBehavior.QA_FAIL, artifact=artifact)
    ).run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    assert isinstance(result.artifact, QaReportArtifact)
    assert result.artifact.content.status is QaReportStatus.FAIL

    with pytest.raises(AgentConfigurationError, match="QA_FAIL requires qa"):
        FakeAgentAdapter(
            default=FakeScenario(behavior=FakeBehavior.QA_FAIL, artifact=artifact)
        ).run(_request(AgentRole.CODER))


def test_review_reject_is_only_emitted_by_reviewer() -> None:
    request = _request(AgentRole.REVIEWER)
    artifact = _align(make_review_artifact(), request)
    assert isinstance(artifact, ReviewReportArtifact)
    finding = Finding(
        finding_id="finding_major",
        severity=FindingSeverity.MAJOR,
        message="The candidate misses a required check.",
        evidence_ids=("ev_review_diff",),
    )
    content = ReviewReportContent(
        verdict=ReviewVerdict.REJECT,
        findings=(finding,),
        checked_dimensions=artifact.content.checked_dimensions,
        evidence=artifact.content.evidence,
    )
    artifact = artifact.model_copy(update={"content": content})

    result = FakeAgentAdapter(
        default=FakeScenario(behavior=FakeBehavior.REVIEW_REJECT, artifact=artifact)
    ).run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    assert isinstance(result.artifact, ReviewReportArtifact)
    assert result.artifact.content.verdict is ReviewVerdict.REJECT


@pytest.mark.parametrize(
    ("behavior", "code", "transient"),
    (
        (FakeBehavior.TIMEOUT, AgentErrorCode.TIMEOUT, True),
        (FakeBehavior.INVALID_OUTPUT, AgentErrorCode.INVALID_OUTPUT, False),
        (FakeBehavior.PROVIDER_ERROR, AgentErrorCode.PROVIDER_ERROR, True),
    ),
)
def test_failures_never_carry_an_artifact_or_verdict(
    behavior: FakeBehavior, code: AgentErrorCode, transient: bool
) -> None:
    result = FakeAgentAdapter(default=FakeScenario(behavior=behavior)).run(
        _request(AgentRole.CODER)
    )

    expected_status = (
        AgentRunStatus.TIMED_OUT if behavior is FakeBehavior.TIMEOUT else AgentRunStatus.FAILED
    )
    assert result.status is expected_status
    assert result.artifact is None
    assert result.error is not None
    assert result.error == AgentFailure(
        code=code, message=result.error.message, transient=transient
    )


def test_scripted_scenarios_override_default_by_role_and_attempt() -> None:
    request = _request(AgentRole.QA, attempt=2)
    artifact = _align(make_qa_artifact(), request)
    artifact = artifact.model_copy(
        update={"content": artifact.content.model_copy(update={"status": QaReportStatus.FAIL})}
    )
    adapter = FakeAgentAdapter(
        scenarios={
            (AgentRole.QA, 2): FakeScenario(behavior=FakeBehavior.QA_FAIL, artifact=artifact)
        },
        default=FakeScenario(behavior=FakeBehavior.TIMEOUT),
    )

    assert adapter.run(request).status is AgentRunStatus.SUCCEEDED
    assert (
        adapter.run(_request(AgentRole.CODER, run_id="run_fake_coder")).status
        is AgentRunStatus.TIMED_OUT
    )


def test_missing_scenario_fails_closed() -> None:
    with pytest.raises(AgentConfigurationError, match="no fake scenario"):
        FakeAgentAdapter().run(_request(AgentRole.CODER))


def test_invalid_scenario_key_fails_closed() -> None:
    with pytest.raises(AgentConfigurationError, match="scenario keys"):
        FakeAgentAdapter(
            scenarios={("coder",): FakeScenario(behavior=FakeBehavior.TIMEOUT)}  # type: ignore[dict-item]
        )


@pytest.mark.parametrize("field", ("task_id", "source_revision", "context_manifest_id"))
def test_artifact_identity_mismatch_becomes_invalid_output(field: str) -> None:
    request = _request(AgentRole.CODER)
    artifact = _align(make_implementation_artifact(), request)
    updates = {field: "wrong-value"}
    mismatched = artifact.model_copy(update=updates)

    result = FakeAgentAdapter(
        default=FakeScenario(behavior=FakeBehavior.SUCCESS, artifact=mismatched)
    ).run(request)

    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None
    assert result.error.code is AgentErrorCode.INVALID_OUTPUT


def test_artifact_role_kind_and_run_mismatch_become_invalid_output() -> None:
    qa_request = _request(AgentRole.QA, run_id="run_fake_qa")
    coder_artifact = _align(make_implementation_artifact(), qa_request)
    role_result = FakeAgentAdapter(
        default=FakeScenario(behavior=FakeBehavior.SUCCESS, artifact=coder_artifact)
    ).run(qa_request)

    assert role_result.status is AgentRunStatus.FAILED
    assert role_result.error is not None
    assert role_result.error.code is AgentErrorCode.INVALID_OUTPUT

    coder_request = _request(AgentRole.CODER, run_id="run_fake_coder")
    coder_artifact = _align(make_implementation_artifact(), coder_request)
    wrong_run = coder_artifact.model_copy(
        update={"producer": coder_artifact.producer.model_copy(update={"run_id": "run_wrong"})}
    )
    run_result = FakeAgentAdapter(
        default=FakeScenario(behavior=FakeBehavior.SUCCESS, artifact=wrong_run)
    ).run(coder_request)

    assert run_result.status is AgentRunStatus.FAILED
    assert run_result.error is not None
    assert run_result.error.code is AgentErrorCode.INVALID_OUTPUT


def test_same_run_id_with_changed_request_is_rejected() -> None:
    request = _request(AgentRole.CODER)
    artifact = _align(make_implementation_artifact(), request)
    adapter = FakeAgentAdapter(
        default=FakeScenario(behavior=FakeBehavior.SUCCESS, artifact=artifact)
    )
    adapter.run(request)

    with pytest.raises(AgentRequestConflict):
        adapter.run(request.model_copy(update={"attempt": 2}))


def test_agent_request_is_immutable_and_rejects_unknown_fields() -> None:
    request = _request(AgentRole.CODER)

    with pytest.raises(ValidationError):
        AgentRequest.model_validate({**request.to_wire(), "unexpected": True})
    with pytest.raises(ValidationError, match="output_schema"):
        AgentRequest.model_validate(
            {**request.to_wire(), "output_schema": "schemas/review-report.schema.json"}
        )
    with pytest.raises(ValidationError):
        request.role = AgentRole.QA


def test_agent_result_itself_rejects_artifact_identity_mismatch() -> None:
    request = _request(AgentRole.CODER)
    artifact = _align(make_implementation_artifact(), request)
    mismatched = artifact.model_copy(update={"source_revision": "d" * 40})

    with pytest.raises(ValidationError, match="source_revision"):
        AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=mismatched,
        )


@pytest.mark.parametrize(
    "status,artifact,error",
    (
        (AgentRunStatus.SUCCEEDED, None, None),
        (AgentRunStatus.FAILED, make_implementation_artifact(), None),
        (
            AgentRunStatus.TIMED_OUT,
            None,
            AgentFailure(code=AgentErrorCode.PROVIDER_ERROR, message="bad", transient=True),
        ),
    ),
)
def test_agent_result_rejects_invalid_state_combinations(
    status: AgentRunStatus, artifact: Artifact | None, error: AgentFailure | None
) -> None:
    with pytest.raises(ValidationError):
        AgentResult(
            run_id="run_fake_001",
            task_id=TASK_ID,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=CANDIDATE_SHA,
            context_manifest_id=CONTEXT_ID,
            status=status,
            artifact=artifact,
            error=error,
            duration_ms=0,
        )
