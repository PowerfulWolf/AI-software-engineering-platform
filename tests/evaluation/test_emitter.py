"""Automatic AgentResult-to-EvaluationEvent instrumentation."""

from datetime import timedelta

from ai_software_engineer.agents import FakeAgentAdapter, FakeBehavior, FakeScenario
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.evaluation import (
    AgentRunEvent,
    ArtifactOutputStatus,
    EvaluatingAgentAdapter,
    InMemoryEvaluationEventStore,
)
from tests.agents.test_fake import _align, _request
from tests.domain.factories import NOW, make_implementation_artifact


def test_evaluating_adapter_emits_valid_output_and_preserves_exact_replay() -> None:
    request = _request(AgentRole.CODER)
    delegate = FakeAgentAdapter(
        default=FakeScenario(
            behavior=FakeBehavior.SUCCESS,
            artifact=_align(make_implementation_artifact(), request),
        )
    )
    store = InMemoryEvaluationEventStore()
    observations = iter((NOW, NOW + timedelta(days=1)))
    adapter = EvaluatingAgentAdapter(
        case_id="case_domain_001",
        delegate=delegate,
        event_store=store,
        clock=lambda: next(observations),
    )

    first = adapter.run(request)
    replay = adapter.run(request)

    assert replay == first
    events = store.list_for_case("case_domain_001")
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, AgentRunEvent)
    assert event.occurred_at == NOW
    assert event.output_status is ArtifactOutputStatus.VALID
    assert event.artifact_id == "art_impl_001"


def test_evaluating_adapter_counts_invalid_output_without_artifact() -> None:
    request = _request(AgentRole.CODER)
    store = InMemoryEvaluationEventStore()
    adapter = EvaluatingAgentAdapter(
        case_id="case_domain_001",
        delegate=FakeAgentAdapter(default=FakeScenario(behavior=FakeBehavior.INVALID_OUTPUT)),
        event_store=store,
        clock=lambda: NOW,
    )

    result = adapter.run(request)
    event = store.list_for_case("case_domain_001")[0]

    assert result.artifact is None
    assert isinstance(event, AgentRunEvent)
    assert event.output_status is ArtifactOutputStatus.INVALID
    assert event.artifact_id is None
