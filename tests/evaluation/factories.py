"""Independent known-good Evaluation event examples."""

from datetime import timedelta

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.evaluation import (
    AgentRunEvent,
    ArtifactOutputStatus,
    CaseStartedEvent,
    HumanAction,
    HumanActionEvent,
    RegressionCheckEvent,
    RegressionStatus,
)
from tests.domain.factories import NOW


def make_case_started() -> CaseStartedEvent:
    return CaseStartedEvent(
        event_id="evalevt_case_started_001",
        case_id="case_domain_001",
        task_id="task_domain_001",
        occurred_at=NOW,
        base_revision="a" * 40,
        model_id="fake-v0.1",
        prompt_version="prompt-v0.1",
        spec_version="spec-v0.1",
        test_entrypoints=("pytest",),
        included=True,
    )


def make_agent_run() -> AgentRunEvent:
    return AgentRunEvent(
        event_id="evalevt_agent_run_001",
        case_id="case_domain_001",
        task_id="task_domain_001",
        occurred_at=NOW + timedelta(minutes=1),
        run_id="run_coder_001",
        role=AgentRole.CODER,
        attempt=1,
        output_status=ArtifactOutputStatus.VALID,
        artifact_id="art_impl_001",
        policy_violations=0,
        caught_policy_violations=0,
        duration_ms=120,
    )


def make_human_action(*, action: HumanAction = HumanAction.VIEW_HANDOFF) -> HumanActionEvent:
    return HumanActionEvent(
        event_id="evalevt_human_action_001",
        case_id="case_domain_001",
        task_id="task_domain_001",
        occurred_at=NOW + timedelta(minutes=2),
        action=action,
        evidence_uri="human://audit/action-001",
        note="Recorded by the evaluation harness.",
    )


def make_regression_check(
    *, status: RegressionStatus = RegressionStatus.PASS
) -> RegressionCheckEvent:
    return RegressionCheckEvent(
        event_id="evalevt_regression_001",
        case_id="case_domain_001",
        task_id="task_domain_001",
        occurred_at=NOW + timedelta(days=1),
        status=status,
        window_started_at=NOW + timedelta(hours=1),
        window_ended_at=NOW + timedelta(days=1),
        evidence_uri="evidence://regression/check-001",
        hidden_tests=True,
    )
