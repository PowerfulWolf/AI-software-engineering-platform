"""Deterministic offline AgentAdapter for contract and orchestration tests."""

from collections.abc import Mapping

from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    FakeBehavior,
    FakeScenario,
)
from ai_software_engineer.agents.ports import AgentConfigurationError, AgentRequestConflict
from ai_software_engineer.domain.agent import ROLE_OUTPUT
from ai_software_engineer.domain.artifact import Artifact
from ai_software_engineer.domain.enums import AgentRole, QaReportStatus, ReviewVerdict

ScenarioKey = tuple[AgentRole, int]


class FakeAgentAdapter:
    """Run scripted typed outcomes without network, Git, filesystem, or SDK calls."""

    def __init__(
        self,
        *,
        scenarios: Mapping[ScenarioKey, FakeScenario] | None = None,
        default: FakeScenario | None = None,
    ) -> None:
        self._scenarios = dict(scenarios or {})
        self._default = default
        self._requests: dict[str, AgentRequest] = {}
        self._results: dict[str, AgentResult] = {}
        for key in self._scenarios:
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or not isinstance(key[0], AgentRole)
                or type(key[1]) is not int
            ):
                raise AgentConfigurationError("fake scenario keys must be (AgentRole, int)")
            if not 1 <= key[1] <= 10:
                raise AgentConfigurationError("fake scenario attempt must be between 1 and 10")

    def run(self, request: AgentRequest) -> AgentResult:
        """Return a deterministic result, caching exact run replay."""
        prior_request = self._requests.get(request.run_id)
        if prior_request is not None:
            if prior_request != request:
                raise AgentRequestConflict(
                    f"run ID already used with a different request: {request.run_id}"
                )
            return self._results[request.run_id]

        scenario = self._scenarios.get((request.role, request.attempt), self._default)
        if scenario is None:
            raise AgentConfigurationError(
                f"no fake scenario configured for {request.role.value} attempt {request.attempt}"
            )
        self._validate_scenario_role(request, scenario)
        result = self._execute(request, scenario)
        self._requests[request.run_id] = request
        self._results[request.run_id] = result
        return result

    def _execute(self, request: AgentRequest, scenario: FakeScenario) -> AgentResult:
        if scenario.behavior is FakeBehavior.TIMEOUT:
            return self._failure_result(
                request,
                AgentRunStatus.TIMED_OUT,
                AgentErrorCode.TIMEOUT,
                scenario.message,
                transient=True,
                duration_ms=scenario.duration_ms,
            )
        if scenario.behavior is FakeBehavior.INVALID_OUTPUT:
            return self._failure_result(
                request,
                AgentRunStatus.FAILED,
                AgentErrorCode.INVALID_OUTPUT,
                scenario.message,
                transient=False,
                duration_ms=scenario.duration_ms,
            )
        if scenario.behavior is FakeBehavior.PROVIDER_ERROR:
            return self._failure_result(
                request,
                AgentRunStatus.FAILED,
                AgentErrorCode.PROVIDER_ERROR,
                scenario.message,
                transient=True,
                duration_ms=scenario.duration_ms,
            )

        artifact = scenario.artifact
        if artifact is None:
            raise AgentConfigurationError("successful fake scenario has no artifact")
        invalid_reason = self._artifact_mismatch(request, scenario.behavior, artifact)
        if invalid_reason is not None:
            return self._failure_result(
                request,
                AgentRunStatus.FAILED,
                AgentErrorCode.INVALID_OUTPUT,
                invalid_reason,
                transient=False,
                duration_ms=scenario.duration_ms,
            )
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=artifact,
            duration_ms=scenario.duration_ms,
        )

    def _validate_scenario_role(self, request: AgentRequest, scenario: FakeScenario) -> None:
        if scenario.behavior is FakeBehavior.QA_FAIL and request.role is not AgentRole.QA:
            raise AgentConfigurationError("QA_FAIL requires qa role")
        if (
            scenario.behavior is FakeBehavior.REVIEW_REJECT
            and request.role is not AgentRole.REVIEWER
        ):
            raise AgentConfigurationError("REVIEW_REJECT requires reviewer role")

    def _artifact_mismatch(
        self, request: AgentRequest, behavior: FakeBehavior, artifact: Artifact
    ) -> str | None:
        expected_kind = ROLE_OUTPUT[request.role]
        if artifact.task_id != request.task_id:
            return "fake Artifact task_id does not match AgentRequest"
        if artifact.producer.role is not request.role:
            return "fake Artifact producer role does not match AgentRequest"
        if artifact.producer.run_id != request.run_id:
            return "fake Artifact producer run_id does not match AgentRequest"
        if artifact.kind is not expected_kind:
            return "fake Artifact kind does not match Agent role contract"
        if artifact.source_revision != request.source_revision:
            return "fake Artifact source_revision does not match AgentRequest"
        if artifact.context_manifest_id != request.context_manifest_id:
            return "fake Artifact context_manifest_id does not match AgentRequest"
        if request.role is AgentRole.QA:
            status = getattr(artifact.content, "status", None)
            expected_status = (
                QaReportStatus.FAIL if behavior is FakeBehavior.QA_FAIL else QaReportStatus.PASS
            )
            if status is not expected_status:
                return "fake QA Artifact status does not match scenario"
        if request.role is AgentRole.REVIEWER:
            verdict = getattr(artifact.content, "verdict", None)
            expected_verdict = (
                ReviewVerdict.REJECT
                if behavior is FakeBehavior.REVIEW_REJECT
                else ReviewVerdict.APPROVE
            )
            if verdict is not expected_verdict:
                return "fake Review Artifact verdict does not match scenario"
        return None

    @staticmethod
    def _failure_result(
        request: AgentRequest,
        status: AgentRunStatus,
        code: AgentErrorCode,
        message: str,
        *,
        transient: bool,
        duration_ms: int,
    ) -> AgentResult:
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=status,
            error=AgentFailure(code=code, message=message, transient=transient),
            duration_ms=duration_ms,
        )


__all__ = ["FakeAgentAdapter", "ScenarioKey"]
